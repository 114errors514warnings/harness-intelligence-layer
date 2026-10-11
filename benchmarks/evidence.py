#!/usr/bin/env python3
"""Phase 4 evidence gate.

``docs/roadmap.md`` §6 keeps four expansions behind a trigger: optional
embeddings/reranker, a Unified Validator, a Model Router, and a vector store
such as FAISS or Qdrant. This script makes each trigger *decidable from
recorded evidence* instead of from appetite. It implements none of them; it
reports, per trigger, whether the recorded numbers justify starting.

Exit code is always 0: this is a decision report, not a build gate. A trigger
that reads ``FIRED`` means "the evidence the roadmap asked for now exists"; it
does not by itself create an obligation to build, and every claim still has to
be measured by ``benchmarks/measure.py`` before it is advertised.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = Path(__file__).resolve().parent
for _extra in (PROJECT_ROOT / "src", BENCHMARKS_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import measure  # noqa: E402

DEFAULT_BASELINE = BENCHMARKS_DIR / "results" / "baseline.json"
DEFAULT_AB = BENCHMARKS_DIR / "results" / "ab.jsonl"
DEFAULT_QUALITY = BENCHMARKS_DIR / "results" / "quality.json"
DEFAULT_REUSE = BENCHMARKS_DIR / "results" / "reuse.json"
ARTIFACT_DIR = PROJECT_ROOT / ".hil" / "results"

#: Roadmap §6 "already accumulated at least 100 comparable task results".
ROUTER_MIN_RECORDS = 100
#: Roadmap §4/§5 exit criterion: retrieval P95 must stay under one second.
LATENCY_BUDGET_MS = 1000.0


def _load(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _filled_records(path: Path) -> int:
    """Count worksheet rows whose two arms were both measured."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    filled = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record.get("native"), dict) and isinstance(record.get("hil"), dict):
            filled += 1
    return filled


def _latest_latency() -> float | None:
    """P95 latency from the newest per-run report under ``.hil/results``."""
    if not ARTIFACT_DIR.exists():
        return None
    reports = sorted(ARTIFACT_DIR.glob("hil_*.json"), key=lambda path: path.stat().st_mtime)
    for report in reversed(reports):
        payload = _load(report)
        if isinstance(payload, dict):
            value = payload.get("summary", {}).get("p95_latency_ms")
            if isinstance(value, (int, float)):
                return float(value)
    return None


def evaluate(baseline_path: Path, ab_path: Path, quality_path: Path) -> list[dict]:
    triggers: list[dict] = []

    baseline = _load(baseline_path)
    variants = baseline.get("variants", {}) if isinstance(baseline, dict) else {}
    measured = {
        variant: summary.get("mean_recall_pct")
        for variant, summary in variants.items()
        if isinstance(summary, dict) and isinstance(summary.get("mean_recall_pct"), (int, float))
    }
    if not measured:
        triggers.append(
            {
                "trigger": "embeddings + reranker",
                "state": "NOT EVIDENCED",
                "detail": f"no measured recall in {baseline_path.name}; run benchmarks/measure.py",
            }
        )
    else:
        shortfalls = {
            variant: value for variant, value in measured.items() if value < measure.TARGET_RECALL_PCT
        }
        detail = ", ".join(f"{variant} {value}%" for variant, value in sorted(measured.items()))
        triggers.append(
            {
                "trigger": "embeddings + reranker",
                "state": "FIRED" if shortfalls else "NOT FIRED",
                "detail": (
                    f"lexical recall {detail} against a {measure.TARGET_RECALL_PCT}% target; "
                    "the residual gap is cross-language (see docs/roadmap.md §4)"
                    if shortfalls
                    else f"lexical recall {detail} already meets the {measure.TARGET_RECALL_PCT}% target"
                ),
            }
        )

    quality = _load(quality_path)
    edits = quality.get("edits") if isinstance(quality, dict) else None
    if not isinstance(edits, list) or not edits:
        triggers.append(
            {
                "trigger": "unified validator",
                "state": "NOT EVIDENCED",
                "detail": (
                    f"no judged edit set in {quality_path.name}; nothing shows that code-change "
                    "quality is currently non-comparable"
                ),
            }
        )
    else:
        incomparable = [edit for edit in edits if edit.get("comparable") is False]
        triggers.append(
            {
                "trigger": "unified validator",
                "state": "FIRED" if incomparable else "NOT FIRED",
                "detail": f"{len(incomparable)}/{len(edits)} judged edits are non-comparable",
            }
        )

    filled = _filled_records(ab_path)
    triggers.append(
        {
            "trigger": "model router",
            "state": "FIRED" if filled >= ROUTER_MIN_RECORDS else "NOT FIRED",
            "detail": (
                f"{filled} filled A/B records; roadmap requires >= {ROUTER_MIN_RECORDS}"
            ),
        }
    )

    p95 = _latest_latency()
    if p95 is None:
        triggers.append(
            {
                "trigger": "vector store (FAISS/Qdrant)",
                "state": "NOT EVIDENCED",
                "detail": "no per-run latency report under .hil/results/",
            }
        )
    else:
        triggers.append(
            {
                "trigger": "vector store (FAISS/Qdrant)",
                "state": "FIRED" if p95 >= LATENCY_BUDGET_MS else "NOT FIRED",
                "detail": f"retrieval p95 {p95:.0f} ms against a {LATENCY_BUDGET_MS:.0f} ms budget",
            }
        )
    return triggers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report which Phase 4 evidence triggers have fired")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--ab", default=str(DEFAULT_AB))
    parser.add_argument("--quality", default=str(DEFAULT_QUALITY))
    args = parser.parse_args(argv)

    print("Phase 4 evidence gate (docs/roadmap.md section 6)")
    print("")
    for trigger in evaluate(Path(args.baseline), Path(args.ab), Path(args.quality)):
        print(f"  [{trigger['state']}] {trigger['trigger']}")
        print(f"           {trigger['detail']}")
    print("")
    print("A FIRED trigger means the evidence exists, not that the work must be built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
