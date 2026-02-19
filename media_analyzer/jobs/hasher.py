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
            logger.warning("Failed to compute dhash at %.1fs in %s", timestamp, file_path)

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
