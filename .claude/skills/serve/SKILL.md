---
name: serve
description: Start a local development server for the frontend dashboard at localhost:8000
---

# Serve Frontend

Start a local HTTP server to preview the dashboard.

## Steps

1. Check if `docs/data/` contains JSON files:
   ```bash
   ls docs/data/*.json 2>/dev/null
   ```

2. If `docs/data/` is empty or missing JSON files, warn the user:
   > "No data files found in docs/data/. Run `/run-pipeline` first to generate the dashboard data."

3. Start the local server:
   ```bash
   python -m http.server 8000 --directory docs
   ```

4. Print: `Dashboard available at http://localhost:8000`