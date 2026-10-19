"""Usage metrics must be local, bounded, silent on failure, and content-free."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from harness_intelligence import metrics


class MetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = os.environ.get(metrics.METRICS_ENV)
        os.environ.pop(metrics.METRICS_ENV, None)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop(metrics.METRICS_ENV, None)
        else:
            os.environ[metrics.METRICS_ENV] = self.previous
        self.temp.cleanup()

    def _record(self) -> None:
        metrics.record(
            self.root,
            latency_ms=12.34,
            fragments=3,
            tokens=100,
            memories=1,
            mode="lexical",
            confidence="high",
            sufficient=True,
        )

    def test_a_call_appends_one_line_without_any_text(self) -> None:
        self._record()
        rows = metrics.load(self.root)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["fragments"], 3)
        self.assertEqual(row["latency_ms"], 12.3)
        # No query text, task, fragments content, or memory text.
        for forbidden in ("task", "query", "content", "title"):
            self.assertNotIn(forbidden, row)

    def test_off_disables_everything(self) -> None:
        os.environ[metrics.METRICS_ENV] = "off"
        self._record()
        self.assertEqual(metrics.load(self.root), [])

    def test_rotation_keeps_one_previous_generation(self) -> None:
        original = metrics.MAX_BYTES
        metrics.MAX_BYTES = 1
        try:
            self._record()
            self._record()
        finally:
            metrics.MAX_BYTES = original
        self.assertTrue((self.root / ".hil" / "metrics.jsonl.1").exists())
        self.assertEqual(len(metrics.load(self.root)), 2)

    def test_a_broken_path_is_swallowed(self) -> None:
        # Pointing at a file (not a directory) must not raise out of record().
        blocker = self.root / "blocked"
        blocker.write_text("x", encoding="utf-8")
        metrics.record(
            blocker,
            latency_ms=1,
            fragments=0,
            tokens=0,
            memories=0,
            mode="lexical",
            confidence=None,
            sufficient=False,
        )
        self.assertEqual(metrics.load(blocker), [])


if __name__ == "__main__":
    unittest.main()
