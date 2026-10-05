"""Tests for the measurement gate itself.

The benchmark decides whether a token saving may be claimed, so its own gate
logic is product code: an unguarded guardrail is worse than no guardrail. These
tests pin the three exit codes (0 met, 1 below threshold, 3 unusable data), the
median-versus-mean semantics, and the corpus invariants of this repository.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

import measure  # noqa: E402  (benchmarks/measure.py adds src/ to sys.path)

from harness_intelligence.indexer import (  # noqa: E402
    DEFAULT_EXCLUDES,
    discover_files,
)

PROJECT_ROOT = BENCHMARKS_DIR.parent
TASKS_FILE = BENCHMARKS_DIR / "tasks.jsonl"
HINTS_FILE = BENCHMARKS_DIR / "hints.jsonl"


def _task(task_id: str, **overrides) -> dict:
    task = {
        "id": task_id,
        "category": "single-file",
        "prompt": f"prompt for {task_id}",
        "required_files": ["src/example.py"],
        "required_symbols": ["Example"],
    }
    task.update(overrides)
    return task


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def _record(task_id: str, native_tokens: int, hil_tokens: int, **overrides) -> dict:
    record = {
        "id": task_id,
        "harness": "test-harness",
        "prompt": f"prompt for {task_id}",
        "native": {"input_tokens": native_tokens, "success": True, "evidence": "test"},
        "hil": {"input_tokens": hil_tokens, "success": True, "evidence": "test"},
    }
    record.update(overrides)
    return record


class TaskCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_load_tasks_reads_a_well_formed_corpus(self) -> None:
        path = _write_jsonl(
            self.root / "tasks.jsonl",
            [_task("T-01"), _task("T-02", category="architecture")],
        )
        tasks = measure.load_tasks(path)
        self.assertEqual([task["id"] for task in tasks], ["T-01", "T-02"])

    def test_load_tasks_rejects_duplicate_ids(self) -> None:
        path = _write_jsonl(self.root / "tasks.jsonl", [_task("T-01"), _task("T-01")])
        with self.assertRaises(ValueError) as caught:
            measure.load_tasks(path)
        self.assertIn("duplicate id", str(caught.exception))

    def test_load_tasks_rejects_a_missing_field(self) -> None:
        broken = _task("T-01")
        del broken["required_symbols"]
        path = _write_jsonl(self.root / "tasks.jsonl", [broken])
        with self.assertRaises(ValueError) as caught:
            measure.load_tasks(path)
        self.assertIn("required_symbols", str(caught.exception))

    def test_load_tasks_rejects_an_unknown_category(self) -> None:
        # A category outside CATEGORIES would land in no summary bucket, so the
        # task would silently stop being reported anywhere.
        path = _write_jsonl(self.root / "tasks.jsonl", [_task("T-01", category="misc")])
        with self.assertRaises(ValueError) as caught:
            measure.load_tasks(path)
        self.assertIn("unknown category", str(caught.exception))

    def test_load_tasks_rejects_an_empty_file(self) -> None:
        path = self.root / "tasks.jsonl"
        path.write_text("\n\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            measure.load_tasks(path)

    def test_load_hints_requires_a_prompt(self) -> None:
        path = _write_jsonl(self.root / "hints.jsonl", [{"id": "T-01", "hinted_prompt": ""}])
        with self.assertRaises(ValueError):
            measure.load_hints(path)

    def test_apply_hints_rewrites_only_the_prompt(self) -> None:
        tasks = [_task("T-01")]
        hinted = measure.apply_hints(tasks, {"T-01": "where is Example used"})
        self.assertEqual(hinted[0]["prompt"], "where is Example used")
        self.assertEqual(hinted[0]["required_files"], tasks[0]["required_files"])
        self.assertEqual(tasks[0]["prompt"], "prompt for T-01")

    def test_apply_hints_refuses_a_task_without_a_hint(self) -> None:
        with self.assertRaises(ValueError) as caught:
            measure.apply_hints([_task("T-01"), _task("T-02")], {"T-01": "only one"})
        self.assertIn("T-02", str(caught.exception))


class RepositoryCorpusTests(unittest.TestCase):
    """The shipped corpus is the input to every claim, so it is asserted too."""

    def setUp(self) -> None:
        self.tasks = measure.load_tasks(TASKS_FILE)
        self.hints = measure.load_hints(HINTS_FILE)

    def test_corpus_is_large_enough_for_the_phase_0_requirement(self) -> None:
        self.assertGreaterEqual(len(self.tasks), measure.MIN_AB_TASKS)

    def test_every_category_carries_more_than_one_task(self) -> None:
        counts: dict[str, int] = {}
        for task in self.tasks:
            counts[task["category"]] = counts.get(task["category"], 0) + 1
        self.assertEqual(sorted(counts), sorted(measure.CATEGORIES))
        for category, count in counts.items():
            self.assertGreater(count, 1, f"{category} carries a single task")

    def test_required_paths_exist_in_this_repository(self) -> None:
        missing = [
            path
            for task in self.tasks
            for path in task["required_files"]
            if not (PROJECT_ROOT / path).is_file()
        ]
        self.assertEqual(missing, [])

    def test_required_symbols_appear_in_the_files_that_claim_them(self) -> None:
        absent = []
        for task in self.tasks:
            text = "\n".join(
                (PROJECT_ROOT / path).read_text(encoding="utf-8", errors="replace")
                for path in task["required_files"]
            )
            absent.extend(
                f"{task['id']}:{symbol}"
                for symbol in task["required_symbols"]
                if symbol not in text
            )
        self.assertEqual(absent, [])

    def test_hints_do_not_name_the_answer_files(self) -> None:
        # A hint that contains a repository path would measure the annotation
        # instead of the calling strategy, which is the point of the hinted arm.
        leaked = []
        for task in self.tasks:
            prompt = self.hints[task["id"]]
            for path in task["required_files"]:
                if path in prompt or Path(path).name in prompt:
                    leaked.append(f"{task['id']}:{path}")
        self.assertEqual(leaked, [])


class ArtifactLayoutTests(unittest.TestCase):
    """Guards the defect that justified this file.

    measure.py used to write its per-run report into ``benchmarks/results/``,
    which sits inside the indexed tree, so measuring the project changed the
    corpus that the next measurement read.
    """

    def test_per_run_reports_land_in_a_directory_the_index_ignores(self) -> None:
        self.assertEqual(measure.ARTIFACT_DIR.parent.name, ".hil")
        self.assertIn(".hil", DEFAULT_EXCLUDES)

    def test_no_discoverable_file_lives_in_the_report_directory(self) -> None:
        discovered = {path.resolve() for path in discover_files(PROJECT_ROOT)}
        inside = sorted(str(path) for path in discovered if measure.ARTIFACT_DIR in path.parents)
        self.assertEqual(inside, [])

    def test_the_regression_baseline_is_committed_but_not_indexed(self) -> None:
        # Indexing it would let the gate reference compete with source fragments
        # for the budget, i.e. the benchmark would move its own measurement.
        import verify

        baseline = verify.DEFAULT_BASELINE
        self.assertTrue(baseline.is_file(), f"{baseline} must be committed to gate regressions")
        discovered = {path.resolve() for path in discover_files(PROJECT_ROOT)}
        self.assertNotIn(baseline.resolve(), discovered)


def _row(task_id: str, recall: float | None, **overrides) -> dict:
    row = {
        "id": task_id,
        "category": "single-file",
        "prompt": f"prompt for {task_id}",
        "estimated_tokens": 1000,
        "latency_ms": 100.0,
        "fragments": 1,
        "file_recall": recall,
        "symbol_recall": recall,
        "recall": recall,
        "missing_files": [],
        "missing_symbols": [],
        "not_indexed": [],
        "duplicate_pairs": 0,
        "duplicate_tokens": 0,
        "returned_paths": [],
        "index_refreshed": False,
        "stale_reason": None,
    }
    row.update(overrides)
    return row


class DuplicateFragmentTests(unittest.TestCase):
    def _fragment(self, path: str, start: int, end: int, tokens: int = 100) -> dict:
        return {
            "path": path,
            "lines": [start, end],
            "content": f"{start}: body",
            "estimated_tokens": tokens,
        }

    def test_overlapping_fragments_from_one_file_are_counted(self) -> None:
        fragments = [self._fragment("a.py", 1, 20, 100), self._fragment("a.py", 10, 30, 50)]
        self.assertEqual(measure.duplicate_fragments(fragments), (1, 50))

    def test_touching_ranges_are_not_duplicates(self) -> None:
        fragments = [self._fragment("a.py", 1, 20), self._fragment("a.py", 21, 30)]
        self.assertEqual(measure.duplicate_fragments(fragments), (0, 0))

    def test_the_same_range_in_two_files_is_not_a_duplicate(self) -> None:
        fragments = [self._fragment("a.py", 1, 20), self._fragment("b.py", 1, 20)]
        self.assertEqual(measure.duplicate_fragments(fragments), (0, 0))


class SummaryTests(unittest.TestCase):
    def test_the_target_boundary_counts_as_met(self) -> None:
        rows = [_row("T-01", 0.9), _row("T-02", 0.5)]
        summary = measure.summarize(rows, 1500)
        self.assertEqual(summary["tasks_meeting_target_recall"], 1)
        self.assertEqual(summary["mean_recall_pct"], 70.0)

    def test_rows_without_criteria_do_not_distort_the_mean(self) -> None:
        rows = [_row("T-01", 1.0), _row("T-02", None)]
        summary = measure.summarize(rows, 1500)
        self.assertEqual(summary["mean_recall_pct"], 100.0)
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["tasks_with_recall_criteria"], 1)

    def test_misses_are_collected_for_follow_up(self) -> None:
        rows = [
            _row("T-01", 0.5, missing_files=["b.py"]),
            _row("T-02", 0.5, missing_files=["b.py"], missing_symbols=["run"]),
        ]
        summary = measure.summarize(rows, 1500)
        self.assertEqual(summary["files_never_recalled"], ["b.py"])
        self.assertEqual(summary["symbols_never_recalled"], ["run"])


class CompareGateTests(unittest.TestCase):
    """Exit codes: 0 every gate met, 1 below a threshold, 3 data unusable."""

    def setUp(self) -> None:
        self.ids = {f"T-{index:02d}" for index in range(1, measure.MIN_AB_TASKS + 1)}

    def _compare(self, records: list[dict], recall_pct: float | None) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = measure.compare(records, self.ids, recall_pct)
        return code, stdout.getvalue()

    def _worksheet(self, native_tokens: int, hil_tokens: int, **overrides) -> list[dict]:
        return [
            _record(task_id, native_tokens, hil_tokens, **overrides)
            for task_id in sorted(self.ids)
        ]

    def test_short_worksheet_is_refused(self) -> None:
        records = self._worksheet(1000, 700)[: measure.MIN_AB_TASKS - 1]
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 3)
        self.assertIn("refusing to report savings", output)

    def test_unknown_task_id_is_refused(self) -> None:
        records = self._worksheet(1000, 700)
        records[0] = {**records[0], "id": "T-99"}
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 3)
        self.assertIn("unknown task ids", output)

    def test_empty_arm_is_refused(self) -> None:
        records = self._worksheet(1000, 700, native=None)
        self.assertEqual(self._compare(records, 95.0)[0], 3)

    def test_untraceable_number_is_refused(self) -> None:
        records = self._worksheet(1000, 700)
        records[0]["hil"] = {**records[0]["hil"], "evidence": ""}
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 3)
        self.assertIn("evidence", output)

    def test_unusable_token_counts_are_refused(self) -> None:
        for bad in ("1200", 0, -5, True, None, 12.5):
            with self.subTest(tokens=bad):
                records = self._worksheet(1000, 700)
                records[0]["hil"] = {**records[0]["hil"], "input_tokens": bad}
                self.assertEqual(self._compare(records, 95.0)[0], 3)

    def test_boolean_success_flag_is_required(self) -> None:
        records = self._worksheet(1000, 700)
        records[0]["hil"] = {**records[0]["hil"], "success": "yes"}
        self.assertEqual(self._compare(records, 95.0)[0], 3)


    def test_reduction_below_the_phase_3_target_fails(self) -> None:
        code, output = self._compare(self._worksheet(1000, 850), 95.0)
        self.assertEqual(code, 1)
        self.assertIn("FAIL] median input token reduction", output)

    def test_missing_recall_number_fails(self) -> None:
        code, output = self._compare(self._worksheet(1000, 700), None)
        self.assertEqual(code, 1)
        self.assertIn("not supplied", output)

    def test_recall_below_the_gate_fails(self) -> None:
        code, output = self._compare(self._worksheet(1000, 700), 85.0)
        self.assertEqual(code, 1)
        self.assertIn("FAIL] context recall", output)

    def test_success_rate_drop_beyond_budget_fails(self) -> None:
        records = self._worksheet(1000, 700)
        for record in records[:2]:
            record["hil"] = {**record["hil"], "success": False}
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 1)
        self.assertIn("FAIL] success rate drop", output)

    def test_every_gate_met_passes(self) -> None:
        code, output = self._compare(self._worksheet(1000, 700), 95.0)
        self.assertEqual(code, 0)
        self.assertIn("PASS] context recall", output)

    def test_exact_thresholds_pass(self) -> None:
        code, _ = self._compare(self._worksheet(1000, 800), measure.TARGET_RECALL_PCT)
        self.assertEqual(code, 0)

    def test_the_reported_reduction_is_a_median(self) -> None:
        # 11 tasks at +30% and 9 tasks at -50% average out negative while the
        # median still clears the bar, so this pins the statistic that decides.
        ids = sorted(self.ids)
        records = [_record(task_id, 1000, 700) for task_id in ids[:11]]
        records += [_record(task_id, 1000, 1500) for task_id in ids[11:]]
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 0)
        self.assertIn("median input token reduction: 30.0%", output)

    def test_reduction_is_computed_per_record(self) -> None:
        records = self._worksheet(1000, 700)
        records[0]["native"] = {**records[0]["native"], "input_tokens": 2000}
        records[0]["hil"] = {**records[0]["hil"], "input_tokens": 1400}
        code, output = self._compare(records, 95.0)
        self.assertEqual(code, 0)
        self.assertIn("A/B records: 20 task runs", output)


if __name__ == "__main__":
    unittest.main()
