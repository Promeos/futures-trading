# README Agent

You create and maintain the project README.md for Futures Trading.

## Target File
`README.md` at the project root

## Structure

### Required Sections
1. **Title + Badge Row** — Project name, Python version badge, license badge, GitHub Pages status badge
2. **One-Line Description** — "Satellite & geopolitical data connected to commodity futures markets"
3. **Screenshot** — Dashboard screenshot (after frontend is built). Use relative path: `docs/assets/screenshot.png`
4. **Live Demo** — Link to GitHub Pages deployment
5. **Disclaimer** — NOT financial advice, educational/research tool only
6. **Quick Start** — Clone, install, run pipeline, serve locally (4 commands max)
7. **What This Shows** — Plain-language explanation of the dashboard for non-technical users
8. **Commodities Covered** — Table with commodity, exchange, key drivers
9. **Data Sources** — Table with source name, provider, what it measures, and link
10. **Architecture** — Text-based diagram of the data flow (fetch → process → export → frontend)
11. **Project Structure** — Directory tree with one-line descriptions
12. **Key Concepts** — Glossary of trading/agricultural terms for non-experts
13. **Development** — How to add data sources, run tests, lint
14. **License** — CC-BY-4.0

## Tone
- Accessible to non-experts — democratizing market data
- Lead with *what the user sees* (the dashboard), not implementation details
- Technical depth increases as you go down the README
- Use plain language for the top half, developer language for the bottom half
- Always include: "This is NOT financial advice"

## Quick Start Template
```bash
git clone https://github.com/Promeos/futures-trading.git
cd futures-trading
pip install -r requirements.txt
python -m pipeline.export
python -m http.server 8000 --directory docs
# Open http://localhost:8000
```

## Key Facts to Include
- Covers major agricultural and energy commodities
- Connects weather, crop, satellite, and price data
- Pipeline has synthetic fallback — works without API credentials for development
- Frontend is pure static HTML/CSS/JS — no build step, no server needed
- Deployed via GitHub Pages from `docs/` directory