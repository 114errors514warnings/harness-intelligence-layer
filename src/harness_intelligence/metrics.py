"""Local, privacy-preserving usage metrics for the retrieval tool.

Every ``get_project_context`` call may append **one JSON line** to
``<project>/.hil/metrics.jsonl``:

    {"t": "...", "latency_ms": 12.3, "fragments": 8, "tokens": 1200,
     "memories": 1, "mode": "lexical", "confidence": "high",
     "sufficient": true, "reranked": 0}

Deliberate limits:

* **No query text, no file contents, no memory text.** Only counts, timing and the
  categorical flags a dashboard needs.
* **Never breaks a call.** Every failure (read-only filesystem, full disk, malformed
  env) is swallowed: metrics are observability, not a dependency.
* **Bounded.** The file rotates once it passes ``MAX_BYTES``; only one previous
  generation is kept.
* **Off switch.** ``HIL_METRICS=off`` disables it. The benchmarks set this so their
  runs do not look like real usage.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

METRICS_ENV = "HIL_METRICS"
METRICS_FILE = "metrics.jsonl"
MAX_BYTES = 5 * 1024 * 1024
OFF_VALUES = {"off", "0", "false", "no", "disabled"}


def enabled() -> bool:
    return os.environ.get(METRICS_ENV, "").strip().lower() not in OFF_VALUES


def metrics_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".hil" / METRICS_FILE


def record(
    project_root: str | Path,
    *,
    latency_ms: float,
    fragments: int,
    tokens: int,
    memories: int,
    mode: str,
    confidence: str | None,
    sufficient: bool,
    reranked: int = 0,
) -> None:
    """Append one usage line. Silently does nothing when disabled or on any error."""
    if not enabled():
        return
    try:
        path = metrics_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            # Keep the rotated name identical to what ``load`` reads back.
            path.replace(path.with_name(path.name + ".1"))
        line = json.dumps(
            {
                "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "latency_ms": round(float(latency_ms), 1),
                "fragments": int(fragments),
                "tokens": int(tokens),
                "memories": int(memories),
                "mode": mode,
                "confidence": confidence,
                "sufficient": bool(sufficient),
                "reranked": int(reranked),
            }
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - observability must never break retrieval
        return


def load(project_root: str | Path) -> list[dict]:
    """Read the current plus the rotated generation, oldest first."""
    root = Path(project_root).resolve()
    rows: list[dict] = []
    for name in (f"{METRICS_FILE}.1", METRICS_FILE):
        path = root / ".hil" / name
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
