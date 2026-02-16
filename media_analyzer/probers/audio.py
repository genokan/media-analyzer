"""Audio file prober using ffprobe."""

from media_analyzer.probers.base import BaseProber

LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "tak", "pcm_s16le", "pcm_s24le", "pcm_s32le"}


class AudioProber(BaseProber):
    supported_extensions = {".mp3", ".aac", ".flac", ".wav", ".ogg", ".wma", ".m4a", ".opus"}

    def probe(self, file_path: str) -> dict | None:
        # Get audio stream info
        data = self._run_ffprobe(
            [
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,bits_per_raw_sample,channels,bit_rate",
            ],
            file_path,
        )
        if not data or not data.get("streams"):
            return None

        stream = data["streams"][0]
        codec = stream.get("codec_name")
        sample_rate = self._parse_int(stream.get("sample_rate"))
        bit_depth = self._parse_int(stream.get("bits_per_raw_sample"))
        channels = self._parse_int(stream.get("channels"))
        audio_bitrate = self._parse_int(stream.get("bit_rate"))

        # Get format-level info
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

        if not audio_bitrate:
            audio_bitrate = overall_bitrate

        # Get tags
        tag_data = self._run_ffprobe(
            ["-show_entries", "format_tags=title,artist,album,genre,date,track"],
            file_path,
        )
        tags = {}
        if tag_data and tag_data.get("format") and tag_data["format"].get("tags"):
            raw_tags = tag_data["format"]["tags"]
            # Tags can be mixed case
            for key, value in raw_tags.items():
                tags[key.lower()] = value

        is_lossless = codec in LOSSLESS_CODECS if codec else False

        return {
            "media_type": "audio",
            "container_format": container_format,
            "duration": duration,
            "bitrate": audio_bitrate or overall_bitrate,
            "audio": {
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "channels": channels,
                "audio_bitrate": audio_bitrate,
                "is_lossless": is_lossless,
                "title": tags.get("title"),
                "artist": tags.get("artist"),
                "album": tags.get("album"),
                "genre": tags.get("genre"),
                "year": tags.get("date"),
                "track_number": tags.get("track"),
            },
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
