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
        db.upsert_media_file({
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
        import time

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
            # Small sleep so the main thread can observe cancel_requested
            # between futures completing, preventing all 20 from finishing
            # before the cancellation flag is checked.
            time.sleep(0.005)
            written.append(path)
            if len(written) >= 3:
                phash_progress.cancel_requested = True
            return "h"

        config = {"hashing": {"workers": 1}}
        with patch("media_analyzer.jobs.phash_job.video_phash", side_effect=fake_phash):
            run_phash_job(db, config)

        assert len(written) < 20
