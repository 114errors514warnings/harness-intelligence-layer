from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness_intelligence.indexer import index_project
from harness_intelligence.retrieval import (
    MAX_WINDOWS,
    MAX_WINDOW_TOKENS,
    PATH_HIT_WEIGHT,
    _entry_candidates,
    _windows,
    get_project_context,
)
from harness_intelligence.terms import content_pattern


def candidates(
    text: str, terms: list[str], symbols: list[dict] | None = None, path: str = "src/impl.py"
):
    """Score one file the way retrieval does, without touching a real tree."""
    return _entry_candidates(path, symbols or [], text, terms, content_pattern(terms))


def window_hits(fragment) -> int:
    return next(
        (
            int(reason.split(":", 1)[1])
            for reason in fragment.reasons
            if reason.startswith("text_hits:")
        ),
        0,
    )


def prose(lines: int) -> str:
    return "\n".join(
        f"line {number} 索引与陈旧检测的说明文本用于压测窗口上限" for number in range(1, lines + 1)
    )


class FragmentScoringTests(unittest.TestCase):
    """The fragment, not the file, is what gets scored and ranked."""

    def test_dense_prose_is_split_into_bounded_windows(self) -> None:
        # Before the cap, a dense run of hits merged into one multi-hundred-token
        # window. Its score saturated while its cost did not, so it lost every
        # budget race to a small code window.
        found = candidates(prose(120), ["索引"])
        self.assertEqual(len(found), MAX_WINDOWS)
        for fragment in found:
            self.assertLessEqual(fragment.token_cost - 24, MAX_WINDOW_TOKENS)

    def test_windows_of_one_file_never_overlap(self) -> None:
        # A duplicated line is a wasted line in a fixed token budget.
        found = candidates(prose(120), ["索引"])
        spans = sorted((fragment.start_line, fragment.end_line) for fragment in found)
        for earlier, later in zip(spans, spans[1:]):
            self.assertLess(earlier[1], later[0])

    def test_the_densest_window_of_the_file_is_emitted(self) -> None:
        text = prose(120)
        lines = text.splitlines()
        hits = [number for number, line in enumerate(lines, 1) if "索引" in line.lower()]
        best = max(
            sum(1 for line in hits if start <= line <= end) for start, end in _windows(lines, hits)
        )
        found = candidates(text, ["索引"])
        self.assertEqual(max(window_hits(fragment) for fragment in found), best)

    def test_a_named_identifier_outweighs_a_word_inside_a_longer_name(self) -> None:
        symbols = [{"name": "discover_files", "kind": "function", "line": 1}]
        text = "def discover_files(root):\n    return root\n"
        exact = candidates(text, ["discover_files"], symbols)
        word = candidates(text, ["discover", "files"], symbols)
        self.assertGreater(exact[0].score, word[0].score)
        self.assertTrue(any(reason.startswith("symbols:") for reason in exact[0].reasons))
        self.assertTrue(any(reason.startswith("symbol_words:") for reason in word[0].reasons))

    def test_a_word_inside_another_word_is_not_a_symbol_hit(self) -> None:
        # "json" used to hit "_write_jsonl" by substring.
        symbols = [{"name": "_write_jsonl", "kind": "function", "line": 1}]
        text = "def _write_jsonl(path):\n    pass\n"
        loose = candidates(text, ["json"], symbols, path="benchmarks/measure.py")
        tight = candidates(text, ["jsonl"], symbols, path="benchmarks/measure.py")
        self.assertFalse(any(reason.startswith("symbol") for reason in loose[0].reasons))
        self.assertTrue(any(reason.startswith("symbol_words:") for reason in tight[0].reasons))

    def test_a_path_hit_is_a_candidate_without_any_content_hit(self) -> None:
        found = candidates("nothing matches here\n", ["indexer"], path="src/indexer.py")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].score, PATH_HIT_WEIGHT)
        self.assertIn("path:indexer", found[0].reasons)

    def test_a_generic_short_term_does_not_match_a_path_segment(self) -> None:
        # "git" used to hit ".github/" and "ai" used to hit "openai.yaml": a flat
        # path bonus on files that have nothing to do with the question, which
        # crowded the file that actually answers it out of the budget.
        self.assertEqual(candidates("unrelated body\n", ["git"], path=".github/workflows/ci.yml"), [])
        self.assertEqual(candidates("unrelated body\n", ["ai"], path="skills/agents/openai.yaml"), [])

    def test_a_long_enough_term_still_matches_a_path_segment_by_prefix(self) -> None:
        # The length gate must not cost a file the caller actually named:
        # "token" still reaches tokens.py, "index" still reaches indexer.py.
        for term, path in (("token", "src/tokens.py"), ("index", "src/indexer.py")):
            found = candidates("unrelated body\n", [term], path=path)
            self.assertEqual(len(found), 1, f"{term} -> {path}")
            self.assertEqual(found[0].score, PATH_HIT_WEIGHT)

    def test_a_file_without_any_hit_yields_nothing(self) -> None:
        self.assertEqual(candidates("nothing matches here\n", ["indexer"]), [])

    def test_a_file_known_only_by_a_symbol_yields_its_definition_window(self) -> None:
        symbols = [{"name": "staleness_reason", "kind": "function", "line": 3}]
        text = "one\ntwo\ndef staleness_reason(root, payload):\n    return None\n"
        found = candidates(text, ["staleness_reason"], symbols)
        self.assertTrue(found)
        self.assertTrue(
            any(fragment.start_line <= 3 <= fragment.end_line for fragment in found)
        )

    def test_the_window_holding_a_named_symbol_beats_a_denser_window(self) -> None:
        # The Phase 3 pilot lost 5 tasks because the one emitted window was the
        # densest one, not the one holding the identifier the query named: the
        # model got the file but not the line that answers the question.
        lines = [f"line {n} 索引 陈旧 检测 说明文字 索引 陈旧 检测" for n in range(1, 40)]
        lines[29] = "DEFAULT_EXCLUDES = {'.git', '.hil'}"
        symbols = [{"name": "DEFAULT_EXCLUDES", "kind": "constant", "line": 30}]
        found = candidates("\n".join(lines), ["索引", "default_excludes"], symbols)
        self.assertTrue(found)
        self.assertTrue(
            any(fragment.start_line <= 30 <= fragment.end_line for fragment in found)
        )

    def test_terms_are_matched_case_insensitively(self) -> None:
        found = candidates("Load_Index()\n", ["load_index"])
        self.assertEqual(window_hits(found[0]), 1)


