#!/usr/bin/env python3
"""Phase 0 measurement harness.

Two independent things live here and they must not be confused:

* default ``--run`` measures the HIL arm mechanically: context recall against the
  annotated task set, token cost of the package, retrieval latency and duplicated
  fragments. No model is involved, so these numbers are reproducible anywhere.
* ``--compare`` validates a hand-filled A/B worksheet whose token numbers come
  from harness session usage. While that worksheet is incomplete the script
  refuses to report any reduction percentage.

Usage::

    python benchmarks/measure.py
    python benchmarks/measure.py --budget 2000 --label openclaw
    python benchmarks/measure.py --worksheet benchmarks/results/ab_worksheet.jsonl
    python benchmarks/measure.py --variant hinted
    python benchmarks/measure.py --compare benchmarks/results/ab.jsonl

Per-run reports default to ``.hil/results/``. That directory is already excluded
by both discovery paths, so measuring the project can never change the index that
the next measurement reads.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from harness_intelligence import __version__ as HIL_VERSION  # noqa: E402
from harness_intelligence.indexer import (  # noqa: E402
    INDEX_VERSION,
    index_project,
    load_index,
)
from harness_intelligence.retrieval import get_project_context  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_TASKS = HERE / "tasks.jsonl"
DEFAULT_HINTS = HERE / "hints.jsonl"
ARTIFACT_DIR = PROJECT_ROOT / ".hil" / "results"  # per-run reports, never indexed
CATEGORIES = {"single-file", "cross-module", "bug-localization", "architecture"}
REQUIRED_FIELDS = ("id", "category", "prompt", "required_files", "required_symbols")

MIN_AB_TASKS = 20            # roadmap Phase 0: 20-30 real tasks
TARGET_REDUCTION_PCT = 20.0  # roadmap Phase 3: median input token reduction
TARGET_RECALL_PCT = 90.0     # roadmap Phase 2 exit / Phase 3 gate
MAX_SUCCESS_DROP_PP = 2.0    # roadmap Phase 3: success rate drop budget


def load_tasks(path: Path) -> list[dict]:
    tasks: list[dict] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        task = json.loads(line)
        missing = [field for field in REQUIRED_FIELDS if field not in task]
        if missing:
            raise ValueError(f"{path}:{number} missing fields: {', '.join(missing)}")
        if task["category"] not in CATEGORIES:
            raise ValueError(f"{path}:{number} unknown category {task['category']!r}")
        if task["id"] in seen:
            raise ValueError(f"{path}:{number} duplicate id {task['id']!r}")
        seen.add(task["id"])
        tasks.append(task)
    if not tasks:
        raise ValueError(f"{path}: no tasks found")
    return tasks


def load_hints(path: Path) -> dict[str, str]:
    hints: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if not record.get("id") or not record.get("hinted_prompt"):
            raise ValueError(f"{path}:{number} needs id and hinted_prompt")
        hints[record["id"]] = record["hinted_prompt"]
    if not hints:
        raise ValueError(f"{path}: no hints found")
    return hints


def apply_hints(tasks: list[dict], hints: dict[str, str]) -> list[dict]:
    """Re-express every task the way a harness that names identifiers would ask.

    A hint must not contain repository file paths: naming the answer file would
    measure the annotation instead of the calling strategy.
    """
    missing = [task["id"] for task in tasks if task["id"] not in hints]
    if missing:
        raise ValueError(f"hints file is missing ids: {', '.join(missing)}")
    return [{**task, "prompt": hints[task["id"]]} for task in tasks]


def _symbol_hit(symbol: str, fragments: list[dict]) -> bool:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    return any(pattern.search(fragment["content"]) for fragment in fragments)


def _overlap(earlier: dict, later: dict) -> bool:
    if earlier["path"] != later["path"]:
        return False
    return earlier["lines"][0] <= later["lines"][1] and later["lines"][0] <= earlier["lines"][1]


def duplicate_fragments(fragments: list[dict]) -> tuple[int, int]:
    """Return (overlapping pairs, tokens spent on the later fragment of each pair)."""
    pairs = 0
    wasted = 0
    for index, fragment in enumerate(fragments):
        if any(_overlap(fragment, earlier) for earlier in fragments[:index]):
            pairs += 1
            wasted += fragment["estimated_tokens"]
    return pairs, wasted


def _task_recall(file_recall: float | None, symbol_recall: float | None) -> float | None:
    parts = [value for value in (file_recall, symbol_recall) if value is not None]
    return round(sum(parts) / len(parts), 3) if parts else None


def run_hil_arm(
    tasks: list[dict],
    root: Path,
    budget: int,
    indexed_paths: set[str],
    embedding: str | None = None,
) -> list[dict]:
    """Measure the HIL arm. No model is involved, so this is fully reproducible."""
    rows: list[dict] = []
    for task in tasks:
        started = time.perf_counter()
        result = get_project_context(task["prompt"], root, budget, embedding=embedding)
        latency_ms = (time.perf_counter() - started) * 1000
        fragments = result["fragments"]
        returned = [fragment["path"] for fragment in fragments]
        required_files = list(task["required_files"])
        required_symbols = list(task["required_symbols"])
        missing_files = [path for path in required_files if path not in returned]
        missing_symbols = [
            symbol for symbol in required_symbols if not _symbol_hit(symbol, fragments)
        ]
        file_recall = (
            round((len(required_files) - len(missing_files)) / len(required_files), 3)
            if required_files
            else None
        )
        symbol_recall = (
            round((len(required_symbols) - len(missing_symbols)) / len(required_symbols), 3)
            if required_symbols
            else None
        )
        pairs, wasted = duplicate_fragments(fragments)
        rows.append(
            {
                "id": task["id"],
                "category": task["category"],
                "prompt": task["prompt"],
                "estimated_tokens": result["estimated_tokens"],
                "latency_ms": round(latency_ms, 1),
                "fragments": len(fragments),
                "file_recall": file_recall,
                "symbol_recall": symbol_recall,
                "recall": _task_recall(file_recall, symbol_recall),
                "missing_files": missing_files,
                "missing_symbols": missing_symbols,
                "not_indexed": [path for path in required_files if path not in indexed_paths],
                "duplicate_pairs": pairs,
                "duplicate_tokens": wasted,
                "returned_paths": returned,
                "index_refreshed": result["index"]["refreshed"],
                "stale_reason": result["index"]["stale_reason"],
                "retrieval_mode": result["retrieval"]["mode"],
                "sufficient": result["sufficient"],
                "fallback": result["fallback"],
            }
        )
    return rows


def summarize(rows: list[dict], budget: int) -> dict:
    recalls = [row["recall"] for row in rows if row["recall"] is not None]
    latencies = sorted(row["latency_ms"] for row in rows)
    tokens = sorted(row["estimated_tokens"] for row in rows)
    return {
        "tasks": len(rows),
        "tasks_with_recall_criteria": len(recalls),
        "mean_recall_pct": round(statistics.fmean(recalls) * 100, 1) if recalls else None,
        "min_recall_pct": round(min(recalls) * 100, 1) if recalls else None,
        "perfect_recall_tasks": sum(1 for value in recalls if value >= 1.0),
        "tasks_meeting_target_recall": sum(
            1 for value in recalls if value * 100 >= TARGET_RECALL_PCT
        ),
        "target_recall_pct": TARGET_RECALL_PCT,
        "median_package_tokens": int(statistics.median(tokens)) if tokens else 0,
        "mean_package_tokens": round(statistics.fmean(tokens), 1) if tokens else 0.0,
        "token_budget": budget,
        "p50_latency_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
        "p95_latency_ms": (
            round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1)
            if latencies
            else 0.0
        ),
        "max_latency_ms": latencies[-1] if latencies else 0.0,
        "duplicate_pairs": sum(row["duplicate_pairs"] for row in rows),
        "duplicate_tokens": sum(row["duplicate_tokens"] for row in rows),
        "index_refresh_events": sum(1 for row in rows if row["index_refreshed"]),
        "tasks_without_fragments": sum(1 for row in rows if not row["sufficient"]),
        "retrieval_modes": sorted({row["retrieval_mode"] for row in rows}),
        "files_never_recalled": sorted({path for row in rows for path in row["missing_files"]}),
        "symbols_never_recalled": sorted(
            {symbol for row in rows for symbol in row["missing_symbols"]}
        ),
    }


def print_table(rows: list[dict]) -> None:
    print(f"{'id':<9}{'category':<17}{'recall':>8}{'tokens':>8}{'ms':>8}{'dup':>5}  missing")
    for row in rows:
        recall = "-" if row["recall"] is None else f"{row['recall'] * 100:.0f}%"
        missing = ",".join(row["missing_files"] + row["missing_symbols"]) or "-"
        print(
            f"{row['id']:<9}{row['category']:<17}{recall:>8}{row['estimated_tokens']:>8}"
            f"{row['latency_ms']:>8.0f}{row['duplicate_pairs']:>5}  {missing}"
        )


def write_worksheet(
    tasks: list[dict], path: Path, harnesses: list[str], seed: int = 0
) -> None:
    """Emit an empty A/B worksheet with a recorded randomisation.

    Roadmap §5 asks for native/HIL allocation to be randomised, and a seed is
    recorded on every row so the assignment can be replayed and reviewed. Each
    task is measured in both arms (a paired design: the token comparison is then
    within-task, which is the strongest test available at this sample size), and
    the *order* in which an operator runs the two arms is randomised and the rows
    are shuffled, so a harness's learning or caching effect is not correlated
    with the arm it happens to run second.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows = []
    for task in tasks:
        for harness in harnesses:
            order = ["native", "hil"]
            rng.shuffle(order)
            rows.append(
                {
                    "id": task["id"],
                    "harness": harness,
                    "prompt": task["prompt"],
                    "seed": seed,
                    "order": order,
                    "native": None,
                    "hil": None,
                }
            )
    rng.shuffle(rows)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"worksheet written: {path}")
    print(f"randomisation seed: {seed} (recorded on every row, replay with --seed {seed})")
    print(f"rows: {len(lines)} - fill every native/hil arm from harness session usage")


