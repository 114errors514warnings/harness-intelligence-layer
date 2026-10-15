from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_intelligence.indexer import index_project, load_index
from harness_intelligence.memory import record_memory, search_memory
from harness_intelligence.retrieval import get_project_context
from harness_intelligence.tokens import estimate_tokens


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "auth.py").write_text(
            "class TokenValidator:\n"
            "    def validate_token(self, token):\n"
            "        return token == 'valid'\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text("Authentication service\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_index_extracts_symbols(self) -> None:
        result = index_project(self.root)
        self.assertEqual(result["indexed_files"], 2)
        index = load_index(self.root)
        auth = next(item for item in index["files"] if item["path"] == "auth.py")
        names = {symbol["name"] for symbol in auth["symbols"]}
        self.assertIn("TokenValidator", names)
        self.assertIn("validate_token", names)

    def test_index_excludes_memory_store(self) -> None:
        record_memory("architecture", "Hidden fact", "Must not be indexed as code.", self.root)
        index_project(self.root)
        paths = {item["path"] for item in load_index(self.root)["files"]}
        self.assertFalse(any(path.startswith(".ai-memory/") for path in paths))

    def test_context_respects_budget_and_finds_code(self) -> None:
        index_project(self.root)
        result = get_project_context("fix validate_token authentication", self.root, 500)
        self.assertLessEqual(result["estimated_tokens"], 500)
        self.assertTrue(any(item["path"] == "auth.py" for item in result["fragments"]))

    def test_context_counts_memory_against_budget(self) -> None:
        index_project(self.root)
        record_memory("architecture", "Auth token", "Authentication token validation lives in auth.py.", self.root)
        result = get_project_context("auth token", self.root, 300)
        self.assertLessEqual(result["estimated_tokens"], 300)
        self.assertTrue(result["memories"])

    def test_memory_round_trip(self) -> None:
        saved = record_memory(
            "decisions", "Token validation", "Use constant-time token comparison.", self.root, ["auth"]
        )
        self.assertTrue(Path(saved["path"]).exists())
        found = search_memory("token auth", self.root)
        self.assertEqual(found[0]["id"], saved["id"])
        json.loads(Path(saved["path"]).read_text(encoding="utf-8"))

    def test_memory_records_the_owning_project(self) -> None:
        # The store lives inside the project it describes, so the owner is what
        # makes a misfiled fact checkable rather than a guess.
        saved = record_memory("conventions", "Ownership", "Facts belong to one project.", self.root)
        self.assertEqual(saved["project"], str(Path(self.root).resolve()))
        found = search_memory("ownership facts", self.root)
        self.assertEqual(found[0]["project"], saved["project"])

    def test_rebuild_reuses_unchanged_entries(self) -> None:
        first = index_project(self.root)
        self.assertEqual(first["reused_files"], 0)  # nothing to reuse yet
        again = index_project(self.root)
        self.assertEqual(again["reused_files"], 2)  # neither file changed
        (self.root / "auth.py").write_text(
            "class TokenValidator:\n"
            "    def validate_token(self, token):\n"
            "        return token == 'valid'\n\n\n"
            "def refresh_token(token):\n"
            "    return token\n",
            encoding="utf-8",
        )
        third = index_project(self.root)
        self.assertEqual(third["reused_files"], 1)  # only auth.py was re-read
        auth = next(
            item for item in load_index(self.root)["files"] if item["path"] == "auth.py"
        )
        self.assertIn("refresh_token", {symbol["name"] for symbol in auth["symbols"]})

    def test_selection_summary_accounts_for_the_budget(self) -> None:
        index_project(self.root)
        result = get_project_context("authentication token validate_token", self.root, 200)
        selection = result["selection"]
        self.assertEqual(selection["selected"], len(result["fragments"]))
        self.assertEqual(
            selection["selected"] + selection["evicted"], selection["candidates"]
        )
        self.assertLessEqual(len(selection["evicted_top"]), 5)
        self.assertLessEqual(selection["memory_selected"], 3)
        self.assertLessEqual(selection["memory_selected"] + selection["memory_evicted"], 3)

    def test_memory_dir_env_overrides_the_read_path(self) -> None:
        # The store is gitignored, so a benchmark pins it to get reproducible
        # recall. Only reads move; writes still land in the project's own store.
        import os

        from harness_intelligence import memory as memory_module

        record_memory("conventions", "Local fact", "visible in the project store", self.root)
        empty = Path(self.temp.name) / "empty-memory"
        empty.mkdir()
        previous = os.environ.get(memory_module.MEMORY_DIR_ENV)
        os.environ[memory_module.MEMORY_DIR_ENV] = str(empty)
        try:
            self.assertEqual(search_memory("local fact", self.root), [])
            self.assertEqual(memory_module.memory_dir(self.root), empty.resolve())
        finally:
            if previous is None:
                os.environ.pop(memory_module.MEMORY_DIR_ENV, None)
            else:
                os.environ[memory_module.MEMORY_DIR_ENV] = previous
        self.assertTrue(search_memory("local fact", self.root))

    def test_confidence_is_high_when_a_named_symbol_matches(self) -> None:
        index_project(self.root)
        result = get_project_context("validate_token", self.root, 500)
        self.assertEqual(result["confidence"], "high")

    def test_confidence_is_low_without_a_named_symbol(self) -> None:
        index_project(self.root)
        result = get_project_context("Authentication service", self.root, 500)
        self.assertEqual(result["confidence"], "low")
        self.assertIn("Low-confidence package", result["notice"])

    def test_context_rejects_budget_below_minimum(self) -> None:
        index_project(self.root)
        with self.assertRaises(ValueError):
            get_project_context("auth", self.root, 199)

    def test_cjk_token_estimate_is_conservative(self) -> None:
        self.assertGreaterEqual(estimate_tokens("这是中文上下文"), 7)


if __name__ == "__main__":
    unittest.main()
