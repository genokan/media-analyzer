"""Media Analyzer - scan video/audio files and browse results via web UI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("media-analyzer")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