class ChineseQueryRecallTests(unittest.TestCase):
    """A Chinese-only prompt has to be able to recall Chinese text."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "notes.md").write_text(
            "索引陈旧检测依赖哪些元数据\n"
            "指纹由相对路径、文件大小与修改时间组成\n"
            "重建索引之后文档仍然检索不到时先检查文件集\n",
            encoding="utf-8",
        )
        (self.root / "src").mkdir()
        (self.root / "src" / "impl.py").write_text(
            "def load_index(root):\n    return root\n", encoding="utf-8"
        )
        index_project(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_chinese_only_prompt_recalls_the_chinese_document(self) -> None:
        # The defect this guards: the run "索引陈旧检测依赖哪些元数据" was one term
        # and matched nothing, so a Chinese-only task recalled nothing at all.
        result = get_project_context("索引陈旧检测依赖哪些元数据？", self.root, 600)
        self.assertTrue(
            any(fragment["path"] == "docs/notes.md" for fragment in result["fragments"])
        )

    def test_the_package_stays_inside_its_budget_and_has_no_duplicates(self) -> None:
        result = get_project_context("索引陈旧检测依赖哪些元数据？", self.root, 600)
        self.assertLessEqual(result["estimated_tokens"], 600)
        seen: list[tuple[str, int, int]] = []
        for fragment in result["fragments"]:
            start, end = fragment["lines"]
            for path, other_start, other_end in seen:
                if path == fragment["path"]:
                    self.assertTrue(end < other_start or other_end < start)
            seen.append((fragment["path"], start, end))

    def test_terms_are_reported_as_ngrams(self) -> None:
        result = get_project_context("索引陈旧", self.root, 600)
        self.assertIn("索引", result["terms"])
        self.assertIn("陈旧", result["terms"])
        self.assertNotIn("索引陈旧", result["terms"])


if __name__ == "__main__":
    unittest.main()

