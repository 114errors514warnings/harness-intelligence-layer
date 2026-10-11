#!/usr/bin/env python3
"""Cross-phase verification that unit tests cannot provide.

Unit tests prove code contracts. This script proves the things they cannot:

* a real tree still produces a well-formed, budget-respecting package;
* the two file-discovery paths (ripgrep and the os.walk fallback) agree;
* retrieval numbers have not regressed against a recorded baseline;
* the index mirrors the source set instead of drifting silently;
* the A/B gate still refuses incomplete or under-threshold data.

Every check prints exactly one of:

* ``PASS`` - the invariant holds on this tree, right now;
* ``FAIL`` - the invariant is broken (exit code 1);
* ``SKIP`` - the check could not run here (missing ripgrep, missing baseline,
  ``--limit``). A skip is never counted as a pass, so a green run means
  "verified here", not "assumed fine".

Usage::

    python benchmarks/verify.py
    python benchmarks/verify.py --variant hinted --limit 6
    python benchmarks/verify.py --write-baseline
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = Path(__file__).resolve().parent
for _extra in (PROJECT_ROOT / "src", BENCHMARKS_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import measure  # noqa: E402  (benchmarks/measure.py)
from harness_intelligence import __version__ as HIL_VERSION  # noqa: E402
from harness_intelligence import indexer, memory  # noqa: E402
from harness_intelligence.indexer import (  # noqa: E402
    INDEX_VERSION,
    discover_files,
    index_project,
    load_index,
    read_text,
)
from harness_intelligence.retrieval import get_project_context  # noqa: E402

DEFAULT_TASKS = BENCHMARKS_DIR / "tasks.jsonl"
DEFAULT_HINTS = BENCHMARKS_DIR / "hints.jsonl"
DEFAULT_BASELINE = BENCHMARKS_DIR / "results" / "baseline.json"

#: Per-run measurement reports. They are written under ``.hil/results/``, which
#: both discovery paths already exclude; one landing in the indexed tree would
#: change the corpus that the next measurement run reads.
GENERATED_REPORT_GLOB = "hil_*.json"

#: One task flipping from recalled to missed moves the 26-task mean by ~3.8pp, so
#: the gate tolerates two tasks of legitimate drift before it fires (~8pp).
RECALL_TOLERANCE_PP = 8.0
TARGET_MET_TOLERANCE = 2
PACKAGE_TOKEN_TOLERANCE_PCT = 5.0
PACKAGE_TOKEN_TOLERANCE_FLOOR = 50

MIN_AB_RECORDS = measure.MIN_AB_TASKS


class Report:
    """Collects PASS/FAIL/SKIP lines and decides the exit code."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.skips: list[str] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        label = "PASS" if passed else "FAIL"
        suffix = f" - {detail}" if detail else ""
        print(f"  [{label}] {name}{suffix}")
        if not passed:
            self.failures.append(name)

    def skip(self, name: str, reason: str) -> None:
        print(f"  [SKIP] {name} - {reason}")
        self.skips.append(name)

    def info(self, text: str) -> None:
        print(f"         {text}")


