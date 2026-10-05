"""Tests for ``.hilignore``: the project's own rule for what is not source.

The benchmark writes its evidence inside the tree, and the index reads that
tree, so without a project-level rule the benchmark changes its own input. The
rule has to apply to both discovery paths, or the index would depend on whether
ripgrep happens to be installed.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_intelligence import indexer
from harness_intelligence.indexer import (
    discover_files,
    ignore_patterns,
    index_project,
    is_ignored,
    staleness_reason,
)


def _discovered(root: Path, rg_files: list[Path] | None) -> list[str]:
    """Run discovery with one forced path, the way the verification harness does."""
    original = indexer._rg_files
    indexer._rg_files = lambda _root: rg_files
    try:
        return sorted(path.relative_to(root).as_posix() for path in discover_files(root))
    finally:
        indexer._rg_files = original


class IgnorePatternTests(unittest.TestCase):
    def test_a_directory_pattern_covers_everything_under_it(self) -> None:
        self.assertTrue(is_ignored("benchmarks/results/baseline.json", ["benchmarks/results/"]))
        self.assertTrue(is_ignored("benchmarks/results/ab.jsonl", ["benchmarks/results/"]))
        self.assertFalse(is_ignored("benchmarks/tasks.jsonl", ["benchmarks/results/"]))

    def test_a_name_pattern_matches_at_any_depth(self) -> None:
        self.assertTrue(is_ignored("benchmarks/results/baseline.json", ["baseline.json"]))
        self.assertTrue(is_ignored("baseline.json", ["baseline.json"]))

    def test_a_glob_pattern_matches_the_whole_path(self) -> None:
        self.assertTrue(is_ignored("benchmarks/results/report.json", ["benchmarks/*/*.json"]))
        self.assertFalse(is_ignored("benchmarks/report.json", ["benchmarks/*/*.json"]))

    def test_an_empty_rule_set_ignores_nothing(self) -> None:
        self.assertFalse(is_ignored("src/app.py", []))


class ProjectIgnoreFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (self.root / "benchmarks" / "results").mkdir(parents=True)
        (self.root / "benchmarks" / "results" / "baseline.json").write_text(
            json.dumps({"mean_recall_pct": 30.8}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_ignore(self, text: str) -> None:
        (self.root / ".hilignore").write_text(text, encoding="utf-8")

    def test_comments_and_blank_lines_are_not_patterns(self) -> None:
        self._write_ignore("# evidence\n\nbenchmarks/results/\n")
        self.assertEqual(ignore_patterns(self.root), ["benchmarks/results/"])

    def test_without_the_file_nothing_is_excluded(self) -> None:
        self.assertIn("benchmarks/results/baseline.json", _discovered(self.root, None))

    def test_the_walk_path_honours_the_rule(self) -> None:
        self._write_ignore("benchmarks/results/\n")
        self.assertEqual(_discovered(self.root, None), ["src/app.py"])

    def test_the_ripgrep_path_honours_the_same_rule(self) -> None:
        # ripgrep reports everything under the tree; the rule is applied in
        # Python precisely so both paths end up with the same file set.
        self._write_ignore("benchmarks/results/\n")
        everything = [
            self.root / "src" / "app.py",
            self.root / "benchmarks" / "results" / "baseline.json",
        ]
        self.assertEqual(_discovered(self.root, everything), ["src/app.py"])
        self.assertEqual(_discovered(self.root, everything), _discovered(self.root, None))


class IgnoredFileIndexTests(unittest.TestCase):
    """The rule must reach the index itself, not just the file walk."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (self.root / "benchmarks" / "results").mkdir(parents=True)
        self.evidence = self.root / "benchmarks" / "results" / "baseline.json"
        self.evidence.write_text(json.dumps({"mean_recall_pct": 30.8}), encoding="utf-8")
        (self.root / ".hilignore").write_text("# evidence\nbenchmarks/results/\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _payload(self) -> dict:
        return json.loads((self.root / ".hil" / "index.json").read_text(encoding="utf-8"))

    def test_the_ignored_file_never_enters_the_index(self) -> None:
        index_project(self.root)
        paths = {entry["path"] for entry in self._payload()["files"]}
        self.assertEqual(paths, {"src/app.py"})

    def test_rewriting_the_ignored_file_does_not_stale_the_index(self) -> None:
        # Evidence is regenerated by every measurement run; if that invalidated
        # the index, every run would rebuild what the previous run just built.
        index_project(self.root)
        payload = self._payload()
        self.evidence.write_text(json.dumps({"mean_recall_pct": 41.2}), encoding="utf-8")
        self.assertIsNone(staleness_reason(self.root, payload))

    def test_removing_the_rule_puts_the_file_back(self) -> None:
        index_project(self.root)
        (self.root / ".hilignore").write_text("", encoding="utf-8")
        index_project(self.root)
        paths = {entry["path"] for entry in self._payload()["files"]}
        self.assertIn("benchmarks/results/baseline.json", paths)
        self.assertEqual(len(paths), 2)


if __name__ == "__main__":
    unittest.main()
