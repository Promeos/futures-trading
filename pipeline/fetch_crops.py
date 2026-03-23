"""Fetch USDA crop production, yield, and acreage data.

Data source:
  - USDA NASS QuickStats API (https://quickstats.nass.usda.gov/api)
  - Requires NASS_API_KEY in .env (free registration)

Fetches annual state-level data for crop commodities and aggregates
across growing region states. Energy commodities and coffee are skipped.
"""

import json
import logging
import os
import time

import numpy as np
from dotenv import load_dotenv

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    NASS_BASE_URL,
    REGIONS,
)

logger = logging.getLogger(__name__)

# Commodities that have USDA crop data
NASS_COMMODITY_MAP = {
    "corn": {"nass_name": "CORN", "unit": "bu/acre"},
    "wheat": {"nass_name": "WHEAT", "unit": "bu/acre"},
    "soybeans": {"nass_name": "SOYBEANS", "unit": "bu/acre"},
    "cotton": {"nass_name": "COTTON", "unit": "lbs/acre"},
    "sugar": {"nass_name": "SUGARCANE", "unit": "tons/acre"},
}

NASS_STAT_CATEGORIES = ["YIELD", "AREA PLANTED", "AREA HARVESTED", "PRODUCTION"]


# ---------------------------------------------------------------------------
# Region-to-commodity mapping
# ---------------------------------------------------------------------------


def _build_commodity_state_map():
    """Derive which states to query per commodity from REGIONS config.

    Returns:
        Dict mapping commodity -> {"states": [...], "regions": [...]}.
    """
    commodity_map = {}
    for region_key, cfg in REGIONS.items():
        for commodity in cfg.get("commodities", []):
            if commodity not in NASS_COMMODITY_MAP:
                continue
            if commodity not in commodity_map:
                commodity_map[commodity] = {"states": [], "regions": []}
            commodity_map[commodity]["regions"].append(region_key)
            for state in cfg["states"]:
                if state not in commodity_map[commodity]["states"]:
                    commodity_map[commodity]["states"].append(state)
    return commodity_map


# ---------------------------------------------------------------------------
# NASS API
# ---------------------------------------------------------------------------


def _parse_nass_value(val_str):
    """Parse a NASS Value string to float, handling commas and special codes.

    Args:
        val_str: Raw value string from NASS (e.g., "94,641,000", "(D)", "(NA)").

    Returns:
        Float value, or None if the value is withheld/unavailable.
    """
    if not val_str or val_str.strip() in ("(D)", "(NA)", "(Z)", "(S)", ""):
        return None
    try:
        return float(val_str.replace(",", ""))
    except ValueError:
        return None


def _fetch_nass_query(api_key, commodity_desc, stat_cat, states, years):
    """Execute NASS QuickStats API queries, one per state.

    NASS does not accept comma-separated state_alpha values, so we
    query each state individually and merge results.

    Args:
        api_key: NASS API key string.
        commodity_desc: NASS commodity name (e.g., "CORN").
        stat_cat: Statistic category (e.g., "YIELD").
        states: List of state abbreviations.
        years: List of year integers.

    Returns:
        List of record dicts from the NASS API, or None on failure.
    """
    import requests

    all_records = []
    for state in states:
        params = {
            "key": api_key,
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "commodity_desc": commodity_desc,
            "statisticcat_desc": stat_cat,
            "agg_level_desc": "STATE",
            "state_alpha": state,
            "year__GE": str(min(years)),
            "year__LE": str(max(years)),
            "freq_desc": "ANNUAL",
            "reference_period_desc": "YEAR",
            "format": "JSON",
        }

        try:
            resp = requests.get(NASS_BASE_URL, params=params, timeout=30)
            if resp.status_code != 200:
                # Some states may not grow certain crops — that's OK
                logger.debug(
                    "NASS: returned %s for %s/%s/%s",
                    resp.status_code,
                    commodity_desc,
                    stat_cat,
                    state,
                )
                continue

            data = resp.json()
            records = data.get("data", [])
            all_records.extend(records)

        except Exception as exc:
            logger.warning(
                "NASS: query failed for %s/%s/%s: %s",
                commodity_desc,
                stat_cat,
                state,
                exc,
            )
            return None

        time.sleep(0.2)  # Rate limit between state queries

    if not all_records:
        logger.debug(
            "NASS: no records for %s/%s across %s", commodity_desc, stat_cat, states
        )

    return all_records


