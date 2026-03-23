# Pipeline & Data Engineering Agent

You maintain and extend the Futures Trading Python data pipeline in `pipeline/`.

## Current Status

| Module | Status |
|--------|--------|
| `config.py` | Complete — commodities, regions, API endpoints, time ranges |
| `fetch_weather.py` | Complete — Open-Meteo + Drought Monitor, synthetic fallback |
| `fetch_satellites.py` | Complete — AppEEARS NDVI + Open-Meteo soil moisture, synthetic fallback |
| `fetch_crops.py` | **Not yet built** — see fetcher-builder agent |
| `fetch_futures.py` | **Not yet built** — see fetcher-builder agent |
| `fetch_geopolitical.py` | **Not yet built** — see fetcher-builder agent |
| `process.py` | Partial — crop health scoring only, needs correlations and signals |
| `export.py` | **Not yet built** — see fetcher-builder agent |

## Entry Points
```bash
python -m pipeline.export              # Full pipeline: fetch → process → export JSON
python -m pipeline.fetch_weather       # Weather data only
python -m pipeline.fetch_crops         # USDA crop data only
python -m pipeline.fetch_satellites    # Satellite vegetation indices only
python -m pipeline.fetch_futures       # Futures price data only
python -m pipeline.fetch_geopolitical  # Geopolitical data only
python -m pipeline.process             # Processing only (requires fetched data)
```

## Architecture
- All config in `pipeline/config.py`: commodity definitions, API endpoints, growing regions, time ranges
- Each fetcher follows: check if data exists → try real download → fall back to synthetic generation
- `process.py` combines all data sources into correlation analysis and signals
- `export.py` writes JSON files to `docs/data/`

## Key Data Structures

**Weather (fetch_weather.py):**
```python
{"dates": [...], "regions": {...}, "temperature_anomaly_c": [...], "precipitation_anomaly_pct": [...], "drought_index": [...]}
```

**Crops (fetch_crops.py):**
```python
{"commodity": "corn", "years": [...], "yield_bu_acre": [...], "acreage_million": [...], "production_million_bu": [...], "usda_projections": {...}}
```

**Satellites (fetch_satellites.py):**
```python
{"dates": [...], "regions": {...}, "ndvi": [time x region], "soil_moisture": [time x region]}
```

**Futures (fetch_futures.py):**
```python
{"commodity": "corn", "dates": [...], "close": [...], "volume": [...], "open_interest": [...]}
```

**Geopolitical (fetch_geopolitical.py):**
```python
{"events": [{"date": "...", "type": "...", "region": "...", "commodity_impact": [...], "severity": 1-5}]}
```

## Conventions
- `logging` module — never `print()`
- `pathlib.Path` for all file operations
- Fixed `np.random.seed()` for reproducible synthetic data
- Compact JSON: `separators=(",", ":")`
- Round values: 1-3 decimal places in export

## Adding New Data Sources
Follow the existing fetcher pattern:
1. Create `pipeline/fetch_<source>.py` with `fetch_<source>_data()` and `load_<source>_data()`
2. Include synthetic fallback with fixed seed
3. Add constants to `pipeline/config.py`
4. Integrate into `process.py:run_pipeline()`
5. Add relevant fields to `export.py` JSON output
6. Update the frontend data contract

## Key Commodities
| Commodity | Exchange | Unit | Key Growing Region |
|-----------|----------|------|-------------------|
| Corn | CBOT | bushels | US Corn Belt (IA, IL, IN, NE) |
| Wheat | CBOT | bushels | Great Plains (KS, ND, MT, OK) |
| Soybeans | CBOT | bushels | Midwest (IL, IA, MN, IN) |
| Cotton | ICE | pounds | South/Southwest (TX, GA, MS) |
| Sugar | ICE | pounds | Brazil, India, Thailand |
| Coffee | ICE | pounds | Brazil, Colombia, Vietnam |
| Crude Oil | NYMEX | barrels | Global |
| Natural Gas | NYMEX | MMBtu | Global |
