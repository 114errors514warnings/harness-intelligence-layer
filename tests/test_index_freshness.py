from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from harness_intelligence.indexer import (
    INDEX_VERSION,
    extract_symbols,
    index_project,
    load_index,
    staleness_reason,
)
from harness_intelligence.memory import record_memory
from harness_intelligence.retrieval import get_project_context


class SymbolExtractionTests(unittest.TestCase):
    """Module constants are symbols a query can name outright."""

    def test_module_constants_are_extracted_as_symbols(self) -> None:
        # Without this, a query naming MAX_TERMS or DEFAULT_EXCLUDES had no symbol
        # to anchor on, so the emitted window was chosen by hit density and often
        # missed the constant's own line.
        symbols = {symbol.name for symbol in extract_symbols("MAX_TERMS = 200\nDEFAULT_EXCLUDES = {\n")}
        self.assertIn("MAX_TERMS", symbols)
        self.assertIn("DEFAULT_EXCLUDES", symbols)

    def test_lowercase_assignments_and_short_names_are_not_constants(self) -> None:
        symbols = {symbol.name for symbol in extract_symbols("    memory_cap = 1\nID = 2\n")}
        self.assertNotIn("memory_cap", symbols)
        self.assertNotIn("ID", symbols)


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

    def test_index_from_another_root_is_stale(self) -> None:
        # A backup/restore can drop an index built in a different tree into .hil/.
        # Its relative paths may still resolve, so the root has to be checked.
        index_project(self.root)
        path = self.root / ".hil" / "index.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["root"] = str(self.root / "elsewhere")
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_index(self.root)
        self.assertTrue(loaded["refreshed"])
        self.assertIn("another root", loaded["stale_reason"])

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


class RipgrepDiscoveryTests(unittest.TestCase):
    """ripgrep must not be able to hang the server on an inherited stdin.

    The MCP server's stdin is the client's JSON-RPC pipe and never reaches EOF
    while the session lives. ripgrep reads stdin when it is not a TTY and no path
    is given, so inheriting that pipe made ``index_project`` block forever and
    every later tool call time out behind it.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "auth.py").write_text("x = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_discovery_does_not_block_on_an_open_stdin(self) -> None:
        import subprocess
        import sys
        import textwrap

        # A child whose stdin is an open pipe, exactly like the stdio server. It
        # calls the real discovery path; if stdin were inherited by ripgrep this
        # process would hang instead of printing DONE.
        program = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})
            from pathlib import Path
            from harness_intelligence.indexer import discover_files
            files = list(discover_files(Path({str(self.root)!r})))
            print("DONE", len(files))
            """
        )
        read_fd, write_fd = os.pipe()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", program],
                stdin=read_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                out, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("discover_files blocked when stdin was an open pipe")
        finally:
            os.close(read_fd)
            os.close(write_fd)
        self.assertIn("DONE 1", out)


if __name__ == "__main__":
    unittest.main()