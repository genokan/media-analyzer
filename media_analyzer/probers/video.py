"""Video file prober using ffprobe."""

from media_analyzer.probers.base import BaseProber


def _resolution_label(height: int) -> str:
    """Map height to a human-readable resolution label."""
    if height >= 4320:
        return "8K"
    if height >= 2880:
        return "5.7K"
    if height >= 2160:
        return "4K"
    if height >= 1440:
        return "1440p"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    if height >= 480:
        return "480p"
    return f"{height}p"


def _parse_frame_rate(rate_str: str | None) -> float | None:
    """Parse frame rate string like '30/1' or '29.97' to float."""
    if not rate_str:
        return None
    if "/" in rate_str:
        parts = rate_str.split("/")
        try:
            num, den = float(parts[0]), float(parts[1])
            return round(num / den, 3) if den else None
        except (ValueError, IndexError):
            return None
    try:
        return round(float(rate_str), 3)
    except ValueError:
        return None


class VideoProber(BaseProber):
    supported_extensions = {".mp4", ".mkv", ".avi", ".mov", ".m4v"}

    def probe(self, file_path: str) -> dict | None:
        # Get video stream info
        data = self._run_ffprobe(
            [
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,codec_name,pix_fmt,color_space,bit_rate",
            ],
            file_path,
        )
        if not data or not data.get("streams"):
            return None

        stream = data["streams"][0]
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        if not width or not height:
            return None

        video_codec = stream.get("codec_name")
        frame_rate = _parse_frame_rate(stream.get("r_frame_rate"))
        pixel_format = stream.get("pix_fmt")
        color_space = stream.get("color_space")
        video_bitrate = self._parse_int(stream.get("bit_rate"))

        # Get audio stream info
        audio_data = self._run_ffprobe(
            ["-select_streams", "a:0", "-show_entries", "stream=codec_name,bit_rate"],
            file_path,
        )
        audio_codec = None
        audio_bitrate = None
        if audio_data and audio_data.get("streams"):
            a_stream = audio_data["streams"][0]
            audio_codec = a_stream.get("codec_name")
            audio_bitrate = self._parse_int(a_stream.get("bit_rate"))

        # Get format-level info (overall bitrate, duration, container)
        fmt_data = self._run_ffprobe(
            ["-show_entries", "format=duration,bit_rate,format_name"],
            file_path,
        )
        duration = None
        overall_bitrate = None
        container_format = None
        if fmt_data and fmt_data.get("format"):
            fmt = fmt_data["format"]
            duration = self._parse_float(fmt.get("duration"))
            overall_bitrate = self._parse_int(fmt.get("bit_rate"))
            container_format = fmt.get("format_name")

        # If video bitrate not available from stream, estimate from overall
        if not video_bitrate and overall_bitrate and audio_bitrate:
            video_bitrate = overall_bitrate - audio_bitrate
        elif not video_bitrate and overall_bitrate:
            video_bitrate = overall_bitrate

        # Calculate bitrate per pixel
        bitrate_per_pixel = None
        if video_bitrate and width and height and frame_rate:
            pixels_per_sec = width * height * frame_rate
            if pixels_per_sec > 0:
                bitrate_per_pixel = round(video_bitrate / pixels_per_sec, 4)

        return {
            "media_type": "video",
            "container_format": container_format,
            "duration": duration,
            "bitrate": overall_bitrate,
            "width": width,
            "height": height,
            "resolution_label": _resolution_label(height),
            "frame_rate": frame_rate,
            "pixel_format": pixel_format,
            "color_space": color_space,
            "video_bitrate": video_bitrate,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "audio_bitrate": audio_bitrate,
            "bitrate_per_pixel": bitrate_per_pixel,
        }

    @staticmethod
    def _parse_int(val) -> int | None:
        if val is None or val == "N/A":
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_float(val) -> float | None:
        if val is None or val == "N/A":
            return None
        try:
            return round(float(val), 3)
        except (ValueError, TypeError):
            return None
