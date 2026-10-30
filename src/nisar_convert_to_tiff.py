import argparse
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import aiohttp
import fsspec
import h5py
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from utils.variables import (
    EARTHDATA_TOKEN,
    NISAR_GEOTIFF_PATH,
    NISAR_H5_PATH,
    NISAR_PROCESSING_INFO,
)

# NISAR .h5 files use 4 MiB file-space pages, so remote reads fetch whole pages
REMOTE_BLOCK_SIZE = 4 << 20


def is_url(source) -> bool:
    return str(source).startswith(("http://", "https://"))


@contextmanager
def open_h5(source):
    """Open a local .h5, or a remote one over HTTP (only the byte ranges actually read are fetched)."""
    if not is_url(source):
        with h5py.File(source, "r") as src:
            yield src
        return

    if not EARTHDATA_TOKEN:
        raise RuntimeError("EARTHDATA_TOKEN is not set; add it to .env")
    fs = fsspec.filesystem(
        "https",
        client_kwargs={"headers": {"Authorization": f"Bearer {EARTHDATA_TOKEN}"}},
    )
    try:
        with (
            fs.open(source, block_size=REMOTE_BLOCK_SIZE, cache_type="blockcache") as f,
            h5py.File(f, "r") as src,
        ):
            yield src
    # e.g. 401 from an expired token; RuntimeError like download_scene, so batch loops record it and move on
    except aiohttp.ClientResponseError as exc:
        raise RuntimeError(f"{exc.status} {exc.message} for {source}") from exc


def to_output(block, db: bool = False):
    """Complex SLC -> intensity |z|^2 (optionally dB); always float32."""
    if np.iscomplexobj(block):
        block = block.real**2 + block.imag**2  # same as abs(z)**2, cheaper
    block = block.astype("float32", copy=False)
    if db:
        with np.errstate(divide="ignore", invalid="ignore"):
            block = np.where(block > 0, 10 * np.log10(block), np.nan).astype("float32")
    return block


def show(name, obj):
    if isinstance(obj, h5py.Dataset):
        print(f"{name}  {obj.dtype} {obj.shape}")
    else:
        print(f"{name}/")


def convert_scene_to_geotiff(
    h5_path: Path | str,
    frequency: str = "A",
    polarization: str | None = None,
    remove_h5: bool = False,
    db: bool = False,
    bbox: list[float] | None = None,
    aoi_name: str = "crop",
    out_dir: Path | str = NISAR_GEOTIFF_PATH,
) -> Path:
    """
    Convert a single, specified h5 file to GeoTIFF.
    h5_path can also be an ASF download URL, read remotely without downloading the whole file
    (worthwhile with a bbox, since only the cropped area is fetched).
    """

    remote = is_url(h5_path)
    if not remote:
        # Use path as given, look in NISAR_H5_PATH otherwise
        h5_path = Path(h5_path)
        if not h5_path.exists():
            h5_path = NISAR_H5_PATH / h5_path.name

        # Check the h5 file exists
        if not h5_path.exists():
            raise FileNotFoundError(f"{h5_path} not found; download it first")

    # Granule name from the file name, local or in the URL
    granule_name = PurePosixPath(urlparse(str(h5_path)).path).stem

    # Determine NISAR Processing Level from granule dile name
    processing_level = granule_name.split("_")[3]

    if processing_level not in NISAR_PROCESSING_INFO:
        raise ValueError(f"No information defined for {processing_level}")

    data_specs = NISAR_PROCESSING_INFO[processing_level]
    if db and not data_specs.get("db_accepted"):
        raise ValueError(
            f"--db is only meaningful for GSLC/GCOV, not {processing_level}"
        )
    names = {
        "frequency": frequency,
        "polarization": polarization or data_specs["default_polarization"],
    }

    # Define outfile name, same as infile name but just as .tiffName the output after the scene so different scenes never overwrite each other
    suffix = data_specs["suffix"].format(**names)
    if db:
        suffix += "_dB"
    if bbox:
        suffix += f"_{aoi_name}"

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{granule_name}_{suffix}.tif"

    if out_path.exists():
        print(f"    Skipping {out_path.name} (already exists)")
        return out_path

    # Write to a partial file so a failed conversion never looks complete
    part = out_path.with_suffix(".tif.part")
    try:
        with open_h5(h5_path) as src:
            grid = src[data_specs["grid"].format(**names)]
            data = grid[data_specs["dataset"].format(**names)]

            xcoords = grid["xCoordinates"][:]
            ycoords = grid["yCoordinates"][:]
            dx = float(grid["xCoordinateSpacing"][()])
            dy = float(grid["yCoordinateSpacing"][()])
            epsg = int(grid["projection"][()])

            transform = from_origin(
                xcoords[0] - dx / 2, ycoords[0] - dy / 2, dx, abs(dy)
            )

            # Full grid, or just the bbox (reprojected into the scene's CRS)
            full = Window(0, 0, data.shape[1], data.shape[0])
            if bbox:
                b = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox)
                try:
                    win = (
                        from_bounds(*b, transform)
                        .round_offsets()
                        .round_lengths()
                        .intersection(full)
                    )
                except rasterio.errors.WindowError:
                    raise ValueError(f"bbox {bbox} does not overlap {granule_name}")
            else:
                win = full
            h, w = int(win.height), int(win.width)
            r_off, c_off = int(win.row_off), int(win.col_off)

            with rasterio.open(
                part,
                "w",
                driver="GTiff",
                height=h,
                width=w,
                count=1,
                dtype="float32",
                crs=f"EPSG:{epsg}",
                transform=window_transform(win, transform),
                nodata=data_specs["nodata"],
                tiled="YES",
                compress="DEFLATE",
                interleave="BAND",
                predictor=3,
                BIGTIFF="yes",
            ) as dst:
                # Write in row blocks so the full array never has to fit in memory
                for r in range(0, h, 2048):
                    n = min(2048, h - r)
                    block = data[
                        r_off + r : r_off + r + n, c_off : c_off + w
                    ]  # h5py reads only this slice
                    dst.write(to_output(block, db), 1, window=Window(0, r, w, n))

            # Overviews so full scenes render quickly when zoomed out (skipped for small crops)
            with (
                rasterio.Env(COMPRESS_OVERVIEW="DEFLATE"),
                rasterio.open(part, "r+") as dst,
            ):
                factors = [2**i for i in range(1, 10) if max(dst.shape) / 2**i >= 256]
                if factors:
                    dst.build_overviews(factors, Resampling.average)
                    dst.update_tags(ns="rio_overview", resampling="average")

    except Exception:
        part.unlink(missing_ok=True)
        raise

    part.replace(out_path)

    if remove_h5 and not remote:
        h5_path.unlink()

    return out_path


