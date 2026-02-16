"""Tests for media probers."""

from unittest.mock import patch

import pytest

from media_analyzer.probers.audio import AudioProber
from media_analyzer.probers.video import VideoProber, _parse_frame_rate, _resolution_label
from media_analyzer.probers.vr import VRProber, _detect_format_from_ratio, _detect_vr_from_filename

# --- Video Prober ---


class TestResolutionLabel:
    def test_8k(self):
        assert _resolution_label(4320) == "8K"

    def test_4k(self):
        assert _resolution_label(2160) == "4K"

    def test_1080p(self):
        assert _resolution_label(1080) == "1080p"

    def test_720p(self):
        assert _resolution_label(720) == "720p"

    def test_480p(self):
        assert _resolution_label(480) == "480p"

    def test_custom(self):
        assert _resolution_label(360) == "360p"


class TestParseFrameRate:
    def test_fraction(self):
        assert _parse_frame_rate("30/1") == 30.0

    def test_ntsc(self):
        assert _parse_frame_rate("30000/1001") == pytest.approx(29.97, abs=0.01)

    def test_decimal(self):
        assert _parse_frame_rate("59.94") == pytest.approx(59.94, abs=0.01)

    def test_none(self):
        assert _parse_frame_rate(None) is None

    def test_invalid(self):
        assert _parse_frame_rate("invalid") is None


def _mock_ffprobe_video():
    """Return mock ffprobe outputs for a standard video file."""
    video_stream = {
        "streams": [
            {
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "color_space": "bt709",
                "bit_rate": "5000000",
            }
        ]
    }
    audio_stream = {"streams": [{"codec_name": "aac", "bit_rate": "128000"}]}
    format_info = {
        "format": {
            "duration": "120.5",
            "bit_rate": "5128000",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        }
    }
    return video_stream, audio_stream, format_info


class TestVideoProber:
    @patch.object(VideoProber, "_run_ffprobe")
    def test_probe_success(self, mock_ffprobe):
        video, audio, fmt = _mock_ffprobe_video()
        mock_ffprobe.side_effect = [video, audio, fmt]

        prober = VideoProber()
        result = prober.probe("/test/video.mp4")

        assert result is not None
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["video_codec"] == "h264"
        assert result["audio_codec"] == "aac"
        assert result["resolution_label"] == "1080p"
        assert result["media_type"] == "video"
        assert result["duration"] == 120.5
        assert result["bitrate_per_pixel"] is not None

    @patch.object(VideoProber, "_run_ffprobe")
    def test_probe_no_streams(self, mock_ffprobe):
        mock_ffprobe.return_value = {"streams": []}
        prober = VideoProber()
        assert prober.probe("/test/video.mp4") is None

    @patch.object(VideoProber, "_run_ffprobe")
    def test_probe_failure(self, mock_ffprobe):
        mock_ffprobe.return_value = None
        prober = VideoProber()
        assert prober.probe("/test/video.mp4") is None


# --- VR Detection ---


class TestVRFilenameDetection:
    def test_180(self):
        indicators = _detect_vr_from_filename("video_180_sbs.mp4")
        assert indicators.get("180") is True

    def test_360(self):
        indicators = _detect_vr_from_filename("video_360_tb.mp4")
        assert indicators.get("360") is True

    def test_sbs(self):
        indicators = _detect_vr_from_filename("video_sbs_4k.mp4")
        assert indicators.get("sbs") is True

    def test_lr(self):
        indicators = _detect_vr_from_filename("video_lr_hd.mp4")
        assert indicators.get("sbs") is True

    def test_tb(self):
        indicators = _detect_vr_from_filename("video_tb_uhd.mp4")
        assert indicators.get("tb") is True

    def test_ou(self):
        indicators = _detect_vr_from_filename("video_ou_hd.mp4")
        assert indicators.get("tb") is True

    def test_3dh(self):
        indicators = _detect_vr_from_filename("video_3dh_4k.mp4")
        assert indicators.get("half_sbs") is True

    def test_no_match(self):
        indicators = _detect_vr_from_filename("regular_video.mp4")
        assert len(indicators) == 0


