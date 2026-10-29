# About
This is a toolbox for searching, downloading, and accessing NISAR data. It began as a local, proof-of-concept exploration of NISAR data. In its current state, it is intended to assist in SkyTruth's incident response work, to facilitate the incorporation of NISAR data into workflows that currently utilize Sentinel-1 or Sentinel-2 imagery.

A general note on the NISAR data processing described below, nisar_access defaults to Frequency B products. These are lower resolution, and also substantially smaller than Frequency A data. The suggested workflow is to search and evaluate on Frequency B data, and only download the Frequency A as needed.

In time, it will hopefully explore access to other less-utilized NASA data products, such as ICESat-2. 

Where possible it prioritizes the use of Rust-based libraries (e.g. polars, pyreqwest, ruff).


# Python Environment

This project uses `uv` as its default Python environment manager. The checked-in
environment contract is `pyproject.toml`, `uv.lock`, and `.python-version`.

Run all commands in this README from the repository root.

1. Set up the shared environment:
```bash
uv sync --locked
```

2. Create all local, git-ignored files and directories (can be re-run, will not overwrite any already existing files/dirs).
```bash
uv run python -m utils.setup
```
This creates `.env` (from `.env.default`), an empty `utils/aois.py`, `archive/`, and the `data/nisar_*` folders.


Optional: Start Jupyter with the same environment:

```bash
uv run jupyter lab
```

In Cursor or VS Code notebooks, choose the Python environment from this repo's
`.venv`. If prompted for a kernel source, select `Python Environments...`, then
the interpreter under `.venv`.

# Repository Structure

- `src/`: search / download / convert tools, run as modules (see NISAR Data Access)
- `utils/aois.py`: private AOIs (git-ignored)
- `utils/generate_aoi_details.py`: interactive helper that builds an AOI entry
- `utils/setup.py`: one-time setup; creates `.env`, `utils/aois.py`, `archive/`, and the `data/` folders if missing
- `utils/variables.py`: shared constants: ASF settings, data paths, per-product H5 layouts, `.env` loading
- `data/`: git-ignored except `.gitkeep`
  - `earth_access_tests/`, `other_data/`: samples for other explorations
  - `nisar_geotiffs/`: converted GeoTIFFs
  - `nisar_granule_files/`: granule CSVs from ASF searches
  - `nisar_h5_scenes/`: downloaded `.h5` scenes
- `notebooks/`: Jupyter notebooks (outputs should be stripped before committing)
- `archive/`: old snippets, miscellaneous code used only in local, throw-away tests (git-ignored)

Large source documents, licensed datasets, private materials, and downloaded research PDFs should not be committed to this repository unless they are clearly approved for redistribution.

# Notebook Hygiene
TODO: strip notebook outputs before commit (nbstripout filter or `.githooks/pre-commit`).

# Linting and Formatting
This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and code
formatting. Ruff is declared in the `dev` dependency group, so `uv sync` installs it
automatically.

Check the repository for lint issues:

```bash
uv run ruff check .
```

Apply the safe automatic fixes Ruff can make for the enabled rules:

```bash
uv run ruff check --fix .
```

Format the code:

```bash
uv run ruff format .
```

Verify formatting without editing files — handy as a pre-PR check:

```bash
uv run ruff format --check .
```

# NISAR Data Access
All commands below must be run from the repository root: `python -m src.…` and `python -m utils.…` only find the `src` and `utils` packages from there.

## Set up Earthdata Credentials
The code in this repo requires an Earthdata access token. Tokens last 60 days. To generate a token follow these steps:
1. Open `.env` (created by `utils.setup`; or run `cp .env.default .env`)
2. Go to: https://urs.earthdata.nasa.gov/ and login (or create an account)
3. Go to the **Generate Token** tab
4. Click the **Generate Token** button
5. Copy the Token and paste it into the `.env` file's `EARTHDATA_TOKEN`.
6. In the `.env` set the `EARTHDATA_TOKEN_DATE` to the date the token was generated

## Define AOIs
The search and download features of this repository depend on AOIs, currently defined by bounding boxes. AOI information should be stored in the git-ignored `utils/aois.py`. A few test AOIs (wva-test-area, drc-test-area, indian-ocean-test-area) defined in utils/variables.py are always available; an AOI in aois.py with the same name overrides them. Entry format: `"aoi-name": {"bbox": "min_lon,min_lat,max_lon,max_lat"},`. You can append the file directly following that format, or you can run the following code to generate one from bounds or a point plus a km buffer:
```bash
uv run python utils/generate_aoi_details.py
```

## Products
`src.nisar_access` and the GeoTIFF conversion support `GSLC`, `GCOV` (default), `GUNW`, `SME2`.
- `--db` applies to GSLC/GCOV only.
- `src.asf_sar_search` will also accept `GOFF` (search only; not currently supported by the geotiff conversion).