def convert_scenes_to_geotiff(
    h5_paths: list[Path],
    frequency: str = "A",
    polarization: str | None = None,
    remove_h5: bool = False,
    db: bool = False,
    bbox: list[float] | None = None,
    aoi_name: str = "crop",
    out_dir: Path | str = NISAR_GEOTIFF_PATH,
) -> list[Path]:
    """
    Convert a list of h5 scenes to GeoTIFF.
    """
    tifs: list[Path] = []
    failures: list[tuple[str, str]] = []
    for i, h5_path in enumerate(h5_paths, start=1):
        name = PurePosixPath(urlparse(str(h5_path)).path).name
        print(f"Converting {i}/{len(h5_paths)} {name}")
        try:
            tifs.append(
                convert_scene_to_geotiff(
                    h5_path,
                    frequency,
                    polarization,
                    remove_h5,
                    db,
                    bbox,
                    aoi_name,
                    out_dir,
                )
            )

        # OSError: missing/unreadable h5 or tif write failure (includes RasterioIOError)
        # KeyError: dataset path not in this h5 (e.g. wrong polarization/frequency)
        # ValueError: unsupported processing level
        # IndexError: file name doesn't follow the NISAR granule naming convention
        except (OSError, KeyError, ValueError, IndexError) as exc:
            print(f"  FAILED: {exc}")
            failures.append((name, str(exc)))

    print(f"\nDone. {len(tifs)} converted, {len(failures)} failed.")
    for name, err in failures:
        print(f"  {name}: {err}")
    return tifs


def main():
    parser = argparse.ArgumentParser(
        description="Convert downloaded NISAR .h5 scenes to GeoTIFF."
    )
    parser.add_argument(
        "--h5",
        "--infile",
        dest="h5",
        nargs="+",
        required=True,
        help="One or more .h5 files or granule names (looked up in data/nisar_h5_scenes/), or ASF download URLs (read remotely; use with --bbox).",
    )
    parser.add_argument("--frequency", choices=["A", "B"], default="A")
    parser.add_argument(
        "--polarization",
        help="GCOV: HHHH or HVHV. GUNW: HH or HV. Ignored for SME2. Defaults per product.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print the .h5 structure instead of converting.",
    )
    parser.add_argument(
        "--remove-h5",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Remove each .h5 file after a successful conversion to geotiff (default: False).",
    )
    parser.add_argument(
        "--db", action="store_true", help="Write intensity in dB (10*log10)."
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Crop to this lon/lat box at conversion time.",
    )
    parser.add_argument(
        "--aoi-name",
        default="crop",
        help="Appended to the output name when --bbox is used.",
    )
    parser.add_argument(
        "--out-dir",
        "--outdir",
        "--outpath",
        dest="out_dir",
        default=NISAR_GEOTIFF_PATH,
        help=f"Folder to write GeoTIFFs to; created if missing. Defaults to {NISAR_GEOTIFF_PATH}.",
    )

    args = parser.parse_args()

    if args.inspect:
        for h5_file in args.h5:
            with h5py.File(NISAR_H5_PATH / f"{Path(h5_file).stem}.h5", "r") as src:
                src.visititems(show)
    else:
        convert_scenes_to_geotiff(
            args.h5,
            args.frequency,
            args.polarization,
            args.remove_h5,
            args.db,
            args.bbox,
            args.aoi_name,
            args.out_dir,
        )


if __name__ == "__main__":
    main()