class TestFormatFromRatio:
    def test_sbs(self):
        assert _detect_format_from_ratio(3840, 1920) == "SBS"

    def test_tb(self):
        assert _detect_format_from_ratio(3840, 3840) == "TB"

    def test_regular(self):
        assert _detect_format_from_ratio(1920, 1080) is None

    def test_tb_low_res(self):
        # 1:1 but low res - not VR
        assert _detect_format_from_ratio(1000, 1000) is None


class TestVRProber:
    @patch.object(VRProber, "_run_ffprobe_raw")
    @patch.object(VRProber, "_run_ffprobe")
    def test_vr_by_filename(self, mock_ffprobe, mock_raw):
        video, audio, fmt = _mock_ffprobe_video()
        # Override to 2:1 ratio for SBS
        video["streams"][0]["width"] = 3840
        video["streams"][0]["height"] = 1920
        mock_ffprobe.side_effect = [video, audio, fmt]
        mock_raw.return_value = ""

        prober = VRProber()
        result = prober.probe("/test/video_180_sbs.mp4")

        assert result is not None
        assert result["media_type"] == "vr"
        assert result["vr"]["is_vr"] is True
        assert result["vr"]["vr_format"] == "SBS"
        assert result["vr"]["per_eye_width"] == 1920

    @patch.object(VRProber, "_run_ffprobe_raw")
    @patch.object(VRProber, "_run_ffprobe")
    def test_non_vr(self, mock_ffprobe, mock_raw):
        video, audio, fmt = _mock_ffprobe_video()
        mock_ffprobe.side_effect = [video, audio, fmt]
        mock_raw.return_value = ""

        prober = VRProber()
        result = prober.probe("/test/regular_video.mp4")

        assert result is not None
        assert result["media_type"] == "video"
        assert result["vr"]["is_vr"] is False


# --- Audio Prober ---


class TestAudioProber:
    @patch.object(AudioProber, "_run_ffprobe")
    def test_probe_mp3(self, mock_ffprobe):
        audio_stream = {
            "streams": [
                {
                    "codec_name": "mp3",
                    "sample_rate": "44100",
                    "bits_per_raw_sample": "16",
                    "channels": "2",
                    "bit_rate": "320000",
                }
            ]
        }
        fmt = {
            "format": {
                "duration": "240.0",
                "bit_rate": "320000",
                "format_name": "mp3",
            }
        }
        tags = {
            "format": {
                "tags": {
                    "title": "Test Song",
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "genre": "Rock",
                    "date": "2024",
                    "track": "1",
                }
            }
        }
        mock_ffprobe.side_effect = [audio_stream, fmt, tags]

        prober = AudioProber()
        result = prober.probe("/test/song.mp3")

        assert result is not None
        assert result["media_type"] == "audio"
        assert result["audio"]["sample_rate"] == 44100
        assert result["audio"]["channels"] == 2
        assert result["audio"]["is_lossless"] is False
        assert result["audio"]["title"] == "Test Song"
        assert result["audio"]["artist"] == "Test Artist"

    @patch.object(AudioProber, "_run_ffprobe")
    def test_probe_flac_lossless(self, mock_ffprobe):
        audio_stream = {
            "streams": [
                {
                    "codec_name": "flac",
                    "sample_rate": "96000",
                    "bits_per_raw_sample": "24",
                    "channels": "2",
                    "bit_rate": None,
                }
            ]
        }
        fmt = {
            "format": {
                "duration": "300.0",
                "bit_rate": "1500000",
                "format_name": "flac",
            }
        }
        tags = {"format": {"tags": {}}}
        mock_ffprobe.side_effect = [audio_stream, fmt, tags]

        prober = AudioProber()
        result = prober.probe("/test/song.flac")

        assert result is not None
        assert result["audio"]["is_lossless"] is True
        assert result["audio"]["bit_depth"] == 24
        assert result["audio"]["sample_rate"] == 96000

    @patch.object(AudioProber, "_run_ffprobe")
    def test_probe_failure(self, mock_ffprobe):
        mock_ffprobe.return_value = None
        prober = AudioProber()
        assert prober.probe("/test/song.mp3") is None
