# Fetcher Builder Agent

You build the missing data fetcher modules for the Futures Trading pipeline. Follow the established pattern from `fetch_weather.py` and `fetch_satellites.py` exactly.

## Modules to Build

| Module | Data Source | API Key | Synthetic Seed |
|--------|------------|---------|----------------|
| `fetch_crops.py` | USDA NASS QuickStats API | `USDA_API_KEY` in `.env` | 44 |
| `fetch_futures.py` | FRED API (Federal Reserve) | `FRED_API_KEY` in `.env` | 45 |
| `fetch_geopolitical.py` | GDELT Project / synthetic | None required | 46 |
| `export.py` | N/A (reads cache, writes JSON) | N/A | N/A |

## Required Fetcher Pattern

Every fetcher module must follow this structure. Reference `pipeline/fetch_weather.py` as the canonical example.

```python
"""One-line summary of what this fetcher does.

Data sources:
  - Source name: URL or description

Each source has a synthetic fallback with fixed random seed for
reproducible development and CI without API credentials.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    COMMODITIES,
    REGIONS,
)

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path():
    """Return the cache file path."""
    return CACHE_DIR / "<source>.json"

def _cache_is_fresh():
    """Check if cache exists and is within CACHE_MAX_AGE_HOURS."""
    path = _cache_path()
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(hours=CACHE_MAX_AGE_HOURS)

def _load_cache():
    """Load and return cached data."""
    with open(_cache_path()) as f:
        return json.load(f)

def _save_cache(data):
    """Write data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Real API fetch
# ---------------------------------------------------------------------------

def _fetch_<source>_real():
    """Fetch live data from the API. Return dict or None on failure."""
    api_key = os.getenv("<API_KEY_NAME>")
    if not api_key:
        logger.warning("No API key found, will use synthetic data")
        return None
    # ... API calls with error handling ...
    return data


# ---------------------------------------------------------------------------
# Synthetic fallback
# ---------------------------------------------------------------------------

def _generate_synthetic_data():
    """Generate realistic synthetic data with fixed seed."""
    np.random.seed(<SEED>)
    # ... generate data with seasonal patterns, realistic ranges ...
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_<source>_data():
    """Fetch data: cache -> real API -> synthetic fallback.

    Returns:
        Dict with the data structure documented below.
    """
    if _cache_is_fresh():
        logger.info("Loading <source> data from cache")
        return _load_cache()

    data = _fetch_<source>_real()
    if data is None:
        logger.info("Using synthetic <source> data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data

def load_<source>_data():
    """Load cached data without fetching. Returns None if no cache."""
    if _cache_path().exists():
        return _load_cache()
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    data = fetch_<source>_data()
    logger.info("Fetched %d records", len(data.get("dates", data.get("events", []))))
```

## Data Structure Contracts

These MUST match what `docs/js/dashboard.js` expects.

### fetch_crops.py output
```python
{
    "corn": {
        "yield_history": {"years": [2015, ...], "yields": [168.4, ...]},
        "acreage_million": [88.0, ...],
        "production_million_bu": [13602, ...],
    },
    "wheat": { ... },
    "soybeans": { ... },
    # One entry per commodity in COMMODITIES that has crop data
}
```
Dashboard reads: `crops[commodity].yield_history.years` and `.yields`

### fetch_futures.py output
```python
{
    "corn": {
        "last_price": 456.25,
        "price_change_pct": -2.14,
        "price_history": {"dates": ["2023-01-03", ...], "prices": [672.5, ...]},
        "volume": [125000, ...],
        "open_interest": [450000, ...],
    },
    # One entry per commodity in COMMODITIES
}
```
Dashboard reads: `commodities[name].last_price`, `.price_change_pct`, `.price_history.dates`, `.price_history.prices`

### fetch_geopolitical.py output
```python
{
    "events": [
        {
            "date": "2024-03-15",
            "type": "trade_policy",       # trade_policy, sanctions, conflict, weather_disaster, supply_disruption
            "region": "us_corn_belt",
            "commodity_impact": ["corn", "soybeans"],
            "severity": 3,                # 1-5 scale
            "description": "...",
        },
        ...
    ]
}
```

### export.py — Output Files

`export.py` reads all cache files, calls `process.process_all()`, and writes 5 JSON files to `docs/data/`:

| File | Top-level Keys |
|------|---------------|
| `summary.json` | `last_updated`, `commodities_tracked`, `active_signals`, `regions_monitored`, `data_sources` |
| `commodities.json` | Per-commodity: `last_price`, `price_change_pct`, `correlation_weather`, `correlation_crop`, `signal`, `price_history` |
| `weather.json` | Per-region: `temperature_anomaly: {dates, values}`, `precipitation_anomaly`, `drought_index` |
| `crops.json` | Per-commodity: `yield_history: {years, yields}`, `acreage`, `production` |
| `signals.json` | Array of `{commodity, message, severity}` |

## Synthetic Data Guidelines

- Use `np.random.seed(<assigned_seed>)` at the top of `_generate_synthetic_data()`
- Realistic ranges: corn yield 150-200 bu/acre, wheat 40-55, soybeans 45-55
- Futures prices: corn $350-700/bu, wheat $400-900, crude oil $50-120/bbl
- Seasonal patterns: yields peak in harvest season, prices have seasonal cycles
- Date range: `DEFAULT_START_DATE` to `DEFAULT_END_DATE` from config
- Generate daily data for futures, annual for crops, irregular for geopolitical events

## Conventions
- `logging` module — never `print()`
- `pathlib.Path` for all file paths
- Compact JSON: `json.dump(data, f, separators=(",", ":"))`
- Round values to 1-3 decimal places in export
- Import shared constants from `pipeline.config`
