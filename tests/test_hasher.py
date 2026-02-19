"""Tests for quick_hash and video_phash functions."""

import io
from unittest.mock import patch

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

        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")

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
            assert len(part) > 0

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

        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")

        img = PIL.Image.new("RGB", (64, 64))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        frame_bytes = buf.getvalue()

        side_effects = [frame_bytes, None, None, None]
        with patch("media_analyzer.jobs.hasher._extract_frame", side_effect=side_effects):
            result = video_phash(str(f), 120.0, num_frames=4)

        assert result is not None
        assert "|" not in result  # only one hash, no pipe
