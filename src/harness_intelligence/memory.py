from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


CATEGORIES = {
    "architecture", "decisions", "bugs", "conventions", "experiments", "tasks"
}
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u3400-\u9fff]{2,}")


def _terms(text: str) -> set[str]:
    return {match.group(0).lower() for match in WORD_RE.finditer(text)}


def record_memory(
    category: str,
    title: str,
    content: str,
    project_root: str | Path,
    tags: list[str] | None = None,
    source: str | None = None,
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    if not title.strip() or not content.strip():
        raise ValueError("title and content are required")
    root = Path(project_root).resolve()
    memory_id = uuid.uuid4().hex[:12]
    payload = {
        "id": memory_id,
        "category": category,
        "title": title.strip(),
        "content": content.strip(),
        "tags": tags or [],
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    target = root / ".ai-memory" / category
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{memory_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**payload, "path": str(path)}


def search_memory(query: str, project_root: str | Path, limit: int = 5) -> list[dict]:
    root = Path(project_root).resolve()
    memory_root = root / ".ai-memory"
    if not memory_root.exists():
        return []
    query_set = _terms(query)
    matches = []
    for path in memory_root.glob("*/*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        haystack = " ".join([payload.get("title", ""), payload.get("content", ""), *payload.get("tags", [])])
        overlap = query_set & _terms(haystack)
        if overlap or not query_set:
            matches.append(
                {
                    **payload,
                    "score": len(overlap),
                    "matched_terms": sorted(overlap),
                    "path": str(path.relative_to(root)),
                }
            )
    matches.sort(key=lambda item: (item["score"], item.get("created_at", "")), reverse=True)
    return matches[: max(1, limit)]

