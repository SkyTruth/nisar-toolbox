import argparse
import re
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from src.nisar_convert_to_tiff import to_output
from utils.variables import (
    ALOS2_ATTRIBUTION,
    ALOS2_CAL_DB,
    ALOS2_GEOTIFF_PATH,
    ALOS2_MASK_DROP,
    ALOS2_TIF_PATH,
)

# e.g. ALOS2585563700-250327_WBDR2.2GUD_HH_SLP -> scene ID, polarization
L22_FILE_RE = re.compile(r"(ALOS2\d{9}-\d{6}_\w{3}[RL]2\.2GU[AD])_(HH|HV)_SLP")
CAL_LINEAR = np.float32(10 ** (ALOS2_CAL_DB / 10))


def dn_to_gamma0(block):
    """uint16 DN -> linear gamma0 (DN^2 * 10^-8.3); DN 0 is nodata."""
    block = block.astype("float32")
    gamma0 = block * block * CAL_LINEAR
    gamma0[block == 0] = np.nan
    return gamma0


def convert_scene_to_geotiff(
    tif_path: Path,
    remove_tif: bool = False,
    db: bool = False,
    mask: bool = False,
    bbox: list[float] | None = None,
    aoi_name: str = "crop",
    out_dir: Path | str = ALOS2_GEOTIFF_PATH,
) -> Path:
    """
    Convert a single, specified PALSAR-2 L2.2 HH/HV GeoTIFF (DN) to a calibrated gamma0 GeoTIFF.
    """

    # Use path as given, look in ALOS2_TIF_PATH otherwise
    tif_path = Path(tif_path)
    if not tif_path.exists():
        tif_path = ALOS2_TIF_PATH / tif_path.name

    # Check the tif file exists
    if not tif_path.exists():
        raise FileNotFoundError(f"{tif_path} not found; download it first")

    # Determine scene and polarization from the file name
    m = L22_FILE_RE.fullmatch(tif_path.stem)
    if m is None:
        raise ValueError(f"{tif_path.name} is not a PALSAR-2 L2.2 HH/HV file")
    scene_id, polarization = m.groups()

    mask_path = tif_path.with_name(f"{scene_id}_MSK.tif")
    if mask and not mask_path.exists():
        raise FileNotFoundError(
            f"{mask_path.name} not found; download it with alos2_dl --mask"
        )

    # Name the output after the input so different scenes never overwrite each other
    suffix = "gamma0"
    if db:
        suffix += "_dB"
    if mask:
        suffix += "_masked"
    if bbox:
        suffix += f"_{aoi_name}"

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tif_path.stem}_{suffix}.tif"

    if out_path.exists():
        print(f"    Skipping {out_path.name} (already exists)")
        return out_path

    # Write to a partial file so a failed conversion never looks complete
    part = out_path.with_suffix(".tif.part")
    try:
        with (
            rasterio.open(tif_path) as src,
            rasterio.open(mask_path) if mask else nullcontext() as msk,
        ):
            # Full grid, or just the bbox (reprojected into the scene's UTM CRS)
            full = Window(0, 0, src.width, src.height)
            if bbox:
                b = transform_bounds("EPSG:4326", src.crs, *bbox)
                try:
                    win = (
                        from_bounds(*b, src.transform)
                        .round_offsets()
                        .round_lengths()
                        .intersection(full)
                    )
                except rasterio.errors.WindowError:
                    raise ValueError(f"bbox {bbox} does not overlap {tif_path.name}")
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
                crs=src.crs,
                transform=window_transform(win, src.transform),
                nodata=float("nan"),
                tiled="YES",
                compress="DEFLATE",
                interleave="BAND",
                predictor=3,
                BIGTIFF="yes",
            ) as dst:
                # Write in row blocks so the full array never has to fit in memory
                for r in range(0, h, 2048):
                    n = min(2048, h - r)
                    read_win = Window(c_off, r_off + r, w, n)
                    block = dn_to_gamma0(src.read(1, window=read_win))
                    if msk is not None:
                        block[
                            np.isin(msk.read(1, window=read_win), ALOS2_MASK_DROP)
                        ] = np.nan
                    dst.write(to_output(block, db), 1, window=Window(0, r, w, n))

                dst.update_tags(
                    ATTRIBUTION=ALOS2_ATTRIBUTION,
                    SCENE_ID=scene_id,
                    POLARIZATION=polarization,
                    UNITS="gamma0 (dB)" if db else "gamma0 (linear power)",
                    CALIBRATION="gamma0 = DN^2 * 10^(-8.3)",
                )

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

    if remove_tif:
        tif_path.unlink()

    return out_path


def convert_scenes_to_geotiff(
    tif_paths: list[Path],
    remove_tif: bool = False,
    db: bool = False,
    mask: bool = False,
    bbox: list[float] | None = None,
    aoi_name: str = "crop",
    out_dir: Path | str = ALOS2_GEOTIFF_PATH,
) -> list[Path]:
    """
    Convert a list of PALSAR-2 L2.2 tifs to calibrated GeoTIFFs.
    """
    tifs: list[Path] = []
    failures: list[tuple[str, str]] = []
    for i, tif_path in enumerate(tif_paths, start=1):
        name = Path(tif_path).name
        print(f"Converting {i}/{len(tif_paths)} {name}")
        try:
            tifs.append(
                convert_scene_to_geotiff(
                    tif_path, remove_tif, db, mask, bbox, aoi_name, out_dir
                )
            )

        # OSError: missing/unreadable tif or tif write failure (includes RasterioIOError)
        # ValueError: not an L2.2 HH/HV file name, or bbox outside the scene
        except (OSError, ValueError) as exc:
            print(f"  FAILED: {exc}")
            failures.append((name, str(exc)))

    print(f"\nDone. {len(tifs)} converted, {len(failures)} failed.")
    for name, err in failures:
        print(f"  {name}: {err}")
    return tifs


def main():
    parser = argparse.ArgumentParser(
        description="Convert downloaded PALSAR-2 L2.2 GeoTIFFs (DN) to calibrated gamma0 GeoTIFFs."
    )
    parser.add_argument(
        "--tif",
        "--infile",
        dest="tif",
        nargs="+",
        required=True,
        help="One or more _HH_SLP/_HV_SLP .tif files (looked up in data/alos2_tif_scenes/).",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print the tif's profile and tags instead of converting.",
    )
    parser.add_argument(
        "--remove-tif",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Remove each source .tif after a successful conversion (default: False).",
    )
    parser.add_argument(
        "--db", action="store_true", help="Write gamma0 in dB (10*log10)."
    )
    parser.add_argument(
        "--mask",
        action="store_true",
        help="Set layover, shadow and invalid pixels to NaN (needs the scene's _MSK.tif).",
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
        default=ALOS2_GEOTIFF_PATH,
        help=f"Folder to write GeoTIFFs to; created if missing. Defaults to {ALOS2_GEOTIFF_PATH}.",
    )

    args = parser.parse_args()

    if args.inspect:
        for tif_file in args.tif:
            with rasterio.open(ALOS2_TIF_PATH / f"{Path(tif_file).stem}.tif") as src:
                print(src.profile)
                print(src.tags())
    else:
        convert_scenes_to_geotiff(
            args.tif,
            args.remove_tif,
            args.db,
            args.mask,
            args.bbox,
            args.aoi_name,
            args.out_dir,
        )


if __name__ == "__main__":
    main()