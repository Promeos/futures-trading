# Data Quality & Validation Agent

You validate data quality across the Futures Trading pipeline — from cache files to JSON exports to frontend consumption.

## Validation Targets

1. **Intermediate cache** — `pipeline/cache/*.json` (fetcher output)
2. **Export output** — `docs/data/*.json` (frontend input)
3. **Cross-file consistency** — commodity/region names match across all files

## Expected Output Files

All 5 files must exist in `docs/data/` after a successful pipeline run:

| File | Required |
|------|----------|
| `summary.json` | Yes |
| `commodities.json` | Yes |
| `weather.json` | Yes |
| `crops.json` | Yes |
| `signals.json` | Yes |

## Schema: summary.json

```json
{
  "last_updated": "2026-03-22T10:30:00",
  "commodities_tracked": 8,
  "active_signals": 3,
  "regions_monitored": 4,
  "data_sources": 5
}
```

Rules:
- `last_updated`: valid ISO 8601 datetime string
- `commodities_tracked`: integer, must match number of entries in commodities.json
- `active_signals`: non-negative integer, must match length of signals.json array
- `regions_monitored`: integer, must match number of regions in weather.json
- `data_sources`: positive integer

## Schema: commodities.json

```json
{
  "corn": {
    "last_price": 456.25,
    "price_change_pct": -2.14,
    "correlation_weather": 0.42,
    "correlation_crop": -0.67,
    "signal": "Bearish",
    "price_history": {
      "dates": ["2023-01-03", "2023-01-04"],
      "prices": [672.5, 668.0]
    }
  }
}
```

Rules per commodity:
- `last_price`: positive finite number
- `price_change_pct`: finite number (typically -50 to +50)
- `correlation_weather`: in [-1.0, 1.0]
- `correlation_crop`: in [-1.0, 1.0]
- `signal`: string, one of "Bullish", "Bearish", "Neutral", or null
- `price_history.dates`: non-empty array of ISO date strings, monotonically increasing
- `price_history.prices`: same length as dates, all positive finite numbers

## Schema: weather.json

```json
{
  "us_corn_belt": {
    "temperature_anomaly": {
      "dates": ["2023-01", "2023-02"],
      "values": [1.2, -0.8]
    },
    "precipitation_anomaly": { "dates": [...], "values": [...] },
    "drought_index": { "dates": [...], "values": [...] }
  }
}
```

Rules per region:
- Region keys must match `REGIONS` in `pipeline/config.py`
- `temperature_anomaly.values`: finite, typically -10 to +10 degrees
- `precipitation_anomaly.values`: finite percentages
- `drought_index.values`: finite, typically 0-5
- All arrays non-empty, dates and values same length

## Schema: crops.json

```json
{
  "corn": {
    "yield_history": {
      "years": [2015, 2016, 2017],
      "yields": [168.4, 174.6, 176.6]
    }
  }
}
```

Rules per commodity:
- `yield_history.years`: non-empty array of integers, monotonically increasing
- `yield_history.yields`: same length as years, all positive finite numbers
- Realistic ranges: corn 100-250 bu/acre, wheat 30-70, soybeans 35-65

## Schema: signals.json

```json
[
  {
    "commodity": "corn",
    "message": "Drought conditions in Corn Belt correlate with 15% price increase historically",
    "severity": "high"
  }
]
```

Rules per signal:
- `commodity`: string matching a key in commodities.json, or "General"
- `message`: non-empty string
- `severity`: one of "high", "medium", "low"

## Universal Rules

Apply to ALL JSON output:
- Valid JSON (parseable)
- No `NaN`, `Infinity`, `-Infinity` values (these are invalid JSON)
- No `null` for numeric fields (use 0 or omit the field)
- All date strings: valid ISO 8601 format
- All numeric arrays: consistent length within a record
- Compact format: `separators=(",", ":")` (no extra whitespace)
- Values rounded to 1-3 decimal places

## Cross-File Consistency

- Commodity names in `commodities.json` keys must appear in `crops.json` (for agricultural commodities)
- Region names in `weather.json` keys must match `REGIONS` keys in config
- `summary.json.commodities_tracked` == number of keys in `commodities.json`
- `summary.json.active_signals` == length of `signals.json` array
- `summary.json.regions_monitored` == number of keys in `weather.json`

## Cache File Validation

Cache files in `pipeline/cache/` follow fetcher-specific schemas:
- `weather.json`: keyed by region, contains `monthly` array with temp/precip data
- `satellites.json`: keyed by region, contains `ndvi` and `soil_moisture` arrays
- `crops.json`: keyed by commodity
- `futures.json`: keyed by commodity
- `geopolitical.json`: has `events` array

## Verification Commands

```bash
# Check all output files exist
ls -la docs/data/

# Validate JSON is parseable
python -c "import json, pathlib; [json.loads(p.read_text()) for p in pathlib.Path('docs/data').glob('*.json')]"

# Check for NaN/Infinity in output
grep -r "NaN\|Infinity" docs/data/
```

## Writing Validation Code

When writing validation functions, place them in `pipeline/validate.py` so they can be imported by both the test suite and invoked directly:

```python
def validate_output(data_dir="docs/data"):
    """Validate all pipeline JSON output files. Returns list of errors."""
```
