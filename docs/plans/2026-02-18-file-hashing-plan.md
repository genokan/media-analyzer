# File Hashing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add quick hash (always-on during scan) and video perceptual hash (opt-in, bulk triggered) with a shared ThreadPoolExecutor job runner that also speeds up the existing scan.

**Architecture:** New `media_analyzer/jobs/` package with `JobRunner` (parallel workers, serialized writes, cancellation), `hasher.py` (quick_hash + video_phash functions), and `phash_job.py` (bulk phash operation). Scanner is refactored to use `JobRunner` for parallel probing. DB gains two nullable columns and the `file_unchanged` check is tightened to require `quick_hash IS NOT NULL`.

**Tech Stack:** Python stdlib (`hashlib`, `threading`, `concurrent.futures`), `imagehash>=4.3`, `Pillow>=10.0`, `ffmpeg` subprocess for frame extraction (already present via ffprobe dependency).

---

## Task 1: Add imagehash + Pillow dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies**

Edit the `[project]` dependencies list in `pyproject.toml`:

```toml
dependencies = [
    "flask>=3.0",
    "pyyaml>=6.0",
    "imagehash>=4.3",
    "Pillow>=10.0",
]
```

**Step 2: Sync and verify**

```bash
uv sync --dev
uv run python -c "import imagehash, PIL; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add imagehash and Pillow for video perceptual hashing"
```

---

## Task 2: DB migration — new columns and methods

**Files:**
- Modify: `media_analyzer/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the failing tests**

Create `tests/test_db.py`:

```python
"""Tests for database layer — hashing additions."""

import pytest

from media_analyzer.db import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def sample_file_id(db):
    return db.upsert_media_file({
        "file_path": "/test/video.mp4",
        "filename": "video.mp4",
        "file_size": 1000000,
        "modified_date": "2024-01-01T00:00:00",
        "media_type": "video",
    })


class TestSchema:
    def test_quick_hash_column_exists(self, db, sample_file_id):
        """media_files must have a quick_hash column."""
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(media_files)").fetchall()]
        conn.close()
        assert "quick_hash" in cols

    def test_video_phash_column_exists(self, db, sample_file_id):
        """media_files must have a video_phash column."""
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(media_files)").fetchall()]
        conn.close()
        assert "video_phash" in cols

    def test_migration_idempotent(self, db):
        """Running _init_schema twice must not raise."""
        db._init_schema()  # called again — should not raise


class TestFileUnchanged:
    def test_unchanged_without_hash_returns_false(self, db, sample_file_id):
        """file_unchanged must return False when quick_hash is NULL (needs hashing)."""
        result = db.file_unchanged("/test/video.mp4", 1000000, "2024-01-01T00:00:00")
        assert result is False

    def test_unchanged_with_hash_returns_true(self, db, sample_file_id):
        """file_unchanged must return True only when quick_hash is present."""
        db.upsert_quick_hash(sample_file_id, "abc123")
        result = db.file_unchanged("/test/video.mp4", 1000000, "2024-01-01T00:00:00")
        assert result is True

    def test_changed_size_returns_false(self, db, sample_file_id):
        db.upsert_quick_hash(sample_file_id, "abc123")
        result = db.file_unchanged("/test/video.mp4", 9999, "2024-01-01T00:00:00")
        assert result is False

    def test_missing_file_returns_false(self, db):
        result = db.file_unchanged("/nonexistent.mp4", 1000, "2024-01-01")
        assert result is False


class TestFileNeedsHashOnly:
    def test_existing_file_without_hash(self, db, sample_file_id):
        """Returns True when file exists with same stats but no quick_hash."""
        result = db.file_needs_hash_only("/test/video.mp4", 1000000, "2024-01-01T00:00:00")
        assert result is True

    def test_existing_file_with_hash(self, db, sample_file_id):
        """Returns False when file already has quick_hash."""
        db.upsert_quick_hash(sample_file_id, "abc123")
        result = db.file_needs_hash_only("/test/video.mp4", 1000000, "2024-01-01T00:00:00")
        assert result is False

    def test_missing_file_returns_false(self, db):
        result = db.file_needs_hash_only("/nonexistent.mp4", 1000, "2024-01-01")
        assert result is False


class TestUpsertQuickHash:
    def test_sets_hash(self, db, sample_file_id):
        db.upsert_quick_hash(sample_file_id, "deadbeef")
        detail = db.get_file_detail(sample_file_id)
        assert detail["quick_hash"] == "deadbeef"

    def test_updates_existing_hash(self, db, sample_file_id):
        db.upsert_quick_hash(sample_file_id, "first")
        db.upsert_quick_hash(sample_file_id, "second")
        detail = db.get_file_detail(sample_file_id)
        assert detail["quick_hash"] == "second"

    def test_upsert_by_path(self, db, sample_file_id):
        db.upsert_quick_hash_by_path("/test/video.mp4", "frompath")
        detail = db.get_file_detail(sample_file_id)
        assert detail["quick_hash"] == "frompath"


class TestUpsertVideoPhash:
    def test_sets_phash(self, db, sample_file_id):
        db.upsert_video_phash(sample_file_id, "hash1|hash2|hash3|hash4")
        detail = db.get_file_detail(sample_file_id)
        assert detail["video_phash"] == "hash1|hash2|hash3|hash4"


