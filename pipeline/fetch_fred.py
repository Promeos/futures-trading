"""Fetch economic indicators from FRED (Federal Reserve Economic Data).

Data source:
  - FRED API (https://fred.stlouisfed.org/docs/api/fred/)
  - Requires FRED_API_KEY in .env (free registration)

Fetches commodity-related economic time series: price indices,
interest rates, dollar index, and agricultural input costs.
"""

import json
import logging
import os
import time

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    FRED_BASE_URL,
)

logger = logging.getLogger(__name__)

# FRED series relevant to commodity futures analysis
FRED_SERIES = {
    # Commodity prices
    "DCOILWTICO": {"name": "WTI Crude Oil", "unit": "$/barrel", "freq": "daily"},
    "DHHNGSP": {"name": "Henry Hub Natural Gas", "unit": "$/MMBtu", "freq": "daily"},
    # Agricultural inputs
    "WPU0652": {"name": "Fertilizer PPI", "unit": "index", "freq": "monthly"},
    "APU0000711211": {"name": "Diesel Fuel Price", "unit": "$/gallon", "freq": "monthly"},
    # Macro indicators
    "DTWEXBGS": {"name": "Trade-Weighted Dollar Index", "unit": "index", "freq": "daily"},
    "DFF": {"name": "Fed Funds Rate", "unit": "%", "freq": "daily"},
    "T10YIE": {"name": "10Y Breakeven Inflation", "unit": "%", "freq": "daily"},
    # Food prices
    "CPIUFDSL": {"name": "CPI Food", "unit": "index", "freq": "monthly"},
}


# ---------------------------------------------------------------------------
# FRED API
# ---------------------------------------------------------------------------

def _fetch_fred_series(api_key, series_id, start_date, end_date):
    """Fetch a single FRED time series.

    Args:
        api_key: FRED API key.
        series_id: FRED series identifier.
        start_date: Start date.
        end_date: End date.

    Returns:
        Dict with dates and values lists, or None on failure.
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date.isoformat(),
        "observation_end": end_date.isoformat(),
    }

    try:
        resp = requests.get(
            f"{FRED_BASE_URL}/series/observations", params=params, timeout=30
        )
        if resp.status_code != 200:
            logger.warning("FRED: returned %s for %s", resp.status_code, series_id)
            return None

        data = resp.json()
        observations = data.get("observations", [])

        dates = []
        values = []
        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str == ".":
                continue
            try:
                dates.append(obs["date"])
                values.append(round(float(val_str), 3))
            except (ValueError, KeyError):
                continue

        if not dates:
            logger.debug("FRED: no observations for %s", series_id)
            return None

        return {"dates": dates, "values": values}

    except requests.RequestException as exc:
        logger.warning("FRED: request failed for %s: %s", series_id, exc)
        return None


def _fetch_fred_real():
    """Fetch all configured FRED series.

    Returns:
        Dict mapping series_id -> series data, or None on failure.
    """
    load_dotenv()
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.warning(
            "FRED: no API key found. Set FRED_API_KEY in .env. "
            "Get a free key at https://fred.stlouisfed.org/"
        )
        return None

    result = {}
    for series_id, meta in FRED_SERIES.items():
        logger.info("Fetching FRED %s (%s)", series_id, meta["name"])
        data = _fetch_fred_series(api_key, series_id, DEFAULT_START_DATE, DEFAULT_END_DATE)
        if data is not None:
            data["name"] = meta["name"]
            data["unit"] = meta["unit"]
            data["frequency"] = meta["freq"]
            result[series_id] = data
        time.sleep(0.2)

    return result if result else None


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------

def _generate_synthetic_data():
    """Generate synthetic FRED data.

    Uses np.random.seed(47) for reproducibility.

    Returns:
        Dict mapping series_id -> series data.
    """
    np.random.seed(47)
    dates = pd.bdate_range(DEFAULT_START_DATE, DEFAULT_END_DATE)
    date_strs = [d.strftime("%Y-%m-%d") for d in dates]
    n = len(dates)

    baselines = {
        "DCOILWTICO": {"base": 70, "vol": 0.02},
        "DHHNGSP": {"base": 3.5, "vol": 0.03},
        "WPU0652": {"base": 200, "vol": 0.005},
        "APU0000711211": {"base": 3.5, "vol": 0.01},
        "DTWEXBGS": {"base": 110, "vol": 0.003},
        "DFF": {"base": 2.0, "vol": 0.01},
        "T10YIE": {"base": 2.3, "vol": 0.005},
        "CPIUFDSL": {"base": 260, "vol": 0.002},
    }

    result = {}
    for series_id, meta in FRED_SERIES.items():
        base = baselines.get(series_id, {"base": 100, "vol": 0.01})
        returns = np.random.normal(0, base["vol"], n)
        values = base["base"] * np.exp(np.cumsum(returns))

        # Monthly series: take first of each month
        if meta["freq"] == "monthly":
            monthly_idx = [0] + [
                i for i in range(1, n) if dates[i].month != dates[i - 1].month
            ]
            d = [date_strs[i] for i in monthly_idx]
            v = [round(float(values[i]), 3) for i in monthly_idx]
        else:
            d = date_strs
            v = [round(float(x), 3) for x in values]

        result[series_id] = {
            "dates": d,
            "values": v,
            "name": meta["name"],
            "unit": meta["unit"],
            "frequency": meta["freq"],
        }

    logger.info("Generated synthetic FRED data for %d series", len(result))
    return result


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path():
    return CACHE_DIR / "fred.json"


def _cache_is_fresh():
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("FRED cache read failed: %s", exc)
        return None


def _save_cache(data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached FRED data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_fred_data():
    """Fetch FRED economic indicators.

    Checks cache first, then tries FRED API, falls back to synthetic.

    Returns:
        Dict mapping series_id -> time series data.
    """
    if _cache_is_fresh():
        logger.info("Using cached FRED data")
        return _load_cache()

    data = None
    try:
        data = _fetch_fred_real()
    except Exception:
        logger.exception("FRED fetch error, falling back to synthetic")

    if data is None:
        logger.info("Using synthetic FRED data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data


def load_fred_data():
    return _load_cache()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    data = fetch_fred_data()
    for series_id, info in data.items():
        logger.info(
            "%s (%s): %d observations, %s to %s",
            series_id, info["name"], len(info["dates"]),
            info["dates"][0], info["dates"][-1],
        )
