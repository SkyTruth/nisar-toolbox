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
The search and download features of this repository depend on AOIs, currently defined by bounding boxes. AOI information should be stored in the git-ignored `utils/aois.py`. A few test AOIs (wva-test-area, drc-test-area, indian-ocean-test-area) defined in utils/variables.py are always available; an AOI in aois.py with the same name overrides them. Entry format, either a bounding box or a point with a buffer:
- `"aoi-name": {"bbox": "min_lon,min_lat,max_lon,max_lat"},`
- `"aoi-name": {"point": "lon,lat", "buffer_km": 10},`: the bbox is computed as a square `buffer_km` around the point (in the point's UTM zone). If an entry has both, the point and buffer take precedence.

You can append the file directly following that format, or you can run the following code to generate one from bounds or a point plus a km buffer:
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
- `--crop`: crops the output GeoTIFF to the AOI bbox (defaults to keeping the full scene).
- `--keep-h5`: by default each downloaded `.h5` is deleted after converting

How the data is fetched: each `.h5` is several GB, but `nisar_access` only needs one band from it. When that band is small, it is read directly from ASF over HTTP instead of downloading the whole file:

For GCOV, the switch is the number of pixels read: output pixels (crop or full scene, at 10 m for frequency A or 80 m for B) × number of polarizations. Up to 60 Mpx the bands are read remotely; above that the whole `.h5` is downloaded.

| GCOV, one polarization | `--crop` (20 km AOI) | uncropped |
|---|---|---|
| Frequency A | ~4 Mpx: read remotely (~15 s/scene) | ~1,100 Mpx: download whole `.h5` (~80-100 s/scene) |
| Frequency B | ~0.06 Mpx: read remotely (~6 s/scene) | ~18 Mpx: read remotely (~12 s/scene) |

Remote reads are many small sequential requests, so their time grows with the pixels read: about 10 s + 0.9 s per million pixels (a 50 km AOI at frequency A is ~25 Mpx, ~40 s), versus ~80-100 s to download a whole `.h5` whatever is used from it. The crossover is near 80 Mpx; the 60 Mpx limit is `NISAR_REMOTE_MAX_PIXELS` in `utils/variables.py`. Times are from test scenes at ~65 MB/s. Other products read crops remotely and download full scenes. If a scene's `.h5` is already in `data/nisar_h5_scenes/` (e.g. from `--keep-h5`), it is used instead.
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
    - `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT --aoi-name NAME`: crop. `--h5` also accepts ASF download URLs (the `URL` column of the search CSV), which with `--bbox` reads just that area without downloading the file.
    - `--remove-h5`
    - `--out-dir`
    - `--inspect`: print the H5 structure instead of converting

# License
This work is licensed under the Apache License, Version 2.0. See LICENSE
