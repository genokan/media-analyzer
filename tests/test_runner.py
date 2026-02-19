"""Tests for JobRunner parallel execution infrastructure."""

import threading
import time

from media_analyzer.jobs.runner import JobProgress, JobRunner


class TestJobProgress:
    def test_initial_state(self):
        p = JobProgress()
        assert p.running is False
        assert p.total == 0
        assert p.processed == 0
        assert p.cancel_requested is False

    def test_to_dict(self):
        p = JobProgress()
        p.total = 10
        p.processed = 5
        p.running = True
        d = p.to_dict()
        assert d["total"] == 10
        assert d["processed"] == 5
        assert d["running"] is True
        assert d["percent"] == 50.0

    def test_percent_zero_when_total_zero(self):
        p = JobProgress()
        assert p.to_dict()["percent"] == 0

    def test_update_thread_safe(self):
        """Concurrent updates must not corrupt state."""
        p = JobProgress()
        p.total = 100
        errors = []

        def updater(i):
            try:
                p.update(i, f"file_{i}.mp4")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestJobRunner:
    def test_runs_all_items(self):
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 3
        results = []

        def worker(item):
            return item * 2

        def writer(item, result):
            results.append(result)

        written = runner.run([1, 2, 3], worker, writer, progress)
        assert written == 3
        assert sorted(results) == [2, 4, 6]

    def test_skips_none_results(self):
        """Worker returning None must not call writer."""
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 4
        written_items = []

        def worker(item):
            return item if item % 2 == 0 else None

        def writer(item, result):
            written_items.append(item)

        written = runner.run([1, 2, 3, 4], worker, writer, progress)
        assert written == 2
        assert set(written_items) == {2, 4}

    def test_worker_exception_does_not_abort(self):
        """A worker raising must not stop processing of other items."""
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 3
        results = []

        def worker(item):
            if item == 2:
                raise ValueError("boom")
            return item

        def writer(item, result):
            results.append(result)

        written = runner.run([1, 2, 3], worker, writer, progress)
        assert written == 2
        assert sorted(results) == [1, 3]

    def test_cancellation_stops_processing(self):
        """Setting cancel_requested stops issuing new writer calls."""
        runner = JobRunner(max_workers=1)
        progress = JobProgress()
        progress.total = 100
        results = []

        def worker(item):
            time.sleep(0.01)
            return item

        def writer(item, result):
            results.append(result)
            if len(results) >= 3:
                progress.cancel_requested = True

        runner.run(list(range(100)), worker, writer, progress)
        # Should stop well before 100 items
        assert len(results) < 50

    def test_progress_updated_per_item(self):
        runner = JobRunner(max_workers=2)
        progress = JobProgress()
        progress.total = 4

        def worker(item):
            return item

        def writer(item, result):
            pass

        runner.run([1, 2, 3, 4], worker, writer, progress)
        assert progress.processed == 4

    def test_writer_exception_does_not_abort(self):
        """A writer raising must not stop processing of other items."""
        runner = JobRunner(max_workers=1)
        progress = JobProgress()
        progress.total = 3
        written = []

        def worker(item):
            return item

        def writer(item, result):
            if result == 2:
                raise RuntimeError("write failed")
            written.append(result)

        count = runner.run([1, 2, 3], worker, writer, progress)
        assert count == 2
        assert sorted(written) == [1, 3]
