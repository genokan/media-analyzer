"""Tests for database layer — hashing additions."""

import sqlite3

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
        conn = sqlite3.connect(db.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(media_files)").fetchall()]
        conn.close()
        assert "quick_hash" in cols

    def test_video_phash_column_exists(self, db, sample_file_id):
        """media_files must have a video_phash column."""
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