class TestGetUnhashedVideos:
    def test_returns_videos_without_phash(self, db):
        db.upsert_media_file({
            "file_path": "/movies/film.mp4",
            "filename": "film.mp4",
            "file_size": 5000000,
            "modified_date": "2024-01-01",
            "media_type": "video",
            "duration": 7200.0,
        })
        db.upsert_media_file({
            "file_path": "/music/song.mp3",
            "filename": "song.mp3",
            "file_size": 5000000,
            "modified_date": "2024-01-01",
            "media_type": "audio",
        })
        rows = db.get_unhashed_videos()
        assert len(rows) == 1
        assert rows[0]["file_path"] == "/movies/film.mp4"

    def test_excludes_already_hashed(self, db):
        fid = db.upsert_media_file({
            "file_path": "/movies/film.mp4",
            "filename": "film.mp4",
            "file_size": 5000000,
            "modified_date": "2024-01-01",
            "media_type": "video",
        })
        db.upsert_video_phash(fid, "somehash")
        rows = db.get_unhashed_videos()
        assert len(rows) == 0

    def test_filter_by_scan_dirs(self, db):
        db.upsert_media_file({
            "file_path": "/movies/film.mp4",
            "filename": "film.mp4",
            "file_size": 1000,
            "modified_date": "2024-01-01",
            "media_type": "video",
        })
        db.upsert_media_file({
            "file_path": "/tv/show.mp4",
            "filename": "show.mp4",
            "file_size": 1000,
            "modified_date": "2024-01-01",
            "media_type": "video",
        })
        rows = db.get_unhashed_videos(scan_dirs=["/movies"])
        assert len(rows) == 1
        assert rows[0]["file_path"] == "/movies/film.mp4"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py -v
```

Expected: Multiple failures — columns don't exist, methods don't exist.

**Step 3: Implement the DB changes**

In `media_analyzer/db.py`, make the following changes:

**3a. Add migration method** — insert after `SCHEMA_SQL` constant, before the `Database` class:

The `_init_schema` method should call `_migrate_schema` after `executescript`. Add a new private method `_migrate_schema`:

```python
_MIGRATION_SQL = [
    "ALTER TABLE media_files ADD COLUMN quick_hash TEXT",
    "ALTER TABLE media_files ADD COLUMN video_phash TEXT",
    "CREATE INDEX IF NOT EXISTS idx_media_files_quick_hash ON media_files(quick_hash)",
]
```

Modify `_init_schema`:
```python
def _init_schema(self):
    with self._connect() as conn:
        conn.executescript(SCHEMA_SQL)
        self._migrate_schema(conn)

def _migrate_schema(self, conn: sqlite3.Connection):
    """Apply additive schema migrations. Safe to run on existing databases."""
    for sql in _MIGRATION_SQL:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column or index already exists
```

**3b. Modify `file_unchanged`** — require `quick_hash IS NOT NULL`:

```python
def file_unchanged(self, file_path: str, file_size: int, modified_date: str) -> bool:
    """Check if a file is already scanned, unchanged, and has a quick_hash."""
    with self._connect() as conn:
        row = conn.execute(
            """SELECT 1 FROM media_files
               WHERE file_path=? AND file_size=? AND modified_date=?
               AND quick_hash IS NOT NULL""",
            (file_path, file_size, modified_date),
        ).fetchone()
        return row is not None
```

**3c. Add `file_needs_hash_only`**:

```python
def file_needs_hash_only(self, file_path: str, file_size: int, modified_date: str) -> bool:
    """True if file exists with matching stats but has no quick_hash yet."""
    with self._connect() as conn:
        row = conn.execute(
            """SELECT 1 FROM media_files
               WHERE file_path=? AND file_size=? AND modified_date=?
               AND quick_hash IS NULL""",
            (file_path, file_size, modified_date),
        ).fetchone()
        return row is not None
```

**3d. Add `upsert_quick_hash`**:

```python
def upsert_quick_hash(self, file_id: int, quick_hash: str):
    """Store the quick hash for a file by ID."""
    with self._connect() as conn:
        conn.execute(
            "UPDATE media_files SET quick_hash=? WHERE id=?",
            (quick_hash, file_id),
        )

def upsert_quick_hash_by_path(self, file_path: str, quick_hash: str):
    """Store the quick hash for a file by path (used for hash-only updates)."""
    with self._connect() as conn:
        conn.execute(
            "UPDATE media_files SET quick_hash=? WHERE file_path=?",
            (quick_hash, file_path),
        )
```

**3e. Add `upsert_video_phash`**:

```python
def upsert_video_phash(self, file_id: int, video_phash: str):
    """Store the perceptual hash for a video file."""
    with self._connect() as conn:
        conn.execute(
            "UPDATE media_files SET video_phash=? WHERE id=?",
            (video_phash, file_id),
        )
