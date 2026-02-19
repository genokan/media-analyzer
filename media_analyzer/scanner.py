"""Directory scanner — walks configured dirs, probes files, stores results."""

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from media_analyzer.db import Database
from media_analyzer.jobs.hasher import quick_hash
from media_analyzer.jobs.runner import JobRunner
from media_analyzer.probers.audio import AudioProber
from media_analyzer.probers.vr import VRProber

logger = logging.getLogger(__name__)


class ScanProgress:
    """Thread-safe scan progress tracker."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.processed = 0
        self.current_file = ""
        self.running = False
        self.scan_id: int | None = None
        self.cancel_requested = False

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "processed": self.processed,
                "current_file": self.current_file,
                "scan_id": self.scan_id,
                "percent": round(self.processed / self.total * 100, 1) if self.total else 0,
            }

    def update(self, processed: int, current_file: str):
        with self._lock:
            self.processed = processed
            self.current_file = current_file


# Global progress instance shared with the API layer.
scan_progress = ScanProgress()


def _collect_files(scan_dirs: list[str], extensions: dict) -> list[tuple[str, str]]:
    """Walk directories and collect (file_path, category) tuples.

    category is 'video' or 'audio' based on extension.
    """
    video_exts = set(extensions.get("video", []))
    audio_exts = set(extensions.get("audio", []))
    all_exts = video_exts | audio_exts
    files = []

    for scan_dir in scan_dirs:
        dir_path = Path(scan_dir)
        if not dir_path.is_dir():
            logger.warning("Scan directory does not exist: %s", scan_dir)
            continue
        for root, _dirs, filenames in os.walk(dir_path):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in all_exts:
                    full_path = os.path.join(root, fname)
                    try:
                        real = os.path.realpath(full_path)
                        if not real.startswith(os.path.realpath(scan_dir)):
                            logger.warning("Skipping symlink escape: %s", full_path)
                            continue
                    except OSError:
                        continue
                    category = "video" if ext in video_exts else "audio"
                    files.append((full_path, category))
    return files


def run_scan(db: Database, config: dict, override_scan_dirs: list[str] | None = None) -> int:
    """Execute a full library scan. Returns the scan_id.

    Uses JobRunner for parallel probing (expensive) with serialized DB writes
    (cheap). Quick hash is computed for every new or modified file. Files that
    are unchanged and already hashed are skipped entirely; unchanged files
    missing a hash receive only a quick_hash update without re-probing.
    """
    global scan_progress

    if override_scan_dirs is not None:
        scan_dirs = override_scan_dirs
    else:
        scan_dirs = config.get("scan_dirs") or []
    if isinstance(scan_dirs, str):
        scan_dirs = [scan_dirs]

    extensions = config.get("file_extensions", {})
    max_workers = config.get("hashing", {}).get("workers", 4)

    vr_prober = VRProber()
    audio_prober = AudioProber()

    files = _collect_files(scan_dirs, extensions)
    logger.info("Scan starting: %d files found, %d workers", len(files), max_workers)

    scan_id = db.start_scan()
    scan_progress.running = True
    scan_progress.total = len(files)
    scan_progress.processed = 0
    scan_progress.scan_id = scan_id
    scan_progress.cancel_requested = False

    files_written = 0

    def worker(item: tuple[str, str]) -> dict | None:
        file_path, category = item
        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            modified_date = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()

            if db.file_unchanged(file_path, file_size, modified_date):
                return None  # fully up-to-date, skip

            if db.file_needs_hash_only(file_path, file_size, modified_date):
                logger.debug("Hash-only update for: %s", file_path)
                return {
                    "_hash_only": True,
                    "_file_path": file_path,
                    "_quick_hash": quick_hash(file_path),
                }

            if category == "audio":
                result = audio_prober.probe(file_path)
            else:
                result = vr_prober.probe(file_path)

            if result is None:
                logger.warning("Could not probe: %s", file_path)
                return None

            result["_file_path"] = file_path
            result["_filename"] = os.path.basename(file_path)
            result["_file_size"] = file_size
            result["_modified_date"] = modified_date
            result["_category"] = category
            result["_quick_hash"] = quick_hash(file_path)
            return result

        except Exception:
            logger.exception("Error processing: %s", file_path)
            return None

    def writer(item: tuple[str, str], result: dict):
        nonlocal files_written

        if result.get("_hash_only"):
            db.upsert_quick_hash_by_path(result["_file_path"], result["_quick_hash"])
            files_written += 1
            return

        media_data = {
            "file_path": result["_file_path"],
            "filename": result["_filename"],
            "file_size": result["_file_size"],
            "modified_date": result["_modified_date"],
            "media_type": result["media_type"],
            "container_format": result.get("container_format"),
            "duration": result.get("duration"),
            "bitrate": result.get("bitrate"),
        }

        file_id = db.upsert_media_file(media_data)
        db.upsert_quick_hash(file_id, result["_quick_hash"])

        category = result["_category"]
        if category == "audio":
            db.upsert_audio_metadata(file_id, result.get("audio", {}))
        else:
            db.upsert_video_metadata(file_id, result)
            if "vr" in result:
                db.upsert_vr_metadata(file_id, result["vr"])

        files_written += 1

    runner = JobRunner(max_workers=max_workers)
    try:
        runner.run(files, worker, writer, scan_progress)
        db.finish_scan(scan_id, len(files), files_written, 0)
        logger.info("Scan complete: %d/%d files written", files_written, len(files))
    except Exception:
        logger.exception("Scan failed")
        db.fail_scan(scan_id, files_written)
    finally:
        scan_progress.running = False
        scan_progress.cancel_requested = False

    return scan_id
