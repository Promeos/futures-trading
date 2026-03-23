"""Fetch weather data: temperature, precipitation, and drought indices.

Data sources:
  - Temperature & precipitation: Open-Meteo Historical Archive (ERA5-Land)
  - Drought indices: US Drought Monitor REST API

No API keys required. Each source has a synthetic fallback with fixed
random seed for reproducible development and CI.
"""

import json
import logging
import time

import numpy as np
import pandas as pd
import requests

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    OPEN_METEO_ARCHIVE_URL,
    REGIONS,
)

logger = logging.getLogger(__name__)

# US Drought Monitor base URL
DROUGHT_MONITOR_URL = "https://usdmdataservices.unl.edu/api"

# FIPS codes for drought queries (one representative county per region)
REGION_FIPS = {
    "us_corn_belt": "19153",  # Polk County, IA (Des Moines)
    "great_plains": "20173",  # Sedgwick County, KS (Wichita)
    "california_central_valley": "06019",  # Fresno County, CA
    "gulf_coast": "48201",  # Harris County, TX (Houston)
}

# Drought categories (D0-D4) and their labels
DROUGHT_CATEGORIES = {
    "D0": "abnormally_dry",
    "D1": "moderate_drought",
    "D2": "severe_drought",
    "D3": "extreme_drought",
    "D4": "exceptional_drought",
}


# ---------------------------------------------------------------------------
# Open-Meteo — Temperature & Precipitation
# ---------------------------------------------------------------------------


def _fetch_weather_openmeteo(center, start_date, end_date):
    """Fetch daily temperature and precipitation from Open-Meteo ERA5-Land.

    Args:
        center: Dict with "lat" and "lon" floats (region center point).
        start_date: Start date (datetime.date).
        end_date: End date (datetime.date).

    Returns:
        Dict with keys temp_max, temp_min, temp_mean (°C), precipitation (mm),
        each as a pandas Series indexed by date. None on failure.
    """
    params = {
        "latitude": center["lat"],
        "longitude": center["lon"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "temperature_2m_mean",
                "precipitation_sum",
            ]
        ),
        "timezone": "UTC",
        "temperature_unit": "celsius",
    }

    try:
        resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
        if resp.status_code != 200:
            logger.warning(
                "Open-Meteo weather: returned %s for lat=%.2f lon=%.2f",
                resp.status_code,
                center["lat"],
                center["lon"],
            )
            return None

        data = resp.json()
        daily = data.get("daily", {})
        dates = pd.to_datetime(daily.get("time", []))

        if len(dates) == 0:
            logger.warning("Open-Meteo weather: empty response")
            return None

        def to_series(key):
            vals = daily.get(key, [])
            return pd.Series(
                [v if v is not None else float("nan") for v in vals],
                index=dates,
            )

        return {
            "temp_max": to_series("temperature_2m_max"),
            "temp_min": to_series("temperature_2m_min"),
            "temp_mean": to_series("temperature_2m_mean"),
            "precipitation": to_series("precipitation_sum"),
        }

    except requests.RequestException as exc:
        logger.warning("Open-Meteo weather: request failed: %s", exc)
        return None


def _resample_to_monthly(daily_data):
    """Resample daily weather data to monthly aggregates.

    Args:
        daily_data: Dict of pandas Series (temp_max, temp_min, temp_mean, precipitation).

    Returns:
        Dict with monthly aggregated Series.
    """
    return {
        "temp_max": daily_data["temp_max"].resample("MS").mean(),
        "temp_min": daily_data["temp_min"].resample("MS").mean(),
        "temp_mean": daily_data["temp_mean"].resample("MS").mean(),
        "precipitation": daily_data["precipitation"].resample("MS").sum(),
    }


def _compute_anomalies(monthly_data):
    """Compute temperature and precipitation anomalies from monthly data.

    Anomalies are deviations from the month-of-year mean across all years.

    Args:
        monthly_data: Dict of monthly pandas Series.

    Returns:
        Dict with anomaly Series for temp_mean and precipitation.
    """
    temp = monthly_data["temp_mean"]
    precip = monthly_data["precipitation"]

    # Monthly climatology (mean per calendar month)
    temp_clim = temp.groupby(temp.index.month).transform("mean")
    precip_clim = precip.groupby(precip.index.month).transform("mean")

    return {
        "temp_anomaly": temp - temp_clim,
        "precip_anomaly": precip - precip_clim,
    }