```

**3f. Add `get_unhashed_videos`**:

```python
def get_unhashed_videos(self, scan_dirs: list[str] | None = None) -> list[dict]:
    """Return video/VR files missing a perceptual hash, optionally scoped to dirs."""
    with self._connect() as conn:
        if scan_dirs:
            placeholders = " OR ".join("file_path LIKE ?" for _ in scan_dirs)
            params = [d.rstrip("/") + "/%" for d in scan_dirs]
            rows = conn.execute(
                f"""SELECT id, file_path, duration FROM media_files
                    WHERE media_type IN ('video', 'vr') AND video_phash IS NULL
                    AND ({placeholders})""",
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, file_path, duration FROM media_files
                   WHERE media_type IN ('video', 'vr') AND video_phash IS NULL"""
            ).fetchall()
        return [dict(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```

Expected: All green.

**Step 5: Run full suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: All tests pass.

**Step 6: Commit**

```bash
git add media_analyzer/db.py tests/test_db.py
git commit -m "feat: add quick_hash and video_phash DB columns with migration"
```

---

## Task 3: JobProgress + JobRunner with tests

**Files:**
- Create: `media_analyzer/jobs/__init__.py`
- Create: `media_analyzer/jobs/runner.py`
- Create: `tests/test_runner.py`

**Step 1: Write the failing tests**

Create `tests/test_runner.py`:

```python
"""Tests for JobRunner parallel execution infrastructure."""

import threading
import time

import pytest

from media_analyzer.jobs.runner import JobProgress, JobRunner


class TestJobProgress:
    def test_initial_state(self):
        p = JobProgress()
        assert p.running is False
        assert p.total == 0
        assert p.processed == 0
        assert p.cancel_requested is False

    def test_to_dict(self):
        p = JobProgress()
        p.total = 10
        p.processed = 5
        p.running = True
        d = p.to_dict()
        assert d["total"] == 10
        assert d["processed"] == 5
        assert d["running"] is True
        assert d["percent"] == 50.0

    def test_percent_zero_when_total_zero(self):
        p = JobProgress()
        assert p.to_dict()["percent"] == 0

    def test_update_thread_safe(self):
        """Concurrent updates must not corrupt state."""
        p = JobProgress()
        p.total = 100
        errors = []

        def updater(i):
            try:
                p.update(i, f"file_{i}.mp4")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestJobRunner:
    def test_runs_all_items(self):
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 3

        results = []

        def worker(item):
            return item * 2

        def writer(item, result):
            results.append(result)

        written = runner.run([1, 2, 3], worker, writer, progress)
        assert written == 3
        assert sorted(results) == [2, 4, 6]

    def test_skips_none_results(self):
        """Worker returning None must not call writer."""
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 3
        written_items = []

        def worker(item):
            return item if item % 2 == 0 else None

        def writer(item, result):
            written_items.append(item)

        written = runner.run([1, 2, 3, 4], worker, writer, progress)
        assert written == 2
        assert set(written_items) == {2, 4}

    def test_worker_exception_does_not_abort(self):
        """A worker raising must not stop processing of other items."""
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 3
        results = []

        def worker(item):
            if item == 2:
                raise ValueError("boom")
            return item

        def writer(item, result):
            results.append(result)

        written = runner.run([1, 2, 3], worker, writer, progress)
        assert written == 2
        assert sorted(results) == [1, 3]

    def test_cancellation_stops_processing(self):
        """Setting cancel_requested stops issuing new writer calls."""
        runner = JobRunner(max_workers=1)
        progress = JobProgress()
        progress.total = 100
        results = []

        def worker(item):
            time.sleep(0.01)
            return item

        def writer(item, result):
            results.append(result)
            if len(results) >= 3:
                progress.cancel_requested = True

        runner.run(list(range(100)), worker, writer, progress)
        # Should stop well before 100 items
        assert len(results) < 50

    def test_progress_updated_per_item(self):
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 4

        def worker(item):
            return item

        def writer(item, result):
            pass

        runner.run([1, 2, 3, 4], worker, writer, progress)
        assert progress.processed == 4

    def test_writer_exception_does_not_abort(self):
        """A writer raising must not stop processing of other items."""
        runner = JobRunner(max_workers=1)
        progress = JobProgress()
        progress.total = 3
        written = []

        def worker(item):
            return item

        def writer(item, result):
            if result == 2:
                raise RuntimeError("write failed")
            written.append(result)

        count = runner.run([1, 2, 3], worker, writer, progress)
        assert count == 2
        assert sorted(written) == [1, 3]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_runner.py -v
```

Expected: `ImportError` — module doesn't exist yet.

**Step 3: Create the jobs package**

Create `media_analyzer/jobs/__init__.py` (empty):
```python
```

Create `media_analyzer/jobs/runner.py`:

```python
"""Shared job runner: parallel workers with serialized DB writes and cancellation."""

import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)


class JobProgress:
    """Thread-safe progress tracker with cancellation support."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.processed = 0
        self.current_file = ""
        self.running = False
        self.cancel_requested = False

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "processed": self.processed,
                "current_file": self.current_file,
                "percent": round(self.processed / self.total * 100, 1) if self.total else 0,
            }

    def update(self, processed: int, current_file: str):
        with self._lock:
            self.processed = processed
            self.current_file = current_file


