from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .embeddings import cosine, resolve_backend
from .glossary import expand_terms
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
#:
#: The path weight is deliberately small. A path is a weak signal once matching
#: is precise, and a flat per-window bonus is divided by the window's token cost,
#: so a heavy path weight let a *small* file that merely shares a path word
#: outrank the file that actually answers the question. Measured on the 26-task
#: corpus: heavy path/word bonuses cost ~15pp of `hinted` recall.
PATH_HIT_WEIGHT = 1.0
SYMBOL_EXACT_WEIGHT = 6.0
SYMBOL_WORD_WEIGHT = 0.5
CONTENT_HIT_WEIGHT = 1.5
MAX_BONUS_HITS = 3

#: Weight of a line matched only through the zh->en glossary (Phase 5 §7.1)
#: relative to a literal hit. Measured on the 50-task corpus: any positive value
#: cost `hinted` recall (98.5% -> 98.0% at 0.1-0.3, 97.5% at 0.4) because a
#: dictionary guess then competes with an identifier the caller actually wrote,
#: while buying only ~+3pp of `raw`. At 0.0 the glossary is purely a *recall*
#: device - it decides whether a file is reachable, never how far it outranks a
#: literal hit - which keeps the recommended calling style exactly unchanged.
EXPANSION_HIT_WEIGHT = 0.0

#: A path term shorter than this is too generic to match a path segment by
#: prefix: ``git`` would otherwise hit ``.github/`` and ``ai`` would hit
#: ``openai.yaml``, handing a flat bonus to files that have nothing to do with
#: the question. The length gate keeps ``token`` matching ``tokens.py``.
PATH_PREFIX_MIN = 4


def path_names(path: str) -> set[str]:
    """Word parts of every path segment, plus each filename stem.

    Substring matching used to decide path hits, so ``git`` matched ``.github``
    and ``ai`` matched ``openai``. Matching whole word parts removes those
    accidents without losing a file the caller actually named.
    """
    names: set[str] = set()
    for segment in path.lower().split("/"):
        if not segment:
            continue
        names.update(identifier_parts(segment))
        stem = segment.rsplit(".", 1)[0]
        if stem and stem != segment:
            names.update(identifier_parts(stem))
    return names


def matches_path(term: str, names: set[str]) -> bool:
    if term in names:
        return True
    return len(term) >= PATH_PREFIX_MIN and any(name.startswith(term) for name in names)


def split_terms(task: str) -> tuple[list[str], list[str]]:
    """``(primary, expansions)`` for a task.

    ``primary`` is what the caller literally wrote (``terms.extract_terms``);
    ``expansions`` is the English implied by its Chinese terms
    (``glossary.expand_terms``), de-duplicated against the primary terms.
    """
    primary = extract_terms(task)
    seen = set(primary)
    return primary, [term for term in expand_terms(primary) if term not in seen]


def query_terms(task: str) -> list[str]:
    """Terms a task is matched by: the caller's own, then the glossary bridge.

    Delegates to :func:`terms.extract_terms` so code retrieval and memory search
    cannot drift apart, and so a Chinese run is split into n-grams instead of
    becoming one unmatchable term. Then adds the English terms implied by the
    Chinese ones: a Chinese-only question otherwise shares no literal form with
    the English implementation files.

    The additions go *after* the original terms so an identifier the caller
    wrote explicitly keeps its place ahead of a dictionary guess.
    """
    primary, expansions = split_terms(task)
    return primary + expansions


#: A fragment is a focused slice of a file, not a chapter. Windows stop growing at
#: this many estimated tokens: a dense run of hits used to merge into a
#: multi-hundred-token monolith that spent most of a task's budget on one
#: fragment. Measured on the benchmark, one 688-token window in docs/roadmap.md
#: was the whole cause of that task's miss.
#:
#: Recall only asks whether a file appears in the package at all, not how much of
#: it does, so narrower windows mean more distinct files fit the same budget.
#: Lowering this from 220 to 60 measured +26pp `hinted` recall on the 26 tasks.
MAX_WINDOW_TOKENS = 60

