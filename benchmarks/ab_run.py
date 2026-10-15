#!/usr/bin/env python3
"""Run one arm of the cross-harness A/B through a real harness CLI.

``docs/roadmap.md`` §5/§9 (Phase 3). This automates *capture*, not judgement: it
runs the harness, parses the usage the harness reports, and writes raw rows. The
``success`` field is deliberately **not** produced here - it needs a judge against
each task's ``success_criteria`` - so the script never invents it.

The one thing it does touch outside the repo is the harness's MCP config, and only
to toggle the ``hil`` server for the arm being measured; the change is restored in
a ``finally`` block, so an interrupt cannot leave HIL enabled for a native run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CLINE_BIN = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "cline" / "bin" / "cline"
CLINE_SETTINGS = Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
#: Per-attempt cap. A single task that keeps spinning is a lost data point, not a
#: reason to stall the whole arm; a shorter cap plus a retry bounds the tail.
DEFAULT_TIMEOUT_SECONDS = 300

#: The treatment. Both arms get the same task text; only the HIL arm is told to pull
#: the context package first, exactly like the OpenClaw run in ``docs/roadmap.md``
#: §5. That calling difference is deliberately visible, because §9 asks for it to be
#: separated from the retrieval contribution rather than hidden.
HIL_INSTRUCTION = (
    "\n\nBefore answering, call the hil MCP tool get_project_context with the task "
    "text above as its `task` argument, then answer using the returned package."
)

#: A neutral ASCII tail applied to **both** arms. The harness CLI receives the task
#: as a command-line argument, and a prompt that ends in a non-ASCII character is
#: intermittently mangled on Windows (observed as "Unknown command or unquoted
#: prompt" on ~40% of the native arm, while the HIL arm - whose prompt already ended
#: in ASCII - never failed). The same tail on both arms keeps the comparison fair.
ANSWER_TAIL = "\n\nAnswer concisely and cite the file paths you relied on."

#: The attribution experiment (`docs/roadmap.md` §9): both arms get the *same*
#: instruction and no hil tool; the only difference is whether the retriever's
#: package is pasted into the prompt. That separates "the package helped" from
#: "being told to fetch context changed the agent's behaviour".
INJECT_HEADER = (
    "\n\nProject context package from the HIL retriever (use it if relevant):\n"
)


def context_package(root: Path, task: str, budget: int = 1500) -> str:
    """The HIL package for ``task``, rendered as plain text for prompt injection."""
    sys.path.insert(0, str(ROOT / "src"))
    from harness_intelligence.retrieval import get_project_context

    result = get_project_context(task, root, budget)
    blocks = [
        f"### {fragment['path']}:{fragment['lines'][0]}-{fragment['lines'][1]}\n"
        f"{fragment['content']}"
        for fragment in result["fragments"]
    ]
    return "\n\n".join(blocks)


def load_tasks(path: Path, limit: int, task_ids: list[str]) -> list[dict]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))
    if task_ids:
        wanted = set(task_ids)
        tasks = [task for task in tasks if task["id"] in wanted]
    return tasks[:limit] if limit else tasks


def set_hil(enabled: bool, project_root: Path | None = None) -> None:
    """Toggle the ``hil`` MCP server for Cline, keeping a one-time backup.

    ``project_root`` also repoints the server's ``HIL_PROJECT_ROOT`` so an isolated
    run queries the copy it is actually working in, not the real checkout.
    """
    payload = json.loads(CLINE_SETTINGS.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers", {})
    if "hil" not in servers:
        raise SystemExit("hil is not configured for Cline; register it first")
    backup = CLINE_SETTINGS.with_suffix(".json.ab-run-backup")
    if not backup.exists():
        shutil.copyfile(CLINE_SETTINGS, backup)
    servers["hil"]["disabled"] = not enabled
    if project_root is not None:
        servers["hil"].setdefault("env", {})["HIL_PROJECT_ROOT"] = str(project_root)
    CLINE_SETTINGS.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse(stdout: str) -> tuple[dict, Counter, str]:
    usage: dict = {}
    final_text = ""
    tools: Counter[str] = Counter()
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "run_result":
            body = event.get("usage", {})
            usage = {
                "input_tokens": body.get("inputTokens"),
                "output_tokens": body.get("outputTokens"),
                "cache_read_tokens": body.get("cacheReadTokens"),
                "model": (event.get("model") or {}).get("id"),
                "provider": (event.get("model") or {}).get("provider"),
                "duration_ms": event.get("durationMs"),
                "iterations": event.get("iterations"),
                "finish_reason": event.get("finishReason"),
            }
            final_text = (event.get("text") or "")[:2000]
        inner = event.get("event") or {}
        if inner.get("contentType") == "tool" and inner.get("toolName"):
            tools[inner["toolName"]] += 1
    return usage, tools, final_text


def run_cline(
    prompt: str,
    model: str,
    provider: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    root: Path | None = None,
) -> tuple[dict, Counter, str, str]:
    """Run one turn, retrying once: return ``(usage, tools, text, error)``.

    A transient harness/API failure must not silently become a zero-token data
    point, so an attempt with no ``run_result`` is retried once and, if it still
    fails, the row carries the error instead of being counted.
    """
    command = [
        "node", str(CLINE_BIN), "--json", "-c", str(root or ROOT), "--thinking", "none"
    ]
    if provider:
        command += ["-P", provider]
    if model:
        command += ["-m", model]
    command.append(prompt)
    error = ""
    for _ in range(2):
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            error = "timeout"
            continue
        except Exception as exc:  # noqa: BLE001 - one bad run must not sink the arm
            error = f"{exc.__class__.__name__}: {exc}"[:400]
            continue
        usage, tools, final_text = _parse(proc.stdout)
        if usage:
            return usage, tools, final_text, ""
        error = (proc.stderr or proc.stdout or "no output").strip()[-400:]
    return {}, Counter(), "", error or "no run_result"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one A/B arm through a harness CLI")
    parser.add_argument("--harness", default="cline")
    parser.add_argument("--arm", choices=["native", "hil", "control", "injected"], required=True)
    parser.add_argument("--tasks", default=str(HERE / "tasks.jsonl"))
    parser.add_argument("--out", required=True, help="JSONL output path")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="comma-separated task ids")
    parser.add_argument("--model", default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--jobs", type=int, default=4, help="concurrent runs")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--root",
        default="",
        help="working tree the harness runs in (an isolated copy, so it cannot "
        "mutate the real checkout)",
    )
    args = parser.parse_args()
    if args.harness != "cline":
        raise SystemExit("only the cline harness is wired up so far")

    tasks = load_tasks(Path(args.tasks), args.limit, [i for i in args.ids.split(",") if i])
    root = Path(args.root).resolve() if args.root else ROOT
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    def measure(task: dict) -> dict:
        prompt = task["prompt"] + ANSWER_TAIL
        if args.arm == "hil":
            prompt += HIL_INSTRUCTION
        if args.arm == "injected":
            prompt += INJECT_HEADER + context_package(root, task["prompt"])
        usage, tools, text, error = run_cline(
            prompt, args.model, args.provider, args.timeout, root
        )
        return {
            "id": task["id"],
            "harness": args.harness,
            "arm": args.arm,
            "category": task["category"],
            "prompt": task["prompt"],
            "success": None,
            "usage": usage,
            "tool_counts": dict(tools),
            "hil_called": any("hil" in name.lower() for name in tools),
            "answer_excerpt": text,
            "error": error,
            "evidence": (
                f"cline {args.harness} {args.arm} run "
                f"{datetime.now(timezone.utc).isoformat()}"
            ),
        }

    def report(done: int, row: dict) -> None:
        print(
            f"[{done}/{len(tasks)}] {row['id']} in={row['usage'].get('input_tokens')} "
            f"out={row['usage'].get('output_tokens')} hil={row['hil_called']} "
            f"tools={len(row['tool_counts'])} err={row['error'][:60]}",
            flush=True,
        )

    rows: list[dict] = []
    # The hil toggle is per arm, not per task, so runs within one arm are
    # independent and can safely overlap.
    set_hil(args.arm == "hil", root)
    try:
        if args.jobs > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {pool.submit(measure, task): task for task in tasks}
                for done, future in enumerate(as_completed(futures), 1):
                    task = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:  # noqa: BLE001 - record, do not sink the arm
                        row = {
                            "id": task["id"],
                            "harness": args.harness,
                            "arm": args.arm,
                            "category": task["category"],
                            "prompt": task["prompt"],
                            "success": None,
                            "usage": {},
                            "tool_counts": {},
                            "hil_called": False,
                            "answer_excerpt": "",
                            "error": f"{exc.__class__.__name__}: {exc}"[:400],
                            "evidence": (
                                f"cline {args.harness} {args.arm} run "
                                f"{datetime.now(timezone.utc).isoformat()}"
                            ),
                        }
                    rows.append(row)
                    report(done, row)
        else:
            for index, task in enumerate(tasks, 1):
                row = measure(task)
                rows.append(row)
                report(index, row)
    finally:
        set_hil(True, root)
    rows.sort(key=lambda row: row["id"])

    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    called = sum(1 for row in rows if row["hil_called"])
    print(f"wrote {len(rows)} rows to {out}; hil called in {called}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