class JobRunner:
    """Run a batch job with parallel workers and serialized writes.

    Pattern:
        worker_fn(item) runs in the thread pool — expensive I/O and subprocess calls.
        writer_fn(item, result) runs on the calling thread — serialized DB writes.
        Items where worker_fn returns None are silently skipped (no writer call).

    The progress object must expose:
        - cancel_requested (bool): set True externally to request early stop
        - update(processed: int, current_file: str): called after each item
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers

    def run(
        self,
        items: list[Any],
        worker_fn: Callable[[Any], Any | None],
        writer_fn: Callable[[Any, Any], None],
        progress: Any,
    ) -> int:
        """Process items in parallel. Returns count of items passed to writer_fn."""
        written = 0
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(worker_fn, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]

                if progress.cancel_requested:
                    for f in futures:
                        f.cancel()
                    logger.info("Job cancelled after %d written items", written)
                    break

                try:
                    result = future.result()
                except Exception:
                    name = item[0] if isinstance(item, tuple) else str(item)
                    logger.exception("Worker failed for: %s", name)
                    result = None

                if result is not None:
                    try:
                        writer_fn(item, result)
                        written += 1
                    except Exception:
                        name = item[0] if isinstance(item, tuple) else str(item)
                        logger.exception("Writer failed for: %s", name)

                name = item[0] if isinstance(item, tuple) else str(item)
                progress.update(written, os.path.basename(str(name)))

        return written
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_runner.py -v
```

Expected: All green.

**Step 5: Commit**

```bash
git add media_analyzer/jobs/__init__.py media_analyzer/jobs/runner.py tests/test_runner.py
git commit -m "feat: add JobRunner with parallel workers and cancellation support"
```

---

## Task 4: Hasher functions — quick_hash and video_phash

**Files:**
- Create: `media_analyzer/jobs/hasher.py`
- Create: `tests/test_hasher.py`

**Step 1: Write the failing tests**

Create `tests/test_hasher.py`:

```python
"""Tests for quick_hash and video_phash functions."""

import io
import os
from unittest.mock import patch

import pytest

from media_analyzer.jobs.hasher import quick_hash, video_phash


class TestQuickHash:
    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"hello world" * 1000)
        result = quick_hash(str(f))
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest length

    def test_same_content_same_hash(self, tmp_path):
        content = b"x" * 200_000
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(content)
        b.write_bytes(content)
        assert quick_hash(str(a)) == quick_hash(str(b))

    def test_different_content_different_hash(self, tmp_path):
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        a.write_bytes(b"aaaa" * 50_000)
        b.write_bytes(b"bbbb" * 50_000)
        assert quick_hash(str(a)) != quick_hash(str(b))

    def test_small_file(self, tmp_path):
        """Files smaller than one chunk must still hash correctly."""
        f = tmp_path / "small.mp4"
        f.write_bytes(b"tiny")
        result = quick_hash(str(f))
        assert len(result) == 64

    def test_size_included_in_hash(self, tmp_path):
        """Two files with the same first+last bytes but different sizes differ."""
        a = tmp_path / "a.mp4"
        b = tmp_path / "b.mp4"
        # Same content for first and last 64KB, but different total sizes
        a.write_bytes(b"A" * 65536 + b"B" * 1000 + b"C" * 65536)
        b.write_bytes(b"A" * 65536 + b"B" * 500 + b"C" * 65536)
        assert quick_hash(str(a)) != quick_hash(str(b))


class TestVideoPhash:
    def test_returns_none_for_zero_duration(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")
        assert video_phash(str(f), 0.0) is None

    def test_returns_none_for_none_duration(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")
        assert video_phash(str(f), None) is None

    def test_returns_pipe_separated_hashes(self, tmp_path):
        """With mocked ffmpeg, returns a pipe-separated dhash string."""
        import PIL.Image
        import imagehash

        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")

        # Create a real small image as fake frame bytes
        img = PIL.Image.new("RGB", (64, 64), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        frame_bytes = buf.getvalue()

        with patch("media_analyzer.jobs.hasher._extract_frame", return_value=frame_bytes):
            result = video_phash(str(f), 120.0, num_frames=4)

        assert result is not None
        parts = result.split("|")
        assert len(parts) == 4
        for part in parts:
            assert len(part) > 0  # each part is a dhash hex string

    def test_returns_none_when_all_frames_fail(self, tmp_path):
        """Returns None if ffmpeg extraction fails for all frames."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")

        with patch("media_analyzer.jobs.hasher._extract_frame", return_value=None):
            result = video_phash(str(f), 120.0)

        assert result is None

    def test_partial_frames_still_returns(self, tmp_path):
        """If some frames succeed and some fail, returns hash of successful frames."""
        import PIL.Image
        import imagehash

        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")

        img = PIL.Image.new("RGB", (64, 64))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        frame_bytes = buf.getvalue()

        # Return frame for first call, None for rest
        side_effects = [frame_bytes, None, None, None]
        with patch("media_analyzer.jobs.hasher._extract_frame", side_effect=side_effects):
            result = video_phash(str(f), 120.0, num_frames=4)

        assert result is not None
        assert "|" not in result  # only one hash, no pipe
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_hasher.py -v
```

Expected: `ImportError` — hasher module doesn't exist.

**Step 3: Implement `media_analyzer/jobs/hasher.py`**

```python
"""Hash functions for media files: quick hash and video perceptual hash."""

import hashlib
import io
import logging
import os
import subprocess

import imagehash
from PIL import Image

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 65536  # 64 KB — first and last chunks for quick hash


def quick_hash(file_path: str) -> str:
    """Compute a fast partial SHA-256 of a file.

    Reads the first and last 64 KB plus includes the file size in the digest.
    Fast enough to run on every file during a scan. Not cryptographically
    robust against adversarial tampering, but sufficient for dedup and
    data-integrity checks.
    """
    h = hashlib.sha256()
    file_size = os.path.getsize(file_path)
    h.update(file_size.to_bytes(8, "little"))

    with open(file_path, "rb") as f:
        h.update(f.read(_CHUNK_SIZE))
        if file_size > _CHUNK_SIZE:
            seek_back = min(_CHUNK_SIZE, file_size - _CHUNK_SIZE)
            f.seek(-seek_back, 2)
            h.update(f.read(_CHUNK_SIZE))

    return h.hexdigest()


def video_phash(file_path: str, duration: float | None, num_frames: int = 4) -> str | None:
    """Compute a perceptual hash for a video file.

    Extracts num_frames evenly spaced throughout the video, computes
    imagehash.dhash() for each frame, and returns them as a pipe-separated
    string. Returns None if duration is missing or all frame extractions fail.

    The resulting hash is stable across re-encodes and minor edits, but will
    change with significant visual content changes.
    """
    if not duration:
        return None

    hashes = []
    for i in range(1, num_frames + 1):
        timestamp = duration * i / (num_frames + 1)
        frame_bytes = _extract_frame(file_path, timestamp)
        if frame_bytes is None:
            continue
        try:
            img = Image.open(io.BytesIO(frame_bytes))
            hashes.append(str(imagehash.dhash(img)))
        except Exception:
            logger.warning(
                "Failed to compute dhash at %.1fs in %s", timestamp, file_path
            )

    if not hashes:
        logger.warning("No frames extracted for phash: %s", file_path)
        return None

    return "|".join(hashes)


