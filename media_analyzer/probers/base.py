"""Base prober interface."""

import json
import logging
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseProber(ABC):
    supported_extensions: set[str] = set()

    @abstractmethod
    def probe(self, file_path: str) -> dict | None:
        """Probe a media file and return metadata dict, or None on failure."""

    def _run_ffprobe(self, args: list[str], file_path: str) -> dict | None:
        """Run ffprobe with the given arguments and return parsed JSON output."""
        cmd = ["ffprobe", "-v", "error"] + args + ["-of", "json", file_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.warning("ffprobe failed for %s: %s", file_path, e)
            return None

    def _run_ffprobe_raw(self, args: list[str], file_path: str) -> str | None:
        """Run ffprobe and return raw stdout text."""
        cmd = ["ffprobe", "-v", "error"] + args + [file_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.warning("ffprobe failed for %s: %s", file_path, e)
            return None
