# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --group dev

# Run the application
uv run undock

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run ty check

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/path/to/test_file.py::test_name

# Build Docker image
docker compose build

# Run in Docker
docker compose up
```

## Architecture

A Python TUI application for managing Docker containers.

- **`undock/app.py`** — Main entry point (`main()` function), registered as the `undock` CLI script. Contains the textual `App` class and all UI logic.
- **Framework**: [textual](https://textual.textualize.io/) for the TUI.
- **Docker integration**: Uses the `docker` Python SDK to communicate with the Docker daemon, and `pyyaml` to parse compose files.

Core features:
1. Detect and display services from the current repo's `compose.yml`
2. List all containers (running and stopped), visually distinguishing compose-defined vs. others
3. Per-service actions: start+build, force rebuild, open in browser
4. Live log panel with auto-refresh

**Python 3.14+ is required.** Use `uv` for all dependency management — do not use pip directly.