def _extract_frame(file_path: str, timestamp: float) -> bytes | None:
    """Extract a single frame at the given timestamp via ffmpeg.

    Returns raw JPEG bytes, or None if ffmpeg fails.
    """
    cmd = [
        "ffmpeg",
        "-ss", str(timestamp),
        "-i", file_path,
        "-frames:v", "1",
        "-f", "image2",
        "-vcodec", "mjpeg",
        "-q:v", "5",
        "pipe:1",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.warning(
            "ffmpeg frame extraction failed at %.1fs for %s: %s", timestamp, file_path, e
        )
        return None
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_hasher.py -v
```

Expected: All green.

**Step 5: Commit**

```bash
git add media_analyzer/jobs/hasher.py tests/test_hasher.py
git commit -m "feat: add quick_hash and video_phash functions"
```

---

## Task 5: Update config defaults + fix test fixtures

**Files:**
- Modify: `media_analyzer/config.py`
- Modify: `tests/test_api.py`

**Step 1: Add hashing defaults to `config.py`**

In `config.py`, update `DEFAULT_CONFIG` to include:

```python
import os  # add to existing imports at top

DEFAULT_CONFIG = {
    "scan_dirs": [],
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "db_path": "data/media_analyzer.db",
    "secret_token": None,
    "file_extensions": {
        "video": [".mp4", ".mkv", ".avi", ".mov", ".m4v"],
        "audio": [".mp3", ".aac", ".flac", ".wav", ".ogg", ".wma", ".m4a", ".opus"],
    },
    "hashing": {
        "workers": min(4, os.cpu_count() or 1),
        "phash": False,
    },
}
```

**Step 2: Update the test fixture in `tests/test_api.py`**

Add `hashing` to the config dict in the `app` fixture and `test_auth_*` helpers:

```python
config = {
    "scan_dirs": [],
    "server": {"host": "127.0.0.1", "port": 8080},
    "db_path": db_path,
    "secret_token": None,
    "_flask_secret": "test-secret",
    "file_extensions": {
        "video": [".mp4", ".mkv"],
        "audio": [".mp3", ".flac"],
    },
    "hashing": {"workers": 1, "phash": False},
}
```

Apply the same `"hashing": {"workers": 1, "phash": False}` addition to all four inline config dicts inside `TestAuth` methods.

**Step 3: Verify tests pass**

```bash
uv run pytest tests/ -v
```

Expected: All green.

**Step 4: Commit**

```bash
git add media_analyzer/config.py tests/test_api.py
git commit -m "feat: add hashing config defaults (workers, phash toggle)"
```

---

## Task 6: Refactor scanner to use JobRunner

**Files:**
- Modify: `media_analyzer/scanner.py`

This is the largest single change. The existing `run_scan` sequential loop is replaced with `JobRunner`. Existing tests must still pass. No new test file needed — the existing API test suite covers scan behavior.

**Step 1: Rewrite `media_analyzer/scanner.py`**

Replace the entire file with:

```python
"""Directory scanner — walks configured dirs, probes files, stores results."""

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from media_analyzer.db import Database
from media_analyzer.jobs.hasher import quick_hash
from media_analyzer.jobs.runner import JobRunner
from media_analyzer.probers.audio import AudioProber
from media_analyzer.probers.vr import VRProber

logger = logging.getLogger(__name__)


class ScanProgress:
    """Thread-safe scan progress tracker."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.processed = 0
        self.current_file = ""
        self.running = False
        self.scan_id: int | None = None
        self.cancel_requested = False

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "processed": self.processed,
                "current_file": self.current_file,
                "scan_id": self.scan_id,
                "percent": round(self.processed / self.total * 100, 1) if self.total else 0,
            }

    def update(self, processed: int, current_file: str):
        with self._lock:
            self.processed = processed
            self.current_file = current_file


# Global progress instance shared with the API layer.
scan_progress = ScanProgress()


def _collect_files(scan_dirs: list[str], extensions: dict) -> list[tuple[str, str]]:
    """Walk directories and collect (file_path, category) tuples."""
    video_exts = set(extensions.get("video", []))
    audio_exts = set(extensions.get("audio", []))
    all_exts = video_exts | audio_exts
    files = []

    for scan_dir in scan_dirs:
        dir_path = Path(scan_dir)
        if not dir_path.is_dir():
            logger.warning("Scan directory does not exist: %s", scan_dir)
            continue
        for root, _dirs, filenames in os.walk(dir_path):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in all_exts:
                    full_path = os.path.join(root, fname)
                    try:
                        real = os.path.realpath(full_path)
                        if not real.startswith(os.path.realpath(scan_dir)):
                            logger.warning("Skipping symlink escape: %s", full_path)
                            continue
                    except OSError:
                        continue
                    category = "video" if ext in video_exts else "audio"
                    files.append((full_path, category))
    return files


def run_scan(db: Database, config: dict, override_scan_dirs: list[str] | None = None) -> int:
    """Execute a full library scan. Returns the scan_id.

    Uses JobRunner for parallel probing (expensive) with serialized DB writes
    (cheap). Quick hash is computed for every new or modified file. Files that
    are unchanged and already hashed are skipped entirely; unchanged files
    missing a hash receive only a quick_hash update without re-probing.
    """
    global scan_progress

    scan_dirs = override_scan_dirs if override_scan_dirs is not None else config.get("scan_dirs") or []
    if isinstance(scan_dirs, str):
        scan_dirs = [scan_dirs]

    extensions = config.get("file_extensions", {})
    max_workers = config.get("hashing", {}).get("workers", 4)

    vr_prober = VRProber()
    audio_prober = AudioProber()

    files = _collect_files(scan_dirs, extensions)
    logger.info("Scan starting: %d files found, %d workers", len(files), max_workers)

    scan_id = db.start_scan()
    scan_progress.running = True
    scan_progress.total = len(files)
    scan_progress.processed = 0
    scan_progress.scan_id = scan_id
    scan_progress.cancel_requested = False

    files_written = 0

    def worker(item: tuple[str, str]) -> dict | None:
        file_path, category = item
        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            modified_date = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()

            if db.file_unchanged(file_path, file_size, modified_date):
                return None  # fully up-to-date

            if db.file_needs_hash_only(file_path, file_size, modified_date):
                logger.debug("Hash-only update for: %s", file_path)
                return {
                    "_hash_only": True,
                    "_file_path": file_path,
                    "_quick_hash": quick_hash(file_path),
                }

            if category == "audio":
                result = audio_prober.probe(file_path)
            else:
                result = vr_prober.probe(file_path)

            if result is None:
                logger.warning("Could not probe: %s", file_path)
                return None

            result["_file_path"] = file_path
            result["_filename"] = os.path.basename(file_path)
            result["_file_size"] = file_size
            result["_modified_date"] = modified_date
            result["_category"] = category
            result["_quick_hash"] = quick_hash(file_path)
            return result

        except Exception:
            logger.exception("Error processing: %s", file_path)
            return None

    def writer(item: tuple[str, str], result: dict):
        nonlocal files_written

        if result.get("_hash_only"):
            db.upsert_quick_hash_by_path(result["_file_path"], result["_quick_hash"])
            files_written += 1
            return

        media_data = {
            "file_path": result["_file_path"],
            "filename": result["_filename"],
            "file_size": result["_file_size"],
            "modified_date": result["_modified_date"],
            "media_type": result["media_type"],
            "container_format": result.get("container_format"),
            "duration": result.get("duration"),
            "bitrate": result.get("bitrate"),
        }

        file_id = db.upsert_media_file(media_data)
        db.upsert_quick_hash(file_id, result["_quick_hash"])

        category = result["_category"]
        if category == "audio":
            db.upsert_audio_metadata(file_id, result.get("audio", {}))
        else:
            db.upsert_video_metadata(file_id, result)
            if "vr" in result:
                db.upsert_vr_metadata(file_id, result["vr"])

        files_written += 1

    runner = JobRunner(max_workers=max_workers)
    try:
        runner.run(files, worker, writer, scan_progress)
        db.finish_scan(scan_id, len(files), files_written, 0)
        logger.info("Scan complete: %d/%d files written", files_written, len(files))
    except Exception:
        logger.exception("Scan failed")
        db.fail_scan(scan_id, files_written)
    finally:
        scan_progress.running = False
        scan_progress.cancel_requested = False

    return scan_id
```

**Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All green. If any test fails, investigate before continuing.

**Step 3: Run linter**

```bash
uv run ruff check media_analyzer/scanner.py
```

Expected: No issues.

**Step 4: Commit**

```bash
git add media_analyzer/scanner.py
git commit -m "refactor: scanner uses JobRunner for parallel probing and quick hash"
```

---

## Task 7: Phash job

**Files:**
- Create: `media_analyzer/jobs/phash_job.py`
- Create: `tests/test_phash_job.py`

**Step 1: Write the failing tests**

Create `tests/test_phash_job.py`:

```python
"""Tests for the video perceptual hash background job."""

from unittest.mock import patch

import pytest

from media_analyzer.db import Database
from media_analyzer.jobs.phash_job import phash_progress, run_phash_job


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def video_file_id(db):
    return db.upsert_media_file({
        "file_path": "/movies/film.mp4",
        "filename": "film.mp4",
        "file_size": 5_000_000,
        "modified_date": "2024-01-01T00:00:00",
        "media_type": "video",
        "duration": 7200.0,
    })


class TestRunPhashJob:
    def test_sets_video_phash(self, db, video_file_id):
        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", return_value="hash1|hash2"):
            run_phash_job(db, config)
        detail = db.get_file_detail(video_file_id)
        assert detail["video_phash"] == "hash1|hash2"

    def test_skips_audio_files(self, db):
        db.upsert_media_file({
            "file_path": "/music/song.mp3",
            "filename": "song.mp3",
            "file_size": 5_000_000,
            "modified_date": "2024-01-01",
            "media_type": "audio",
        })
        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", return_value="h") as mock_phash:
            run_phash_job(db, config)
        mock_phash.assert_not_called()

    def test_skips_already_hashed(self, db, video_file_id):
        db.upsert_video_phash(video_file_id, "existing_hash")
        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", return_value="new") as mock_phash:
            run_phash_job(db, config)
        mock_phash.assert_not_called()

    def test_scoped_to_scan_dirs(self, db, video_file_id):
        other_id = db.upsert_media_file({
            "file_path": "/tv/show.mp4",
            "filename": "show.mp4",
            "file_size": 1_000,
            "modified_date": "2024-01-01",
            "media_type": "video",
            "duration": 3600.0,
        })
        config = {"hashing": {"workers": 1}}
        hashed = []
        def fake_phash(path, duration, **kw):
            hashed.append(path)
            return "h"
        with patch("media_analyzer.jobs.phash_job.video_phash", side_effect=fake_phash):
            run_phash_job(db, config, scan_dirs=["/movies"])
        assert hashed == ["/movies/film.mp4"]

    def test_progress_resets_after_job(self, db, video_file_id):
        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", return_value="h"):
            run_phash_job(db, config)
        assert phash_progress.running is False

    def test_cancelled_job_stops_early(self, db):
        for i in range(20):
            db.upsert_media_file({
                "file_path": f"/movies/film{i}.mp4",
                "filename": f"film{i}.mp4",
                "file_size": 1_000,
                "modified_date": "2024-01-01",
                "media_type": "video",
                "duration": 100.0,
            })

        phash_progress.cancel_requested = False
        written = []

        def fake_phash(path, duration, **kw):
            written.append(path)
            if len(written) >= 3:
                phash_progress.cancel_requested = True
            return "h"

        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", side_effect=fake_phash):
            run_phash_job(db, config)

        assert len(written) < 20
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_phash_job.py -v
```

Expected: `ImportError`.

**Step 3: Create `media_analyzer/jobs/phash_job.py`**

```python
"""Background job for computing video perceptual hashes in bulk."""

import logging

from media_analyzer.db import Database
from media_analyzer.jobs.hasher import video_phash
from media_analyzer.jobs.runner import JobProgress, JobRunner

logger = logging.getLogger(__name__)

# Global progress tracker shared with the API layer.
phash_progress = JobProgress()


def run_phash_job(
    db: Database,
    config: dict,
    scan_dirs: list[str] | None = None,
) -> int:
    """Compute perceptual hashes for video files missing video_phash.

    Args:
        db: Database instance.
        config: Application config dict.
        scan_dirs: Optional list of directories to scope the job. If None,
            all video/VR files in the DB are eligible.

    Returns:
        Count of files successfully hashed.
    """
    max_workers = config.get("hashing", {}).get("workers", 4)
    files = db.get_unhashed_videos(scan_dirs=scan_dirs)
    logger.info(
        "Phash job starting: %d files to hash, %d workers", len(files), max_workers
    )

    phash_progress.running = True
    phash_progress.total = len(files)
    phash_progress.processed = 0
    phash_progress.cancel_requested = False

    def worker(row: dict) -> dict | None:
        file_path = row["file_path"]
        try:
            h = video_phash(file_path, row.get("duration"))
            if h is None:
                return None
            return {"file_id": row["id"], "video_phash": h}
        except Exception:
            logger.exception("Phash worker failed for: %s", file_path)
            return None

    def writer(row: dict, result: dict):
        db.upsert_video_phash(result["file_id"], result["video_phash"])

    runner = JobRunner(max_workers=max_workers)
    try:
        written = runner.run(files, worker, writer, phash_progress)
        logger.info("Phash job complete: %d/%d files hashed", written, len(files))
        return written
    finally:
        phash_progress.running = False
        phash_progress.cancel_requested = False
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_phash_job.py -v
```

Expected: All green.

**Step 5: Commit**

```bash
git add media_analyzer/jobs/phash_job.py tests/test_phash_job.py
git commit -m "feat: add phash job with folder scoping and cancellation"
```

---

## Task 8: API endpoints for hash job

**Files:**
- Modify: `media_analyzer/server/api.py`
- Modify: `tests/test_api.py`

**Step 1: Write the failing tests**

Add a new class to `tests/test_api.py`:

```python
class TestHashAPI:
    def test_hash_status_not_running(self, client):
        res = client.get("/api/hash/status")
        assert res.status_code == 200
        data = res.get_json()
        assert data["running"] is False

    def test_hash_start_returns_started(self, client):
        from unittest.mock import patch
        import threading
        # Patch run_phash_job to do nothing
        with patch("media_analyzer.server.api.run_phash_job") as mock_job:
            mock_job.return_value = 0
            res = client.post("/api/hash", json={})
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "started"

    def test_hash_stop_when_not_running(self, client):
        res = client.post("/api/hash/stop")
        assert res.status_code == 409

    def test_hash_start_rejects_invalid_dirs(self, client):
        res = client.post("/api/hash", json={"scan_dirs": ["/not/configured"]})
        assert res.status_code == 400

    def test_hash_status_shape(self, client):
        res = client.get("/api/hash/status")
        data = res.get_json()
        assert "running" in data
        assert "total" in data
        assert "processed" in data
        assert "percent" in data
```

**Step 2: Run new tests to verify they fail**

```bash
uv run pytest tests/test_api.py::TestHashAPI -v
```

Expected: 404s — endpoints don't exist yet.

**Step 3: Add endpoints to `media_analyzer/server/api.py`**

Add these imports at the top (with existing imports):
```python
from media_analyzer.jobs.phash_job import phash_progress, run_phash_job
```

Add these three routes after the existing scan routes:

```python
@api_bp.route("/hash", methods=["POST"])
def trigger_hash():
    if phash_progress.running:
        return jsonify(
            {
                "error": "Phash job already in progress",
                "progress": phash_progress.to_dict(),
            }
        ), 409

    db = _get_db()
    config = _get_config()

    override_dirs = None
    body = request.get_json(silent=True)
    if body and "scan_dirs" in body:
        requested = body["scan_dirs"]
        configured = set(config.get("scan_dirs", []))
        invalid = [d for d in requested if d not in configured]
        if invalid:
            return jsonify({"error": "Directories not in config", "invalid": invalid}), 400
        override_dirs = requested

    thread = threading.Thread(
        target=run_phash_job, args=(db, config, override_dirs), daemon=True
    )
    thread.start()
    return jsonify({"status": "started", "message": "Phash job started in background"})


@api_bp.route("/hash/status")
def hash_status():
    return jsonify(phash_progress.to_dict())


@api_bp.route("/hash/stop", methods=["POST"])
def stop_hash():
    if not phash_progress.running:
        return jsonify({"error": "No phash job is running"}), 409
    phash_progress.cancel_requested = True
    return jsonify({"status": "stopping", "message": "Phash stop requested"})
```

**Step 4: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All green.

**Step 5: Commit**

```bash
git add media_analyzer/server/api.py tests/test_api.py
git commit -m "feat: add /api/hash, /api/hash/status, /api/hash/stop endpoints"
```

---

## Task 9: UI changes

**Files:**
- Modify: `media_analyzer/server/templates/videos.html`

Add a `video_phash` column (hidden by default) to the column selector and a "Compute Hashes" toolbar button with a folder-picker modal and progress bar. The button and modal are conditionally rendered based on a config value injected via the `/api/config` response.

**Step 1: Update `videos.html`**

**1a.** Add `video_phash` to the `COLUMNS` array:

```javascript
{ key: 'video_phash', label: 'Perceptual Hash', sort: null, default: false },
```

**1b.** Add a `video_phash` case to `cellValue`:

```javascript
case 'video_phash': {
    if (!f.video_phash) return { text: '—' };
    const short = f.video_phash.substring(0, 16) + '…';
    return { text: short, title: f.video_phash };
}
```

**1c.** Add the "Compute Hashes" button to the toolbar div (after the col-toggle div):

```html
<div id="hash-toolbar" style="display:none;">
    <button type="button" id="btn-hash" class="btn-secondary">Compute Hashes</button>
</div>
```

**1d.** Add a modal and progress section after the pagination div and before `{% endblock %}`:

```html
<!-- Perceptual hash modal -->
<div id="hash-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:100; align-items:center; justify-content:center;">
    <div class="card" style="min-width:360px; max-width:480px; margin:0;">
        <h3 style="margin-bottom:16px;">Compute Perceptual Hashes</h3>
        <label style="display:block; margin-bottom:8px; color:#8b949e; font-size:13px;">Scope</label>
        <select id="hash-dir-select" style="width:100%; margin-bottom:16px;">
            <option value="">All configured directories</option>
        </select>
        <div id="hash-progress-area" style="display:none; margin-bottom:16px;">
            <div style="font-size:13px; color:#8b949e; margin-bottom:4px;">
                <span id="hash-progress-label">Starting…</span>
            </div>
            <div class="progress-bar"><div class="fill" id="hash-progress-fill" style="width:0%"></div></div>
        </div>
        <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button type="button" id="btn-hash-cancel" class="btn-secondary">Cancel</button>
            <button type="button" id="btn-hash-stop" class="btn-danger" style="display:none;">Stop</button>
            <button type="button" id="btn-hash-start">Start</button>
        </div>
    </div>
</div>
```

**1e.** Add the JS logic at the bottom of the `<script>` block (before the final `fetchFiles()` call):

```javascript
// --- Perceptual hash UI ---
let hashPollInterval = null;

async function loadHashConfig() {
    try {
        const res = await fetch('/api/config');
        const cfg = await res.json();
        if (cfg.hashing && cfg.hashing.phash) {
            document.getElementById('hash-toolbar').style.display = '';
            // Populate dir selector
            const sel = document.getElementById('hash-dir-select');
            (cfg.scan_dirs || []).forEach(dir => {
                const opt = document.createElement('option');
                opt.value = dir; opt.textContent = dir;
                sel.appendChild(opt);
            });
        }
    } catch(e) {}
}

document.getElementById('btn-hash').onclick = () => {
    document.getElementById('hash-modal').style.display = 'flex';
    document.getElementById('hash-progress-area').style.display = 'none';
    document.getElementById('btn-hash-start').style.display = '';
    document.getElementById('btn-hash-stop').style.display = 'none';
};

document.getElementById('btn-hash-cancel').onclick = () => {
    clearInterval(hashPollInterval);
    document.getElementById('hash-modal').style.display = 'none';
};

document.getElementById('btn-hash-start').onclick = async () => {
    const dir = document.getElementById('hash-dir-select').value;
    const body = dir ? { scan_dirs: [dir] } : {};
    try {
        const res = await fetch('/api/hash', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json();
            alert(err.error || 'Failed to start');
            return;
        }
        document.getElementById('btn-hash-start').style.display = 'none';
        document.getElementById('btn-hash-stop').style.display = '';
        document.getElementById('hash-progress-area').style.display = '';
        hashPollInterval = setInterval(pollHashProgress, 1500);
    } catch(e) { alert('Request failed'); }
};

document.getElementById('btn-hash-stop').onclick = async () => {
    await fetch('/api/hash/stop', { method: 'POST' });
};

async function pollHashProgress() {
    try {
        const res = await fetch('/api/hash/status');
        const d = await res.json();
        document.getElementById('hash-progress-fill').style.width = d.percent + '%';
        document.getElementById('hash-progress-label').textContent =
            d.running
                ? `${d.processed} / ${d.total} hashed (${d.percent}%)`
                : `Done — ${d.processed} files hashed`;
        if (!d.running) {
            clearInterval(hashPollInterval);
            document.getElementById('btn-hash-stop').style.display = 'none';
            document.getElementById('btn-hash-start').style.display = '';
            fetchFiles(); // refresh table to show new phash values
        }
    } catch(e) {}
}

loadHashConfig();
```

**Step 2: Also expose `hashing` config in the GET /api/config response**

In `media_analyzer/server/api.py`, update `get_config()`:

```python
@api_bp.route("/config", methods=["GET"])
def get_config():
    config = _get_config()
    safe_config = {
        "scan_dirs": config.get("scan_dirs", []),
        "server": config.get("server", {}),
        "file_extensions": config.get("file_extensions", {}),
        "has_secret_token": bool(config.get("secret_token")),
        "hashing": config.get("hashing", {}),
    }
    return jsonify(safe_config)
```

**Step 3: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All green.

**Step 4: Run linter on all changed files**

```bash
uv run ruff check .
uv run ruff format --check .
```

Fix any issues.

**Step 5: Commit**

```bash
git add media_analyzer/server/templates/videos.html media_analyzer/server/api.py
git commit -m "feat: add phash column and Compute Hashes UI to videos page"
```

---

## Task 10: Full verification

**Step 1: Run the complete test suite**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass, no warnings.

**Step 2: Run linter across entire project**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: No issues.

**Step 3: Verify the jobs package is importable**

```bash
uv run python -c "
from media_analyzer.jobs.runner import JobRunner, JobProgress
from media_analyzer.jobs.hasher import quick_hash, video_phash
from media_analyzer.jobs.phash_job import run_phash_job, phash_progress
print('All imports OK')
"
```

Expected: `All imports OK`

**Step 4: Final commit if any lint fixes were needed**

```bash
git add -A
git status  # review what changed
git commit -m "chore: lint fixes and final cleanup"
```

---

## Summary of Files Changed

| Action | File |
|--------|------|
| Modify | `pyproject.toml` |
| Modify | `media_analyzer/config.py` |
| Modify | `media_analyzer/db.py` |
| Modify | `media_analyzer/scanner.py` |
| Modify | `media_analyzer/server/api.py` |
| Modify | `media_analyzer/server/templates/videos.html` |
| Create | `media_analyzer/jobs/__init__.py` |
| Create | `media_analyzer/jobs/runner.py` |
| Create | `media_analyzer/jobs/hasher.py` |
| Create | `media_analyzer/jobs/phash_job.py` |
| Create | `tests/test_db.py` |
| Create | `tests/test_runner.py` |
| Create | `tests/test_hasher.py` |
| Create | `tests/test_phash_job.py` |
| Modify | `tests/test_api.py` |
