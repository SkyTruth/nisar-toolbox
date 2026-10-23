import argparse

from pyreqwest.client import SyncClientBuilder
from pyreqwest.exceptions import RequestError

from src.alos2_convert_to_tiff import convert_scene_to_geotiff
from src.alos2_dl import URL_COLUMNS, download_scene, file_name
from src.alos2_search import construct_s3_search
from utils.variables import ALOS2_GEOTIFF_PATH, ALOS2_MODES, SEARCH_AOIS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search, download and convert PALSAR-2 L2.2 scenes for a saved AOI in one run."
    )
    parser.add_argument(
        "--aoi",
        required=True,
        choices=sorted(SEARCH_AOIS),
        help="Named AOI from SEARCH_AOIS in utils/variables.py.",
    )
    parser.add_argument(
        "--mode",
        nargs="+",
        choices=ALOS2_MODES,
        help="Only these beam modes. WBD/WWD/VBD are HH+HV; WBS/WWS are HH only.",
    )
    parser.add_argument(
        "--sd", "--start", dest="start", required=True, help="Start Date: YYYY-MM-DD"
    )
    parser.add_argument(
        "--ed", "--end", dest="end", required=True, help="End Date: YYYY-MM-DD"
    )
    parser.add_argument(
        "--polarization",
        nargs="+",
        default=["HH", "HV"],
        type=str.upper,
        choices=["HH", "HV"],
        help="One GeoTIFF per polarization (default: HH HV). HV is skipped for HH-only scenes.",
    )
    parser.add_argument(
        "--db", action="store_true", help="Write gamma0 in dB (10*log10)."
    )
    parser.add_argument(
        "--mask",
        action="store_true",
        help="Set layover, shadow and invalid pixels to NaN (downloads each scene's _MSK.tif).",
    )
    parser.add_argument(
        "--crop",
        action="store_true",
        help="Crop the GeoTIFF to the AOI bbox; by default will write the whole scene to disk.",
    )
    parser.add_argument(
        "--keep-tif",
        action="store_true",
        help="Keep each downloaded source .tif after converting (default: delete).",
    )
    parser.add_argument(
        "--out-dir",
        "--outpath",
        dest="out_dir",
        default=ALOS2_GEOTIFF_PATH,
        help=f"Folder to write GeoTIFFs to; created if missing. Defaults to {ALOS2_GEOTIFF_PATH}.",
    )
    args = parser.parse_args()

    bbox_str = SEARCH_AOIS[args.aoi]["bbox"]
    # Converter expects (min_lon, min_lat, max_lon, max_lat) as floats
    crop_bbox = [float(v) for v in bbox_str.split(",")] if args.crop else None

    granules = construct_s3_search(
        bbox=bbox_str,
        start=args.start,
        end=args.end,
        modes=args.mode,
        location=args.aoi,
    )
    scenes = granules.unique(subset="Granule Name", keep="first", maintain_order=True)
    print(
        f"\n{scenes.height} scenes found for {args.aoi} (PALSAR-2 L2.2, {args.start} to {args.end})"
    )

    tifs: list = []
    failures: list[tuple[str, str]] = []
    with SyncClientBuilder().build() as client:
        for i, row in enumerate(scenes.iter_rows(named=True), start=1):
            granule_name = row["Granule Name"]
            print(f"\n[{i}/{scenes.height}] {granule_name}")
            downloaded = []
            try:
                if args.mask:
                    url = row[URL_COLUMNS["MSK"]]
                    downloaded.append(download_scene(client, file_name(url), url))
                for pol in args.polarization:
                    url = row[URL_COLUMNS[pol]]
                    if not url:
                        print(f"    No {pol} for this scene (HH-only)")
                        continue
                    src_tif = download_scene(
                        client, file_name(url), url
                    )  # skips if already on disk
                    downloaded.append(src_tif)
                    tifs.append(
                        convert_scene_to_geotiff(
                            src_tif,
                            db=args.db,
                            mask=args.mask,
                            bbox=crop_bbox,
                            aoi_name=args.aoi,
                            out_dir=args.out_dir,
                        )
                    )
                # Only reached if every polarization converted
                if not args.keep_tif:
                    for path in downloaded:
                        path.unlink()

            # Same failure types the standalone batch loops catch, so one bad scene doesn't stop the run
            except (RequestError, RuntimeError, OSError, ValueError) as exc:
                print(f"  FAILED: {exc}")
                failures.append((granule_name, str(exc)))

    print(f"\nDone. {len(tifs)} GeoTIFFs written, {len(failures)} scenes failed.")
    for name, err in failures:
        print(f"  {name}: {err}")


if __name__ == "__main__":
    main()