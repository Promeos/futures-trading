---
name: run-tests
description: Run the pytest test suite with optional arguments (e.g., -x for fail-fast, specific test file)
---

# Run Tests

Execute the project test suite and report results.

## Steps

1. Ensure dev dependencies are installed:
   ```bash
   pip install -r requirements-dev.txt
   ```

2. Run the test suite. Pass through any user-provided arguments (e.g., `-x`, `-k "test_weather"`, `--tb=short`, a specific file path):
   ```bash
   python -m pytest tests/ -v $ARGS
   ```

3. Report the results:
   - Total tests run, passed, failed, skipped
   - For failures: show the test name and the assertion error
   - Suggest fixes for common failure patterns

4. If no tests exist yet (empty `tests/` directory), inform the user and suggest using the **testing** agent to create the test suite.
