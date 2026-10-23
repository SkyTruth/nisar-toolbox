import argparse
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import shapely
from pyreqwest.client import SyncClientBuilder
from pyreqwest.exceptions import RequestError
from shapely.errors import GEOSException
from shapely.geometry import shape

from utils.variables import (
    ASF_API_BASE,
    ASF_DATASET,
    ASF_DEFAULT_PROCESSING_LEVEL,
    GRANULE_CSV_PATH,
    NISAR_ARCHIVE_START,
)

# Columns in an S2 match file that describe the S2 scene rather than the slick
S2_COLUMNS = ["s2_id", "s2_time", "dt_hours", "cloud_pct"]
ASF_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RETRIES = 3

MATCH_SCHEMA = {
    "nisar_id": pl.String,
    "nisar_time": pl.Datetime("us", "UTC"),
    "dt_hours": pl.Float64,
    "nisar_direction": pl.String,
    "nisar_track": pl.Int32,
    "nisar_frame": pl.Int32,
    "nisar_collection": pl.String,
    "nisar_coverage_frac": pl.Float64,
    "nisar_size_mb": pl.Float64,
    "nisar_url": pl.String,
    "nisar_browse_url": pl.String,
    "nisar_footprint_wkt": pl.String,
}


def load_slicks(path: Path) -> tuple[pl.DataFrame, str]:
    """One row per slick, plus the input's GeoParquet metadata so the output stays GeoParquet."""
    geo = pl.read_parquet_metadata(path).get("geo")
    if geo is None:
        raise ValueError(f"{path} has no GeoParquet 'geo' metadata")
    geo_metadata = json.loads(geo)
    # bbox is optional in GeoParquet and would describe the input, not the output
    for column in geo_metadata["columns"].values():
        column.pop("bbox", None)

    # Polars doesn't know the geoarrow.wkb extension type; the WKB bytes are all we need
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Extension type 'geoarrow.wkb'")
        df = pl.read_parquet(path)

    # An S2 match file has one row per slick x S2 scene; keep the count so triple coincidences are easy to find
    slicks = df.unique("slick", keep="first", maintain_order=True).drop(
        S2_COLUMNS, strict=False
    )
    if "s2_id" in df.columns:
        n_s2 = df.group_by("slick").agg(
            n_s2_matches=pl.col("s2_id").is_not_null().sum()
        )
        slicks = slicks.join(n_s2, on="slick", how="left")

    return slicks, json.dumps(geo_metadata)


def query_asf(client, params: dict) -> list[dict]:
    error = ""
    for attempt in range(RETRIES):
        try:
            resp = client.get(ASF_API_BASE).query(params).build().send()
            if resp.status == 200:
                return resp.json()["features"]
            error = f"{resp.status} from ASF"
        except RequestError as exc:
            error = str(exc)
        if attempt < RETRIES - 1:
            time.sleep(2**attempt)
    raise RuntimeError(error)


def search_slick(
    client, slick: dict, window: timedelta, processing_level: str
) -> list[dict]:
    """NISAR scenes whose footprint overlaps the slick within +/- window of the slick timestamp."""
    geom = shapely.make_valid(shapely.from_wkb(slick["geometry"]))
    slick_time = slick["slick_timestamp"]
    params = {
        "dataset": ASF_DATASET,
        "processingLevel": processing_level,
        # Slicks can have thousands of vertices; the hull keeps the URL short and only adds candidates
        "intersectsWith": shapely.to_wkt(
            shapely.convex_hull(geom), rounding_precision=5
        ),
        "start": (slick_time - window).strftime(ASF_TIME_FORMAT),
        "end": (slick_time + window).strftime(ASF_TIME_FORMAT),
        "output": "geojson",
    }

    rows = []
    for feature in query_asf(client, params):
        props = feature["properties"]
        footprint = shapely.make_valid(shape(feature["geometry"]))
        # Ratio of areas in degrees; fine at slick scale
        coverage = footprint.intersection(geom).area / geom.area
        # Hits on the hull that miss the slick itself
        if coverage == 0:
            continue

        nisar_time = datetime.fromisoformat(props["startTime"])
        h5_bytes = props.get("bytes", {}).get(props["fileName"], {}).get("bytes")
        rows.append(
            {
                "slick": slick["slick"],
                "nisar_id": props["sceneName"],
                "nisar_time": nisar_time,
                "dt_hours": (nisar_time - slick_time).total_seconds() / 3600,
                "nisar_direction": props["flightDirection"],
                "nisar_track": props["pathNumber"],
                "nisar_frame": props["frameNumber"],
                "nisar_collection": props["collectionName"],
                "nisar_coverage_frac": coverage,
                # Same units as the "Size (MB)" column in ASF's CSV output
                "nisar_size_mb": h5_bytes / 1e6 if h5_bytes else None,
                "nisar_url": props["url"],
                "nisar_browse_url": (props.get("browse") or [None])[0],
                "nisar_footprint_wkt": footprint.wkt,
            }
        )
    return rows


