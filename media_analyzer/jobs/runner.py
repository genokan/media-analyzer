"""Shared job runner: parallel workers with serialized DB writes and cancellation."""

import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)


class JobProgress:
    """Thread-safe progress tracker with cancellation support."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0
        self.processed = 0
        self.current_file = ""
        self.running = False
        self.cancel_requested = False

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "total": self.total,
                "processed": self.processed,
                "current_file": self.current_file,
                "percent": round(self.processed / self.total * 100, 1) if self.total else 0,
            }

    def update(self, processed: int, current_file: str):
        with self._lock:
            self.processed = processed
            self.current_file = current_file


class JobRunner:
    """Run a batch job with parallel workers and serialized writes.

    Pattern:
        worker_fn(item) runs in the thread pool — expensive I/O and subprocess calls.
        writer_fn(item, result) runs on the calling thread — serialized DB writes.
        Items where worker_fn returns None are silently skipped (no writer call).

    The progress object must expose:
        - cancel_requested (bool): set True externally to request early stop.
        - update(processed: int, current_file: str): called after each item.
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers

    def run(
        self,
        items: list[Any],
        worker_fn: Callable[[Any], Any | None],
        writer_fn: Callable[[Any, Any], None],
        progress: Any,
    ) -> int:
        """Process items in parallel. Returns count of items passed to writer_fn."""
        written = 0
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(worker_fn, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]

                if progress.cancel_requested:
                    for f in futures:
                        f.cancel()
                    logger.info("Job cancelled after %d written items", written)
                    break

                try:
                    result = future.result()
                except Exception:
                    name = item[0] if isinstance(item, tuple) else str(item)
                    logger.exception("Worker failed for: %s", name)
                    result = None

                if result is not None:
                    try:
                        writer_fn(item, result)
                        written += 1
                    except Exception:
                        name = item[0] if isinstance(item, tuple) else str(item)
                        logger.exception("Writer failed for: %s", name)

                name = item[0] if isinstance(item, tuple) else str(item)
                progress.update(written, os.path.basename(str(name)))

        return written