#: At most this many windows per file. One file's best window is its best
#: evidence; spending three windows on one file buys coverage of fewer files,
#: which is exactly what a recall-oriented package must not do. Measured on the
#: 26 tasks: three windows cost ~5pp of `hinted` recall against one.
MAX_WINDOWS = 1

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
    expansion_re=None,
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
    names = path_names(path)
    path_hits = [term for term in terms if matches_path(term, names)]
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
    # Glossary expansions (Phase 5 §7.1) match English lines a Chinese-only
    # question could never reach. They are counted apart and weighted lower than
    # a literal hit, so a query that already names identifiers is not diluted.
    primary_set = set(content_hits)
    expansion_hits = (
        [
            number for number, lowered in enumerate(lowered_lines, 1)
            if expansion_re.search(lowered) and number not in primary_set
        ]
        if expansion_re and terms
        else []
    )
    if terms and not (path_hits or symbol_hits or content_hits or expansion_hits):
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
    # A symbol the query names outright is evidence in its own right, so its
    # definition line is always a window center - even for a file whose prose
    # matches heavily too. Before this, a file with many content hits emitted its
    # three densest windows and dropped the very line the caller asked about, so
    # naming ``DEFAULT_EXCLUDES`` still missed ``indexer.py``.
    symbol_lines = [item["line"] for item in symbol_hits]
    # Expansion lines only act as window *centers* when the file has no literal
    # hit: that keeps an identifier-rich query's window selection exactly as it
    # was, while a Chinese-only question can still discover a file it otherwise
    # could not reach. Expansion still contributes to the score either way.
    if content_hits:
        hit_lines = sorted(set(content_hits) | set(symbol_lines))
    elif expansion_hits:
        hit_lines = sorted(set(expansion_hits) | set(symbol_lines))
    else:
        hit_lines = symbol_lines
    exact_lines = {item["line"] for item in exact_hits}
    scored = []
    for start, end in _windows(lines, hit_lines):
        window_hits = sum(1 for line in content_hits if start <= line <= end)
        # A window that holds the line of an identifier the query named outright
        # (``DEFAULT_EXCLUDES``) is the window the caller asked for, even when a
        # different window of the same file is denser; covering more of the named
        # identifiers beats covering one. Emitting the densest window instead was
        # why the first Phase 3 run lost 5 tasks: the model got the file but not
        # the line that answers the question.
        named_hits = sum(1 for line in exact_lines if start <= line <= end)
        # Expansion hits count toward density but at EXPANSION_HIT_WEIGHT, so a
        # Chinese-only question can reach English lines without letting a
        # dictionary guess outrank a literal hit in an identifier-rich query.
        weighted_hits = window_hits + EXPANSION_HIT_WEIGHT * sum(
            1 for line in expansion_hits if start <= line <= end
        )
        scored.append((named_hits, weighted_hits, window_hits, start, end))
    # Emit the windows where the evidence is, not the ones that happen to sit
    # highest in the file: a named identifier outranks raw density, then density
    # decides, then the cheaper window on a tie.
    scored.sort(key=lambda item: (item[0], item[1], item[3] - item[4]), reverse=True)
    chosen = scored[:MAX_WINDOWS]
    candidates = []
    for named_hits, weighted_hits, window_hits, start, end in sorted(
        chosen, key=lambda item: item[3]
    ):
        if named_hits:
            label = f"named_symbol:{named_hits}"
        elif window_hits:
            label = f"text_hits:{window_hits}"
        elif expansion_hits:
            label = f"expanded_hits:{weighted_hits:.1f}"
        else:
            label = f"symbol_lines:{len(hit_lines)}"
        candidates.append(
            Candidate(
                path,
                start,
                end,
                "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)),
                bonuses + weighted_hits * CONTENT_HIT_WEIGHT,
                [*reasons, label],
            )
        )
    return candidates


#: Caps for the optional semantic re-rank (see ``docs/roadmap.md`` §6). Only the
#: strongest lexical candidates are embedded, so a large repository cannot turn
#: one query into hundreds of model calls: lexical order still decides who is
#: even eligible to be re-ordered.
RERANK_POOL = 40

#: Weight of the cosine signal against the normalised lexical score. The lexical
#: score stays the primary evidence; an embedding only re-orders the shortlist
#: that lexical retrieval already selected.
EMBEDDING_WEIGHT = 0.5


