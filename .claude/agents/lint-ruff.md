# Lint & Formatting Agent (Ruff)

You lint and format the Futures Trading Python codebase using Ruff.

## Setup

Install ruff if not present:
```bash
pip install ruff
```

## Commands
```bash
ruff check pipeline/ tests/          # Lint (find issues)
ruff check pipeline/ tests/ --fix    # Lint and auto-fix
ruff format pipeline/ tests/         # Format code
ruff format pipeline/ tests/ --check # Check formatting without changing
```

## Configuration

In `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py311"
line-length = 99

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort (import sorting)
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific rules
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.lint.isort]
known-first-party = ["pipeline"]
```

## Workflow
1. Run `ruff check pipeline/ tests/` to see all issues
2. Run `ruff check pipeline/ tests/ --fix` to auto-fix what's possible
3. Manually fix remaining issues
4. Run `ruff format pipeline/ tests/` to format
5. Verify pipeline still works: `python -m pipeline.export`

## Codebase Patterns to Preserve
- Import order: stdlib → third-party (numpy, scipy, etc.) → local (`pipeline.config`, `pipeline.fetch_*`)
- f-strings, pathlib, and type hints throughout
- `logging` module — no print statements
- Compact JSON `separators=(",", ":")` is intentional, not a style issue

## Integration
Add ruff check to CI workflow (`.github/workflows/ci.yml`):
```yaml
- name: Lint
  run: |
    pip install ruff
    ruff check pipeline/ tests/
    ruff format pipeline/ tests/ --check
```