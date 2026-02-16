# Contributing

Thanks for your interest in contributing to Media Analyzer!

## Development Workflow

1. **Fork** the repository
2. **Create a branch** from `main` for your work:
   - `feature/description` for new features
   - `fix/description` for bug fixes
   - `chore/description` for maintenance tasks
3. **Make your changes** and ensure they pass lint and tests
4. **Open a pull request** against `main`

## Requirements

All PRs must pass the CI checks before merging:

- **Lint**: `ruff check .`
- **Format**: `ruff format --check .`
- **Tests**: `pytest tests/ -v`

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt pytest ruff

# Run the server
python -m media_analyzer serve

# Run tests
pytest tests/ -v

# Lint and format
ruff check .
ruff format .
```

## Code Style

- Python code follows [ruff](https://docs.astral.sh/ruff/) defaults with a 100-character line limit
- Frontend is vanilla JS with no build tools or frameworks
- Keep changes focused — one feature or fix per PR

## Branch Protection

The `main` branch is protected. Direct pushes are not allowed. All changes must go through a pull request with passing CI checks.