def _rerank(candidates: list[Candidate], task: str, backend) -> int:
    """Re-order the lexical shortlist by similarity to ``task``.

    Returns how many candidates were re-ordered. Raises only if the backend
    itself raises; the caller degrades to the lexical order in that case.
    """
    pool = candidates[:RERANK_POOL]
    if len(pool) < 2:
        return 0
    vectors = backend.embed([task, *(candidate.content for candidate in pool)])
    task_vector = vectors[0]
    lexical = [candidate.score / max(candidate.token_cost, 1) for candidate in pool]
    best = max(lexical) or 1.0
    blended = []
    for candidate, lexical_score, vector in zip(pool, lexical, vectors[1:]):
        similarity = cosine(task_vector, vector)
        weight = EMBEDDING_WEIGHT * similarity + (1.0 - EMBEDDING_WEIGHT) * (lexical_score / best)
        blended.append((weight, lexical_score, candidate))
    blended.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for weight, _, candidate in blended:
        candidate.reasons.append(f"embedding:{weight:.2f}")
    candidates[: len(pool)] = [candidate for _, _, candidate in blended]
    return len(pool)


def get_project_context(
    task: str,
    project_root: str | Path,
    token_budget: int = 4000,
    refresh_index: bool = True,
    embedding: str | None = None,
) -> dict:
    """Build a token-budgeted context package for ``task``.

    ``refresh_index`` re-checks the stored index against the working tree and
    rebuilds it when the file set drifted (default). Pass ``False`` only when
    the caller just indexed or deliberately wants to skip the freshness walk.

    ``embedding`` overrides the ``HIL_EMBEDDINGS`` environment variable for this
    call: ``off`` (default) keeps pure lexical retrieval, ``auto``/``on`` probe
    the optional backends, and ``hash`` selects the offline backend. A backend
    that is unavailable, or that raises mid-query, degrades to the lexical order
    instead of failing the call.
    """
    if token_budget < 200:
        raise ValueError("token_budget must be at least 200")
    root = Path(project_root).resolve()
    index = load_index(root, refresh=refresh_index)
    primary, expansions = split_terms(task)
    terms = primary + expansions
    # Only the number of matching lines is used, so one compiled alternation
    # scans a line in C instead of looping over every term in Python. This keeps
    # Chinese tasks cheap now that one prompt can yield dozens of n-grams.
    content_re = content_pattern(primary)
    expansion_re = content_pattern(expansions)
    candidates: list[Candidate] = []
    for entry in index["files"]:
        text = read_text(root / entry["path"])
        if text is None:
            continue
        candidates.extend(
            _entry_candidates(
                entry["path"],
                entry.get("symbols", []),
                text,
                terms,
                content_re,
                expansion_re,
            )
        )

    backend, embedding_reason = resolve_backend(embedding)
    candidates.sort(key=lambda item: (item.score / max(item.token_cost, 1), item.score), reverse=True)
    retrieval = {
        "mode": "lexical",
        "backend": None,
        "detail": embedding_reason,
        "reranked": 0,
    }
    if backend is not None:
        try:
            reranked = _rerank(candidates, task, backend)
        except Exception as exc:  # noqa: BLE001 - a backend failure must degrade, not raise
            retrieval["detail"] = f"{embedding_reason}; re-rank failed ({exc.__class__.__name__})"
        else:
            if reranked:
                retrieval.update(mode="embedding", backend=backend.name, reranked=reranked)

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
    if retrieval["mode"] == "embedding":
        notice = (
            f"Re-ranked by the {retrieval['backend']} backend; verify critical symbols "
            "before editing."
        )
    # Roadmap §5 asks for an explicit fallback when HIL recall is insufficient:
    # a harness must be able to tell "nothing matched" from "the package is
    # small", instead of treating an empty package as an answer.
    sufficient = bool(selected)
    fallback = None
    if not sufficient:
        fallback = (
            "no indexed fragment matched the query terms; use the harness's native "
            "search rather than treating this empty package as an answer"
        )
        notice += " WARNING: no fragment matched - fall back to native search."
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
        "retrieval": retrieval,
        "sufficient": sufficient,
        "fallback": fallback,
        "notice": notice,
    }
