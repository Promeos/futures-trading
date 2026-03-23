"""Fetch satellite vegetation indices (NDVI) and soil moisture data.

Data sources:
  - NDVI: NASA AppEEARS API (MODIS MOD13A2.061, 1 km 16-day composites)
  - Soil moisture: Open-Meteo Historical Archive (ERA5-Land reanalysis)

Each source has a synthetic fallback with fixed random seed for
reproducible development and CI without API credentials.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from pipeline.config import (
    APPEEARS_BASE_URL,
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    NDVI_LAYER,
    NDVI_PRODUCT,
    OPEN_METEO_ARCHIVE_URL,
    REGIONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dates — canonical 16-day composite calendar
# ---------------------------------------------------------------------------


def _generate_composite_dates(start_date, end_date):
    """Generate 16-day composite dates aligned to MODIS schedule.

    Args:
        start_date: First date (inclusive).
        end_date: Last date (inclusive).

    Returns:
        List of ISO date strings at 16-day intervals.
    """
    dates = []
    current = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day)
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=16)
    return dates


# ---------------------------------------------------------------------------
# AppEEARS — NDVI
# ---------------------------------------------------------------------------


def _appeears_authenticate():
    """Authenticate with NASA AppEEARS and return a Bearer token.

    Tries JWT token first, then falls back to Basic Auth if
    EARTHDATA_PASSWORD is set.

    Returns:
        Bearer token string, or None on failure.
    """
    username = os.getenv("EARTHDATA_USERNAME")
    token = os.getenv("EARTHDATA_KEY")

    # Strategy 1: try JWT as Bearer token by hitting a lightweight endpoint
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(
                f"{APPEEARS_BASE_URL}/task", headers=headers, timeout=15
            )
            if resp.status_code == 200:
                logger.info("AppEEARS: authenticated via JWT token")
                return token
            logger.debug("AppEEARS: JWT token returned %s", resp.status_code)
        except requests.RequestException as exc:
            logger.debug("AppEEARS: JWT probe failed: %s", exc)

    # Strategy 2: Basic Auth with username + password
    password = os.getenv("EARTHDATA_PASSWORD")
    if username and password:
        try:
            resp = requests.post(
                f"{APPEEARS_BASE_URL}/login",
                auth=(username, password),
                timeout=15,
            )
            if resp.status_code == 200:
                bearer = resp.json().get("token")
                if bearer:
                    logger.info("AppEEARS: authenticated via username/password")
                    return bearer
            logger.warning(
                "AppEEARS: login returned %s: %s", resp.status_code, resp.text[:200]
            )
        except requests.RequestException as exc:
            logger.warning("AppEEARS: login request failed: %s", exc)

    if not username:
        logger.warning("AppEEARS: EARTHDATA_USERNAME not set")
    elif not token and not password:
        logger.warning(
            "AppEEARS: set EARTHDATA_KEY (JWT) or EARTHDATA_PASSWORD in .env. "
            "Register at https://appeears.earthdatacloud.nasa.gov/"
        )
    return None


def _bounds_to_geojson_feature(region_key, bounds):
    """Convert a bounding box to a GeoJSON Feature with polygon geometry.

    Args:
        region_key: Region identifier string.
        bounds: Dict with min_lat, max_lat, min_lon, max_lon.

    Returns:
        GeoJSON Feature dict.
    """
    min_lon, min_lat = bounds["min_lon"], bounds["min_lat"]
    max_lon, max_lat = bounds["max_lon"], bounds["max_lat"]
    return {
        "type": "Feature",
        "properties": {"Name": region_key},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]
            ],
        },
    }


def _appeears_submit_ndvi_task(token, regions):
    """Submit an area extraction task to AppEEARS for NDVI across all regions.

    Args:
        token: Bearer token string.
        regions: Dict of region configs from pipeline.config.REGIONS.

    Returns:
        Task ID string, or None on failure.
    """
    features = [
        _bounds_to_geojson_feature(key, cfg["bounds"]) for key, cfg in regions.items()
    ]
    geo = {"type": "FeatureCollection", "features": features}

    start_str = DEFAULT_START_DATE.strftime("%m-%d-%Y")
    end_str = DEFAULT_END_DATE.strftime("%m-%d-%Y")

    payload = {
        "task_type": "area",
        "task_name": f"futures_ndvi_{int(time.time())}",
        "params": {
            "dates": [{"startDate": start_str, "endDate": end_str}],
            "layers": [{"product": NDVI_PRODUCT, "layer": NDVI_LAYER}],
            "output": {"format": {"type": "geotiff"}, "projection": "geographic"},
            "geo": geo,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{APPEEARS_BASE_URL}/task",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code in (200, 202):
            task_id = resp.json().get("task_id")
            logger.info("AppEEARS: submitted NDVI task %s", task_id)
            return task_id
        logger.warning(
            "AppEEARS: task submission returned %s: %s",
            resp.status_code,
            resp.text[:300],
        )
    except requests.RequestException as exc:
        logger.warning("AppEEARS: task submission failed: %s", exc)
    return None


def _appeears_poll_task(token, task_id, timeout_seconds=600, interval=30):
    """Poll an AppEEARS task until completion or timeout.

    Args:
        token: Bearer token string.
        task_id: AppEEARS task ID.
        timeout_seconds: Maximum wait time (default 10 minutes).
        interval: Seconds between polls (default 30).

    Returns:
        True if the task completed, False on timeout or error.
    """
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            # Use /task/{id} endpoint which returns the full task object
            # with a reliable "status" field (pending, queued, processing, done, error)
            resp = requests.get(
                f"{APPEEARS_BASE_URL}/task/{task_id}",
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                task_data = resp.json()
                status = task_data.get("status", "unknown")
                if status == "done":
                    logger.info("AppEEARS: task %s completed", task_id)
                    return True
                if status == "error":
                    error_msg = task_data.get("error", "unknown error")
                    logger.error("AppEEARS: task %s errored: %s", task_id, error_msg)
                    return False
                # Log progress details if available
                progress = task_data.get("progress", {})
                details = progress.get("details", [])
                active_step = next(
                    (d for d in details if 0 < d.get("pct_complete", 0) < 100),
                    None,
                )
                if active_step:
                    logger.info(
                        "AppEEARS: task %s status=%s (%s %d%%), waiting %ds...",
                        task_id,
                        status,
                        active_step["desc"],
                        active_step["pct_complete"],
                        interval,
                    )
                else:
                    logger.info(
                        "AppEEARS: task %s status=%s, waiting %ds...",
                        task_id,
                        status,
                        interval,
                    )
        except requests.RequestException as exc:
            logger.warning("AppEEARS: poll failed: %s", exc)

        time.sleep(interval)

    logger.warning("AppEEARS: task %s timed out after %ds", task_id, timeout_seconds)
    return False


def _appeears_download_ndvi(token, task_id, region_keys):
    """Download and parse NDVI statistics from a completed AppEEARS task.

    AppEEARS area tasks produce a Statistics CSV with columns:
    File Name, Dataset, aid, Date, Count, Minimum, Maximum, Range,
    Mean, Standard Deviation, Variance, ...

    The 'aid' column maps to regions in submission order (aid0001, aid0002, ...).

    Args:
        token: Bearer token string.
        task_id: Completed AppEEARS task ID.
        region_keys: List of region key strings (order matches task submission).

    Returns:
        Dict mapping region_key -> list of NDVI floats (sorted by date),
        or None on failure.
    """
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # List available files for the task
        resp = requests.get(
            f"{APPEEARS_BASE_URL}/bundle/{task_id}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("AppEEARS: bundle listing returned %s", resp.status_code)
            return None

        files = resp.json().get("files", [])

        # Find the Statistics CSV (named like "MOD13A2-061-Statistics.csv")
        stats_files = [
            f
            for f in files
            if f.get("file_name", "").endswith("Statistics.csv")
            and "QA" not in f.get("file_name", "")
        ]

        if not stats_files:
            logger.warning("AppEEARS: no Statistics CSV in task bundle")
            return None

        # Build aid -> region_key mapping (aid0001 = first region, etc.)
        aid_to_region = {f"aid{i + 1:04d}": key for i, key in enumerate(region_keys)}

        # Download and parse the statistics CSV
        file_id = stats_files[0]["file_id"]
        dl_resp = requests.get(
            f"{APPEEARS_BASE_URL}/bundle/{task_id}/{file_id}",
            headers=headers,
            timeout=60,
        )
        if dl_resp.status_code != 200:
            logger.warning(
                "AppEEARS: statistics download returned %s", dl_resp.status_code
            )
            return None

        # Parse CSV using pandas for robust handling of quoted fields
        from io import StringIO

        df = pd.read_csv(StringIO(dl_resp.text))

        # Group by region (aid) and collect mean NDVI sorted by date
        ndvi_by_region = {key: [] for key in region_keys}
        for aid, region_key in aid_to_region.items():
            region_df = df[df["aid"] == aid].sort_values("Date")
            for _, row in region_df.iterrows():
                val = row.get("Mean")
                if pd.notna(val):
                    # NDVI values from AppEEARS are already scaled to [-0.2, 1.0]
                    ndvi_by_region[region_key].append(
                        round(float(max(0.0, min(1.0, val))), 3)
                    )
                else:
                    ndvi_by_region[region_key].append(None)

        total = sum(len(v) for v in ndvi_by_region.values())
        logger.info(
            "AppEEARS: parsed %d NDVI values across %d regions",
            total,
            len(region_keys),
        )
        return ndvi_by_region

    except requests.RequestException as exc:
        logger.warning("AppEEARS: download failed: %s", exc)
        return None


def _appeears_find_existing_task(token):
    """Check for an existing NDVI task that is pending, queued, processing, or done.

    Avoids submitting duplicate tasks when a previous run timed out but the
    task is still processing on AppEEARS servers.

    Args:
        token: Bearer token string.

    Returns:
        Tuple of (task_id, status) if a relevant task is found, else (None, None).
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(f"{APPEEARS_BASE_URL}/task", headers=headers, timeout=15)
        if resp.status_code != 200:
            return None, None

        tasks = resp.json()
        # Look for our NDVI tasks (named futures_ndvi_*)
        for task in sorted(tasks, key=lambda t: t.get("created", ""), reverse=True):
            name = task.get("task_name", "")
            status = task.get("status", "")
            if name.startswith("futures_ndvi_") and status in (
                "pending",
                "queued",
                "processing",
                "done",
            ):
                logger.info(
                    "AppEEARS: found existing task %s (status=%s)",
                    task["task_id"],
                    status,
                )
                return task["task_id"], status
    except requests.RequestException as exc:
        logger.debug("AppEEARS: task listing failed: %s", exc)
    return None, None


