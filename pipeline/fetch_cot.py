"""Fetch CFTC Commitments of Traders positioning data for commodity futures.

Data source:
  - CFTC Disaggregated COT Reports (https://www.cftc.gov/MarketReports/CommitmentsofTraders)
  - Historical compressed ZIPs: /files/dea/history/fut_disagg_txt_{year}.zip
  - No API key required — publicly available data

Fetches weekly trader positioning (managed money long/short/spreading) for
commodity futures traded on CBOT, ICE, and NYMEX. The "managed money" category
captures hedge fund and CTA positioning.
"""

import json
import logging
import time
import zipfile
from io import BytesIO

import numpy as np

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    CFTC_COT_BASE_URL,
    COMMODITIES,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
)

logger = logging.getLogger(__name__)

# CFTC market name keywords mapped to our commodity names.
# The Disaggregated report uses descriptive market names; we match substrings.
COT_COMMODITY_MAP = {
    "corn": ["CORN"],
    "wheat": ["WHEAT-SRW", "WHEAT-HRW", "WHEAT-HRS"],
    "soybeans": ["SOYBEANS"],
    "cotton": ["COTTON NO. 2"],
    "sugar": ["SUGAR NO. 11"],
    "coffee": ["COFFEE C"],
    "crude_oil": ["CRUDE OIL, LIGHT SWEET"],
    "natural_gas": ["NAT GAS"],
}

# Disaggregated report columns for managed money (hedge funds/CTAs)
MANAGED_MONEY_COLS = {
    "long": "M_Money_Positions_Long_All",
    "short": "M_Money_Positions_Short_All",
    "spreading": "M_Money_Positions_Spread_All",
}


# ---------------------------------------------------------------------------
# CFTC API
# ---------------------------------------------------------------------------


