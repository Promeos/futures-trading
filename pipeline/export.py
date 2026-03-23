"""Export pipeline results to JSON files for the frontend dashboard.

Orchestrates the full pipeline: fetch all data sources, run processing,
and write 5 JSON files to docs/data/ for the static site.

Output files:
  - summary.json — Headline metrics, active signals, last updated
  - commodities.json — Per-commodity price history and fundamentals
  - weather.json — Regional weather anomalies, drought indices
  - crops.json — Crop yields, acreage, production, health scores
  - signals.json — Cross-dataset correlation signals and alerts
"""

import json
import logging
from datetime import datetime

from pipeline.config import COMMODITIES, DOCS_DATA_DIR, REGIONS
from pipeline.fetch_crops import fetch_crops_data
from pipeline.fetch_cot import fetch_cot_data
from pipeline.fetch_futures import fetch_futures_data
from pipeline.fetch_geopolitical import fetch_geopolitical_data
from pipeline.fetch_satellites import fetch_satellite_data
from pipeline.fetch_weather import fetch_weather_data
from pipeline.process import process_all

logger = logging.getLogger(__name__)


def _write_json(data, filename):
    """Write data to a compact JSON file in docs/data/.

    Args:
        data: Data to serialize.
        filename: Output filename (e.g., "summary.json").
    """
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DATA_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Wrote %s (%d bytes)", path, path.stat().st_size)


def _build_summary(results):
    """Build summary.json with headline metrics.

    Args:
        results: Output of process_all().

    Returns:
        Summary dict.
    """
    signals = results.get("signals", [])
    crop_summary = results.get("crop_health_summary", {})
    futures = results.get("futures", {})

    # Count active signals by severity
    signal_counts = {}
    for sig in signals:
        sev = sig["severity"]
        signal_counts[sev] = signal_counts.get(sev, 0) + 1

    # Latest prices
    latest_prices = {}
    for commodity, fdata in (futures or {}).items():
        close = fdata.get("close", [])
        if close:
            latest_prices[commodity] = {
                "price": close[-1],
                "ticker": fdata.get("ticker", ""),
                "unit": fdata.get("unit", ""),
            }

    # Crop conditions overview
    crop_conditions = {}
    for commodity, summary in crop_summary.items():
        crop_conditions[commodity] = {
            "condition": summary["latest_condition"],
            "trend": summary["trend"],
        }

    return {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active_signals": len(signals),
        "signal_severity_counts": signal_counts,
        "commodities_tracked": len(COMMODITIES),
        "regions_tracked": len(REGIONS),
        "latest_prices": latest_prices,
        "crop_conditions": crop_conditions,
    }


def _build_commodities(results):
    """Build commodities.json with per-commodity data.

    Args:
        results: Output of process_all().

    Returns:
        Commodities dict.
    """
    futures = results.get("futures", {})
    cot = results.get("cot", {})
    crops = results.get("crops", {})
    crop_summary = results.get("crop_health_summary", {})
    price_ndvi = results.get("price_ndvi_correlation", {})
    cot_sentiment = results.get("cot_sentiment", {})

    commodities = {}
    for name, cfg in COMMODITIES.items():
        entry = {
            "exchange": cfg["exchange"],
            "unit": cfg["unit"],
        }

        # Price history
        if futures and name in futures:
            fdata = futures[name]
            entry["price_history"] = {
                "dates": fdata["dates"],
                "close": fdata["close"],
                "volume": fdata["volume"],
            }
            entry["ticker"] = fdata.get("ticker", "")

        # COT positioning
        if cot and name in cot:
            cdata = cot[name]
            entry["cot"] = {
                "dates": cdata["dates"],
                "managed_money_net": cdata["managed_money_net"],
                "managed_money_long": cdata["managed_money_long"],
                "managed_money_short": cdata["managed_money_short"],
            }

        # Crop data
        if crops and name in crops:
            entry["crop_data"] = crops[name]

        # Crop health
        if name in crop_summary:
            entry["crop_health"] = crop_summary[name]

        # Price-NDVI correlation
        if name in price_ndvi:
            entry["price_ndvi_correlation"] = price_ndvi[name]

        # COT sentiment
        if name in cot_sentiment:
            entry["cot_sentiment"] = cot_sentiment[name]

        commodities[name] = entry

    return commodities


def _build_weather(results):
    """Build weather.json from cached weather data.

    Args:
        results: Output of process_all().

    Returns:
        Weather dict with per-region data.
    """
    weather = results.get("weather", {})
    if not weather:
        return {"regions": {}, "last_updated": datetime.utcnow().isoformat()}

    return {
        "regions": weather.get("weather", {}),
        "drought": weather.get("drought", {}),
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _build_crops(results):
    """Build crops.json with crop data and health scores.

    Args:
        results: Output of process_all().

    Returns:
        Crops dict.
    """
    crops = results.get("crops", {})
    crop_health = results.get("crop_health", {})
    crop_summary = results.get("crop_health_summary", {})
    weather_impact = results.get("weather_impact", {})

    output = {}
    for commodity in set(list(crops or {}) + list(crop_health or {})):
        entry = {}
        if crops and commodity in crops:
            entry.update(crops[commodity])
        if crop_health and commodity in crop_health:
            entry["health_history"] = crop_health[commodity]
        if crop_summary and commodity in crop_summary:
            entry["health_summary"] = crop_summary[commodity]
        if weather_impact and commodity in weather_impact:
            entry["weather_impact"] = weather_impact[commodity]
        output[commodity] = entry

    return output


def _build_signals(results):
    """Build signals.json with cross-dataset signals.

    Args:
        results: Output of process_all().

    Returns:
        Signals dict.
    """
    signals = results.get("signals", [])
    geopolitical = results.get("geopolitical", {})

    return {
        "signals": signals,
        "geopolitical_events": geopolitical.get("events", [])[:50]
        if geopolitical
        else [],
        "geopolitical_summary": geopolitical.get("category_counts", {}),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Main export pipeline
# ---------------------------------------------------------------------------


def run_pipeline():
    """Run the full pipeline: fetch → process → export.

    Fetches all data sources, runs processing, and writes 5 JSON
    files to docs/data/ for the frontend.
    """
    logger.info("=== Starting pipeline ===")

    # Fetch all data sources
    logger.info("--- Fetching data ---")
    fetch_satellite_data()
    fetch_weather_data()
    fetch_crops_data()
    fetch_futures_data()
    fetch_cot_data()
    fetch_geopolitical_data()

    # Process
    logger.info("--- Processing ---")
    results = process_all()

    # Export
    logger.info("--- Exporting to docs/data/ ---")
    _write_json(_build_summary(results), "summary.json")
    _write_json(_build_commodities(results), "commodities.json")
    _write_json(_build_weather(results), "weather.json")
    _write_json(_build_crops(results), "crops.json")
    _write_json(_build_signals(results), "signals.json")

    logger.info("=== Pipeline complete ===")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run_pipeline()
