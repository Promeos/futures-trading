# Integration Agent

You ensure end-to-end data flow works across all pipeline stages and into the frontend.

## Data Flow

```
fetch_weather.py ──────┐
fetch_crops.py ────────┤
fetch_satellites.py ───┼─→ process.py ─→ export.py ─→ docs/data/*.json ─→ dashboard.js
fetch_futures.py ──────┤
fetch_geopolitical.py ─┘
```

## Handoff Points to Verify

### 1. Fetchers -> Cache (`pipeline/cache/`)

Each fetcher writes a JSON cache file. Verify:
- File exists after fetcher runs
- JSON is parseable
- Has expected top-level keys
- Data types are correct

```bash
python -m pipeline.fetch_weather
python -m pipeline.fetch_satellites
python -m pipeline.fetch_crops
python -m pipeline.fetch_futures
python -m pipeline.fetch_geopolitical
ls -la pipeline/cache/
```

### 2. Cache -> process.py

`process.py` loads cache files via `load_<source>_data()` functions. Verify:
- `process.process_all()` can load all available cache files
- Missing cache files are handled gracefully (not all fetchers may have run)
- Output dict has expected structure for export

**Current process.py status:** Only implements crop health scoring (NDVI + soil moisture). Needs to be extended with:
- Weather anomaly summaries per region
- Futures price statistics and change calculations
- Weather-price correlations (temperature anomaly vs. price movement)
- Crop-price correlations (yield deviation vs. price movement)
- Signal generation from correlation thresholds
- Geopolitical event integration

### 3. process.py -> export.py

`export.py` takes processed results and writes 5 JSON files. Verify:
- All 5 files created in `docs/data/`
- Each file matches the schema expected by `dashboard.js`
- Values are rounded (1-3 decimal places)
- Compact JSON format: `separators=(",", ":")`

### 4. export.py -> Frontend (dashboard.js)

The frontend loads JSON via `fetch()` and renders with Plotly. The exact data contract:

**summary.json** (consumed by `renderSummary`):
```javascript
data.last_updated          // ISO datetime string
data.commodities_tracked   // integer
data.active_signals        // integer
data.regions_monitored     // integer
data.data_sources          // integer
```

**commodities.json** (consumed by `renderCommodityTable`, `renderPriceChart`, `renderCorrelationChart`):
```javascript
commodities[name].last_price          // number
commodities[name].price_change_pct    // number
commodities[name].correlation_weather // number
commodities[name].correlation_crop    // number
commodities[name].signal              // string
commodities[name].price_history.dates  // string[]
commodities[name].price_history.prices // number[]
```

**weather.json** (consumed by `renderWeatherChart`):
```javascript
weather[region].temperature_anomaly.dates   // string[]
weather[region].temperature_anomaly.values  // number[]
```

**crops.json** (consumed by `renderCropChart`):
```javascript
crops[commodity].yield_history.years   // number[]
crops[commodity].yield_history.yields  // number[]
```

**signals.json** (consumed by `renderSignals`):
```javascript
signals[i].commodity  // string
signals[i].message    // string
signals[i].severity   // "high" | "medium" | "low"
```

## End-to-End Verification

Run the full pipeline and verify the frontend renders:

```bash
# 1. Run full pipeline
python -m pipeline.export

# 2. Verify output files
ls -la docs/data/
python -c "
import json, pathlib
for f in sorted(pathlib.Path('docs/data').glob('*.json')):
    data = json.loads(f.read_text())
    print(f'{f.name}: {type(data).__name__}, top keys: {list(data.keys()) if isinstance(data, dict) else f\"{len(data)} items\"}')"

# 3. Serve and check frontend
python -m http.server 8000 --directory docs
# Open http://localhost:8000 and verify all charts render
```

## Integration Test (`tests/test_integration.py`)

The integration test should:
1. Run all fetchers (synthetic data, no API keys needed)
2. Run `process.process_all()`
3. Run export to a temp directory
4. Verify all 5 JSON files exist and are valid
5. Verify cross-file consistency (commodity counts match, region names match)
6. Verify no NaN/Infinity in any output

```python
def test_full_pipeline(tmp_path):
    """End-to-end: fetch (synthetic) -> process -> export -> validate."""
    # Run each fetcher
    # Run process
    # Export to tmp_path
    # Validate all output files
```

## Known Gaps (as of project setup)

- `fetch_crops.py`: not yet implemented
- `fetch_futures.py`: not yet implemented
- `fetch_geopolitical.py`: not yet implemented
- `export.py`: not yet implemented
- `process.py`: only has crop health scoring, needs correlations and signals
- `docs/data/`: empty, no JSON files yet
- `crop_health.html`: standalone page, not linked from index.html
