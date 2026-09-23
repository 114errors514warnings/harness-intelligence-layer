from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .indexer import load_index, read_text
from .memory import search_memory
from .tokens import estimate_tokens


TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u3400-\u9fff]{2,}")


@dataclass
class Candidate:
    path: str
    start_line: int
    end_line: int
    content: str
    score: float
    reasons: list[str]

    @property
    def token_cost(self) -> int:
        return estimate_tokens(self.content) + 24


def query_terms(task: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).lower() for match in TERM_RE.finditer(task)))


def _windows(lines: list[str], hit_lines: list[int], radius: int = 6) -> list[tuple[int, int]]:
    if not hit_lines:
        return [(1, min(len(lines), 20))]
    ranges = []
    for line in hit_lines[:8]:
        start, end = max(1, line - radius), min(len(lines), line + radius)
        if ranges and start <= ranges[-1][1] + 2:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges[:3]


def get_project_context(task: str, project_root: str | Path, token_budget: int = 4000) -> dict:
    if token_budget < 200:
        raise ValueError("token_budget must be at least 200")
    root = Path(project_root).resolve()
    index = load_index(root)
    terms = query_terms(task)
    candidates: list[Candidate] = []
    for entry in index["files"]:
        path_lower = entry["path"].lower()
        path_hits = [term for term in terms if term in path_lower]
        symbol_hits = [
            symbol for symbol in entry.get("symbols", [])
            if any(term in symbol["name"].lower() for term in terms)
        ]
        text = read_text(root / entry["path"])
        if text is None:
            continue
        lines = text.splitlines()
        content_hits = [
            number for number, line in enumerate(lines, 1)
            if any(term in line.lower() for term in terms)
        ]
        if terms and not (path_hits or symbol_hits or content_hits):
            continue
        base_score = len(path_hits) * 8 + len(symbol_hits) * 6 + min(len(content_hits), 10) * 1.5
        reasons = []
        if path_hits:
            reasons.append("path:" + ",".join(path_hits[:3]))
        if symbol_hits:
            reasons.append("symbols:" + ",".join(item["name"] for item in symbol_hits[:3]))
        if content_hits:
            reasons.append(f"text_hits:{len(content_hits)}")
        for start, end in _windows(lines, content_hits or [item["line"] for item in symbol_hits]):
            content = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
            candidates.append(Candidate(entry["path"], start, end, content, base_score, reasons))

    memory_candidates = search_memory(task, root, limit=3)
    memories = []
    used = 0
    memory_cap = token_budget // 4
    for memory in memory_candidates:
        cost = estimate_tokens(memory.get("title", "") + "\n" + memory.get("content", "")) + 24
        if used + cost > memory_cap:
            continue
        memories.append({**memory, "estimated_tokens": cost})
        used += cost

    candidates.sort(key=lambda item: (item.score / max(item.token_cost, 1), item.score), reverse=True)
    selected = []
    for candidate in candidates:
        if used + candidate.token_cost > token_budget:
            continue
        selected.append(
            {
                "path": candidate.path,
                "lines": [candidate.start_line, candidate.end_line],
                "score": round(candidate.score, 2),
                "reasons": candidate.reasons,
                "estimated_tokens": candidate.token_cost,
                "content": candidate.content,
            }
        )
        used += candidate.token_cost
    return {
        "task": task,
        "project_root": str(root),
        "token_budget": token_budget,
        "estimated_tokens": used,
        "terms": terms,
        "fragments": selected,
        "memories": memories,
        "notice": "Lexical V0.1 retrieval; verify critical symbols before editing.",
    }
