"""Fetch geopolitical events relevant to commodity futures markets.

Data source:
  - GDELT 2.0 DOC API (https://api.gdeltproject.org/api/v2/doc/doc)
  - No API key required — publicly available
  - Returns news articles matching keyword queries

Fetches trade policy, sanctions, supply disruption, and weather disaster
events that could impact commodity prices.
"""

import json
import logging
import time
from datetime import datetime, timedelta

import numpy as np
import requests

from pipeline.config import (
    CACHE_DIR,
    CACHE_MAX_AGE_HOURS,
    COMMODITIES,
)

logger = logging.getLogger(__name__)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Keyword queries grouped by event type.
# GDELT searches the last 3 months of global news.
EVENT_QUERIES = {
    "trade_policy": {
        "query": "commodity (tariff OR trade war OR trade policy OR import ban OR export ban)",
        "label": "Trade Policy",
        "severity_base": 3,
    },
    "sanctions": {
        "query": "(sanctions OR embargo) (oil OR grain OR agriculture OR energy)",
        "label": "Sanctions & Embargoes",
        "severity_base": 4,
    },
    "supply_disruption": {
        "query": "commodity (supply disruption OR port closure OR shipping blockade OR pipeline shutdown)",
        "label": "Supply Disruption",
        "severity_base": 4,
    },
    "weather_disaster": {
        "query": "(drought OR flood OR hurricane OR frost) (crop OR harvest OR agriculture)",
        "label": "Weather Disaster",
        "severity_base": 3,
    },
    "energy_conflict": {
        "query": "(OPEC OR oil production cut OR natural gas supply) (conflict OR geopolitical)",
        "label": "Energy & Conflict",
        "severity_base": 3,
    },
}

# Map event types to affected commodity categories
EVENT_COMMODITY_MAP = {
    "trade_policy": list(COMMODITIES.keys()),
    "sanctions": ["crude_oil", "natural_gas", "wheat", "corn"],
    "supply_disruption": list(COMMODITIES.keys()),
    "weather_disaster": ["corn", "wheat", "soybeans", "cotton", "sugar", "coffee"],
    "energy_conflict": ["crude_oil", "natural_gas"],
}


# ---------------------------------------------------------------------------
# GDELT API
# ---------------------------------------------------------------------------


