"""Tests for Flask API endpoints."""

import json

import pytest

from media_analyzer.server.app import create_app


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
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
    }
    app = create_app(config)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return app.config["DB"]


class TestFilesAPI:
    def test_list_empty(self, client):
        res = client.get("/api/files")
        assert res.status_code == 200
        data = res.get_json()
        assert data["total"] == 0
        assert data["files"] == []

    def test_list_with_data(self, client, db):
        file_id = db.upsert_media_file(
            {
                "file_path": "/test/video.mp4",
                "filename": "video.mp4",
                "file_size": 1000000,
                "modified_date": "2024-01-01T00:00:00",
                "media_type": "video",
                "container_format": "mp4",
                "duration": 120.0,
                "bitrate": 5000000,
            }
        )
        db.upsert_video_metadata(
            file_id,
            {
                "width": 1920,
                "height": 1080,
                "resolution_label": "1080p",
                "video_codec": "h264",
            },
        )

        res = client.get("/api/files")
        data = res.get_json()
        assert data["total"] == 1
        assert data["files"][0]["filename"] == "video.mp4"

    def test_filter_by_type(self, client, db):
        db.upsert_media_file(
            {
                "file_path": "/test/video.mp4",
                "filename": "video.mp4",
                "file_size": 1000,
                "modified_date": "2024-01-01",
                "media_type": "video",
            }
        )
        db.upsert_media_file(
            {
                "file_path": "/test/song.mp3",
                "filename": "song.mp3",
                "file_size": 500,
                "modified_date": "2024-01-01",
                "media_type": "audio",
            }
        )

        res = client.get("/api/files?media_type=audio")
        data = res.get_json()
        assert data["total"] == 1
        assert data["files"][0]["filename"] == "song.mp3"

    def test_search(self, client, db):
        db.upsert_media_file(
            {
                "file_path": "/test/video.mp4",
                "filename": "video.mp4",
                "file_size": 1000,
                "modified_date": "2024-01-01",
                "media_type": "video",
            }
        )
        db.upsert_media_file(
            {
                "file_path": "/test/song.mp3",
                "filename": "song.mp3",
                "file_size": 500,
                "modified_date": "2024-01-01",
                "media_type": "audio",
            }
        )

        res = client.get("/api/files?search=song")
        data = res.get_json()
        assert data["total"] == 1


class TestFileDetail:
    def test_get_existing(self, client, db):
        file_id = db.upsert_media_file(
            {
                "file_path": "/test/video.mp4",
                "filename": "video.mp4",
                "file_size": 1000,
                "modified_date": "2024-01-01",
                "media_type": "video",
            }
        )

        res = client.get(f"/api/files/{file_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["filename"] == "video.mp4"

    def test_get_not_found(self, client):
        res = client.get("/api/files/9999")
        assert res.status_code == 404


class TestStatsAPI:
    def test_empty_stats(self, client):
        res = client.get("/api/stats")
        assert res.status_code == 200
        data = res.get_json()
        assert data["total_files"] == 0

    def test_stats_with_data(self, client, db):
        db.upsert_media_file(
            {
                "file_path": "/test/v.mp4",
                "filename": "v.mp4",
                "file_size": 1000,
                "modified_date": "2024-01-01",
                "media_type": "video",
                "bitrate": 5000000,
            }
        )
        db.upsert_media_file(
            {
                "file_path": "/test/s.mp3",
                "filename": "s.mp3",
                "file_size": 500,
                "modified_date": "2024-01-01",
                "media_type": "audio",
                "bitrate": 320000,
            }
        )

        res = client.get("/api/stats")
        data = res.get_json()
        assert data["total_files"] == 2
        assert data["by_type"]["video"] == 1
        assert data["by_type"]["audio"] == 1


class TestConfigAPI:
    def test_get_config(self, client):
        res = client.get("/api/config")
        assert res.status_code == 200
        data = res.get_json()
        assert "scan_dirs" in data
        assert "has_secret_token" in data
        # Should not expose secrets
        assert "secret_token" not in data
        assert "_flask_secret" not in data

    def test_update_config(self, client):
        res = client.put(
            "/api/config",
            data=json.dumps({"scan_dirs": ["/tmp/test"]}),
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "updated"


class TestScanAPI:
    def test_scan_status(self, client):
        res = client.get("/api/scan/status")
        assert res.status_code == 200
        data = res.get_json()
        assert "running" in data
        assert data["running"] is False


class TestAuth:
    def test_no_auth_when_no_token(self, client):
        # No secret_token configured, all requests pass
        res = client.get("/api/files")
        assert res.status_code == 200

    def test_auth_required_with_token(self, tmp_path):
        config = {
            "scan_dirs": [],
            "server": {"host": "127.0.0.1", "port": 8080},
            "db_path": str(tmp_path / "test.db"),
            "secret_token": "test-secret-123",
            "_flask_secret": "flask-secret",
            "file_extensions": {"video": [], "audio": []},
        }
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Without token - should be 401
        res = client.get("/api/files")
        assert res.status_code == 401

        # With correct header
        res = client.get("/api/files", headers={"X-API-Key": "test-secret-123"})
        assert res.status_code == 200

    def test_auth_with_query_param(self, tmp_path):
        config = {
            "scan_dirs": [],
            "server": {"host": "127.0.0.1", "port": 8080},
            "db_path": str(tmp_path / "test.db"),
            "secret_token": "test-secret-123",
            "_flask_secret": "flask-secret",
            "file_extensions": {"video": [], "audio": []},
        }
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        res = client.get("/api/files?token=test-secret-123")
        assert res.status_code == 200

    def test_auth_bad_token(self, tmp_path):
        config = {
            "scan_dirs": [],
            "server": {"host": "127.0.0.1", "port": 8080},
            "db_path": str(tmp_path / "test.db"),
            "secret_token": "correct-token",
            "_flask_secret": "flask-secret",
            "file_extensions": {"video": [], "audio": []},
        }
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        res = client.get("/api/files", headers={"X-API-Key": "wrong-token"})
        assert res.status_code == 401