def _fetch_commodity_data(api_key, commodity, nass_name, states, years):
    """Fetch all statistics for one commodity and aggregate across states.

    For yield, computes a weighted average using acreage harvested as weights.
    For acreage and production, sums across states.

    Args:
        api_key: NASS API key.
        commodity: Our commodity name (e.g., "corn").
        nass_name: NASS commodity_desc (e.g., "CORN").
        states: List of state abbreviations to query.
        years: List of year integers.

    Returns:
        Dict with yield_history, acreage, production for this commodity,
        or None on failure.
    """
    # Fetch all stat categories
    raw = {}
    for stat_cat in NASS_STAT_CATEGORIES:
        records = _fetch_nass_query(api_key, nass_name, stat_cat, states, years)
        if records is None:
            return None
        raw[stat_cat] = records
        time.sleep(0.3)  # Be polite to the API

    # Parse into {year -> {state -> value}} per stat category
    parsed = {}
    for stat_cat, records in raw.items():
        year_state_vals = {}
        for rec in records:
            year = int(rec.get("year", 0))
            state = rec.get("state_alpha", "")
            val = _parse_nass_value(rec.get("Value", ""))
            # Filter to "ALL PRODUCTION PRACTICES" to avoid double-counting
            prodn = rec.get("prodn_practice_desc", "")
            if prodn and prodn != "ALL PRODUCTION PRACTICES":
                continue
            # Filter out silage (CORN, SILAGE) — keep only GRAIN for corn
            short = rec.get("short_desc", "")
            if "SILAGE" in short:
                continue
            if val is not None and year > 0:
                year_state_vals.setdefault(year, {})[state] = val
        parsed[stat_cat] = year_state_vals

    # Aggregate per year
    result_years = sorted(set(y for cat_data in parsed.values() for y in cat_data))

    yields = []
    planted = []
    harvested = []
    production = []

    for year in result_years:
        # Acreage: sum across states
        yr_planted = parsed.get("AREA PLANTED", {}).get(year, {})
        yr_harvested = parsed.get("AREA HARVESTED", {}).get(year, {})
        yr_production = parsed.get("PRODUCTION", {}).get(year, {})
        yr_yield = parsed.get("YIELD", {}).get(year, {})

        planted.append(int(sum(yr_planted.values())) if yr_planted else None)
        harvested.append(int(sum(yr_harvested.values())) if yr_harvested else None)
        production.append(int(sum(yr_production.values())) if yr_production else None)

        # Yield: weighted average by harvested acreage
        if yr_yield and yr_harvested:
            total_weight = 0
            weighted_sum = 0
            for st, yld in yr_yield.items():
                weight = yr_harvested.get(st, 0)
                if weight > 0:
                    weighted_sum += yld * weight
                    total_weight += weight
            if total_weight > 0:
                yields.append(round(weighted_sum / total_weight, 1))
            else:
                yields.append(round(float(np.mean(list(yr_yield.values()))), 1))
        elif yr_yield:
            yields.append(round(float(np.mean(list(yr_yield.values()))), 1))
        else:
            yields.append(None)

    return {
        "yield_history": {"years": result_years, "yields": yields},
        "acreage": {"years": result_years, "planted": planted, "harvested": harvested},
        "production": {"years": result_years, "values": production},
    }


