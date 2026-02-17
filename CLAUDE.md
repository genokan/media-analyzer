# CLAUDE.md — Media Analyzer

## Project Overview
Web-based media file analyzer: scans video/audio/VR libraries via FFprobe, stores metadata in SQLite, serves a filterable web UI.

## Tech Stack
- **Backend**: Python 3.11+, Flask, SQLite
- **Frontend**: Vanilla JS (no build step), Jinja2 templates
- **Media probing**: FFprobe via subprocess
- **Container**: Docker (python:3.11-slim + ffmpeg)
- **CI**: GitHub Actions — ruff lint, pytest, Docker build/push to GHCR

## Project Structure
```
media_analyzer/           # Main Python package
├── __init__.py           # __version__
├── __main__.py           # CLI entrypoint (python -m media_analyzer)
├── cli.py                # CLI argument parsing
├── config.py             # YAML config loading with defaults
├── db.py                 # SQLite database layer
├── scanner.py            # File discovery and FFprobe execution
├── auth.py               # Optional token auth
├── probers/              # Media type-specific metadata extractors
│   ├── base.py           # Base prober class
│   ├── video.py          # Video metadata
│   ├── audio.py          # Audio metadata
│   └── vr.py             # VR detection (filename + embedded metadata)
└── server/               # Flask web application
    ├── app.py            # Flask app factory
    ├── api.py            # JSON API endpoints
    └── templates/        # Jinja2 HTML templates
pyproject.toml            # Build config, ruff settings, pytest config
docker-compose.yml        # Development/example compose
Dockerfile
requirements.txt
tests/
```

## Git Workflow
- **Never commit directly to main** — always use feature/bug/chore branches
- **All work goes through pull requests** to main
- Branch naming: `feature/`, `bug/`, `chore/` prefixes
- Squash merge PRs to keep main history clean
- Repo: `genokan/media-analyzer`

## Development Commands
```bash
# Install dependencies
pip install -r requirements.txt

# Run the app locally
python -m media_analyzer serve

# Run tests
pytest tests/ -v

# Lint and format
ruff check .
ruff format .

# Build Docker image locally
docker build -t media-analyzer .
```

## Code Standards
- **PEP 8** — all code must follow PEP 8
- **Imports at module top** — never in the middle of classes or functions
- **Ruff** enforces: pycodestyle (E/W), pyflakes (F), isort (I), flake8-bugbear (B), pyupgrade (UP)
- **Line length**: 100 characters
- **Target Python**: 3.11+

## UI Design Rules
- **No horizontal scrollbars** on tables — tables must fit within the viewport
- **Long text**: truncate with ellipsis, show full on hover via `title` attribute
- **Column views**: type-specific pages have a column selector with sensible defaults per type

## Documentation
- All examples must be **SFW** — use movies, TV shows, music artists
- Never reference NSFW content in docs, READMEs, or examples

## Docker / Deployment
- Image: `ghcr.io/genokan/media-analyzer`
- CI pushes `:latest` + version tag on merge to main
- Config: optional `config.yaml` mounted at `/config/config.yaml`
- DB stored in `data/` subdirectory (auto-created)
- Media directories mounted read-only

## Key Config Defaults (config.py)
- `server.host`: `0.0.0.0`
- `server.port`: `8080`
- `db_path`: `data/media_analyzer.db`
- `scan_dirs`: `[]` (must be configured)
- Config loaded from `MEDIA_ANALYZER_CONFIG` env var or `config.yaml` in working dir