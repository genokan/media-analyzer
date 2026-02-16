"""VR video prober - extends VideoProber with VR-specific metadata."""

import re

from media_analyzer.probers.video import VideoProber

# Filename patterns indicating VR content
VR_FILENAME_PATTERNS = {
    "180": re.compile(r"[_\-.]180[_\-.]|180x180", re.IGNORECASE),
    "360": re.compile(r"[_\-.]360[_\-.]", re.IGNORECASE),
    "sbs": re.compile(r"[_\-.](?:sbs|lr)[_\-.]", re.IGNORECASE),
    "tb": re.compile(r"[_\-.](?:tb|ou)[_\-.]", re.IGNORECASE),
    "half_sbs": re.compile(r"[_\-.](?:3dh|half)[_\-.]", re.IGNORECASE),
}


def _detect_vr_from_filename(filename: str) -> dict:
    """Extract VR indicators from filename patterns."""
    indicators = {}
    for key, pattern in VR_FILENAME_PATTERNS.items():
        if pattern.search(filename):
            indicators[key] = True
    return indicators


def _detect_format_from_ratio(width: int, height: int) -> str | None:
    """Detect VR format from aspect ratio (reused from video-analyzer.sh)."""
    if height == 0:
        return None
    ratio = width / height

    # Side-by-side: ~2:1
    if 1.9 <= ratio <= 2.1:
        return "SBS"
    # Top-bottom: ~1:1 with high res
    if 0.9 <= ratio <= 1.1 and width >= 3000:
        return "TB"
    return None


class VRProber(VideoProber):
    """Probes video files for VR-specific metadata.

    This should be tried first for video files. If the result indicates
    the file is VR (is_vr=True), use media_type='vr'; otherwise fall
    back to plain 'video'.
    """

    def probe(self, file_path: str) -> dict | None:
        # Get base video metadata first
        result = super().probe(file_path)
        if result is None:
            return None

        filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        width = result["width"]
        height = result["height"]

        # Check embedded VR metadata via ffprobe
        stereo_mode = self._run_ffprobe_raw(
            [
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream_tags=stereo_mode",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
            ],
            file_path,
        )
        spherical_str = self._run_ffprobe_raw(
            ["-show_entries", "format_tags=Spherical", "-of", "default=noprint_wrappers=1:nokey=1"],
            file_path,
        )
        projection = self._run_ffprobe_raw(
            [
                "-show_entries",
                "format_tags=ProjectionType",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
            ],
            file_path,
        )

        spherical = bool(spherical_str and spherical_str.lower() in ("true", "1", "yes"))
        stereo_mode = stereo_mode if stereo_mode else None
        projection = projection if projection else None

        # Filename-based detection
        fn_indicators = _detect_vr_from_filename(filename)

        # Aspect-ratio-based format detection
        ratio_format = _detect_format_from_ratio(width, height)

        # Determine if VR
        is_vr = False
        vr_format = None
        fov = None

        if stereo_mode or spherical:
            is_vr = True
        if fn_indicators:
            is_vr = True
        if ratio_format:
            is_vr = True
            vr_format = ratio_format
        # High resolution could be VR
        if not is_vr and (width >= 5000 or height >= 2500):
            is_vr = True  # Mark as likely VR

        # Determine VR format from indicators
        if not vr_format:
            if fn_indicators.get("sbs") or fn_indicators.get("half_sbs"):
                vr_format = "SBS"
            elif fn_indicators.get("tb"):
                vr_format = "TB"
            elif stereo_mode:
                if "side" in stereo_mode.lower() or "left" in stereo_mode.lower():
                    vr_format = "SBS"
                elif "top" in stereo_mode.lower() or "bottom" in stereo_mode.lower():
                    vr_format = "TB"

        # Determine FOV
        if fn_indicators.get("180"):
            fov = "180"
        elif fn_indicators.get("360"):
            fov = "360"
        elif spherical:
            fov = "360"

        # Calculate per-eye resolution
        per_eye_width = width
        per_eye_height = height
        if vr_format == "SBS":
            per_eye_width = width // 2
        elif vr_format == "TB":
            per_eye_height = height // 2

        # Per-eye bitrate
        per_eye_bitrate = None
        video_bitrate = result.get("video_bitrate")
        if video_bitrate and vr_format in ("SBS", "TB"):
            per_eye_bitrate = video_bitrate // 2

        # Metadata completeness: what fraction of VR fields are populated
        vr_fields = [stereo_mode, spherical or None, projection, vr_format, fov]
        populated = sum(1 for f in vr_fields if f)
        metadata_completeness = round(populated / len(vr_fields) * 100, 1) if is_vr else None

        result["vr"] = {
            "is_vr": is_vr,
            "vr_format": vr_format,
            "stereo_mode": stereo_mode,
            "projection_type": projection,
            "spherical": spherical,
            "fov": fov,
            "per_eye_width": per_eye_width if is_vr else None,
            "per_eye_height": per_eye_height if is_vr else None,
            "per_eye_bitrate": per_eye_bitrate,
            "metadata_completeness": metadata_completeness,
        }

        if is_vr:
            result["media_type"] = "vr"

        return result
