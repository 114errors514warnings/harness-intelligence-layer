"""A Chinese-only question must emit a window that answers it (Phase 5 §7.2a).

The glossary bridge (Phase 5 §7.1) made English code files *reachable* from a
Chinese-only question, but the emitted window was still chosen by content density
that counted for nothing, so the tie-break could emit a blank filler line instead
of the definition the bridge points at. These tests pin the fixed behaviour: the
window is non-blank and holds a symbol the query actually matched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness_intelligence.indexer import index_project
from harness_intelligence.retrieval import get_project_context


class BridgeWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "store.py").write_text(
            "\n\n"
            "def record_memory(category):\n"
            "    return category\n"
            "\n"
            "\n"
            "def search_memory(query):\n"
            "    return query\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_chinese_only_query_emits_the_matched_symbol_window(self) -> None:
        index_project(self.root)
        result = get_project_context("记忆检索怎么打分", self.root, 400)
        contents = "\n".join(fragment["content"] for fragment in result["fragments"])
        # 检索 -> search, 记忆 -> memory, so the search_memory definition is the
        # window the bridge points at; the denser record_memory line must not win.
        self.assertIn("search_memory", contents)

    def test_no_fragment_is_only_blank_lines(self) -> None:
        index_project(self.root)
        result = get_project_context("记忆检索怎么打分", self.root, 400)
        self.assertTrue(result["fragments"])
        for fragment in result["fragments"]:
            body = [
                line.split(": ", 1)[-1]
                for line in fragment["content"].splitlines()
            ]
            self.assertTrue(any(text.strip() for text in body), fragment)

    def test_pure_chinese_query_warns_about_recall(self) -> None:
        index_project(self.root)
        result = get_project_context("记忆检索怎么打分", self.root, 400)
        self.assertIn("Chinese-only question", result["notice"])

    def test_identifier_bearing_query_has_no_chinese_only_warning(self) -> None:
        index_project(self.root)
        result = get_project_context("search_memory 记忆检索", self.root, 400)
        self.assertNotIn("Chinese-only question", result["notice"])


if __name__ == "__main__":
    unittest.main()
