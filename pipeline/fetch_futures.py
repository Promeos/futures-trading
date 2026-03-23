"""Fetch commodity futures price data from Yahoo Finance.

Data source:
  - Yahoo Finance via yfinance library (continuous front-month contracts)
  - No API key required

Fetches daily OHLCV data for all configured commodities using continuous
futures contract tickers (e.g., ZC=F for corn).
"""

import json
import logging
import time

import numpy as np
import pandas as pd
import yfinance as yf

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    COMMODITIES,
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
)

logger = logging.getLogger(__name__)

# Yahoo Finance continuous futures tickers
FUTURES_TICKERS = {
    "corn": "ZC=F",
    "wheat": "ZW=F",
    "soybeans": "ZS=F",
    "cotton": "CT=F",
    "sugar": "SB=F",
    "coffee": "KC=F",
    "crude_oil": "CL=F",
    "natural_gas": "NG=F",
}


# ---------------------------------------------------------------------------
# yfinance fetch
# ---------------------------------------------------------------------------


def _fetch_commodity_history(ticker, start_date, end_date):
    """Fetch daily OHLCV data for a single commodity.

    Args:
        ticker: Yahoo Finance ticker string (e.g., "ZC=F").
        start_date: Start date.
        end_date: End date.

    Returns:
        Dict with dates, open, high, low, close, volume lists,
        or None on failure.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=start_date.isoformat(), end=end_date.isoformat())

        if hist.empty:
            logger.warning("yfinance: no data for %s", ticker)
            return None

        return {
            "dates": hist.index.strftime("%Y-%m-%d").tolist(),
            "open": [round(float(v), 2) for v in hist["Open"]],
            "high": [round(float(v), 2) for v in hist["High"]],
            "low": [round(float(v), 2) for v in hist["Low"]],
            "close": [round(float(v), 2) for v in hist["Close"]],
            "volume": [int(v) for v in hist["Volume"]],
        }

    except Exception as exc:
        logger.warning("yfinance: fetch failed for %s: %s", ticker, exc)
        return None


def _fetch_futures_real():
    """Fetch price history for all configured commodities.

    Returns:
        Dict mapping commodity -> price data, or None on failure.
    """
    result = {}
    for commodity, ticker in FUTURES_TICKERS.items():
        if commodity not in COMMODITIES:
            continue

        logger.info("Fetching futures prices for %s (%s)", commodity, ticker)
        data = _fetch_commodity_history(ticker, DEFAULT_START_DATE, DEFAULT_END_DATE)
        if data is None:
            logger.warning("Futures: failed to fetch %s", commodity)
            continue

        data["ticker"] = ticker
        data["exchange"] = COMMODITIES[commodity]["exchange"]
        data["unit"] = COMMODITIES[commodity]["unit"]
        result[commodity] = data

        time.sleep(0.3)  # Be polite

    return result if result else None


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data():
    """Generate synthetic futures price data with realistic values.

    Uses np.random.seed(45) for reproducibility. Prices follow a
    geometric Brownian motion around realistic baselines.

    Returns:
        Dict mapping commodity -> price data structure.
    """
    np.random.seed(45)

    trading_days = pd.bdate_range(DEFAULT_START_DATE, DEFAULT_END_DATE)
    dates = [d.strftime("%Y-%m-%d") for d in trading_days]
    n = len(trading_days)

    # Realistic price baselines and daily volatility
    baselines = {
        "corn": {"price": 450, "vol": 0.015},
        "wheat": {"price": 600, "vol": 0.018},
        "soybeans": {"price": 1200, "vol": 0.014},
        "cotton": {"price": 80, "vol": 0.020},
        "sugar": {"price": 20, "vol": 0.022},
        "coffee": {"price": 180, "vol": 0.025},
        "crude_oil": {"price": 75, "vol": 0.020},
        "natural_gas": {"price": 3.0, "vol": 0.030},
    }

    result = {}
    for commodity, cfg in COMMODITIES.items():
        base = baselines.get(commodity, {"price": 100, "vol": 0.02})

        # Geometric Brownian motion: P(t) = P(0) * exp(sum of daily log returns).
        # This produces realistic price paths with multiplicative (not additive)
        # randomness, preserving the positive price constraint.
        returns = np.random.normal(0, base["vol"], n)
        close = base["price"] * np.exp(np.cumsum(returns))

        # Derive OHLV from close
        daily_range = close * np.random.uniform(0.005, 0.02, n)
        high = close + daily_range * np.random.uniform(0.3, 0.7, n)
        low = close - daily_range * np.random.uniform(0.3, 0.7, n)
        open_price = low + (high - low) * np.random.uniform(0.2, 0.8, n)
        volume = np.random.randint(50000, 300000, n)

        ticker = FUTURES_TICKERS.get(commodity, "?")

        result[commodity] = {
            "dates": dates,
            "open": [round(float(v), 2) for v in open_price],
            "high": [round(float(v), 2) for v in high],
            "low": [round(float(v), 2) for v in low],
            "close": [round(float(v), 2) for v in close],
            "volume": [int(v) for v in volume],
            "ticker": ticker,
            "exchange": cfg["exchange"],
            "unit": cfg["unit"],
        }

    logger.info("Generated synthetic futures data for %d commodities", len(result))
    return result


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the futures cache file."""
    return CACHE_DIR / "futures.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is within TTL."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached futures data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Futures cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save futures data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached futures data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_futures_data():
    """Fetch commodity futures price data for all configured commodities.

    Checks cache first, then tries Yahoo Finance via yfinance (no key
    needed), falls back to synthetic geometric Brownian motion prices.

    Returns:
        Dict mapping commodity name to OHLCV price data::

            {
                "<commodity>": {
                    "dates": ["YYYY-MM-DD", ...],  # trading days
                    "open": [float, ...],           # opening price ($)
                    "high": [float, ...],           # daily high ($)
                    "low": [float, ...],            # daily low ($)
                    "close": [float, ...],          # closing/settlement price ($)
                    "volume": [int, ...],           # contracts traded
                    "ticker": str,    # Yahoo Finance symbol (e.g., "ZC=F")
                    "exchange": str,  # exchange code (CBOT, ICE, NYMEX)
                    "unit": str,      # contract unit (bushels, barrels, etc.)
                },
                ...
            }
    """
    if _cache_is_fresh():
        logger.info("Using cached futures data")
        return _load_cache()

    data = None
    try:
        data = _fetch_futures_real()
    except Exception:
        logger.exception("Futures fetch error, falling back to synthetic")

    if data is None:
        logger.info("Using synthetic futures data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data


def load_futures_data():
    """Load futures data from cache without fetching.

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
    data = fetch_futures_data()
    for commodity, info in data.items():
        dates = info["dates"]
        close = info["close"]
        logger.info(
            "%s (%s): %d days, $%.2f → $%.2f (latest $%.2f)",
            commodity,
            info["ticker"],
            len(dates),
            close[0],
            close[-1],
            close[-1],
        )
