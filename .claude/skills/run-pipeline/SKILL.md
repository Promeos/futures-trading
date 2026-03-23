---
name: run-pipeline
description: Run the full Futures Trading data pipeline (fetch, process, export) and verify outputs
---

# Run Pipeline

Execute the full data pipeline and verify the outputs.

## Steps

1. Install dependencies if needed:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the full pipeline (fetch → process → export):
   ```bash
   python -m pipeline.export
   ```

3. Verify all JSON output files exist and are valid:
   - `docs/data/summary.json`
   - `docs/data/commodities.json`
   - `docs/data/weather.json`
   - `docs/data/crops.json`
   - `docs/data/signals.json`

4. Report the key metrics from the pipeline output:
   - Active signals count
   - Commodities with anomalies
   - Weather alerts

5. If the user passes arguments like "serve" or "preview", also start the local server:
   ```bash
   python -m http.server 8000 --directory docs
   ```