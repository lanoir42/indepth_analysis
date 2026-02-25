# CLAUDE.md

## Project

indepth-analysis — Python 3.12 project using uv for dependency management.

## Structure

- `src/indepth_analysis/` — main package (src layout)
- `tests/` — pytest test suite

## Commands

- `uv run pytest` — run tests
- `uv run ruff check .` — lint
- `uv run ruff format .` — format
- `uv add <pkg>` / `uv add --dev <pkg>` — add dependencies

## Conventions

- Use `uv` for all dependency and environment management
- Format with ruff (line-length 88, double quotes)
- Lint rules: E, F, I, N, W, UP
- Tests go in `tests/`, use pytest
- Python 3.12+ features are encouraged
