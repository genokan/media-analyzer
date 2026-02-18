# Contributing

Thanks for your interest in contributing to Media Analyzer!

## Development Setup

```bash
# Install uv (package manager)
# macOS: brew install uv
# Other: curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev tools)
uv sync --dev

# Run the server (config.yaml is auto-generated on first run)
uv run python -m media_analyzer serve

# Run tests
uv run pytest tests/ -v

# Lint and format
uv run ruff check .
uv run ruff format .
```

## Development Workflow

1. **Create a branch** from `main`:
   - `feature/description` for new features
   - `bug/description` for bug fixes
   - `chore/description` for maintenance tasks
2. **Make your changes** and ensure they pass lint and tests
3. **Open a pull request** against `main`
4. PR requires review from a CODEOWNER and passing CI checks
5. Merged branches are automatically deleted

## CI Checks

All PRs must pass before merging:

- **Lint**: `uv run ruff check .`
- **Format**: `uv run ruff format --check .`
- **Tests**: `uv run pytest tests/ -v`

## Code Style

- Python code follows [ruff](https://docs.astral.sh/ruff/) defaults with a 100-character line limit
- Frontend is vanilla JS with no build tools or frameworks
- Keep changes focused — one feature or fix per PR

## Releasing

Releases are tag-driven. Version is derived from git tags via `hatch-vcs` — there is no version string to manually update.

**Stable release:**
```bash
git tag v0.2.0
git push origin v0.2.0
```

**Pre-release:**
```bash
git tag v0.2.0-rc.1
git push origin v0.2.0-rc.1
```

When a `v*` tag is pushed, CI will:
1. Run lint and tests
2. Build and push a versioned Docker image to GHCR
3. Create a GitHub Release with auto-generated changelog
4. Pre-release tags (containing `-`) skip updating `:latest` and are marked as pre-release

## Branch Protection

The `main` branch is protected. Direct pushes are not allowed. All changes must go through a pull request with passing CI checks. Tag creation for `v*` tags is restricted to admins.
