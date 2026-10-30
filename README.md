# About
This is a toolbox for searching, downloading, and accessing NISAR data. It began as a local, proof-of-concept exploration of NISAR data. In its current state, it is intended to assist in SkyTruth's incident response work, to facilitate the incorporation of NISAR data into workflows that currently utilize Sentinel-1 or Sentinel-2 imagery.

A general note on the NISAR data processing described below, nisar_access defaults to Frequency B products. These are lower resolution, and also substantially smaller than Frequency A data. The suggested workflow is to search and evaluate on Frequency B data, and only download the Frequency A as needed.

It also supports ALOS-2 PALSAR-2 ScanSAR L2.2 imagery from JAXA's public S3 bucket (no login needed); see PALSAR-2 Data Access below.

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
This creates `.env` (from `.env.default`), an empty `utils/aois.py`, `archive/`, and the `data/nisar_*` and `data/alos2_*` folders.


Optional: Start Jupyter with the same environment:

```bash
uv run jupyter lab
```

In Cursor or VS Code notebooks, choose the Python environment from this repo's
`.venv`. If prompted for a kernel source, select `Python Environments...`, then
the interpreter under `.venv`.

# Repository Structure

- `src/`: search / download / convert tools, run as modules (see NISAR Data Access and PALSAR-2 Data Access)
- `utils/aois.py`: private AOIs (git-ignored)
- `utils/generate_aoi_details.py`: interactive helper that builds an AOI entry
- `utils/setup.py`: one-time setup; creates `.env`, `utils/aois.py`, `archive/`, and the `data/` folders if missing
- `utils/variables.py`: shared constants: ASF settings, data paths, per-product H5 layouts, `.env` loading, JAXA/PALSAR-2 settings
- `data/`: git-ignored except `.gitkeep`
  - `alos2_geotiffs/`: converted PALSAR-2 gamma0 GeoTIFFs
  - `alos2_granule_files/`: granule CSVs from JAXA S3 searches
  - `alos2_tif_scenes/`: downloaded PALSAR-2 source `.tif` scenes
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

# PALSAR-2 Data Access
ALOS-2 PALSAR-2 ScanSAR L2.2 scenes (Aug 2014 to present) are read from JAXA's public S3 bucket, so no credentials are needed. Searches use the same AOIs as NISAR (see Define AOIs above). All commands below must be run from the repository root.

JAXA's free ScanSAR archive mostly covers tropical land, coasts and polar regions; open ocean and much of the US, Europe and the Middle East are rarely or never observed, so an empty search is common outside those areas.

Any product or figure using this data must credit JAXA (see: `ALOS2_ATTRIBUTION` in `utils/variables.py`).

## Beam Modes
- `WBD`, `WWD`, `VBD`: HH and HV
- `WBS`, `WWS`: HH only; HV is skipped for these scenes


## Search, download, and convert PALSAR-2 data

```bash
uv run python -m src.alos2_access --aoi AOI_NAME --sd YYYY-MM-DD --ed YYYY-MM-DD
```
Flags:
- `--mode MODE [MODE ...]`: only these beam modes (defaults to all)
- `--polarization POL [POL ...]`: `HH` and/or `HV`, one GeoTIFF per polarization (defaults to both)
- `--db`: write gamma0 in dB
- `--mask`: set layover, shadow and invalid pixels to NaN (also downloads each scene's `_MSK.tif`)
- `--crop`: crops the output GeoTIFF to the AOI bbox (defaults to keeping the full scene)
- `--keep-tif`: by default each downloaded source `.tif` is deleted after converting
- `--out-dir`: a user defined path to an output directory, if not defined geotiffs will be written to `data/alos2_geotiffs/`

### Step-by-step runs

1. Search JAXA's S3 archive. Writes a CSV file to `data/alos2_granule_files/`.
    ```bash
    uv run python -m src.alos2_search --aoi AOI_NAME --sd YYYY-MM-DD --ed YYYY-MM-DD
    ```
    OR use an ad-hoc bbox, with an optional `--location` label in the filename:
    ```bash
    uv run python -m src.alos2_search --bbox 'MIN_LON,MIN_LAT,MAX_LON,MAX_LAT' --location LABEL --sd YYYY-MM-DD --ed YYYY-MM-DD
    ```
    `--mode MODE [MODE ...]` limits the search to those beam modes.
2. Download the PALSAR-2 scenes to `data/alos2_tif_scenes/`. Scenes already on disk are skipped.
    ```bash
    uv run python -m src.alos2_dl --granule-file GRANULE_LIST.csv
    ```
    `--granule-file` is required; a bare filename is looked up in `data/alos2_granule_files/`. `--granule NAME [NAME ...]` downloads only those granules from the CSV. `--polarization` picks `HH` and/or `HV` (defaults to both). `--mask` also downloads each scene's `_MSK.tif`, needed for `--mask` at conversion.
3. Convert the source tifs (DN) to calibrated gamma0 GeoTIFFs in `data/alos2_geotiffs/`. A bare filename is looked up in `data/alos2_tif_scenes/`.
    ```bash
    uv run python -m src.alos2_convert_to_tiff --tif SCENE_HH_SLP.tif [SCENE_HV_SLP.tif ...]
    ```
    Flags:
    - `--db`
    - `--mask`: needs the scene's `_MSK.tif` (download it with `src.alos2_dl --mask`)
    - `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT --aoi-name NAME`: crop
    - `--remove-tif`
    - `--out-dir`
    - `--inspect`: print the tif's profile and tags instead of converting

# License
This work is licensed under the Apache License, Version 2.0. See LICENSE