def _fetch_gdelt_articles(query, max_records=50):
    """Fetch articles from the GDELT 2.0 DOC API.

    Args:
        query: Search query string.
        max_records: Maximum articles to return (max 250).

    Returns:
        List of article dicts, or None on failure.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max_records),
        "format": "json",
        "sort": "datedesc",
    }

    for attempt in range(3):
        try:
            resp = requests.get(GDELT_DOC_URL, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.info("GDELT: rate limited, waiting %ds...", wait)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.warning(
                    "GDELT: returned %s for query '%s'", resp.status_code, query[:50]
                )
                return None

            data = resp.json()
            return data.get("articles", [])

        except requests.RequestException as exc:
            logger.warning("GDELT: request failed: %s", exc)
            return None
        except (ValueError, KeyError):
            logger.warning("GDELT: invalid JSON response for query '%s'", query[:50])
            return None

    logger.warning("GDELT: exhausted retries for query '%s'", query[:50])
    return None


def _parse_gdelt_date(date_str):
    """Parse GDELT seendate format (YYYYMMDDTHHMMSSZ) to ISO date.

    Args:
        date_str: GDELT date string.

    Returns:
        ISO date string (YYYY-MM-DD), or None.
    """
    try:
        dt = datetime.strptime(date_str, "%Y%m%dT%H%M%SZ")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _fetch_geopolitical_real():
    """Fetch geopolitical events from GDELT for all event categories.

    Returns:
        Dict with events list and category summaries, or None on failure.
    """
    all_events = []

    for event_type, cfg in EVENT_QUERIES.items():
        logger.info("Fetching GDELT events: %s", cfg["label"])
        articles = _fetch_gdelt_articles(cfg["query"], max_records=50)

        if articles is None:
            logger.warning("GDELT: skipping %s", event_type)
            continue

        affected = EVENT_COMMODITY_MAP.get(event_type, [])

        for article in articles:
            date = _parse_gdelt_date(article.get("seendate", ""))
            if not date:
                continue

            all_events.append(
                {
                    "date": date,
                    "type": event_type,
                    "label": cfg["label"],
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "source_country": article.get("sourcecountry", ""),
                    "domain": article.get("domain", ""),
                    "language": article.get("language", ""),
                    "severity": cfg["severity_base"],
                    "affected_commodities": affected,
                }
            )

        logger.info(
            "GDELT %s: %d articles", cfg["label"], len(articles) if articles else 0
        )
        time.sleep(2)  # Rate limit between queries

    if not all_events:
        return None

    # Sort by date descending
    all_events.sort(key=lambda e: e["date"], reverse=True)

    # Build category summary
    category_counts = {}
    for event in all_events:
        t = event["type"]
        category_counts[t] = category_counts.get(t, 0) + 1

    return {
        "events": all_events,
        "category_counts": category_counts,
        "date_range": {
            "start": all_events[-1]["date"],
            "end": all_events[0]["date"],
        },
    }


# ---------------------------------------------------------------------------
# Synthetic Fallback
# ---------------------------------------------------------------------------


def _generate_synthetic_data():
    """Generate synthetic geopolitical events.

    Uses np.random.seed(46) for reproducibility.

    Returns:
        Dict with events list and category summaries.
    """
    np.random.seed(46)

    event_templates = [
        {
            "type": "trade_policy",
            "label": "Trade Policy",
            "severity": 3,
            "titles": [
                "US announces new tariffs on agricultural imports",
                "EU trade negotiations stall over grain subsidies",
                "China retaliates with commodity import restrictions",
                "USMCA trade dispute impacts corn exports",
            ],
        },
        {
            "type": "sanctions",
            "label": "Sanctions & Embargoes",
            "severity": 4,
            "titles": [
                "New sanctions target Russian oil exports",
                "Grain export corridor agreement under threat",
                "Energy sanctions expanded to include LNG",
            ],
        },
        {
            "type": "supply_disruption",
            "label": "Supply Disruption",
            "severity": 4,
            "titles": [
                "Panama Canal restrictions limit grain shipments",
                "Port strike disrupts commodity loading operations",
                "Red Sea shipping diversions increase costs",
            ],
        },
        {
            "type": "weather_disaster",
            "label": "Weather Disaster",
            "severity": 3,
            "titles": [
                "Severe drought threatens Midwest corn belt",
                "Flooding in Brazil delays soybean harvest",
                "Frost damage to Florida sugar crop",
                "Hurricane disrupts Gulf Coast cotton harvest",
            ],
        },
        {
            "type": "energy_conflict",
            "label": "Energy & Conflict",
            "severity": 3,
            "titles": [
                "OPEC+ announces surprise production cut",
                "Middle East tensions push oil prices higher",
                "European natural gas supply concerns mount",
            ],
        },
    ]

    now = datetime.now()
    events = []
    for template in event_templates:
        n_events = np.random.randint(5, 15)
        for _ in range(n_events):
            days_ago = np.random.randint(1, 90)
            date = (now - timedelta(days=int(days_ago))).strftime("%Y-%m-%d")
            title = np.random.choice(template["titles"])
            affected = EVENT_COMMODITY_MAP.get(template["type"], [])

            events.append(
                {
                    "date": date,
                    "type": template["type"],
                    "label": template["label"],
                    "title": title,
                    "url": "",
                    "source_country": np.random.choice(
                        ["United States", "United Kingdom", "China", "India"]
                    ),
                    "domain": "synthetic.example.com",
                    "language": "English",
                    "severity": template["severity"],
                    "affected_commodities": affected,
                }
            )

    events.sort(key=lambda e: e["date"], reverse=True)

    category_counts = {}
    for event in events:
        t = event["type"]
        category_counts[t] = category_counts.get(t, 0) + 1

    logger.info("Generated %d synthetic geopolitical events", len(events))
    return {
        "events": events,
        "category_counts": category_counts,
        "date_range": {
            "start": events[-1]["date"],
            "end": events[0]["date"],
        },
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path():
    """Return the path to the geopolitical cache file."""
    return CACHE_DIR / "geopolitical.json"


def _cache_is_fresh():
    """Check whether the cache file exists and is within TTL."""
    path = _cache_path()
    if not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_cache():
    """Load and return cached geopolitical data, or None."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Geopolitical cache read failed: %s", exc)
        return None


def _save_cache(data):
    """Save geopolitical data to the cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    logger.info("Cached geopolitical data to %s", _cache_path())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_geopolitical_data():
    """Fetch geopolitical events relevant to commodity markets.

    Checks cache first, then tries GDELT 2.0 DOC API (public, no key
    needed, covers last ~3 months of news), falls back to synthetic.

    Returns:
        Dict with event data::

            {
                "events": [
                    {
                        "date": "YYYY-MM-DD",
                        "type": str,         # trade_policy, sanctions, supply_disruption,
                                             # weather_disaster, or energy_conflict
                        "label": str,        # human-readable category name
                        "title": str,        # article headline
                        "url": str,          # source article URL
                        "source_country": str,
                        "domain": str,       # news domain
                        "language": str,
                        "severity": int,     # 1-5 scale (higher = more impactful)
                        "affected_commodities": [str, ...],
                    },
                    ...  # sorted by date descending
                ],
                "category_counts": {"<event_type>": int, ...},
                "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
            }
    """
    if _cache_is_fresh():
        logger.info("Using cached geopolitical data")
        return _load_cache()

    data = None
    try:
        data = _fetch_geopolitical_real()
    except Exception:
        logger.exception("Geopolitical fetch error, falling back to synthetic")

    if data is None:
        logger.info("Using synthetic geopolitical data")
        data = _generate_synthetic_data()

    _save_cache(data)
    return data


def load_geopolitical_data():
    """Load geopolitical data from cache without fetching.

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
    data = fetch_geopolitical_data()
    logger.info(
        "Geopolitical: %d events, %s to %s",
        len(data["events"]),
        data["date_range"]["start"],
        data["date_range"]["end"],
    )
    for cat, count in data["category_counts"].items():
        logger.info("  %s: %d events", cat, count)
