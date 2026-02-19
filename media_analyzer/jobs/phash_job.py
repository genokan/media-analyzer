"""Background job for computing video perceptual hashes in bulk."""

import logging

from media_analyzer.db import Database
from media_analyzer.jobs.hasher import video_phash
from media_analyzer.jobs.runner import JobProgress, JobRunner

logger = logging.getLogger(__name__)

# Global progress tracker shared with the API layer.
phash_progress = JobProgress()


def run_phash_job(
    db: Database,
    config: dict,
    scan_dirs: list[str] | None = None,
) -> int:
    """Compute perceptual hashes for video files missing video_phash.

    Args:
        db: Database instance.
        config: Application config dict.
        scan_dirs: Optional list of directories to scope the job. If None,
            all video/VR files in the DB are eligible.

    Returns:
        Count of files successfully hashed.
    """
    max_workers = config.get("hashing", {}).get("workers", 4)
    files = db.get_unhashed_videos(scan_dirs=scan_dirs)
    logger.info(
        "Phash job starting: %d files to hash, %d workers", len(files), max_workers
    )

    phash_progress.running = True
    phash_progress.total = len(files)
    phash_progress.processed = 0
    phash_progress.cancel_requested = False

    def worker(row: dict) -> dict | None:
        file_path = row["file_path"]
        try:
            h = video_phash(file_path, row.get("duration"))
            if h is None:
                return None
            return {"file_id": row["id"], "video_phash": h}
        except Exception:
            logger.exception("Phash worker failed for: %s", file_path)
            return None

    def writer(row: dict, result: dict):
        db.upsert_video_phash(result["file_id"], result["video_phash"])

    runner = JobRunner(max_workers=max_workers)
    try:
        written = runner.run(files, worker, writer, phash_progress)
        logger.info("Phash job complete: %d/%d files hashed", written, len(files))
        return written
    finally:
        phash_progress.running = False
        phash_progress.cancel_requested = False
