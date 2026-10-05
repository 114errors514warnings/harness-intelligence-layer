from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .indexer import load_index, read_text
from .memory import search_memory
from .terms import content_pattern, extract_terms, identifier_parts
from .tokens import estimate_tokens


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


#: Bonus weights and their caps. Path and symbol matches are properties of the
#: file, so every one of its windows carries them; capping each kind stops a
#: symbol-rich test file from buying the whole budget on its file's merits, while
#: a fragment that also *contains* matching lines still wins.
#:
#: An identifier the query names outright (``discover_files``) is far stronger
#: evidence than a query word that happens to sit inside a name
#: (``memory`` inside ``test_index_excludes_memory_store``), so the two are
#: weighted apart instead of both counting as "a symbol hit".
PATH_HIT_WEIGHT = 8.0
SYMBOL_EXACT_WEIGHT = 6.0
SYMBOL_WORD_WEIGHT = 2.0
CONTENT_HIT_WEIGHT = 1.5
MAX_BONUS_HITS = 3


def query_terms(task: str) -> list[str]:
    """Terms a task is matched by.

    Delegates to :func:`terms.extract_terms` so code retrieval and memory search
    cannot drift apart, and so a Chinese run is split into n-grams instead of
    becoming one unmatchable term.
    """
    return extract_terms(task)


#: A fragment is a focused slice of a file, not a chapter. Windows stop growing at
#: this many estimated tokens: a dense run of hits used to merge into a
#: multi-hundred-token monolith that spent most of a task's budget on one
#: fragment. Measured on the benchmark, one 688-token window in docs/roadmap.md
#: was the whole cause of that task's miss.
MAX_WINDOW_TOKENS = 220

#: At most this many windows per file, so one file cannot fill the package.
MAX_WINDOWS = 3

#: How many hit lines may act as window centers. A file that mentions the topic
#: everywhere (the word "index" inside indexer.py) would otherwise pay for
#: hundreds of window evaluations that could never all be emitted.
MAX_WINDOW_CENTERS = 40


def _window_cost(lines: list[str], start: int, end: int) -> int:
    """Conservative token estimate of ``lines[start:end]`` with line prefixes.

    Summing per-line estimates overestimates a joined window slightly (each line
    rounds up), which is the safe direction for a cap.
    """
    return sum(
        estimate_tokens(f"{number}: {lines[number - 1]}") for number in range(start, end + 1)
    )


