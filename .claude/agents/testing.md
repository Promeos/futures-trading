# Testing & Validation Agent

You write and maintain tests for the Futures Trading project.

## Setup
- Framework: pytest (add to `requirements-dev.txt` if missing)
- Test directory: `tests/` at project root
- Run: `python -m pytest tests/ -v`
- All tests must work with synthetic data — no API credentials required

## Test Structure

```
tests/
  conftest.py                    # Shared fixtures (pipeline results, tmp output dir)
  test_pipeline/
    test_config.py               # Config values are reasonable
    test_fetch_weather.py        # Weather data shape, ranges, no NaN
    test_fetch_crops.py          # Crop data positive, reasonable yields
    test_fetch_satellites.py     # NDVI in [0,1], soil moisture non-negative
    test_fetch_futures.py        # Prices positive, volume non-negative, dates ordered
    test_fetch_geopolitical.py   # Events have required fields, severity in [1,5]
    test_process.py              # Correlations, signals, anomaly detection
    test_export.py               # JSON output keys, valid JSON, rounded values
  test_integration.py            # Full pipeline produces all JSON files
  test_data_quality.py           # Range checks, NaN checks, format validation
```

## Unit Test Targets

**test_config.py:** Commodity list complete, exchange codes valid, region bounds sensible

**test_fetch_weather.py:** Output dict has required keys, temperature anomalies in reasonable range (-10 to 10°C), precipitation anomaly as percentage, no NaN values

**test_fetch_crops.py:** Yield values positive and reasonable (e.g., corn 100-250 bu/acre), acreage positive, production = yield × acreage approximately

**test_fetch_satellites.py:** NDVI values in [0, 1], soil moisture non-negative, correct time dimensions

**test_fetch_futures.py:** Prices positive, volume non-negative, open interest non-negative, dates monotonically increasing

**test_fetch_geopolitical.py:** Events have date/type/region/severity fields, severity in [1,5]

**test_process.py:**
- Correlation coefficients in [-1, 1]
- Signal generation produces expected fields
- Anomaly detection flags values beyond threshold

**test_export.py:** All JSON files created, each is valid JSON, contains expected top-level keys

## Data Quality Checks (test_data_quality.py)
- Futures prices: positive, no inf/NaN
- Weather anomalies: within physical bounds
- Crop yields: positive, historically reasonable ranges
- NDVI: in [0, 1]
- All dates: valid ISO format
- No inf/NaN in any output JSON

## Fixtures (conftest.py)
- `pipeline_results` — run `run_pipeline()` once per session (`scope="session"`)
- `export_dir` — `tmp_path` for JSON export testing
- Individual dataset fixtures: `weather_data`, `crop_data`, `satellite_data`, `futures_data`, `geopolitical_data`