def check_task_set(report: Report, tasks_path: Path, hints_path: Path) -> list[dict]:
    """The benchmark must be internally consistent before anything else is measured.

    ``apply_hints`` already refuses a task with no hint; the reverse direction
    (a hint for a task that no longer exists) would silently shrink the corpus,
    so it is asserted here.
    """
    print("task set")
    try:
        tasks = measure.load_tasks(tasks_path)
        hints = measure.load_hints(hints_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report.record("task set loads", False, str(exc))
        return []
    report.record("task set loads", True, f"{len(tasks)} tasks, {len(hints)} hints")
    task_ids = {task["id"] for task in tasks}
    hint_ids = set(hints)
    detail = ""
    if task_ids != hint_ids:
        detail = (
            f"only in tasks: {sorted(task_ids - hint_ids)}; "
            f"only in hints: {sorted(hint_ids - task_ids)}"
        )
    report.record("hints cover the task set exactly", task_ids == hint_ids, detail)
    categories = sorted({task["category"] for task in tasks})
    report.record(
        "every category is represented",
        categories == sorted(measure.CATEGORIES),
        ", ".join(categories),
    )
    unproven = [task["id"] for task in tasks if not task.get("provenance")]
    report.record("every task cites provenance", not unproven, ", ".join(unproven))
    return tasks


@contextmanager
def _rg_files_patched(value):
    """Force ``discover_files`` down one discovery path.

    Patching the module attribute is what makes the comparison real: both sets go
    through the shipped ``discover_files`` code, including its suffix and symlink
    filtering, instead of through a reimplementation written for this check.
    """
    original = indexer._rg_files  # the two discovery paths are the thing under test
    indexer._rg_files = lambda _root: value
    try:
        yield
    finally:
        indexer._rg_files = original


def _discovered(root: Path, rg_files) -> set[Path]:
    with _rg_files_patched(rg_files):
        return {path.resolve() for path in discover_files(root)}


def check_discovery_paths(report: Report, root: Path) -> None:
    """The index must not depend on whether ripgrep happens to be installed."""
    print("file discovery")
    rg_files = indexer._rg_files(root)
    if rg_files is None:
        report.skip(
            "ripgrep and os.walk agree",
            "ripgrep is not installed here, so only the os.walk fallback ran",
        )
        return
    via_rg = _discovered(root, rg_files)
    via_walk = _discovered(root, None)
    report.record(
        "ripgrep and os.walk agree",
        via_rg == via_walk,
        f"{len(via_rg)} via rg, {len(via_walk)} via os.walk",
    )
    if via_rg != via_walk:
        report.info(f"only via rg: {sorted(str(path) for path in via_rg - via_walk)[:5]}")
        report.info(f"only via os.walk: {sorted(str(path) for path in via_walk - via_rg)[:5]}")


def check_package_invariants(report: Report, tasks: list[dict], root: Path, budget: int) -> None:
    """Walk the payload a harness actually receives, not just a summary of it.

    ``run_hil_arm`` only keeps counts, so this check reads the raw fragments and
    re-derives line numbers from the files on disk. It is the strongest probe in
    the script: a fragment whose ``lines`` range does not match its own content
    would corrupt the evidence a harness pastes back into a prompt.
    """
    print(f"package invariants (budget {budget})")
    budget_problems: list[str] = []
    memory_problems: list[str] = []
    line_problems: list[str] = []
    fragments_checked = 0
    for task in tasks:
        result = get_project_context(task["prompt"], root, budget)
        task_id = task["id"]
        total = result["estimated_tokens"]
        memory_tokens = sum(item["estimated_tokens"] for item in result["memories"])
        fragment_tokens = sum(item["estimated_tokens"] for item in result["fragments"])
        if total > budget:
            budget_problems.append(f"{task_id}: {total} > budget {budget}")
        if memory_tokens + fragment_tokens != total:
            budget_problems.append(
                f"{task_id}: parts {memory_tokens}+{fragment_tokens} != total {total}"
            )
        if memory_tokens > budget // 4:
            memory_problems.append(f"{task_id}: {memory_tokens} > {budget // 4}")
        for fragment in result["fragments"]:
            fragments_checked += 1
            text = read_text(root / fragment["path"])
            if text is None:
                line_problems.append(f"{task_id}: unreadable {fragment['path']}")
                continue
            lines = text.splitlines()
            start, end = fragment["lines"]
            if not 1 <= start <= end <= len(lines):
                line_problems.append(
                    f"{task_id}: {fragment['path']} lines {start}-{end} outside 1-{len(lines)}"
                )
                continue
            body = fragment["content"].splitlines()
            if len(body) != end - start + 1:
                line_problems.append(
                    f"{task_id}: {fragment['path']} content {len(body)} lines, "
                    f"range claims {end - start + 1}"
                )
            elif not body[0].startswith(f"{start}: "):
                line_problems.append(
                    f"{task_id}: {fragment['path']} content does not start at line {start}"
                )
    report.record(
        "packages fit the budget and account for every token",
        not budget_problems,
        "; ".join(budget_problems[:3]),
    )
    report.record(
        "memory slice stays inside budget/4",
        not memory_problems,
        "; ".join(memory_problems[:3]),
    )
    report.record(
        "every fragment maps to real file lines",
        not line_problems,
        "; ".join(line_problems[:3]),
    )
    report.info(f"fragments inspected: {fragments_checked}")


def run_arms(
    tasks: list[dict], root: Path, budget: int, variants: list[str], hints_path: Path
) -> dict[str, dict]:
    """Run the retrieval harness once per variant, after a warm-up pass.

    The first pass in a process pays for the index rebuild and for cold file
    caching, which measured as a 2.6x latency swing (241 ms to 93 ms p50). Using
    that pass as the reported number would be a false signal, so it is discarded.
    """
    print("retrieval arms")
    index_project(root)
    indexed = {entry["path"] for entry in load_index(root)["files"]}
    measure.run_hil_arm(tasks[:3], root, budget, indexed)
    arms: dict[str, dict] = {}
    for variant in variants:
        arm_tasks = tasks
        if variant == "hinted":
            arm_tasks = measure.apply_hints(tasks, measure.load_hints(hints_path))
        rows = measure.run_hil_arm(arm_tasks, root, budget, indexed)
        summary = measure.summarize(rows, budget)
        arms[variant] = {"rows": rows, "summary": summary}
        print(
            f"  {variant}: mean recall {summary['mean_recall_pct']}% | "
            f"target met {summary['tasks_meeting_target_recall']}/{summary['tasks']} | "
            f"median {summary['median_package_tokens']} tok | "
            f"duplicates {summary['duplicate_pairs']}"
        )
    return arms


def report_categories(report: Report, arms: dict[str, dict]) -> None:
    """Per-category recall, reported but deliberately not gated.

    A category holds four to eight tasks, so one task flipping recall moves its
    mean by up to 25pp. Gating on that would produce a flaky pipeline that
    eventually gets ignored; the aggregate gate in ``check_baseline`` is what
    fails the build, and this table is what explains a failure.
    """
    print("per-category recall (informational, not gated)")
    for variant, arm in arms.items():
        by_category: dict[str, list[float | None]] = {}
        for row in arm["rows"]:
            by_category.setdefault(row["category"], []).append(row["recall"])
        for category in sorted(by_category):
            recalls = by_category[category]
            values = [value for value in recalls if value is not None]
            mean = round(statistics.fmean(values) * 100, 1) if values else 0.0
            met = sum(1 for value in values if value * 100 >= measure.TARGET_RECALL_PCT)
            report.info(
                f"{variant:<7}{category:<17}{mean:>6}%  target met {met}/{len(recalls)}"
            )


def check_baseline(
    report: Report,
    arms: dict[str, dict],
    baseline_path: Path,
    tolerance: float,
    writing: bool,
    limited: bool,
) -> None:
    """Compare this run against the recorded baseline, per variant.

    Four gates, all deliberately loose enough to survive legitimate drift and
    tight enough to catch a retrieval change that breaks the arm (the raw arm is
    the sensitive one: it is the worst case a harness could hit).
    """
    print("regression gate")
    if writing:
        report.skip("baseline regression", "the baseline is being rewritten by this run")
        return
    if limited:
        report.skip("baseline regression", "--limit was used, so this run is not comparable")
        return
    if not baseline_path.exists():
        report.skip(
            "baseline regression",
            f"{baseline_path.name} missing; run --write-baseline once and commit the file",
        )
        return
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.record("baseline is readable", False, str(exc))
        return
    report.record(
        "baseline is readable",
        True,
        f"recorded {baseline.get('generated_at', '?')} on {baseline.get('tasks', '?')} tasks",
    )
    for variant, arm in arms.items():
        recorded = baseline.get("variants", {}).get(variant)
        if not recorded:
            report.skip(f"baseline regression ({variant})", "no baseline for this variant")
            continue
        summary = arm["summary"]
        recall_delta = round(summary["mean_recall_pct"] - recorded["mean_recall_pct"], 1)
        report.record(
            f"mean recall holds ({variant})",
            recall_delta >= -tolerance,
            f"{recorded['mean_recall_pct']}% -> {summary['mean_recall_pct']}% "
            f"({recall_delta:+.1f}pp, tolerance -{tolerance}pp)",
        )
        met_delta = summary["tasks_meeting_target_recall"] - recorded["tasks_meeting_target_recall"]
        report.record(
            f"tasks meeting target hold ({variant})",
            met_delta >= -TARGET_MET_TOLERANCE,
            f"{recorded['tasks_meeting_target_recall']} -> "
            f"{summary['tasks_meeting_target_recall']} of {summary['tasks']}",
        )
        duplicate_delta = summary["duplicate_pairs"] - recorded["duplicate_pairs"]
        report.record(
            f"no new duplicate fragments ({variant})",
            duplicate_delta <= 0,
            f"{recorded['duplicate_pairs']} -> {summary['duplicate_pairs']}",
        )
        allowed = recorded["median_package_tokens"] * (1 + PACKAGE_TOKEN_TOLERANCE_PCT / 100)
        allowed += PACKAGE_TOKEN_TOLERANCE_FLOOR
        report.record(
            f"package size stays lean ({variant})",
            summary["median_package_tokens"] <= allowed,
            f"{recorded['median_package_tokens']} -> {summary['median_package_tokens']} tok "
            f"(allowed <= {allowed:.0f})",
        )


def report_latency(report: Report, arms: dict[str, dict]) -> None:
    """Latency is reported after warm-up and never gated.

    The Phase 2 exit criterion is p95 < 1s, but a single-machine number swings by
    more than 2x between cold and warm runs, so asserting on it in CI would
    produce noise instead of information.
    """
    print("latency (informational, not gated)")
    for variant, arm in arms.items():
        summary = arm["summary"]
        report.info(
            f"{variant}: p50 {summary['p50_latency_ms']} ms | "
            f"p95 {summary['p95_latency_ms']} ms | max {summary['max_latency_ms']} ms"
        )
    report.info("warmed run; Phase 2 exit target is p95 < 1000 ms")


def _relative_to_root(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def check_index_covers(report: Report, root: Path, baseline_path: Path) -> None:
    """The index must mirror the source set exactly, and hold no generated report.

    Measured fact this guards: production packages walk the tree with ``os.walk``
    when ripgrep is absent, and the benchmark writes reports inside that tree. A
    per-run report left behind would enter the index, change its fingerprint on
    every measurement and compete with source fragments for the token budget.
    """
    print("index coverage")
    index_project(root)
    indexed = {entry["path"] for entry in load_index(root)["files"]}
    expected = set()
    oversize_or_unreadable = 0
    for path in discover_files(root):
        relative = path.relative_to(root).as_posix()
        if read_text(path) is None:
            oversize_or_unreadable += 1
            continue
        expected.add(relative)
    extra = sorted(indexed - expected)
    missing = sorted(expected - indexed)
    report.record(
        "index mirrors the source set",
        not extra and not missing,
        f"{len(indexed)} indexed, {len(expected)} expected",
    )
    if extra:
        report.info(f"indexed but not expected: {extra[:5]}")
    if missing:
        report.info(f"expected but not indexed: {missing[:5]}")
    if oversize_or_unreadable:
        report.info(f"skipped as oversize or unreadable: {oversize_or_unreadable}")
    reports = sorted(path for path in indexed if Path(path).match(GENERATED_REPORT_GLOB))
    report.record(
        "no per-run measurement report is indexed",
        not reports,
        ", ".join(reports[:3]) if reports else f"checked {len(indexed)} paths",
    )
    relative_baseline = _relative_to_root(baseline_path, root)
    if relative_baseline is None:
        report.skip(
            "the regression baseline is not indexed", "the baseline lives outside the project"
        )
        return
    report.record(
        "the regression baseline is not indexed",
        relative_baseline not in indexed,
        relative_baseline,
    )


def _write_records(
    path: Path,
    tasks: list[dict],
    count: int,
    reduction: float,
    filled: bool,
    native_retries: int = 0,
    hil_retries: int = 0,
) -> None:
    """Write a synthetic A/B worksheet, so the gate can be tested without a model."""
    lines = []
    for task in tasks[:count]:
        native = 2000
        hil = int(round(native * (1 - reduction / 100)))
        lines.append(
            json.dumps(
                {
                    "id": task["id"],
                    "harness": "synthetic",
                    "prompt": task["prompt"],
                    "native": (
                        {
                            "input_tokens": native,
                            "success": True,
                            "retries": native_retries,
                            "evidence": "self-check",
                        }
                        if filled
                        else None
                    ),
                    "hil": (
                        {
                            "input_tokens": hil,
                            "success": True,
                            "retries": hil_retries,
                            "evidence": "self-check",
                        }
                        if filled
                        else None
                    ),
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_cross_harness_reuse(report: Report, workspace: Path) -> None:
    """A fact written through one harness must be readable through another.

    HIL's answer to the roadmap §5 reuse requirement is structural: facts live in
    the target project's ``.ai-memory/`` instead of a harness-private session
    store, so any harness pointed at that project sees them. This exercises both
    halves on a scratch project - the write names one harness as its source and
    the reads happen with no harness involved at all.
    """
    print("cross-harness memory reuse")
    root = workspace / "reuse-project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    index_project(root)
    written = memory.record_memory(
        "decisions",
        "Shared cache boundary",
        "The identity service owns the shared cache.",
        root,
        ["cache", "boundary"],
        source="cline",
    )
    found = memory.search_memory("shared cache boundary", root)
    context = get_project_context("shared cache boundary", root, 800)
    title = "Shared cache boundary"
    report.record(
        "a fact written through one harness is found by the memory search",
        any(item.get("title") == title for item in found),
        f"{len(found)} match(es)",
    )
    report.record(
        "the same fact is surfaced in the context package",
        any(item.get("title") == title for item in context["memories"]),
        f"{len(context['memories'])} memory slice(s)",
    )
    stored = Path(written["path"])
    report.record(
        "the fact is stored in the project, not a harness-private store",
        stored.is_file() and ".ai-memory" in stored.as_posix(),
        stored.as_posix(),
    )
    indexed = {entry["path"] for entry in load_index(root)["files"]}
    report.record(
        "the memory store is not re-indexed as source",
        not any(path.startswith(".ai-memory/") for path in indexed),
        f"{len(indexed)} indexed path(s)",
    )


def check_ab_gate(report: Report, tasks: list[dict], workspace: Path) -> None:
    """Prove the savings gate still refuses what it is supposed to refuse.

    Exit codes under test: 3 (data is unusable, so no number may be reported),
    1 (data is complete but misses a Phase 3 threshold), 0 (every gate passes).
    Each Phase 3 threshold needs at least one failing case, or the gate would be
    an assertion nobody ever saw work.
    """
    print("savings gate self-check (synthetic data, no model)")
    if len(tasks) < MIN_AB_RECORDS:
        report.skip("savings gate exit codes", f"needs {MIN_AB_RECORDS} tasks in the corpus")
        return
    recall_file = workspace / "recall.json"
    recall_file.write_text(
        json.dumps({"summary": {"mean_recall_pct": 95.0}}), encoding="utf-8"
    )
    reuse_ok = workspace / "reuse_ok.json"
    reuse_ok.write_text(
        json.dumps({"success": True, "pairs": [{"found": True, "evidence": "self-check"}]}),
        encoding="utf-8",
    )
    reuse_bad = workspace / "reuse_bad.json"
    reuse_bad.write_text(
        json.dumps({"success": False, "pairs": [{"found": False, "evidence": "self-check"}]}),
        encoding="utf-8",
    )
    empty = workspace / "empty.jsonl"
    below = workspace / "below.jsonl"
    retries = workspace / "retries.jsonl"
    passing = workspace / "passing.jsonl"
    _write_records(empty, tasks, MIN_AB_RECORDS, 0.0, filled=False)
    _write_records(below, tasks, MIN_AB_RECORDS, 15.0, filled=True)
    _write_records(retries, tasks, MIN_AB_RECORDS, 30.0, filled=True, hil_retries=3)
    _write_records(passing, tasks, MIN_AB_RECORDS, 30.0, filled=True)
    cases = (
        ("incomplete worksheet is refused (exit 3)", empty, [], 3),
        ("under-threshold reduction fails (exit 1)", below, ["--recall-file", str(recall_file)], 1),
        (
            "more retries in the HIL arm fails (exit 1)",
            retries,
            ["--recall-file", str(recall_file), "--reuse-file", str(reuse_ok)],
            1,
        ),
        (
            "a failed reuse gate fails (exit 1)",
            passing,
            ["--recall-file", str(recall_file), "--reuse-file", str(reuse_bad)],
            1,
        ),
        (
            "everything passing returns 0",
            passing,
            ["--recall-file", str(recall_file), "--reuse-file", str(reuse_ok)],
            0,
        ),
    )
    for label, worksheet, extra, expected in cases:
        argv = ["--compare", str(worksheet), *extra]
        with contextlib.redirect_stdout(io.StringIO()):
            code = measure.main(argv)
        report.record(label, code == expected, f"exit {code}, expected {expected}")


def write_baseline(path: Path, tasks: list[dict], arms: dict[str, dict], budget: int) -> None:
    """Record the summaries this run produced, as the reference for later runs.

    The file is meant to be committed: a regression gate without a recorded
    reference would silently skip, and a skip is not evidence.
    """
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hil_version": HIL_VERSION,
        "index_schema_version": INDEX_VERSION,
        "token_budget": budget,
        "tasks": len(tasks),
        "variants": {variant: arm["summary"] for variant, arm in arms.items()},
        "note": (
            "Regenerate with `python benchmarks/verify.py --write-baseline` after an "
            "intentional retrieval change, and review the diff before committing."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"baseline written: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify HIL phase invariants and gates")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="project to verify")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS), help="task corpus jsonl")
    parser.add_argument("--hints", default=str(DEFAULT_HINTS), help="hinted prompts jsonl")
    parser.add_argument("--budget", type=int, default=1500, help="token budget per task")
    parser.add_argument("--limit", type=int, default=0, help="run only N tasks (skips the gate)")
    parser.add_argument(
        "--variant",
        action="append",
        choices=("raw", "hinted"),
        default=[],
        help="retrieval arm to run; repeatable, defaults to both",
    )
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="baseline json")
    parser.add_argument(
        "--recall-tolerance",
        type=float,
        default=RECALL_TOLERANCE_PP,
        help="allowed mean recall drop in percentage points",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record this run as the new baseline instead of comparing against it",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    variants = args.variant or ["raw", "hinted"]
    print(f"HIL {HIL_VERSION} | index schema {INDEX_VERSION} | budget {args.budget}")
    print(f"root: {root}")
    print("")

    report = Report()
    tasks = check_task_set(report, Path(args.tasks), Path(args.hints))
    if not tasks:
        print("")
        print("VERIFY FAILED: no usable task set")
        return 1
    if args.limit:
        tasks = tasks[: args.limit]
        print(f"  (limited to {len(tasks)} tasks; the regression gate will skip)")
    arms = run_arms(tasks, root, args.budget, variants, Path(args.hints))

    print("")
    with tempfile.TemporaryDirectory(prefix="hil-verify-") as tmp:
        check_discovery_paths(report, root)
        check_package_invariants(report, tasks, root, args.budget)
        report_categories(report, arms)
        check_baseline(
            report,
            arms,
            Path(args.baseline),
            args.recall_tolerance,
            args.write_baseline,
            bool(args.limit),
        )
        report_latency(report, arms)
        check_index_covers(report, root, Path(args.baseline))
        check_cross_harness_reuse(report, Path(tmp))
        check_ab_gate(report, tasks, Path(tmp))

    if args.write_baseline:
        print("")
        write_baseline(Path(args.baseline), tasks, arms, args.budget)
        print("review the diff and commit it together with the change that moved the numbers")

    print("")
    if report.failures:
        print(f"VERIFY FAILED: {len(report.failures)} check(s) - {', '.join(report.failures)}")
        return 1
    if report.skips:
        print(
            f"VERIFY PASSED with {len(report.skips)} skipped check(s) "
            f"(skips are not evidence): {', '.join(report.skips)}"
        )
        return 0
    print("VERIFY PASSED: every check ran on this tree and held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