## Search, download, and convert NISAR data

```bash
uv run python -m src.nisar_access --aoi AOI_NAME --sd YYYY-MM-DD --ed YYYY-MM-DD
```
Flags:
- `--product`
- `--polarization POL [POL ...]`: one GeoTIFF per polarization; defaults per product, polarization options may not be consistent by collection
    - GCOV: `HHHH`, `HVHV`, `VVVV`
    - GSLC/GUNW: `HH`, `HV`
- `--frequency A|B`: Frequency A products are higher resolution, but also larger files. Defaults to Frequency B.
- `--db`: applies to GSLC/GCOV only.
- `--crop`: crops the output GeoTIFF to the AOI bbox (defaults to keeping the full scene)
- `--keep-h5`: by default each `.h5` is deleted after converting
- `--out-dir`: a user defined path to an output directory, if not defined geotiffs will be written to `data/nisar_geotiffs/`

### Step-by-step runs

1. Search the ASF API. Writes a CSV file to `data/nisar_granule_files/`.
    ```bash
    uv run python -m src.asf_sar_search --processing-level PROCESSING_LEVEL --aoi AOI_NAME --sd YYYY-MM-DD --ed YYYY-MM-DD
    ```
    OR use an ad-hoc bbox, with an optional `--location` label in the filename:
    ```bash
    uv run python -m src.asf_sar_search --processing-level PROCESSING_LEVEL --bbox 'MIN_LON,MIN_LAT,MAX_LON,MAX_LAT' --location LABEL --sd YYYY-MM-DD --ed YYYY-MM-DD
    ```
2. Download the NISAR H5 scenes in `data/nisar_h5_scenes/`. Scenes already on disk are skipped.
    ```bash
    uv run python -m src.nisar_dl --granule-file GRANULE_LIST.csv
    ```
    `--granule-file` is required; a bare filename is looked up in `data/nisar_granule_files/`. `--granule NAME [NAME ...]` downloads only those granules from the CSV.
3. Convert H5 to GeoTIFF in `data/nisar_geotiffs/`.
    ```bash
    uv run python -m src.nisar_convert_to_tiff --h5 PATH/TO/H5_FILE.h5 [H5_FILE2.h5 ...]
    ```
    Flags:
    - `--polarization`
    - `--frequency A|B`
    - `--db`
    - `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT --aoi-name NAME`: crop
    - `--remove-h5`
    - `--out-dir`
    - `--inspect`: print the H5 structure instead of converting

## Find NISAR and PALSAR-2 scenes near slicks
Given a GeoParquet of slicks (columns `slick`, `slick_timestamp` in UTC, and `geometry`), find every NISAR and PALSAR-2 scene whose footprint overlaps a slick within +/- 24 hours of it. NISAR is searched through the ASF API; PALSAR-2 ScanSAR L2.2 through JAXA's public S3 bucket, using each scene's STAC item for its footprint and centre time. An S2 match file (one row per slick x S2 scene) works as input: every input row is kept, each slick is searched once, and its scenes are attached to all of its rows, with an `n_s2_matches` count.
```bash
uv run python -m src.nisar_slick_search --slicks PATH/TO/SLICKS.parquet
```
Flags:
- `--sensors nisar|palsar [...]`: defaults to both
- `--window-hours`: defaults to 24
- `--processing-level`: NISAR product, defaults to GCOV
- `--workers`: concurrent ASF requests for NISAR, defaults to 8
- `--out`: output GeoParquet path, defaults to `data/nisar_granule_files/`

Every input row is kept in the output, in input order, once per NISAR scene x PALSAR-2 scene of its slick; rows whose slick has no scene from a sensor have empty columns for it. `nisar_search_status` and `palsar_search_status` say whether each slick was `searched`, `failed`, or older than that sensor's data (`before_nisar`: Oct 2025; `before_palsar`: Aug 2014). All NISAR data maturities are searched, since most of the Oct 2025 - Jan 2026 archive is BETA rather than PROVISIONAL. JAXA's L2.2 archive mostly covers land, coasts and polar regions and appears about a month after acquisition, so recent slicks may have no PALSAR-2 scene yet. Three files are written:
- a GeoParquet including, per sensor, the scene id and time, `nisar_dt_hours` / `palsar_dt_hours` (scene minus slick time), `nisar_coverage_frac` / `palsar_coverage_frac` (share of the slick inside the scene footprint), and download URLs
- `..._nisar_granules.csv`, the unique NISAR scenes, which can be passed straight to `src.nisar_dl --granule-file`
- `..._palsar_granules.csv`, the unique PALSAR-2 scenes, which can be passed straight to `src.alos2_dl --granule-file`

# License
This work is licensed under the Apache License, Version 2.0. See LICENSE
