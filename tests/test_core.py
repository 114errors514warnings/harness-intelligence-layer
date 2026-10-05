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

    def test_context_rejects_budget_below_minimum(self) -> None:
        index_project(self.root)
        with self.assertRaises(ValueError):
            get_project_context("auth", self.root, 199)

    def test_cjk_token_estimate_is_conservative(self) -> None:
        self.assertGreaterEqual(estimate_tokens("这是中文上下文"), 7)


if __name__ == "__main__":
    unittest.main()
