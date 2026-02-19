# Contributing to ergo-agent SDK

Thanks for your interest in contributing! This guide covers setup, testing, and PR workflow.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/ergoplatform/ergo-agent-sdk.git
cd ergo-agent-sdk

# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS/Linux

# Install in editable mode with all dev dependencies
pip install -e ".[all,dev]"
```

## Running Tests

```bash
# Unit tests only (fast, no network)
pytest tests/unit/ -v

# Integration tests (requires internet — hits live APIs)
pytest tests/integration/ -v

# All tests
pytest tests/ -v
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Documentation

```bash
pip install mkdocs-material mkdocstrings[python]
mkdocs serve  # preview at http://localhost:8000
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Run `pytest tests/ -v` and `ruff check src/`
5. Update docs if you changed public APIs
6. Submit a PR with a clear description

## Architecture

See the [Architecture docs](https://ergo-agent.readthedocs.io/architecture/) for how the codebase is structured. Key rule: each layer only depends on the one below it (tools → defi → core).