def _split_oversized(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    """Chop ``lines[start:end]`` into consecutive windows of at most the cap.

    A single line longer than the cap still becomes its own one-line window, so
    bounding can never produce an empty or dropped range.
    """
    windows: list[tuple[int, int]] = []
    current = start
    while current <= end:
        last = current
        while last < end and _window_cost(lines, current, last + 1) <= MAX_WINDOW_TOKENS:
            last += 1
        windows.append((current, last))
        current = last + 1
    return windows


def _windows(lines: list[str], hit_lines: list[int], radius: int = 6) -> list[tuple[int, int]]:
    """Every disjoint, token-bounded window around the hits of one file.

    This is a *pool*, not the final choice: which windows are worth emitting is a
    ranking decision and belongs with the scoring in :func:`_entry_candidates`.
    """
    if not hit_lines:
        return _split_oversized(lines, 1, min(len(lines), 20))
    ranges: list[tuple[int, int]] = []
    for line in hit_lines[:MAX_WINDOW_CENTERS]:
        start, end = max(1, line - radius), min(len(lines), line + radius)
        if not ranges:
            ranges.append((start, end))
            continue
        last_start, last_end = ranges[-1]
        if start <= last_end + 2 and _window_cost(lines, last_start, end) <= MAX_WINDOW_TOKENS:
            ranges[-1] = (last_start, end)
            continue
        # The cap can block a merge between two nearby hits, which leaves the new
        # radius window overlapping the previous one. Windows of one file must
        # never re-emit a line: in a fixed token budget a duplicated line is waste,
        # and the benchmark counts it as such. So the new window starts strictly
        # after the previous one; a hit already covered emits no window at all.
        trimmed = max(start, last_end + 1)
        if trimmed <= end:
            ranges.append((trimmed, end))
    return [window for span in ranges for window in _split_oversized(lines, *span)]


def _entry_candidates(
    path: str,
    symbols: list[dict],
    text: str,
    terms: list[str],
    content_re,
) -> list[Candidate]:
    """Score the fragments of one file, by what each fragment itself contains.

    Scoring the fragment rather than the file is what lets a prose file - whose
    every line can match - compete with a code file that has two matching lines
    and a name full of query words. A file-level score handed to every window let
    a hundred-hit file boost its own import block, and it made window size
    irrelevant to relevance.

    Content hits are counted per window and deliberately not capped, because
    ranking is ``score / token_cost``: a window that is larger *and* carries
    proportionally more matching lines must rank the same, not worse. What is
    capped is the file-level bonus, which every window would otherwise inherit
    unbounded.
    """
    term_set = set(terms)
    path_hits = [term for term in terms if term in path.lower()]
    symbol_hits = [
        symbol for symbol in symbols if identifier_parts(symbol["name"]) & term_set
    ]
    lines = text.splitlines()
    lowered_lines = [line.lower() for line in lines]
    content_hits = (
        [
            number for number, lowered in enumerate(lowered_lines, 1)
            if content_re.search(lowered)
        ]
        if content_re
        else []
    )
    if terms and not (path_hits or symbol_hits or content_hits):
        return []
    exact_hits = [item for item in symbol_hits if item["name"].lower() in term_set]
    word_hits = [item for item in symbol_hits if item["name"].lower() not in term_set]
    bonuses = (
        min(len(path_hits), MAX_BONUS_HITS) * PATH_HIT_WEIGHT
        + min(len(exact_hits), MAX_BONUS_HITS) * SYMBOL_EXACT_WEIGHT
        + min(len(word_hits), MAX_BONUS_HITS) * SYMBOL_WORD_WEIGHT
    )
    reasons = []
    if path_hits:
        reasons.append("path:" + ",".join(path_hits[:3]))
    if exact_hits:
        reasons.append("symbols:" + ",".join(item["name"] for item in exact_hits[:3]))
    if word_hits:
        reasons.append(
            "symbol_words:" + ",".join(item["name"] for item in word_hits[:3])
        )
    hit_lines = content_hits or [item["line"] for item in symbol_hits]
    scored = []
    for start, end in _windows(lines, hit_lines):
        window_hits = sum(1 for line in content_hits if start <= line <= end)
        scored.append((window_hits, start, end))
    # Emit the windows where the evidence is, not the ones that happen to sit
    # highest in the file: a file's best fragment is the one a caller would pick.
    # On equal evidence the cheaper window wins, which is the same trade the
    # budget selection makes one step later.
    scored.sort(key=lambda item: (item[0], item[1] - item[2]), reverse=True)
    chosen = scored[:MAX_WINDOWS]
    candidates = []
    for window_hits, start, end in sorted(chosen, key=lambda item: item[1]):
        label = f"text_hits:{window_hits}" if window_hits else f"symbol_lines:{len(hit_lines)}"
        candidates.append(
            Candidate(
                path,
                start,
                end,
                "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)),
                bonuses + window_hits * CONTENT_HIT_WEIGHT,
                [*reasons, label],
            )
        )
    return candidates


def get_project_context(
    task: str,
    project_root: str | Path,
    token_budget: int = 4000,
    refresh_index: bool = True,
) -> dict:
    """Build a token-budgeted context package for ``task``.

    ``refresh_index`` re-checks the stored index against the working tree and
    rebuilds it when the file set drifted (default). Pass ``False`` only when
    the caller just indexed or deliberately wants to skip the freshness walk.
    """
    if token_budget < 200:
        raise ValueError("token_budget must be at least 200")
    root = Path(project_root).resolve()
    index = load_index(root, refresh=refresh_index)
    terms = query_terms(task)
    # Only the number of matching lines is used, so one compiled alternation
    # scans a line in C instead of looping over every term in Python. This keeps
    # Chinese tasks cheap now that one prompt can yield dozens of n-grams.
    content_re = content_pattern(terms)
    candidates: list[Candidate] = []
    for entry in index["files"]:
        text = read_text(root / entry["path"])
        if text is None:
            continue
        candidates.extend(
            _entry_candidates(
                entry["path"], entry.get("symbols", []), text, terms, content_re
            )
        )

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
    index_status = {
        "version": index.get("version"),
        "indexed_at": index.get("indexed_at"),
        "indexed_files": len(index["files"]),
        "refreshed": bool(index.get("refreshed")),
        "stale_reason": index.get("stale_reason"),
    }
    notice = "Lexical V0.1 retrieval; verify critical symbols before editing."
    if index_status["refreshed"]:
        notice += f" Index refreshed automatically ({index_status['stale_reason']})."
    elif index_status["stale_reason"]:
        notice += (
            f" WARNING: index is stale ({index_status['stale_reason']}); "
            "results may miss files - re-run index_project."
        )
    return {
        "task": task,
        "project_root": str(root),
        "token_budget": token_budget,
        "estimated_tokens": used,
        "terms": terms,
        "fragments": selected,
        "memories": memories,
        "index": index_status,
        "notice": notice,
    }
