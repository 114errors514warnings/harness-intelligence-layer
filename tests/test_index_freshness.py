from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_intelligence.indexer import (
    INDEX_VERSION,
    index_project,
    load_index,
    staleness_reason,
)
from harness_intelligence.memory import record_memory
from harness_intelligence.retrieval import get_project_context


class IndexFreshnessTests(unittest.TestCase):
    """A stored index must never be served after the working tree drifted."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write("auth.py", "def validate_token(token):\n    return token == 'valid'\n")
        self._write("docs/auth.md", "Token validation happens in auth.py.\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_current_index_is_reused(self) -> None:
        index_project(self.root)
        loaded = load_index(self.root)
        self.assertFalse(loaded["refreshed"])
        self.assertIsNone(loaded["stale_reason"])
        self.assertIsNone(staleness_reason(self.root, loaded))

    def test_new_file_triggers_rebuild_on_load(self) -> None:
        index_project(self.root)
        self._write("billing.py", "def charge_card(order):\n    return order.total\n")
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        self.assertIn("file set changed", loaded["stale_reason"])
        self.assertIn("billing.py", {entry["path"] for entry in loaded["files"]})

    def test_deleted_file_is_dropped_after_rebuild(self) -> None:
        index_project(self.root)
        (self.root / "docs" / "auth.md").unlink()
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        self.assertNotIn("docs/auth.md", {entry["path"] for entry in loaded["files"]})

    def test_edited_file_triggers_rebuild_on_load(self) -> None:
        index_project(self.root)
        self._write("auth.py", "def validate_token(token):\n    return token == 'valid'\n\n\ndef refresh_token(token):\n    return token\n")
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        auth = next(entry for entry in loaded["files"] if entry["path"] == "auth.py")
        self.assertIn("refresh_token", {symbol["name"] for symbol in auth["symbols"]})

    def test_old_schema_forces_rebuild(self) -> None:
        index_project(self.root)
        path = self.root / ".hil" / "index.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = INDEX_VERSION - 1
        del payload["fingerprint"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        self.assertEqual(loaded["version"], INDEX_VERSION)
        self.assertIn(f"schema version {INDEX_VERSION - 1}", loaded["stale_reason"])

    def test_unreadable_index_is_rebuilt(self) -> None:
        index_project(self.root)
        (self.root / ".hil" / "index.json").write_text("{ not json", encoding="utf-8")
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        self.assertIn("unreadable", loaded["stale_reason"])

    def test_memory_writes_do_not_invalidate_index(self) -> None:
        index_project(self.root)
        record_memory(
            "conventions", "Naming", "Use snake_case for python symbols.", self.root
        )
        loaded = load_index(self.root)
        self.assertFalse(loaded["refreshed"])
        self.assertIsNone(loaded["stale_reason"])

    def test_context_reports_refresh_and_finds_new_file(self) -> None:
        index_project(self.root)
        self._write("billing.py", "def charge_card(order):\n    return order.total\n")
        result = get_project_context("charge_card billing", self.root, 600)
        self.assertTrue(result["index"]["refreshed"])
        self.assertEqual(result["index"]["version"], INDEX_VERSION)
        self.assertIn("refreshed automatically", result["notice"])
        self.assertTrue(any(item["path"] == "billing.py" for item in result["fragments"]))

    def test_context_can_skip_refresh_and_warns(self) -> None:
        index_project(self.root)
        self._write("billing.py", "def charge_card(order):\n    return order.total\n")
        result = get_project_context(
            "charge_card billing", self.root, 600, refresh_index=False
        )
        self.assertFalse(result["index"]["refreshed"])
        self.assertIsNotNone(result["index"]["stale_reason"])
        self.assertIn("WARNING: index is stale", result["notice"])
        self.assertFalse(any(item["path"] == "billing.py" for item in result["fragments"]))


if __name__ == "__main__":
    unittest.main()