def _fetch_cot_real():
    """Fetch Disaggregated COT data from CFTC historical archives.

    Downloads yearly ZIP files containing CSV data with proper column headers.
    Filters to commodity futures matching our COMMODITIES config.

    Returns:
        Dict mapping commodity -> positioning data, or None on failure.
    """
    import requests

    start_year = DEFAULT_START_DATE.year
    end_year = DEFAULT_END_DATE.year

    frames = []
    for year in range(start_year, end_year + 1):
        url = CFTC_COT_BASE_URL.format(year=year)
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            z = zipfile.ZipFile(BytesIO(resp.content))
            import pandas as pd

            with z.open(z.namelist()[0]) as f:
                df = pd.read_csv(f)
            frames.append(df)
            logger.info("CFTC COT %d: %d records", year, len(df))
            time.sleep(0.3)
        except Exception as exc:
            logger.warning("CFTC COT %d: skipped (%s)", year, exc)

    if not frames:
        logger.error("Could not fetch any CFTC COT data")
        return None

    import pandas as pd

    df = pd.concat(frames, ignore_index=True)

    # Check that expected columns exist
    date_col = "Report_Date_as_YYYY-MM-DD"
    market_col = "Market_and_Exchange_Names"
    if date_col not in df.columns or market_col not in df.columns:
        logger.error(
            "CFTC COT: expected columns not found. Got: %s",
            list(df.columns[:10]),
        )
        return None

    result = {}
    for commodity, keywords in COT_COMMODITY_MAP.items():
        if commodity not in COMMODITIES:
            continue

        mask = (
            df[market_col]
            .str.upper()
            .apply(
                lambda x, kw=keywords: (
                    any(k in x for k in kw) if isinstance(x, str) else False
                )
            )
        )
        sub = df[mask].copy()

        if sub.empty:
            logger.warning(
                "CFTC COT: no records for %s (keywords: %s)", commodity, keywords
            )
            continue

        # Aggregate by date: when multiple contract variants match (e.g.,
        # WHEAT-SRW + WHEAT-HRW + WHEAT-HRS), sum positions per week.
        sub = sub.copy()
        sub["_date"] = pd.to_datetime(sub[date_col])
        for col_key in MANAGED_MONEY_COLS.values():
            sub[col_key] = pd.to_numeric(sub.get(col_key, 0), errors="coerce")

        agg = (
            sub.groupby("_date")
            .agg(
                {
                    MANAGED_MONEY_COLS["long"]: "sum",
                    MANAGED_MONEY_COLS["short"]: "sum",
                    MANAGED_MONEY_COLS["spreading"]: "sum",
                }
            )
            .sort_index()
        )

        dates = agg.index.strftime("%Y-%m-%d").tolist()
        long_pos = agg[MANAGED_MONEY_COLS["long"]].tolist()
        short_pos = agg[MANAGED_MONEY_COLS["short"]].tolist()
        spreading = agg[MANAGED_MONEY_COLS["spreading"]].tolist()
        net = [int(lo - sh) for lo, sh in zip(long_pos, short_pos)]

        result[commodity] = {
            "dates": dates,
            # NaN check via v != v (NaN is the only float not equal to itself)
            "managed_money_long": [int(v) if not (v != v) else None for v in long_pos],
            "managed_money_short": [
                int(v) if not (v != v) else None for v in short_pos
            ],
            "managed_money_spreading": [
                int(v) if not (v != v) else None for v in spreading
            ],
            "managed_money_net": [int(v) if not (v != v) else None for v in net],
            "exchange": COMMODITIES[commodity]["exchange"],
        }
        logger.info(
            "CFTC COT %s: %d weeks, %s to %s",
            commodity,
            len(dates),
            dates[0],
            dates[-1],
        )

    return result if result else None


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data():
    """Generate synthetic COT positioning data with realistic values.

    Uses np.random.seed(55) for reproducibility.

    Returns:
        Dict mapping commodity -> positioning data structure.
    """
    np.random.seed(55)

    import pandas as pd

    dates = (
        pd.date_range(DEFAULT_START_DATE, DEFAULT_END_DATE, freq="W-TUE")
        .strftime("%Y-%m-%d")
        .tolist()
    )
    n = len(dates)

    # Realistic baseline positions per commodity (contracts)
    baselines = {
        "corn": {"long": 350000, "short": 150000, "std": 40000},
        "wheat": {"long": 80000, "short": 100000, "std": 15000},
        "soybeans": {"long": 150000, "short": 80000, "std": 20000},
        "cotton": {"long": 70000, "short": 40000, "std": 10000},
        "sugar": {"long": 200000, "short": 120000, "std": 25000},
        "coffee": {"long": 50000, "short": 30000, "std": 8000},
        "crude_oil": {"long": 400000, "short": 200000, "std": 50000},
        "natural_gas": {"long": 100000, "short": 150000, "std": 20000},
    }

    result = {}
    for commodity, base in baselines.items():
        if commodity not in COMMODITIES:
            continue

        long_pos = np.maximum(
            0, base["long"] + np.cumsum(np.random.normal(0, base["std"] * 0.1, n))
        ).astype(int)
        short_pos = np.maximum(
            0, base["short"] + np.cumsum(np.random.normal(0, base["std"] * 0.1, n))
        ).astype(int)
        spreading = np.maximum(
            0, (long_pos * 0.15 + np.random.normal(0, base["std"] * 0.05, n))
        ).astype(int)
        net = (long_pos - short_pos).tolist()

        result[commodity] = {
            "dates": dates,
            "managed_money_long": long_pos.tolist(),
            "managed_money_short": short_pos.tolist(),
            "managed_money_spreading": spreading.tolist(),
            "managed_money_net": net,
            "exchange": COMMODITIES[commodity]["exchange"],
        }

    logger.info("Generated synthetic COT data for %d commodities", len(result))
    return result


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the COT cache file."""
    return CACHE_DIR / "cot.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is within TTL."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached COT data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("COT cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save COT data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached COT data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_cot_data():
    """Fetch CFTC Commitments of Traders positioning data for all commodities.

    Checks cache first, then tries CFTC Disaggregated COT historical
    archives (public, no key needed), falls back to synthetic data.

    Returns:
        Dict mapping commodity name to weekly positioning data::

            {
                "<commodity>": {
                    "dates": ["YYYY-MM-DD", ...],              # Tuesday report dates
                    "managed_money_long": [int, ...],          # hedge fund long contracts
                    "managed_money_short": [int, ...],         # hedge fund short contracts
                    "managed_money_spreading": [int, ...],     # hedge fund spread contracts
                    "managed_money_net": [int, ...],           # long - short
                    "exchange": str,   # exchange code (CBOT, ICE, NYMEX)
                },
                ...
            }
    """
    if _cache_is_fresh():
        logger.info("Using cached COT data")
        return _load_cache()

    data = None
    try:
        data = _fetch_cot_real()
    except Exception:
        logger.exception("COT fetch error, falling back to synthetic")

    if data is None:
        logger.info("Using synthetic COT data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data


def load_cot_data():
    """Load COT data from cache without fetching.

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
    data = fetch_cot_data()
    for commodity, info in data.items():
        dates = info["dates"]
        logger.info(
            "%s (%s): %d weeks, %s to %s, latest net=%s",
            commodity,
            info["exchange"],
            len(dates),
            dates[0],
            dates[-1],
            info["managed_money_net"][-1],
        )