def _arm_metrics(arm: object, label: str, task_id: str) -> dict:
    """Validate one measured arm and return its numbers.

    ``input_tokens``, ``success`` and ``evidence`` are mandatory so a number is
    always traceable. ``retries``, ``tool_result_tokens``, ``cache_read_tokens``
    and the harness-side ``model`` are optional because they were added in
    Phase 3; a missing value must never be silently invented, so absence is
    reported as "not supplied" rather than defaulted to zero for tool tokens.
    """
    if not isinstance(arm, dict):
        raise ValueError(f"{task_id}: {label} arm is empty")
    tokens = arm.get("input_tokens")
    success = arm.get("success")
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
        raise ValueError(f"{task_id}: {label}.input_tokens must be a positive integer")
    if not isinstance(success, bool):
        raise ValueError(f"{task_id}: {label}.success must be true or false")
    if not arm.get("evidence"):
        raise ValueError(f"{task_id}: {label}.evidence is required so the number is traceable")

    def _non_negative(field: str) -> int:
        value = arm.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{task_id}: {label}.{field} must be a non-negative integer when present"
            )
        return value

    def _optional_non_negative(field: str) -> int | None:
        value = arm.get(field)
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{task_id}: {label}.{field} must be a non-negative integer when present"
            )
        return value

    model = arm.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError(f"{task_id}: {label}.model must be a non-empty string when present")
    return {
        "tokens": tokens,
        "success": success,
        "retries": _non_negative("retries"),
        "tool_tokens": _optional_non_negative("tool_result_tokens"),
        "cache_tokens": _optional_non_negative("cache_read_tokens"),
        "model": model,
    }


