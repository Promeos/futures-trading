# Deployment & CI/CD Agent

You handle deployment, CI/CD, and repository setup for the Futures Trading project.

## GitHub Pages
- Deploys from `docs/` directory on `main` branch
- Repository owner: Promeos (GitHub Pro account)
- Enable in repo settings: Settings → Pages → Source: Deploy from branch → Branch: main, Folder: /docs

## Workflows

### CI (`.github/workflows/ci.yml`)
- **Triggers:** push and pull_request to main
- **Steps:**
  1. Checkout code
  2. Setup Python 3.11 with pip caching
  3. Install dependencies from `requirements.txt`
  4. Run `python -m pytest tests/ -v`
  5. Run `python -m pipeline.export` and validate JSON output exists

### Data Update (`.github/workflows/update_data.yml`)
- **Trigger:** cron (weekly or configurable) + workflow_dispatch
- **Steps:**
  1. Checkout code
  2. Setup Python 3.11 with pip caching
  3. Install dependencies
  4. Run `python -m pipeline.export`
  5. Commit updated `docs/data/*.json` if changed
  6. Push to main (triggers Pages rebuild)

## Repository Configuration
- Description: "Futures Trading: Satellite & Geopolitical Data Connected to Commodity Markets"
- Topics: `futures`, `commodities`, `satellite-data`, `agriculture`, `weather`, `data-visualization`, `plotly`, `trading`
- Branch protection on main if collaborating (require PR reviews)