def search_slicks(
    slicks: pl.DataFrame, window: timedelta, processing_level: str, workers: int
) -> tuple[pl.DataFrame, list[tuple]]:
    matches: list[dict] = []
    failures: list[tuple] = []

    with SyncClientBuilder().build() as client, ThreadPoolExecutor(workers) as pool:

        def search(slick: dict) -> tuple[list[dict], tuple | None]:
            try:
                return search_slick(client, slick, window, processing_level), None
            # RuntimeError: ASF kept failing (raised in query_asf)
            # GEOSException: a geometry shapely couldn't intersect
            except (RuntimeError, GEOSException) as exc:
                return [], (slick["slick"], str(exc))

        results = pool.map(search, slicks.iter_rows(named=True))
        for i, (rows, failure) in enumerate(results, start=1):
            matches.extend(rows)
            if failure:
                failures.append(failure)
            if i % 100 == 0 or i == slicks.height:
                print(f"  searched {i}/{slicks.height}")

    schema = {"slick": slicks.schema["slick"], **MATCH_SCHEMA}
    return pl.DataFrame(matches, schema=schema), failures


def print_summary(
    result: pl.DataFrame,
    n_total: int,
    n_searched: int,
    failures: list[tuple],
    hours: float,
    processing_level: str,
) -> None:
    matched = result.filter(pl.col("nisar_id").is_not_null())
    print(
        f"\n{n_total} slicks in file: {n_total - n_searched} end before NISAR data "
        f"({NISAR_ARCHIVE_START:%Y-%m-%d}) and were skipped, {n_searched} searched, {len(failures)} failed"
    )
    print(
        f"{matched['slick'].n_unique()} slicks have a NISAR {processing_level} scene within {hours:g} h "
        f"({matched.height} slick-scene pairs, {matched['nisar_id'].n_unique()} unique scenes)"
    )
    if "n_s2_matches" in matched.columns:
        both = matched.filter(pl.col("n_s2_matches") > 0)["slick"].n_unique()
        print(f"{both} of those also have an S2 match")

    if "hitl_short_name" in result.columns:
        print(
            result.group_by("hitl_short_name")
            .agg(
                searched=pl.col("slick").n_unique(),
                with_nisar=pl.col("slick")
                .filter(pl.col("nisar_id").is_not_null())
                .n_unique(),
            )
            .sort("with_nisar", "searched", descending=True)
        )

    columns = [
        c
        for c in [
            "slick",
            "slick_timestamp",
            "hitl_short_name",
            "n_s2_matches",
            "nisar_id",
            "dt_hours",
            "nisar_coverage_frac",
        ]
        if c in matched.columns
    ]
    with pl.Config(tbl_rows=-1, fmt_str_lengths=100, tbl_width_chars=250):
        print(matched.select(columns))

    for slick_id, err in failures:
        print(f"  FAILED slick {slick_id}: {err}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find NISAR scenes collected within a time window of each slick in a slick GeoParquet."
    )
    parser.add_argument(
        "--slicks",
        type=Path,
        required=True,
        help="GeoParquet of slicks with 'slick', 'slick_timestamp' (UTC) and 'geometry' columns, e.g. an S2 match file.",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=24,
        help="Search +/- this many hours around each slick timestamp (default 24).",
    )
    parser.add_argument(
        "--processing-level",
        default=ASF_DEFAULT_PROCESSING_LEVEL,
        choices=["GSLC", "GOFF", "GCOV", "GUNW", "SME2"],
        help=f"NISAR product type ({ASF_DEFAULT_PROCESSING_LEVEL} default).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent ASF requests (default 8).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output GeoParquet path. Defaults to data/nisar_granule_files/; a CSV of matched granules is written next to it.",
    )
    args = parser.parse_args()

    request_date = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    window = timedelta(hours=args.window_hours)
    out = args.out or (
        GRANULE_CSV_PATH
        / f"slick_nisar_{args.processing_level}_matches_{args.window_hours:g}h_requestMade{request_date}.parquet"
    )

    slicks, geo_metadata = load_slicks(args.slicks)
    # No point asking ASF about slicks whose window closes before NISAR data exists
    searchable = slicks.filter(
        pl.col("slick_timestamp") + window >= NISAR_ARCHIVE_START
    )
    print(
        f"Searching ASF for NISAR {args.processing_level} scenes within {args.window_hours:g} h "
        f"of {searchable.height} slicks"
    )

    matches, failures = search_slicks(
        searchable, window, args.processing_level, args.workers
    )
    failed_ids = [slick_id for slick_id, _ in failures]
    # One row per slick x NISAR scene; slicks with no scene keep one row with null NISAR columns
    result = (
        searchable.filter(~pl.col("slick").is_in(failed_ids))
        .join(matches, on="slick", how="left")
        .sort(pl.col("slick_timestamp"), pl.col("dt_hours").abs(), nulls_last=True)
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    result.write_parquet(out, metadata={"geo": geo_metadata})

    # Same column names as src.asf_sar_search, so src.nisar_dl can download straight from it
    granules = (
        result.filter(pl.col("nisar_id").is_not_null())
        .unique("nisar_id", keep="first", maintain_order=True)
        .select(
            pl.col("nisar_id").alias("Granule Name"),
            pl.col("nisar_time").alias("Start Time"),
            pl.col("nisar_direction").alias("Ascending or Descending?"),
            pl.col("nisar_track").alias("Path Number"),
            pl.col("nisar_frame").alias("Frame Number"),
            pl.col("nisar_url").alias("URL"),
            pl.col("nisar_size_mb").alias("Size (MB)"),
        )
    )
    granule_csv = out.with_name(f"{out.stem}_granules.csv")
    granules.write_csv(granule_csv)

    print_summary(
        result,
        slicks.height,
        searchable.height,
        failures,
        args.window_hours,
        args.processing_level,
    )
    if failures:
        print(
            f"\n{len(failures)} slicks failed and are NOT in the output; re-run to retry them."
        )
    print(f"\nWrote {out}")
    print(f"Wrote {granule_csv}")


if __name__ == "__main__":
    main()
