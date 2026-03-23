---
name: lint
description: Lint and format Python code with ruff (auto-fix by default, pass --check for CI mode)
---

# Lint & Format

Run ruff to lint and format the Python codebase.

## Steps

1. Ensure ruff is installed:
   ```bash
   pip install ruff
   ```

2. Run linting with auto-fix:
   ```bash
   ruff check pipeline/ tests/ --fix
   ```

3. Run formatting:
   ```bash
   ruff format pipeline/ tests/
   ```

4. Report:
   - Number of issues found and auto-fixed
   - Any remaining issues that need manual fixes
   - Files that were reformatted

5. If the user passes `--check` as an argument, run in check-only mode (no modifications):
   ```bash
   ruff check pipeline/ tests/
   ruff format pipeline/ tests/ --check
   ```