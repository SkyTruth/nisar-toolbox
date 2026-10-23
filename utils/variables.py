import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# TOKEN FOR EARTH DATA LOGIN
EARTHDATA_TOKEN = os.getenv("EARTHDATA_TOKEN")
EARTHDATA_TOKEN_DATE = os.getenv("EARTHDATA_TOKEN_DATE")
EARTHDATA_USERNAME = os.getenv("EARTHDATA_USERNAME")
EARTHDATA_PASSWORD = os.getenv("EARTHDATA_PASSWORD")

# ASF VARIABLES
ASF_API_BASE = "https://api.daac.asf.alaska.edu/services/search/param"
ASF_DATASET = "NISAR"
ASF_DEFAULT_PROCESSING_LEVEL = "GCOV"
ASF_DATA_MATURITY = "PROVISIONAL"
ASF_OUT = "csv"
# First NISAR GCOV granules on ASF are from mid-Oct 2025 (BETA maturity until Jan 2026, PROVISIONAL after)
NISAR_ARCHIVE_START = datetime(2025, 10, 1, tzinfo=UTC)

# DATE AND TIME (UTC) OF DATA REQUEST
REQUEST_DATE = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")

# REPO STRUCTURE
REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_PATH = REPO_ROOT / "archive"
DATA_DIRECTORY = REPO_ROOT / "data"
GRANULE_CSV_PATH = DATA_DIRECTORY / "nisar_granule_files"
NISAR_GEOTIFF_PATH = DATA_DIRECTORY / "nisar_geotiffs"
NISAR_H5_PATH = DATA_DIRECTORY / "nisar_h5_scenes"

# TESTING VARIABLES
TEST_URL = "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/NISAR_L2_PR_GCOV_029_026_D_069_4005_DHDH_A_20260827T001756_20260827T001830_P05023_N_F_J_001/NISAR_L2_PR_GCOV_029_026_D_069_4005_DHDH_A_20260827T001756_20260827T001830_P05023_N_F_J_001.h5"
TEST_XML_URL = "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/NISAR_L2_PR_GCOV_029_026_D_069_4005_DHDH_A_20260827T001756_20260827T001830_P05023_N_F_J_001/NISAR_L2_PR_GCOV_029_026_D_069_4005_DHDH_A_20260827T001756_20260827T001830_P05023_N_F_J_001.h5.iso.xml"

# NISAR PROCESSING DATA (where each product's data lives inside the .h5, how to name the output, and its nodata value)
NISAR_PROCESSING_INFO = {
    "GSLC": {
        "grid": "/science/LSAR/GSLC/grids/frequency{frequency}",
        "dataset": "{polarization}",
        "suffix": "freq{frequency}_{polarization}_intensity",
        "default_polarization": "HH",  # HH or HV
        "nodata": float("nan"),
        "db_accepted": True,
    },
    "GCOV": {
        "grid": "/science/LSAR/GCOV/grids/frequency{frequency}",
        "dataset": "{polarization}",
        "suffix": "freq{frequency}_{polarization}",
        "default_polarization": "HHHH",  # HHHH or HVHV
        "nodata": float("nan"),
        "db_accepted": True,
    },
    "GUNW": {
        "grid": "/science/LSAR/GUNW/grids/frequency{frequency}/wrappedInterferogram",
        "dataset": "{polarization}/coherenceMagnitude",
        "suffix": "freq{frequency}_{polarization}_coherence",
        "default_polarization": "HH",  # HH or HV
        "nodata": float("nan"),
        "db_accepted": False,
    },
    "SME2": {
        "grid": "/science/LSAR/SME2/grids",
        "dataset": "soilMoisture",
        "suffix": "soilMoisture",
        "default_polarization": None,
        "nodata": -9999.0,
        "db_accepted": False,
    },
}

# Define Test AOIs, always available
SEARCH_AOIS = {
    "wva-test-area": {"bbox": "-82.233966,37.994819,-81.8204,38.254771"},
    "drc-test-area": {"bbox": "11.173938,-6.499376,11.718339,-5.954592"},
    "indian-ocean-test-area": {"bbox": "87.547812,5.546815,88.452932,6.45293"},
}

# Import AOIs from git-ignored file (utils/aois.py); same names override the test ones
try:
    from utils.aois import SEARCH_AOIS as LOCAL_AOIS

    SEARCH_AOIS |= LOCAL_AOIS
except ImportError:
    pass
