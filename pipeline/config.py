"""Commodity definitions, API endpoints, region bounding boxes, and time ranges.

Central configuration for the futures trading data pipeline. All fetchers
import shared constants from this module rather than defining their own.

Constants are organized into:
  - Paths: project layout and cache/output directories
  - Time ranges: default date window for all fetchers
  - Growing regions: geographic bounding boxes tied to commodity production
  - Commodities: exchange and unit metadata for each tracked market
  - API endpoints: base URLs for external data providers
  - Satellite products: MODIS NDVI product and layer identifiers
  - Cache settings: TTL for fetcher cache files
"""

from datetime import date, timedelta
from pathlib import Path

# -- Paths --
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = PROJECT_ROOT / "pipeline"
CACHE_DIR = PIPELINE_DIR / "cache"
DOCS_DATA_DIR = PROJECT_ROOT / "docs" / "data"

# -- Time Ranges --
DEFAULT_START_DATE = date(2023, 1, 1)
DEFAULT_END_DATE = date.today() - timedelta(days=1)  # Yesterday (latest complete day)

# -- Growing Regions --
# Bounding boxes used for satellite area extractions (AppEEARS) and
# weather queries (Open-Meteo). Each region maps to the primary US
# production area for its associated commodities. Bounds are approximate
# rectangles covering the USDA-defined growing zones.
REGIONS = {
    "us_corn_belt": {
        "name": "US Corn Belt",
        "bounds": {
            "min_lat": 39.0,
            "max_lat": 44.0,
            "min_lon": -96.0,
            "max_lon": -84.0,
        },
        "center": {"lat": 41.5, "lon": -90.0},
        "states": ["IA", "IL", "IN", "NE"],
        "commodities": ["corn", "soybeans"],
    },
    "great_plains": {
        "name": "Great Plains",
        "bounds": {
            "min_lat": 34.0,
            "max_lat": 49.0,
            "min_lon": -104.0,
            "max_lon": -96.0,
        },
        "center": {"lat": 41.5, "lon": -100.0},
        "states": ["KS", "ND", "MT", "OK"],
        "commodities": ["wheat"],
    },
    "california_central_valley": {
        "name": "California Central Valley",
        "bounds": {
            "min_lat": 34.5,
            "max_lat": 40.5,
            "min_lon": -122.0,
            "max_lon": -118.5,
        },
        "center": {"lat": 37.5, "lon": -120.25},
        "states": ["CA"],
        "commodities": ["cotton"],
    },
    "gulf_coast": {
        "name": "Gulf Coast",
        "bounds": {
            "min_lat": 27.0,
            "max_lat": 33.0,
            "min_lon": -98.0,
            "max_lon": -80.0,
        },
        "center": {"lat": 31.0, "lon": -91.0},
        "states": ["TX", "LA", "MS", "AL", "FL"],
        "commodities": ["cotton", "sugar"],
    },
}

# -- Commodities --
# Exchange codes: CBOT (Chicago Board of Trade) for grains,
# ICE (Intercontinental Exchange) for softs, NYMEX (New York Mercantile
# Exchange) for energy. Units match standard futures contract specs.
COMMODITIES = {
    "corn": {"exchange": "CBOT", "unit": "bushels"},
    "wheat": {"exchange": "CBOT", "unit": "bushels"},
    "soybeans": {"exchange": "CBOT", "unit": "bushels"},
    "cotton": {"exchange": "ICE", "unit": "pounds"},
    "sugar": {"exchange": "ICE", "unit": "pounds"},
    "coffee": {"exchange": "ICE", "unit": "pounds"},
    "crude_oil": {"exchange": "NYMEX", "unit": "barrels"},
    "natural_gas": {"exchange": "NYMEX", "unit": "MMBtu"},
}

# -- API Endpoints --
# AppEEARS (Application for Extracting and Exploring Analysis Ready Samples):
# NASA's API for MODIS/VIIRS satellite data. Requires Earthdata credentials.
APPEEARS_BASE_URL = "https://appeears.earthdatacloud.nasa.gov/api"
# Open-Meteo Historical Archive: free ERA5-Land reanalysis data (no key needed).
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# USDA NASS QuickStats: crop production, yield, and acreage data (free key required).
NASS_BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET"
# CFTC Commitments of Traders: weekly hedge fund positioning (public, no key needed).
# URL is templated with {year} for annual ZIP archives.
CFTC_COT_BASE_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

# -- Satellite Products --
# MODIS Terra 16-day Vegetation Indices at 1 km resolution (Collection 6.1).
# NDVI (Normalized Difference Vegetation Index) ranges from -0.2 to 1.0,
# where higher values indicate denser, healthier vegetation.
NDVI_PRODUCT = "MOD13A2.061"
NDVI_LAYER = "_1_km_16_days_NDVI"

# -- Cache Settings --
# Fetcher cache files older than this are re-fetched. 24 hours balances
# freshness against API rate limits and development iteration speed.
CACHE_MAX_AGE_HOURS = 24