def _fetch_ndvi_real(regions):
    """Fetch real NDVI data from AppEEARS for all regions.

    Checks for existing pending/processing tasks before submitting a new one
    to avoid duplicates.

    Args:
        regions: Dict of region configs from pipeline.config.REGIONS.

    Returns:
        Dict mapping region_key -> list of NDVI floats, or None on failure.
    """
    token = _appeears_authenticate()
    if not token:
        return None

    region_keys = list(regions.keys())

    # Check for an existing task first
    task_id, status = _appeears_find_existing_task(token)

    if task_id and status == "done":
        # Task already completed — download directly
        return _appeears_download_ndvi(token, task_id, region_keys)

    if not task_id:
        # No existing task — submit a new one
        task_id = _appeears_submit_ndvi_task(token, regions)
        if not task_id:
            return None

    timeout = int(os.getenv("APPEEARS_TIMEOUT_SECONDS", "1200"))
    if not _appeears_poll_task(token, task_id, timeout_seconds=timeout):
        return None

    return _appeears_download_ndvi(token, task_id, region_keys)


# ---------------------------------------------------------------------------
# Open-Meteo — Soil Moisture
# ---------------------------------------------------------------------------


def _fetch_soil_moisture_openmeteo(center, start_date, end_date):
    """Fetch hourly soil moisture from Open-Meteo and aggregate to daily means.

    Open-Meteo's archive API provides ERA5-Land soil moisture only at hourly
    resolution. We request hourly data and resample to daily means.

    Args:
        center: Dict with "lat" and "lon" floats (region center point).
        start_date: Start date (datetime.date).
        end_date: End date (datetime.date).

    Returns:
        pandas Series with daily soil moisture (m3/m3, 0-7 cm depth layer),
        indexed by date, or None on failure.
    """
    params = {
        "latitude": center["lat"],
        "longitude": center["lon"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": "soil_moisture_0_to_7cm",
        "timezone": "UTC",
    }

    try:
        resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
        if resp.status_code != 200:
            logger.warning(
                "Open-Meteo: returned %s for lat=%.2f lon=%.2f",
                resp.status_code,
                center["lat"],
                center["lon"],
            )
            return None

        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        values = hourly.get("soil_moisture_0_to_7cm", [])

        if not times or not values:
            logger.warning(
                "Open-Meteo: empty response for lat=%.2f lon=%.2f",
                center["lat"],
                center["lon"],
            )
            return None

        series = pd.Series(
            [v if v is not None else float("nan") for v in values],
            index=pd.to_datetime(times),
        )
        # Aggregate hourly to daily means
        daily = series.resample("D").mean()
        return daily

    except requests.RequestException as exc:
        logger.warning("Open-Meteo: request failed: %s", exc)
        return None


def _fetch_soil_moisture_real(regions, composite_dates):
    """Fetch soil moisture for all regions, resampled to 16-day composites.

    Args:
        regions: Dict of region configs.
        composite_dates: List of ISO date strings (16-day intervals).

    Returns:
        Dict mapping region_key -> list of soil moisture floats, or None.
    """
    composite_dt = pd.to_datetime(composite_dates)
    result = {}

    for key, cfg in regions.items():
        logger.info("Fetching soil moisture for %s", cfg["name"])
        series = _fetch_soil_moisture_openmeteo(
            cfg["center"], DEFAULT_START_DATE, DEFAULT_END_DATE
        )
        if series is None:
            return None

        # Resample to 16-day means aligned to composite dates
        resampled = []
        for i, dt in enumerate(composite_dt):
            window_end = (
                composite_dt[i + 1]
                if i + 1 < len(composite_dt)
                else dt + pd.Timedelta(days=16)
            )
            window = series.loc[(series.index >= dt) & (series.index < window_end)]
            if len(window) > 0:
                resampled.append(round(float(window.mean()), 3))
            else:
                resampled.append(None)
        result[key] = resampled

    return result


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data(composite_dates, regions):
    """Generate synthetic NDVI and soil moisture with realistic seasonal patterns.

    Uses np.random.seed(42) for reproducibility. NDVI follows a seasonal
    sine curve peaking in July-August; soil moisture is higher in spring
    and lower in late summer, with regional adjustments.

    Args:
        composite_dates: List of ISO date strings.
        regions: Dict of region configs.

    Returns:
        Tuple of (ndvi_by_region, soil_by_region) dicts.
    """
    np.random.seed(42)
    region_keys = list(regions.keys())
    n_dates = len(composite_dates)

    # Day-of-year for seasonal curve
    doy = np.array(
        [datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday for d in composite_dates]
    )

    # Regional NDVI parameters: (base, amplitude, peak_doy, noise_std)
    ndvi_params = {
        "us_corn_belt": (0.45, 0.35, 200, 0.04),
        "great_plains": (0.35, 0.30, 195, 0.05),
        "california_central_valley": (0.50, 0.15, 150, 0.03),
        "gulf_coast": (0.55, 0.20, 180, 0.04),
    }

    # Regional soil moisture parameters: (base, amplitude, peak_doy, noise_std)
    soil_params = {
        "us_corn_belt": (0.28, 0.08, 120, 0.02),
        "great_plains": (0.20, 0.07, 110, 0.03),
        "california_central_valley": (0.15, 0.05, 90, 0.02),
        "gulf_coast": (0.32, 0.10, 130, 0.03),
    }

    ndvi_by_region = {}
    soil_by_region = {}

    for key in region_keys:
        # NDVI: seasonal sine + noise, clipped to [0, 1]
        base, amp, peak, noise = ndvi_params.get(key, (0.45, 0.25, 200, 0.04))
        seasonal = base + amp * np.sin(2 * np.pi * (doy - peak + 91) / 365)
        ndvi_vals = seasonal + np.random.normal(0, noise, n_dates)
        ndvi_vals = np.clip(ndvi_vals, 0.0, 1.0)
        ndvi_by_region[key] = [round(float(v), 3) for v in ndvi_vals]

        # Soil moisture: seasonal sine + noise, clipped to [0.05, 0.5]
        base, amp, peak, noise = soil_params.get(key, (0.25, 0.07, 120, 0.02))
        seasonal = base + amp * np.sin(2 * np.pi * (doy - peak + 91) / 365)
        soil_vals = seasonal + np.random.normal(0, noise, n_dates)
        soil_vals = np.clip(soil_vals, 0.05, 0.50)
        soil_by_region[key] = [round(float(v), 3) for v in soil_vals]

    logger.info("Generated synthetic satellite data for %d regions", len(region_keys))
    return ndvi_by_region, soil_by_region


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the satellite cache file."""
    return CACHE_DIR / "satellites.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is younger than CACHE_MAX_AGE_HOURS."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached satellite data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save satellite data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path()
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached satellite data to %s", path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_satellite_data():
    """Fetch satellite NDVI and soil moisture data for all growing regions.

    Checks the cache first, then attempts real API calls (AppEEARS for
    NDVI, Open-Meteo for soil moisture). Falls back to synthetic data
    on any failure.

    Returns:
        Dict with the following structure::

            {
                "dates": ["YYYY-MM-DD", ...],  # 16-day composite dates
                "regions": {
                    "<region_key>": {
                        "name": str,    # human-readable region name
                        "lat": float,   # center latitude
                        "lon": float,   # center longitude
                    },
                    ...
                },
                "ndvi": [[float, ...], ...],           # shape [n_dates x n_regions]
                                                       # values in [0, 1], higher = healthier
                "soil_moisture": [[float, ...], ...],  # shape [n_dates x n_regions]
                                                       # volumetric water content (m3/m3)
            }
    """
    # Check cache
    if _cache_is_fresh():
        logger.info("Using cached satellite data")
        return _load_cache()

    load_dotenv()
    regions = REGIONS
    region_keys = list(regions.keys())
    composite_dates = _generate_composite_dates(DEFAULT_START_DATE, DEFAULT_END_DATE)

    # Try real fetch
    ndvi_by_region = None
    soil_by_region = None
    use_synthetic = False

    try:
        ndvi_by_region = _fetch_ndvi_real(regions)
        if ndvi_by_region is None:
            logger.info("NDVI real fetch unavailable, will use synthetic")
            use_synthetic = True
    except Exception:
        logger.exception("NDVI fetch error, falling back to synthetic")
        use_synthetic = True

    try:
        soil_by_region = _fetch_soil_moisture_real(regions, composite_dates)
        if soil_by_region is None:
            logger.info("Soil moisture real fetch unavailable, will use synthetic")
            use_synthetic = True
    except Exception:
        logger.exception("Soil moisture fetch error, falling back to synthetic")
        use_synthetic = True

    # Fall back to synthetic for any failed source
    if use_synthetic:
        syn_ndvi, syn_soil = _generate_synthetic_data(composite_dates, regions)
        if ndvi_by_region is None:
            ndvi_by_region = syn_ndvi
        if soil_by_region is None:
            soil_by_region = syn_soil

    # Assemble output: convert per-region dicts to 2D arrays [time][region]
    n_dates = len(composite_dates)
    ndvi_2d = []
    soil_2d = []
    for t in range(n_dates):
        ndvi_row = []
        soil_row = []
        for key in region_keys:
            ndvi_vals = ndvi_by_region.get(key, [])
            soil_vals = soil_by_region.get(key, [])
            ndvi_row.append(ndvi_vals[t] if t < len(ndvi_vals) else None)
            soil_row.append(soil_vals[t] if t < len(soil_vals) else None)
        ndvi_2d.append(ndvi_row)
        soil_2d.append(soil_row)

    result = {
        "dates": composite_dates,
        "regions": {
            key: {
                "name": cfg["name"],
                "lat": cfg["center"]["lat"],
                "lon": cfg["center"]["lon"],
            }
            for key, cfg in regions.items()
        },
        "ndvi": ndvi_2d,
        "soil_moisture": soil_2d,
    }

    _save_cache(result)
    return result


def load_satellite_data():
    """Load satellite data from cache without fetching.

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
    data = fetch_satellite_data()
    logger.info(
        "Satellite data: %d dates, %d regions, ndvi shape=[%d x %d]",
        len(data["dates"]),
        len(data["regions"]),
        len(data["ndvi"]),
        len(data["ndvi"][0]) if data["ndvi"] else 0,
    )