def _fetch_weather_real(regions):
    """Fetch weather data for all regions with monthly aggregation.

    Args:
        regions: Dict of region configs.

    Returns:
        Dict with per-region weather data, or None on failure.
    """
    result = {}

    for key, cfg in regions.items():
        logger.info("Fetching weather for %s", cfg["name"])
        daily = _fetch_weather_openmeteo(
            cfg["center"], DEFAULT_START_DATE, DEFAULT_END_DATE
        )
        if daily is None:
            return None

        monthly = _resample_to_monthly(daily)
        anomalies = _compute_anomalies(monthly)

        dates = [d.strftime("%Y-%m-%d") for d in monthly["temp_mean"].index]

        result[key] = {
            "dates": dates,
            "temp_max": [round(float(v), 1) for v in monthly["temp_max"]],
            "temp_min": [round(float(v), 1) for v in monthly["temp_min"]],
            "temp_mean": [round(float(v), 1) for v in monthly["temp_mean"]],
            "precipitation_mm": [round(float(v), 1) for v in monthly["precipitation"]],
            "temp_anomaly": [round(float(v), 2) for v in anomalies["temp_anomaly"]],
            "precip_anomaly": [round(float(v), 1) for v in anomalies["precip_anomaly"]],
        }

    return result


# ---------------------------------------------------------------------------
# US Drought Monitor
# ---------------------------------------------------------------------------


def _fetch_drought_monitor(fips, start_date, end_date):
    """Fetch drought data from US Drought Monitor for a county.

    The API returns CSV with columns: MapDate, FIPS, County, State,
    None, D0, D1, D2, D3, D4, ValidStart, ValidEnd, StatisticFormatID.

    Args:
        fips: County FIPS code string (e.g., "19153" for Polk County, IA).
        start_date: Start date (datetime.date).
        end_date: End date (datetime.date).

    Returns:
        List of dicts with date and drought category percentages (% area),
        sorted chronologically, or None on failure.
    """
    start_str = start_date.strftime("%m/%d/%Y")
    end_str = end_date.strftime("%m/%d/%Y")

    try:
        url = f"{DROUGHT_MONITOR_URL}/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent"
        params = {
            "aoi": fips,
            "startdate": start_str,
            "enddate": end_str,
            "statisticsType": "1",
        }
        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code != 200:
            logger.warning(
                "Drought Monitor: returned %s for FIPS %s", resp.status_code, fips
            )
            return None

        text = resp.text.strip()
        if not text:
            logger.warning("Drought Monitor: empty response for FIPS %s", fips)
            return None

        # Parse CSV response
        from io import StringIO

        df = pd.read_csv(StringIO(text))

        if df.empty:
            logger.warning("Drought Monitor: no data for FIPS %s", fips)
            return None

        d_code_map = {
            "D0": "abnormally_dry",
            "D1": "moderate_drought",
            "D2": "severe_drought",
            "D3": "extreme_drought",
            "D4": "exceptional_drought",
        }

        records = []
        for _, row in df.iterrows():
            # MapDate is YYYYMMDD integer — convert to ISO string
            map_date = str(int(row["MapDate"]))
            date_str = f"{map_date[:4]}-{map_date[4:6]}-{map_date[6:]}"

            record = {"date": date_str, "none": round(float(row.get("None", 0)), 1)}
            for d_code, label in d_code_map.items():
                record[label] = round(float(row.get(d_code, 0)), 1)
            records.append(record)

        # Sort chronologically (API returns newest first)
        records.sort(key=lambda r: r["date"])
        return records

    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning("Drought Monitor: request failed for FIPS %s: %s", fips, exc)
        return None


