# File Hashing Design — Issue #13

**Date:** 2026-02-18
**Branch:** `feature/file-hashing`
**Scope:** Quick hash (always-on) + video perceptual hash (opt-in). Audio phash deferred.

---

## Problem

Files are identified only by path. Mount path changes (#12), renames, and metadata edits all create
duplicates or break identity. We need content-based identity that survives path and metadata changes.

---

## Goals

- Quick hash every scanned file for data integrity and exact-match dedup
- Provide optional perceptual hashing for video to detect near-duplicate or re-encoded files
- Speed up the existing scan with parallel processing (shared infrastructure)
- Keep the codebase simple and idiomatic Python

## Non-Goals (this PR)

- Duplicate detection UI / `/api/duplicates` endpoint
- Audio perceptual hashing (chromaprint/acoustid — separate issue)
- GPU acceleration (ffmpeg `-hwaccel auto` provides hardware-aware decoding for free)

---

## Architecture

### New Package: `media_analyzer/jobs/`

```
media_analyzer/jobs/
├── __init__.py
├── runner.py     # JobRunner: ThreadPoolExecutor + progress + cancellation
└── hasher.py     # quick_hash() and video_phash() functions
```

**`JobRunner`** is a small class (~60 lines) that implements the parallel-work pattern:

```
collect items
  → worker_fn(item) runs in thread pool  [expensive: I/O, subprocess]
  → results serialized back to calling thread
  → writer_fn(item, result) writes to DB  [cheap: SQL upsert]
  → progress tracker updated after each write
```

Both the scan and the phash job use `JobRunner`. This eliminates code duplication and gives the
scan the same parallel speedup.

### Scan Refactor

`scanner.py::run_scan` is refactored to use `JobRunner`. The worker function does:
1. `os.stat()` + `file_unchanged()` check (skip if unchanged AND already has quick_hash)
2. FFprobe (existing)
3. `quick_hash()` — partial SHA256 (first 64KB + last 64KB + file size)

The writer function does the existing DB upserts plus `upsert_quick_hash()`.

Behavioral change: none. Performance: parallel probing instead of sequential.

### Phash Job

A new background job (mirroring scan) that:
1. Queries DB for video files with `video_phash IS NULL` in the requested dirs
2. Uses `JobRunner` to compute `video_phash()` per file
3. Writes results with `upsert_video_phash()`
4. Supports cancellation via `phash_progress.cancel_requested`

**`video_phash(file_path, duration)`:**
- Extracts 4 frames at 25%, 50%, 75%, 100% of duration via `ffmpeg` subprocess
- Computes `imagehash.dhash()` for each frame
- Returns `"|".join(str(h) for h in hashes)` — pipe-separated dhash strings

---

## Data Model

### DB Migration

Added to `_init_schema()` — additive only, safe to run on existing DBs:

```sql
ALTER TABLE media_files ADD COLUMN quick_hash TEXT;
ALTER TABLE media_files ADD COLUMN video_phash TEXT;
CREATE INDEX IF NOT EXISTS idx_media_files_quick_hash ON media_files(quick_hash);
```

Each ALTER is wrapped in a try/except for `sqlite3.OperationalError` (column already exists).

---

## Configuration

```yaml
hashing:
  workers: 4       # ThreadPoolExecutor max_workers for scan + phash (default: min(4, cpu_count))
  phash: false     # Enable perceptual hashing endpoint (default: false)
```

Quick hash has no config toggle — it always runs during scan.

New default in `config.py`:
```python
"hashing": {
    "workers": min(4, os.cpu_count() or 1),
    "phash": False,
}
```

---

## New Dependencies

```
imagehash>=4.3
Pillow>=10.0
```

Both are pure-Python friendly, widely available, and have no system-library requirements beyond
what ffmpeg already provides for frame extraction.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/hash` | Start phash job. Body: `{"scan_dirs": [...]}` (optional, defaults to all configured dirs) |
| `GET` | `/api/hash/status` | Returns phash progress dict (mirrors `/api/scan/status`) |
| `POST` | `/api/hash/stop` | Request cancellation of running phash job |

`POST /api/hash` returns 409 if a phash job is already running.

---

## UI Changes

- **Video table**: `video_phash` column added, hidden by default in the column selector
- **Header/toolbar**: "Compute Hashes" button (only shown when `hashing.phash: true` in config)
  - Opens a small modal with a folder selector (configured scan_dirs + "All" option)
  - On submit: calls `POST /api/hash`, shows a progress bar (polls `/api/hash/status`)
  - Cancel button calls `POST /api/hash/stop`

---

## Logging

All new modules use `logging.getLogger(__name__)`. Key log points:

- `INFO`: phash job started/finished, file count, worker count
- `INFO`: quick_hash computed per file (during scan, at DEBUG level to avoid noise)
- `WARNING`: ffmpeg frame extraction failure (phash skipped for that file)
- `WARNING`: phash job cancelled by user

---

## Testing

- `tests/test_runner.py` — `JobRunner` unit tests: parallel execution, cancellation, writer serialization
- `tests/test_hasher.py` — `quick_hash` unit test (temp file), `video_phash` with mocked ffmpeg
- `tests/test_scan.py` — existing scan tests updated to verify quick_hash is written; scan still works correctly after refactor
- `tests/test_hash_api.py` — API endpoint tests for `/api/hash`, `/api/hash/status`, `/api/hash/stop`

---

## Future Work

- **Scan threading was introduced here** — if scan performance is still inadequate, the next step
  is tuning `hashing.workers` or profiling the DB write bottleneck. Open a follow-up issue.
- **Audio perceptual hashing** — chromaprint/acoustid fingerprinting. Requires `pyacoustid` and
  the `chromaprint` system library. Design separately.
- **Duplicate detection UI** — `/api/duplicates` endpoint grouping by `quick_hash`, with UI.
  Blocked on #12 for path normalization.
- **Logging overhaul** — structured logging, log levels configurable per module. Future enhancement.
