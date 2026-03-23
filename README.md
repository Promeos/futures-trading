# Futures Trading: Satellite & Geopolitical Data Connected to Commodity Markets

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![GitHub Pages](https://img.shields.io/badge/Dashboard-Live-blue)](https://promeos.github.io/futures-trading/)

Democratizing Bloomberg Terminal-level data for everyday people. This project connects satellite imagery, weather data, crop yields, and geopolitical events to commodity futures markets through an automated data pipeline and interactive dashboard.

**Live dashboard:** https://promeos.github.io/futures-trading/

## Features

- **Weather monitoring** — Temperature, precipitation, and drought indices from NOAA/ERA5 for major growing regions
- **Crop analytics** — USDA crop production, yield, and acreage data with historical trends
- **Satellite indices** — Vegetation health (NDVI) and soil moisture from satellite imagery
- **Futures prices** — CME/CBOT commodity price data for corn, wheat, soybeans, cotton, sugar, coffee, crude oil, and natural gas
- **Geopolitical tracking** — Trade policy, sanctions, and geopolitical events affecting commodity markets
- **Cross-dataset signals** — Correlation analysis, anomaly detection, and signal generation across all data sources

## Architecture

```
pipeline/               # Python data pipeline
  config.py             # Commodity definitions, API endpoints, region bounds
  fetch_weather.py      # NOAA/ERA5 weather data
  fetch_crops.py        # USDA crop production and yield data
  fetch_satellites.py   # Satellite vegetation indices
  fetch_futures.py      # CME/CBOT futures price data
  fetch_geopolitical.py # Geopolitical events and trade policy data
  process.py            # Correlation analysis, anomaly detection, signal generation
  export.py             # Exports JSON to docs/data/

docs/                   # Static frontend (GitHub Pages)
  index.html            # Dashboard
  css/style.css         # Dark theme design system
  js/dashboard.js       # Chart rendering with Plotly.js
  data/                 # Pipeline JSON output consumed by frontend
```

### Data Flow

```
fetch_weather.py ──────┐
fetch_crops.py ────────┤
fetch_satellites.py ───┼─→ process.py ─→ export.py ─→ docs/data/*.json ─→ dashboard
fetch_futures.py ──────┤
fetch_geopolitical.py ─┘
```

## Getting Started

### Prerequisites

- Python 3.9+

### Installation

```bash
git clone https://github.com/Promeos/futures-trading.git
cd futures-trading
pip install -r requirements.txt
```

### Run the Pipeline

```bash
python -m pipeline.export        # Run full pipeline (fetch + process + export)
```

Individual pipeline stages can be run independently:

```bash
python -m pipeline.fetch_weather
python -m pipeline.fetch_crops
python -m pipeline.fetch_satellites
python -m pipeline.fetch_futures
python -m pipeline.fetch_geopolitical
python -m pipeline.process
```

> Each fetcher includes a synthetic fallback — no API credentials are needed for development.

### Serve the Dashboard Locally

```bash
python -m http.server 8000 --directory docs
```

Then open http://localhost:8000 in your browser.

### Run Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Data Sources & Attribution

| Source | Data | Usage |
|--------|------|-------|
| [USDA NASS](https://quickstats.nass.usda.gov/api) | Crop production, yield, acreage | Subject to NASS API Terms of Service |
| [NOAA](https://www.noaa.gov/) / [ERA5](https://cds.climate.copernicus.eu/) | Temperature, precipitation, drought indices | Weather monitoring for growing regions |
| CME/CBOT | Commodity futures prices | Historical and current market data |

This product uses the NASS API but is not endorsed or certified by NASS. Any processed or derived data (correlations, signals, anomaly detection) is not representative of original NASS data.

## Citation

If you use this project in your research, please cite it:

```bibtex
@software{ortiz_futures_trading_2026,
  author       = {Ortiz, Christopher Logan},
  title        = {Futures Trading: Satellite \& Geopolitical Data Connected to Commodity Markets},
  year         = {2026},
  url          = {https://github.com/Promeos/futures-trading}
}
```

See [CITATION.cff](CITATION.cff) for machine-readable citation metadata.

## License

This work is licensed under a [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/).

See [LICENSE](LICENSE) for the full license text.

## Disclaimer

This project is for educational and research purposes only. It is not financial advice. Data is provided "as is" with no guarantees of accuracy or completeness.
