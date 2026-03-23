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

2. Try running the full pipeline:
   ```bash
   python -m pipeline.export
   ```

3. **If `pipeline.export` fails** (module not yet implemented), fall back to running implemented stages individually:
   ```bash
   python -m pipeline.fetch_weather
   python -m pipeline.fetch_satellites
   python -m pipeline.fetch_crops      # skip if not yet implemented
   python -m pipeline.fetch_futures    # skip if not yet implemented
   python -m pipeline.fetch_geopolitical  # skip if not yet implemented
   python -m pipeline.process
   ```
   Report which stages ran successfully and which are not yet implemented.

4. Verify JSON output files exist and are valid (if export ran):
   - `docs/data/summary.json`
   - `docs/data/commodities.json`
   - `docs/data/weather.json`
   - `docs/data/crops.json`
   - `docs/data/signals.json`

5. Report the key metrics from the pipeline output:
   - Which stages completed
   - Active signals count (if available)
   - Commodities with anomalies (if available)
   - Weather alerts (if available)
   - Cache files produced in `pipeline/cache/`

6. If the user passes arguments like "serve" or "preview", also start the local server:
   ```bash
   python -m http.server 8000 --directory docs
   ```