def _fetch_drought_real(regions):
    """Fetch drought data for all regions.

    Args:
        regions: Dict of region configs.

    Returns:
        Dict mapping region_key -> list of drought records, or None on failure.
    """
    result = {}
    for key, cfg in regions.items():
        fips = REGION_FIPS.get(key)
        if not fips:
            continue

        logger.info("Fetching drought data for %s (FIPS %s)", cfg["name"], fips)
        records = _fetch_drought_monitor(fips, DEFAULT_START_DATE, DEFAULT_END_DATE)
        if records is None:
            return None
        result[key] = records

    return result


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data(regions):
    """Generate synthetic weather and drought data with seasonal patterns.

    Args:
        regions: Dict of region configs.

    Returns:
        Tuple of (weather_data, drought_data) dicts.
    """
    np.random.seed(43)

    months = pd.date_range(DEFAULT_START_DATE, DEFAULT_END_DATE, freq="MS")
    month_strs = [d.strftime("%Y-%m-%d") for d in months]

    # Regional temperature baselines (°C monthly means, approximate)
    temp_baselines = {
        "us_corn_belt": {"annual_mean": 10.0, "amplitude": 15.0},
        "great_plains": {"annual_mean": 12.0, "amplitude": 16.0},
        "california_central_valley": {"annual_mean": 17.0, "amplitude": 10.0},
        "gulf_coast": {"annual_mean": 20.0, "amplitude": 8.0},
    }

    precip_baselines = {
        "us_corn_belt": {"annual_mean": 80.0, "amplitude": 30.0},
        "great_plains": {"annual_mean": 55.0, "amplitude": 25.0},
        "california_central_valley": {"annual_mean": 35.0, "amplitude": 30.0},
        "gulf_coast": {"annual_mean": 110.0, "amplitude": 40.0},
    }

    n_months = len(months)
    month_idx = np.arange(n_months)

    weather_data = {}
    for key in regions:
        t_base = temp_baselines.get(key, {"annual_mean": 15.0, "amplitude": 12.0})
        p_base = precip_baselines.get(key, {"annual_mean": 70.0, "amplitude": 25.0})

        # Temperature: seasonal sine + noise
        temp_mean = (
            t_base["annual_mean"]
            + t_base["amplitude"] * np.sin(2 * np.pi * (month_idx - 3) / 12)
            + np.random.normal(0, 1.5, n_months)
        )
        temp_max = temp_mean + 5 + np.random.normal(0, 1, n_months)
        temp_min = temp_mean - 5 + np.random.normal(0, 1, n_months)

        # Precipitation: seasonal + noise, non-negative
        precip = (
            p_base["annual_mean"]
            + p_base["amplitude"] * np.sin(2 * np.pi * (month_idx - 1) / 12)
            + np.random.normal(0, 15, n_months)
        )
        precip = np.maximum(precip, 0)

        # Anomalies (small random deviations)
        temp_anom = np.random.normal(0, 1.5, n_months)
        precip_anom = np.random.normal(0, 15, n_months)

        weather_data[key] = {
            "dates": month_strs,
            "temp_max": [round(float(v), 1) for v in temp_max],
            "temp_min": [round(float(v), 1) for v in temp_min],
            "temp_mean": [round(float(v), 1) for v in temp_mean],
            "precipitation_mm": [round(float(v), 1) for v in precip],
            "temp_anomaly": [round(float(v), 2) for v in temp_anom],
            "precip_anomaly": [round(float(v), 1) for v in precip_anom],
        }

    # Synthetic drought data (weekly records)
    weeks = pd.date_range(DEFAULT_START_DATE, DEFAULT_END_DATE, freq="W-TUE")
    drought_data = {}
    for key in regions:
        records = []
        base_drought = np.random.uniform(0, 30)
        for w in weeks:
            base_drought += np.random.normal(0, 3)
            base_drought = np.clip(base_drought, 0, 100)
            none_pct = max(0, 100 - base_drought)
            d0 = min(base_drought, np.random.uniform(10, 40))
            remaining = base_drought - d0
            d1 = min(remaining, np.random.uniform(0, 20)) if remaining > 0 else 0
            remaining -= d1
            d2 = min(remaining, np.random.uniform(0, 10)) if remaining > 0 else 0
            remaining -= d2
            d3 = min(remaining, np.random.uniform(0, 5)) if remaining > 0 else 0
            d4 = max(0, remaining - d3)

            records.append(
                {
                    "date": w.strftime("%Y-%m-%d"),
                    "none": round(none_pct, 1),
                    "abnormally_dry": round(d0, 1),
                    "moderate_drought": round(d1, 1),
                    "severe_drought": round(d2, 1),
                    "extreme_drought": round(d3, 1),
                    "exceptional_drought": round(d4, 1),
                }
            )
        drought_data[key] = records

    logger.info("Generated synthetic weather data for %d regions", len(regions))
    return weather_data, drought_data


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the weather cache file."""
    return CACHE_DIR / "weather.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is within TTL."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached weather data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Weather cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save weather data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached weather data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_weather_data():
    """Fetch weather and drought data for all growing regions.

    Checks cache first, then tries real APIs (Open-Meteo for weather,
    US Drought Monitor for drought indices), falls back to synthetic
    data with fixed seed for reproducibility.

    Returns:
        Dict with two top-level keys::

            {
                "weather": {
                    "<region_key>": {
                        "dates": ["YYYY-MM-DD", ...],      # monthly, 1st of month
                        "temp_max": [float, ...],           # °C, monthly mean of daily max
                        "temp_min": [float, ...],           # °C, monthly mean of daily min
                        "temp_mean": [float, ...],          # °C, monthly mean
                        "precipitation_mm": [float, ...],   # mm, monthly total
                        "temp_anomaly": [float, ...],       # °C, deviation from month-of-year mean
                        "precip_anomaly": [float, ...],     # mm, deviation from month-of-year mean
                    },
                    ...
                },
                "drought": {
                    "<region_key>": [
                        {
                            "date": "YYYY-MM-DD",
                            "none": float,                  # % area not in drought
                            "abnormally_dry": float,        # % area D0
                            "moderate_drought": float,      # % area D1
                            "severe_drought": float,        # % area D2
                            "extreme_drought": float,       # % area D3
                            "exceptional_drought": float,   # % area D4
                        },
                        ...  # weekly records, sorted chronologically
                    ],
                    ...
                },
            }
    """
    if _cache_is_fresh():
        logger.info("Using cached weather data")
        return _load_cache()

    regions = REGIONS
    weather_data = None
    drought_data = None
    use_synthetic = False

    try:
        weather_data = _fetch_weather_real(regions)
        if weather_data is None:
            logger.info("Weather real fetch unavailable, will use synthetic")
            use_synthetic = True
    except Exception:
        logger.exception("Weather fetch error, falling back to synthetic")
        use_synthetic = True

    try:
        drought_data = _fetch_drought_real(regions)
        if drought_data is None:
            logger.info("Drought real fetch unavailable, will use synthetic")
            use_synthetic = True
    except Exception:
        logger.exception("Drought fetch error, falling back to synthetic")
        use_synthetic = True

    if use_synthetic:
        syn_weather, syn_drought = _generate_synthetic_data(regions)
        if weather_data is None:
            weather_data = syn_weather
        if drought_data is None:
            drought_data = syn_drought

    result = {
        "weather": weather_data,
        "drought": drought_data,
    }

    _save_cache(result)
    return result


def load_weather_data():
    """Load weather data from cache without fetching.

    Returns:
        Cached data dict, or None if no cache exists.
    """
    return _load_cache()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    data = fetch_weather_data()
    weather = data["weather"]
    drought = data["drought"]
    for key in weather:
        w = weather[key]
        logger.info(
            "%s: %d months, temp %.1f-%.1f°C, precip %.0f-%.0f mm",
            key,
            len(w["dates"]),
            min(w["temp_mean"]),
            max(w["temp_mean"]),
            min(w["precipitation_mm"]),
            max(w["precipitation_mm"]),
        )
    for key in drought:
        logger.info("%s: %d drought records", key, len(drought[key]))
