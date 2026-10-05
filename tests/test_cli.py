from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness_intelligence.cli import main


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "auth.py").write_text(
            "def validate_token(token):\n    return token == 'valid'\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *argv: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["hil", *argv]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            main()
        return json.loads(stdout.getvalue())

    def test_index_then_context_through_cli(self) -> None:
        indexed = self._run("index", str(self.root))
        self.assertEqual(indexed["indexed_files"], 1)
        self.assertEqual(indexed["candidate_files"], 1)
        self.assertIn("indexed_at", indexed)
        result = self._run(
            "context", "validate_token authentication", str(self.root), "--budget", "500"
        )
        self.assertLessEqual(result["estimated_tokens"], 500)
        self.assertTrue(any(item["path"] == "auth.py" for item in result["fragments"]))
        self.assertFalse(result["index"]["refreshed"])

    def test_memory_record_then_search_through_cli(self) -> None:
        saved = self._run(
            "memory-record",
            "decisions",
            "Token policy",
            "Compare tokens in constant time.",
            str(self.root),
            "--tag",
            "auth",
        )
        found = self._run("memory-search", "token policy", str(self.root))
        self.assertEqual(found[0]["id"], saved["id"])

    def test_no_refresh_skips_the_freshness_walk(self) -> None:
        self._run("index", str(self.root))
        (self.root / "billing.py").write_text(
            "def charge_card(order):\n    return order.total\n", encoding="utf-8"
        )
        first = self._run("context", "charge_card", str(self.root))
        self.assertTrue(first["index"]["refreshed"])
        # The refresh above made the index current again, so a second call is a hit.
        current = self._run("context", "charge_card", str(self.root), "--no-refresh")
        self.assertFalse(current["index"]["refreshed"])
        self.assertIsNone(current["index"]["stale_reason"])
        # Drift once more and skip the check: the new file must be reported as unreachable.
        (self.root / "payments.py").write_text(
            "def refund(order):\n    return order.total\n", encoding="utf-8"
        )
        stale = self._run("context", "refund payments", str(self.root), "--no-refresh")
        self.assertFalse(stale["index"]["refreshed"])
        self.assertIsNotNone(stale["index"]["stale_reason"])
        self.assertIn("WARNING: index is stale", stale["notice"])
        self.assertFalse(any(item["path"] == "payments.py" for item in stale["fragments"]))

    def test_budget_below_minimum_exits_with_usage_error(self) -> None:
        self._run("index", str(self.root))
        with self.assertRaises(SystemExit) as caught:
            self._run("context", "auth", str(self.root), "--budget", "100")
        self.assertEqual(caught.exception.code, 2)

    def test_invalid_memory_category_exits_with_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self._run(
                "memory-record", "chat-log", "Title", "Body", str(self.root)
            )
        self.assertEqual(caught.exception.code, 2)

    def test_index_rejects_missing_directory(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self._run("index", str(self.root / "does-not-exist"))
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()