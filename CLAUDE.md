# Futures Trading

Satellite imagery, weather data, crop yields, and geopolitical events connected to commodity futures markets. Democratizing Bloomberg Terminal-level data for everyday people. Deployed as a static GitHub Pages dashboard at https://promeos.github.io/futures-trading/.

## Architecture

```
futures-trading/
  pipeline/               # Python data pipeline
    config.py             # Commodity definitions, API endpoints, region bounds, time ranges
    fetch_weather.py      # NOAA/ERA5 weather data (temperature, precipitation, drought indices)
    fetch_crops.py        # USDA crop production, yield, and acreage data
    fetch_satellites.py   # Satellite vegetation indices (NDVI, soil moisture)
    fetch_futures.py      # CME/CBOT futures price data (corn, wheat, soybeans, etc.)
    fetch_geopolitical.py # Geopolitical events, trade policy, sanctions data
    process.py            # Correlation analysis, anomaly detection, signal generation
    export.py             # Exports JSON files to docs/data/
  docs/                   # GitHub Pages frontend (static site)
    index.html            # Dashboard HTML
    css/style.css         # Dark theme design system (CSS custom properties)
    js/dashboard.js       # Chart rendering, data loading, correlation views
    data/                 # Pipeline JSON output
  .github/workflows/      # CI/CD
  tests/                  # pytest test suite
  requirements.txt        # numpy, pandas, scipy, requests, plotly
  requirements-dev.txt    # pytest, ruff (dev/test dependencies)
  CITATION.cff            # Citation metadata
  .env                    # API credentials (not committed)
```

## Commands

```bash
pip install -r requirements.txt           # Install dependencies
python -m pipeline.export                 # Run full pipeline (fetch + process + export JSON)
python -m http.server 8000 --directory docs  # Serve frontend locally at localhost:8000
python -m pytest tests/ -v                # Run tests
```

Individual pipeline stages:
```bash
python -m pipeline.fetch_weather          # Fetch weather data only
python -m pipeline.fetch_crops            # Fetch USDA crop data only
python -m pipeline.fetch_satellites       # Fetch satellite indices only
python -m pipeline.fetch_futures          # Fetch futures price data only
python -m pipeline.fetch_geopolitical     # Fetch geopolitical data only
python -m pipeline.process                # Run processing only (requires fetched data)
```

## Data Flow

```
fetch_weather.py ──────┐
fetch_crops.py ────────┤
fetch_satellites.py ───┼─→ process.py ─→ export.py ─→ docs/data/*.json ─→ frontend renders
fetch_futures.py ──────┤
fetch_geopolitical.py ─┘
```

Pipeline outputs JSON files to `docs/data/`:
- **summary.json** — Headline metrics, active signals, last updated
- **commodities.json** — Per-commodity price history, fundamentals, correlations
- **weather.json** — Regional weather anomalies, drought indices, forecasts
- **crops.json** — Crop yields, acreage, production estimates vs. USDA projections
- **signals.json** — Cross-dataset correlation signals and anomaly alerts

## Code Conventions

### Python (pipeline/)
- Module-level docstrings explaining data source and purpose
- `logging` module for output — never `print()`
- `pathlib.Path` for all file paths
- Fixed `np.random.seed()` for reproducible synthetic data
- Shared constants imported from `pipeline.config`
- Compact JSON: `json.dump(data, f, separators=(",", ":"))`
- Values rounded to 1-3 decimal places in export

### Frontend (docs/)
- Vanilla JS — no frameworks
- Plotly.js for all charts (loaded via CDN)
- CSS custom properties in `:root` for theming (dark theme)
- Inter font family
- Cards: `border-radius: 12px`, `border: 1px solid var(--border)`
- Responsive breakpoint at 768px

## Deployment

- GitHub Pages serves from `docs/` on the `main` branch
- Live at https://promeos.github.io/futures-trading/
- Any push to `main` that changes `docs/` triggers a Pages rebuild
- Credentials: `.env` with API keys for data providers

## Important Notes

- Each fetcher has a **synthetic fallback** — no API credentials needed for development
- `docs/data/` is the bridge between pipeline and frontend: pipeline writes here, frontend reads
- This is NOT financial advice — educational and research tool only
- Key commodities: corn, wheat, soybeans, cotton, sugar, coffee, crude oil, natural gas
- Growing regions: US Corn Belt, Great Plains, California Central Valley, Gulf Coast
- License: CC-BY-4.0 — attribution required for redistribution
