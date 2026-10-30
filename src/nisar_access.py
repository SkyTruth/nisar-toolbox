import argparse

from pyreqwest.client import SyncClientBuilder
from pyreqwest.exceptions import RequestError

from src.asf_sar_search import construct_api_search
from src.nisar_convert_to_tiff import convert_scene_to_geotiff
from src.nisar_dl import download_scene
from utils.variables import (
    ASF_DEFAULT_PROCESSING_LEVEL,
    EARTHDATA_TOKEN,
    NISAR_GEOTIFF_PATH,
    NISAR_PROCESSING_INFO,
    SEARCH_AOIS,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search, download and convert NISAR scenes for a saved AOI in one run."
    )
    parser.add_argument(
        "--aoi",
        required=True,
        choices=sorted(SEARCH_AOIS),
        help="Named AOI from SEARCH_AOIS in utils/variables.py.",
    )
    parser.add_argument(
        "--product",
        default=ASF_DEFAULT_PROCESSING_LEVEL,
        choices=sorted(NISAR_PROCESSING_INFO),
    )
    parser.add_argument(
        "--sd", "--start", dest="start", required=True, help="Start Date: YYYY-MM-DD"
    )
    parser.add_argument(
        "--ed", "--end", dest="end", required=True, help="End Date: YYYY-MM-DD"
    )
    parser.add_argument("--frequency", choices=["A", "B"], default="B")
    parser.add_argument(
        "--polarization",
        nargs="+",
        help="One GeoTIFF per polarization, e.g. HH, HV, VV, HHHH, HVHV, VVVV. Defaults per product.",
    )
    parser.add_argument(
        "--db", action="store_true", help="Write intensity in dB (GSLC/GCOV only)."
    )
    parser.add_argument(
        "--crop",
        action="store_true",
        help="Crop the GeoTIFF to the AOI bbox, reading only that area from ASF instead of downloading the whole .h5; by default will write the whole scene to disk.",
    )
    parser.add_argument(
        "--keep-h5",
        action="store_true",
        help="Keep each .h5 after converting (default: delete). Ignored with --crop, which downloads no .h5.",
    )
    parser.add_argument(
        "--out-dir",
        "--outpath",
        dest="out_dir",
        default=NISAR_GEOTIFF_PATH,
        help=f"Folder to write GeoTIFFs to; created if missing. Defaults to {NISAR_GEOTIFF_PATH}.",
    )
    args = parser.parse_args()

    # download_scene doesn't check the token itself, so fail before searching
    if not EARTHDATA_TOKEN:
        raise SystemExit("EARTHDATA_TOKEN is not set; add it to .env")

    bbox_str = SEARCH_AOIS[args.aoi]["bbox"]
    # Converter expects (min_lon, min_lat, max_lon, max_lat) as floats
    crop_bbox = [float(v) for v in bbox_str.split(",")] if args.crop else None

    granules = construct_api_search(
        bbox=bbox_str,
        start=args.start,
        end=args.end,
        processing_level=args.product,
        location=args.aoi,
    )
    scenes = granules.unique(
        subset="Granule Name", keep="first", maintain_order=True
    ).select("Granule Name", "URL")
    print(
        f"\n{scenes.height} scenes found for {args.aoi} ({args.product}, {args.start} to {args.end})"
    )

    tifs: list = []
    failures: list[tuple[str, str]] = []
    with SyncClientBuilder().build() as client:
        for i, (granule_name, url) in enumerate(scenes.iter_rows(), start=1):
            print(f"\n[{i}/{scenes.height}] {granule_name}")
            try:
                # --crop reads just the AOI from the remote .h5; otherwise download the whole file
                h5 = (
                    url
                    if args.crop
                    else download_scene(
                        client, granule_name, url
                    )  # skips if already on disk
                )
                for pol in args.polarization or [None]:
                    tifs.append(
                        convert_scene_to_geotiff(
                            h5,
                            frequency=args.frequency,
                            polarization=pol,
                            db=args.db,
                            bbox=crop_bbox,
                            aoi_name=args.aoi,
                            out_dir=args.out_dir,
                        )
                    )
                # Only reached if every polarization converted
                if not args.crop and not args.keep_h5:
                    h5.unlink()

            # Same failure types the standalone batch loops catch, so one bad scene doesn't stop the run
            except (
                RequestError,
                RuntimeError,
                OSError,
                KeyError,
                ValueError,
                IndexError,
            ) as exc:
                print(f"  FAILED: {exc}")
                failures.append((granule_name, str(exc)))

    print(f"\nDone. {len(tifs)} GeoTIFFs written, {len(failures)} scenes failed.")
    for name, err in failures:
        print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
