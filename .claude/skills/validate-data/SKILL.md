---
name: validate-data
description: Validate pipeline JSON output files in docs/data/ for existence, schema, and data quality
---

# Validate Data

Check the pipeline's JSON output files for correctness.

## Steps

1. Check all 5 expected files exist in `docs/data/`:
   - `summary.json`
   - `commodities.json`
   - `weather.json`
   - `crops.json`
   - `signals.json`

2. Validate each file is parseable JSON:
   ```bash
   python -c "import json, pathlib; [json.loads(p.read_text()) for p in pathlib.Path('docs/data').glob('*.json')]"
   ```

3. Check for invalid values (NaN, Infinity):
   ```bash
   grep -r "NaN\|Infinity" docs/data/
   ```

4. Validate expected top-level keys per file:
   - `summary.json`: `last_updated`, `commodities_tracked`, `active_signals`, `regions_monitored`, `data_sources`
   - `commodities.json`: per-commodity objects with `last_price`, `price_change_pct`, `price_history`
   - `weather.json`: per-region objects with `temperature_anomaly`
   - `crops.json`: per-commodity objects with `yield_history`
   - `signals.json`: array of objects with `commodity`, `message`, `severity`

5. Range checks:
   - Prices: positive, finite
   - NDVI values: in [0, 1]
   - Correlations: in [-1, 1]
   - Severity: one of "high", "medium", "low"
   - Dates: valid ISO 8601 format

6. Cross-file consistency:
   - `summary.commodities_tracked` matches number of commodities in `commodities.json`
   - `summary.active_signals` matches length of `signals.json`
   - `summary.regions_monitored` matches number of regions in `weather.json`

7. Report file sizes and record counts for each file.

8. If any files are missing, suggest running `/run-pipeline` first.