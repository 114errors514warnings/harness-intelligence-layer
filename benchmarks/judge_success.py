#!/usr/bin/env python3
"""Judge one A/B arm's answers against each task's ``success_criteria``.

``docs/roadmap.md`` §5 requires a per-arm ``success`` boolean, and §10.4 says a
judge must apply one rubric uniformly. This script is that judge: for every row it
sends the task, its ``success_criteria`` and the harness's answer to the configured
model and records PASS/FAIL plus a one-line reason.

It is deliberately a *separate* step from capture (``ab_run.py``): a judge can be
swapped, re-run, or replaced by a human without re-running the expensive harness
turns. The verdict is written next to the run data, never fabricated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DEFAULT_ENDPOINT = "https://ollama.com/v1/chat/completions"
DEFAULT_JUDGE_MODEL = "deepseek-v4.1-flash"

SYSTEM = (
    "You are a strict grader. You are given a task, its success criteria, and the "
    "answer a coding agent produced. Decide only whether the answer satisfies the "
    "criteria. Ignore style, length, and confidence. If the answer is empty, an "
    "error, or does not address the criteria, answer FAIL. Reply with exactly one "
    "word, PASS or FAIL, then a dash and one short reason."
)


def cline_ollama_key() -> str:
    providers = Path.home() / ".cline" / "data" / "settings" / "providers.json"
    payload = json.loads(providers.read_text(encoding="utf-8"))
    return payload["providers"]["ollama"]["settings"].get("apiKey", "")


def judge(endpoint: str, key: str, model: str, task: dict, answer: str) -> tuple[bool, str]:
    user = (
        f"TASK:\n{task['prompt']}\n\n"
        f"SUCCESS CRITERIA:\n{task['success_criteria']}\n\n"
        f"ANSWER:\n{answer or '(empty)'}\n\n"
        "One word, PASS or FAIL, then a dash and a short reason."
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = (payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    passed = text.upper().startswith("PASS")
    return passed, text[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description="Judge one A/B arm's answers")
    parser.add_argument("--run", required=True, help="run jsonl from ab_run.py")
    parser.add_argument("--tasks", default=str(HERE / "tasks.jsonl"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", default=os.environ.get("HIL_JUDGE_URL", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()

    tasks = {}
    for line in Path(args.tasks).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            task = json.loads(line)
            tasks[task["id"]] = task
    rows = [
        json.loads(line)
        for line in Path(args.run).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    key = cline_ollama_key()
    if not key:
        raise SystemExit("no Ollama API key found in Cline's providers.json")

    judged = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                judge,
                args.endpoint,
                key,
                args.model,
                tasks[row["id"]],
                row.get("answer_excerpt", ""),
            ): row
            for row in rows
            if row["id"] in tasks
        }
        for done, future in enumerate(as_completed(futures), 1):
            row = futures[future]
            try:
                passed, reason = future.result()
            except Exception as exc:  # noqa: BLE001 - a judge failure must be visible
                passed, reason = False, f"judge error: {exc.__class__.__name__}"
            judged.append(
                {
                    "id": row["id"],
                    "arm": row["arm"],
                    "category": row["category"],
                    "success": passed,
                    "judge_reason": reason,
                    "judge_model": args.model,
                }
            )
            print(f"[{done}/{len(futures)}] {row['id']} {row['arm']} -> {passed} | {reason[:70]}", flush=True)
    judged.sort(key=lambda item: item["id"])
    Path(args.out).write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in judged) + "\n",
        encoding="utf-8",
    )
    passed = sum(1 for item in judged if item["success"])
    print(f"wrote {len(judged)} verdicts to {args.out}; pass {passed}/{len(judged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