def _median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def load_reuse(path: Path) -> dict:
    """Read the cross-harness reuse artifact produced by the two-harness check."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("success"), bool):
        raise ValueError(f"{path}: reuse artifact needs a boolean 'success' field")
    pairs = payload.get("pairs", [])
    if not isinstance(pairs, list):
        raise ValueError(f"{path}: 'pairs' must be a list")
    if not pairs:
        raise ValueError(f"{path}: 'pairs' is empty; nothing was actually reused")
    for pair in pairs:
        if not isinstance(pair, dict) or not isinstance(pair.get("found"), bool):
            raise ValueError(f"{path}: every reuse pair needs a boolean 'found' field")
        if not pair.get("evidence"):
            raise ValueError(f"{path}: every reuse pair needs 'evidence'")
    return payload



def compare(
    records: list[dict],
    task_ids: set[str],
    recall_pct: float | None,
    reuse: dict | None = None,
) -> int:
    """Evaluate a filled worksheet against the roadmap Phase 3 thresholds.

    Gates: median input token reduction, success-rate drop, context recall,
    mean retries, and cross-harness memory reuse. Tool-result size and
    prompt-cache reads are reported but deliberately not gated: roadmap §5 asks
    them to be *recorded* so a reviewer can separate a retrieval saving from a
    caching or model effect, not thresholded.
    """
    if len(records) < MIN_AB_TASKS:
        print(
            f"refusing to report savings: {len(records)} records, "
            f"roadmap requires at least {MIN_AB_TASKS}"
        )
        return 3
    unknown = sorted({record.get("id", "?") for record in records} - task_ids)
    if unknown:
        print(f"refusing to report savings: unknown task ids {', '.join(unknown)}")
        return 3
    reductions: list[float] = []
    native_success: list[bool] = []
    hil_success: list[bool] = []
    native_retries: list[int] = []
    hil_retries: list[int] = []
    native_tool: list[int] = []
    hil_tool: list[int] = []
    native_cache: list[int] = []
    hil_cache: list[int] = []
    models: set[str] = set()
    harnesses: set[str] = set()
    try:
        for record in records:
            task_id = record.get("id", "?")
            harnesses.add(str(record.get("harness", "unknown")))
            native = _arm_metrics(record.get("native"), "native", task_id)
            hil = _arm_metrics(record.get("hil"), "hil", task_id)
            reductions.append((native["tokens"] - hil["tokens"]) / native["tokens"] * 100)
            native_success.append(native["success"])
            hil_success.append(hil["success"])
            native_retries.append(native["retries"])
            hil_retries.append(hil["retries"])
            if native["tool_tokens"] is not None and hil["tool_tokens"] is not None:
                native_tool.append(native["tool_tokens"])
                hil_tool.append(hil["tool_tokens"])
            if native["cache_tokens"] is not None and hil["cache_tokens"] is not None:
                native_cache.append(native["cache_tokens"])
                hil_cache.append(hil["cache_tokens"])
            for arm in (native, hil):
                if arm["model"]:
                    models.add(arm["model"])
    except ValueError as exc:
        print(f"refusing to report savings: {exc}")
        return 3

    median_reduction = statistics.median(reductions)
    native_rate = sum(native_success) / len(native_success) * 100
    hil_rate = sum(hil_success) / len(hil_success) * 100
    drop = native_rate - hil_rate
    mean_native_retries = statistics.fmean(native_retries)
    mean_hil_retries = statistics.fmean(hil_retries)
    print(f"A/B records: {len(records)} task runs across {', '.join(sorted(harnesses))}")
    print(f"median input token reduction: {median_reduction:.1f}% (target >= {TARGET_REDUCTION_PCT}%)")
    print(
        f"success rate: native {native_rate:.1f}% -> hil {hil_rate:.1f}% "
        f"(drop {drop:.1f} pp, budget {MAX_SUCCESS_DROP_PP} pp)"
    )
    print(
        f"mean retries: native {mean_native_retries:.2f} -> hil {mean_hil_retries:.2f} "
        "(target: not increased)"
    )
    if native_tool and hil_tool:
        print(
            f"median tool-result tokens: native {_median(native_tool)} -> hil {_median(hil_tool)}"
        )
    else:
        print("median tool-result tokens: not supplied")
    if native_cache and hil_cache:
        print(
            f"median prompt-cache read tokens: native {_median(native_cache)} -> "
            f"hil {_median(hil_cache)} (separates caching from retrieval)"
        )
    if models:
        print(f"models seen: {', '.join(sorted(models))}")
    if recall_pct is None:
        print("context recall: not supplied (pass --recall-file <hil_*.json>)")
    else:
        print(f"context recall (HIL arm): {recall_pct:.1f}% (target >= {TARGET_RECALL_PCT}%)")
    if reuse is None:
        print("cross-harness memory reuse: not supplied (pass --reuse-file <reuse.json>)")
    else:
        pairs = reuse.get("pairs", [])
        found = sum(1 for pair in pairs if pair.get("found"))
        print(
            f"cross-harness memory reuse: {found}/{len(pairs)} facts written by one "
            "harness were retrieved through another"
        )
    checks = [
        ("median input token reduction", median_reduction >= TARGET_REDUCTION_PCT),
        ("success rate drop", drop <= MAX_SUCCESS_DROP_PP),
        ("context recall", recall_pct is not None and recall_pct >= TARGET_RECALL_PCT),
        ("mean retries not increased", mean_hil_retries <= mean_native_retries),
    ]
    if reuse is not None:
        checks.append(("cross-harness memory reuse", bool(reuse.get("success"))))
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    return 0 if all(passed for _, passed in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 measurement harness")
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="project to measure")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--budget", type=int, default=1500)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    parser.add_argument("--label", default="hil")
    parser.add_argument(
        "--variant",
        choices=("raw", "hinted"),
        default="raw",
        help="raw = task prompt as written; hinted = identifier-rich rephrasing",
    )
    parser.add_argument("--hints", default=str(DEFAULT_HINTS))
    parser.add_argument(
        "--embedding",
        choices=("off", "auto", "on", "hash"),
        default=None,
        help="optional semantic re-ranking arm (default: follow HIL_EMBEDDINGS, else off)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="results file path (default .hil/results/, which the index excludes)",
    )
    parser.add_argument("--worksheet", default="", help="write an empty A/B worksheet and exit")
    parser.add_argument(
        "--harness",
        action="append",
        default=[],
        help="harness name for --worksheet (repeatable, default openclaw+cline)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="randomisation seed for --worksheet arm order (recorded on every row)",
    )
    parser.add_argument("--compare", default="", help="filled A/B worksheet to evaluate")
    parser.add_argument("--recall-file", default="", help="HIL results file for the recall gate")
    parser.add_argument(
        "--reuse-file",
        default="",
        help="cross-harness memory reuse artifact for the reuse gate",
    )
    args = parser.parse_args(argv)

    tasks = load_tasks(Path(args.tasks))
    if args.limit:
        tasks = tasks[: args.limit]
    if args.variant == "hinted":
        tasks = apply_hints(tasks, load_hints(Path(args.hints)))

    if args.worksheet:
        write_worksheet(
            tasks, Path(args.worksheet), args.harness or ["openclaw", "cline"], args.seed
        )
        return 0

    if args.compare:
        records = [
            json.loads(line)
            for line in Path(args.compare).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        recall_pct = None
        if args.recall_file:
            report = json.loads(Path(args.recall_file).read_text(encoding="utf-8"))
            recall_pct = report["summary"]["mean_recall_pct"]
        reuse = None
        if args.reuse_file:
            try:
                reuse = load_reuse(Path(args.reuse_file))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"refusing to report savings: {exc}")
                return 3
        return compare(records, {task["id"] for task in tasks}, recall_pct, reuse)

    root = Path(args.root).resolve()
    print(
        f"HIL {HIL_VERSION} | index schema {INDEX_VERSION} | budget {args.budget} "
        f"| variant {args.variant} | embedding {args.embedding or 'off'} | {root}"
    )
    index_project(root)
    indexed_paths = {entry["path"] for entry in load_index(root)["files"]}
    print(f"indexed files: {len(indexed_paths)} | tasks: {len(tasks)}")
    print()
    rows = run_hil_arm(tasks, root, args.budget, indexed_paths, args.embedding)
    summary = summarize(rows, args.budget)
    print_table(rows)
    print()
    for key, value in summary.items():
        print(f"{key}: {value}")

    out = (
        Path(args.out)
        if args.out
        else ARTIFACT_DIR
        / f"hil_{args.label}_{args.variant}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "label": args.label,
                "project_root": str(root),
                "hil_version": HIL_VERSION,
                "index_schema_version": INDEX_VERSION,
                "token_budget": args.budget,
                "variant": args.variant,
                "embedding": args.embedding or "off",
                "summary": summary,
                "tasks": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(f"results written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
