---
name: fetch-single
description: Run a single pipeline fetcher (weather, satellites, crops, futures, geopolitical) and inspect its output
---

# Fetch Single Data Source

Run one fetcher module and inspect the cached output.

## Steps

1. Accept an argument specifying which fetcher to run. Valid options:
   - `weather`
   - `satellites`
   - `crops`
   - `futures`
   - `geopolitical`

2. If no argument provided, ask the user which fetcher to run.

3. Run the fetcher:
   ```bash
   python -m pipeline.fetch_<name>
   ```

4. Check the cache file exists:
   ```bash
   ls -la pipeline/cache/<name>.json
   ```

5. Inspect the output — report:
   - File size
   - Top-level keys
   - Number of records/dates
   - Date range covered
   - Sample values for key metrics

6. If the fetcher module doesn't exist yet, inform the user:
   > "pipeline/fetch_<name>.py has not been implemented yet. Use the **fetcher-builder** agent to create it."