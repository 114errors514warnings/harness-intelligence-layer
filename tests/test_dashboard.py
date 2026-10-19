"""The dashboard is a pure renderer over snapshot + usage aggregates."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "hil_dashboard.py"
_spec = importlib.util.spec_from_file_location("hil_dashboard", TOOL_PATH)
assert _spec and _spec.loader
hil_dashboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hil_dashboard)


class DashboardTests(unittest.TestCase):
    def test_percentile_is_safe_on_empty_and_small_inputs(self) -> None:
        self.assertEqual(hil_dashboard.percentile([], 50), 0)
        self.assertEqual(hil_dashboard.percentile([7], 95), 7)
        self.assertIn(hil_dashboard.percentile([1, 2, 3, 4], 50), (2, 3))

    def test_summarise_usage_reports_the_rates(self) -> None:
        rows = [
            {"latency_ms": 10, "tokens": 100, "sufficient": True, "confidence": "high", "mode": "lexical"},
            {"latency_ms": 30, "tokens": 300, "sufficient": False, "confidence": "low", "mode": "embedding"},
        ]
        summary = hil_dashboard.summarise_usage(rows)
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["tokens"], 200)
        self.assertEqual(summary["fallback"], 50)
        self.assertEqual(summary["low_confidence"], 50)
        self.assertEqual(summary["embedding"], 50)
        self.assertEqual(hil_dashboard.summarise_usage([]), {"calls": 0})

    def test_render_contains_the_project_and_the_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facts = {
                "project": str(root),
                "indexed": True,
                "fresh": True,
                "files": 3,
                "symbols": 7,
                "memory": {"total": 2},
                "issues": [],
            }
            page = hil_dashboard.render(
                [{"facts": facts, "usage": {"calls": 0}, "recent_rows": []}], [root], 7
            )
        self.assertIn("HIL Dashboard", page)
        self.assertIn(root.name, page)
        self.assertIn("近 14 天调用", page)
        self.assertIn("<svg", page)

    def test_daily_counts_cover_the_whole_window(self) -> None:
        buckets = hil_dashboard.daily_counts([], 5)
        self.assertEqual(len(buckets), 5)
        self.assertEqual(sum(count for _day, count in buckets), 0)


if __name__ == "__main__":
    unittest.main()