def _fetch_crops_real():
    """Fetch crop data from NASS for all commodities.

    Returns:
        Dict mapping commodity -> crop data, or None on failure.
    """
    load_dotenv()
    api_key = os.getenv("NASS_API_KEY")
    if not api_key:
        logger.warning(
            "NASS: no API key found. Set NASS_API_KEY in .env. "
            "Get a free key at https://quickstats.nass.usda.gov/api"
        )
        return None

    commodity_state_map = _build_commodity_state_map()
    years = list(range(DEFAULT_START_DATE.year, DEFAULT_END_DATE.year + 1))

    result = {}
    for commodity, info in commodity_state_map.items():
        nass_cfg = NASS_COMMODITY_MAP[commodity]
        logger.info("Fetching NASS data for %s (%s)", commodity, info["states"])

        data = _fetch_commodity_data(
            api_key, commodity, nass_cfg["nass_name"], info["states"], years
        )
        if data is None:
            logger.warning("NASS: failed to fetch %s, aborting real fetch", commodity)
            return None

        data["unit"] = nass_cfg["unit"]
        data["regions"] = info["regions"]
        data["states"] = info["states"]
        result[commodity] = data

        time.sleep(0.5)  # Rate limit between commodities

    return result


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data():
    """Generate synthetic USDA crop data with realistic values.

    Uses np.random.seed(44) for reproducibility.

    Returns:
        Dict mapping commodity -> crop data structure.
    """
    np.random.seed(44)
    commodity_state_map = _build_commodity_state_map()
    years = list(range(DEFAULT_START_DATE.year, DEFAULT_END_DATE.year + 1))

    # Realistic baseline values per commodity
    baselines = {
        "corn": {
            "yield": 181.0,
            "planted_m": 94.0,
            "harvested_m": 87.0,
            "yield_std": 4.0,
        },
        "wheat": {
            "yield": 49.5,
            "planted_m": 47.0,
            "harvested_m": 39.0,
            "yield_std": 2.5,
        },
        "soybeans": {
            "yield": 50.6,
            "planted_m": 84.0,
            "harvested_m": 83.0,
            "yield_std": 2.0,
        },
        "cotton": {
            "yield": 848.0,
            "planted_m": 11.0,
            "harvested_m": 9.5,
            "yield_std": 50.0,
        },
        "sugar": {
            "yield": 32.0,
            "planted_m": 0.9,
            "harvested_m": 0.88,
            "yield_std": 2.0,
        },
    }

    result = {}
    for commodity, info in commodity_state_map.items():
        nass_cfg = NASS_COMMODITY_MAP[commodity]
        base = baselines.get(
            commodity, {"yield": 100, "planted_m": 10, "harvested_m": 9, "yield_std": 5}
        )

        n = len(years)
        yields = base["yield"] + np.random.normal(0, base["yield_std"], n)
        planted = (base["planted_m"] * 1e6 * (1 + np.random.normal(0, 0.02, n))).astype(
            int
        )
        harvested = (
            base["harvested_m"] * 1e6 * (1 + np.random.normal(0, 0.02, n))
        ).astype(int)
        production = (yields * harvested).astype(int)

        result[commodity] = {
            "yield_history": {
                "years": years,
                "yields": [round(float(y), 1) for y in yields],
            },
            "acreage": {
                "years": years,
                "planted": [int(p) for p in planted],
                "harvested": [int(h) for h in harvested],
            },
            "production": {
                "years": years,
                "values": [int(p) for p in production],
            },
            "unit": nass_cfg["unit"],
            "regions": info["regions"],
            "states": info["states"],
        }

    logger.info("Generated synthetic crop data for %d commodities", len(result))
    return result


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the crops cache file."""
    return CACHE_DIR / "crops.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is within TTL."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached crops data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Crops cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save crops data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached crops data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_crops_data():
    """Fetch USDA crop data for all growing region commodities.

    Checks cache first, then tries NASS QuickStats API (requires
    NASS_API_KEY in .env), falls back to synthetic data.

    Returns:
        Dict mapping commodity name to crop data::

            {
                "<commodity>": {
                    "yield_history": {
                        "years": [int, ...],    # calendar years
                        "yields": [float, ...], # weighted avg yield (bu/acre or lbs/acre)
                    },
                    "acreage": {
                        "years": [int, ...],
                        "planted": [int, ...],    # acres planted
                        "harvested": [int, ...],  # acres harvested
                    },
                    "production": {
                        "years": [int, ...],
                        "values": [int, ...],     # total production (bushels, lbs, or tons)
                    },
                    "unit": str,       # yield unit (e.g., "bu/acre")
                    "regions": [str],  # growing region keys
                    "states": [str],   # state abbreviations queried
                },
                ...
            }
    """
    if _cache_is_fresh():
        logger.info("Using cached crops data")
        return _load_cache()

    data = None
    try:
        data = _fetch_crops_real()
    except Exception:
        logger.exception("Crops fetch error, falling back to synthetic")

    if data is None:
        logger.info("Using synthetic crop data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data


def load_crops_data():
    """Load crops data from cache without fetching.

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
    data = fetch_crops_data()
    for commodity, info in data.items():
        yh = info["yield_history"]
        logger.info(
            "%s: years=%s, yields=%s %s, states=%s",
            commodity,
            yh["years"],
            yh["yields"],
            info["unit"],
            info["states"],
        )
