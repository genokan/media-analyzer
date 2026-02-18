# Media Analyzer

A web-based media file analyzer that scans your video, audio, and VR media libraries, extracts metadata using FFprobe, and presents it through a clean, filterable web interface.

## Features

- **Multi-format scanning** — Supports video (MP4, MKV, AVI, MOV, etc.), audio (FLAC, MP3, WAV, OGG, etc.), and VR media
- **Type-specific pages** — Dedicated views for Videos, VR, and Audio with columns tailored to each media type
- **VR metadata detection** — Identifies VR content from embedded metadata and filename patterns, calculates per-eye resolution, tracks metadata completeness
- **Column customization** — Toggle which columns are visible per page, preferences saved in your browser
- **Search, filter, and group** — Filter by codec, resolution, lossless/lossy; group by resolution or artist
- **Expandable detail rows** — Click any row to see all extracted metadata
- **Incremental scanning** — Only re-scans files that have changed since the last scan
- **Docker-ready** — Ships with a Dockerfile and docker-compose for easy deployment
- **Optional auth** — Protect your instance with a secret token

## Quick Start

### Docker Compose (Recommended)

1. Copy the example config and edit it with your media directories:

```bash
cp config.yaml.example config.yaml
```

2. Edit `docker-compose.yml` to mount your media directories as read-only volumes.

3. Start it up:

```bash
docker compose up -d
```

4. Open `http://localhost:8080` and click **Scan All** to index your media.

### Running Locally

```bash
# Install uv (if not already installed)
# macOS: brew install uv
# Other: curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Start the server (config.yaml is auto-generated on first run)
uv run python -m media_analyzer serve
```

Edit the generated `config.yaml` to add your media directories, then restart.

## Pages

### Dashboard (`/`)
Overview of all media with stats cards showing counts by type. Cards link to type-specific pages.

### Videos (`/videos`)
Video files with columns for resolution, codec, frame rate, bitrate, and bitrate-per-pixel. Filter by codec and resolution, group by resolution.

### VR (`/vr`)
VR video files with columns for total resolution, per-eye resolution, VR format (SBS/TB), projection type, FOV, and metadata completeness percentage. Filter by codec and resolution.

### Audio (`/audio`)
Audio files with columns for artist, album, title, sample rate, channels, and lossless status. Filter by lossless/lossy, group by artist.

## Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `scan_dirs` | List of directories to scan | `[]` |
| `server.host` | Server bind address | `0.0.0.0` |
| `server.port` | Server port | `8080` |
| `secret_token` | Optional auth token | _(none)_ |
| `file_extensions.video` | Video file extensions to scan | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.webm`, `.flv` |
| `file_extensions.audio` | Audio file extensions to scan | `.mp3`, `.flac`, `.wav`, `.ogg`, `.m4a`, `.wma`, `.aac`, `.opus` |

## Example Data

```
/data/movies/
├── inception-2010-4k.mkv
├── the-matrix-1999-1080p.mp4
└── planet-earth-s01e01_180_SBS.mp4

/data/music/
├── pink-floyd/
│   ├── dark-side-of-the-moon-speak-to-me.flac
│   └── wish-you-were-here.flac
└── radiohead/
    └── ok-computer-paranoid-android.mp3
```

## API

All data is served via a JSON API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/files` | GET | List files with filtering, sorting, pagination |
| `/api/files/<id>` | GET | Get full metadata for a single file |
| `/api/stats` | GET | Get file counts by type |
| `/api/scan` | POST | Start a background scan |
| `/api/scan/status` | GET | Check scan progress |
| `/api/scan/stop` | POST | Stop a running scan |
| `/api/version` | GET | Get application version |
| `/api/config` | GET/PUT | Read or update configuration |

## Development

```bash
# Install all dependencies (including dev tools)
uv sync --dev

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## Tech Stack

- **Backend**: Python 3.11+, Flask, SQLite
- **Media probing**: FFprobe (via subprocess)
- **Frontend**: Vanilla JS, no build step
- **Container**: Docker with Python 3.11-slim + FFmpeg

## License

MIT
