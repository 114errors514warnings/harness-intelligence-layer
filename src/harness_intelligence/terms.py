"""One definition of "what counts as a query term", shared by every matcher.

The index stores raw text and matching is by containment. That works for ASCII,
where identifiers and words are delimited, and fails for Chinese: a run such as
``重建索引之后`` never appears literally in the source or in the docs, so a
whole-run term matched nothing and a Chinese-only task recalled nothing at all.

Splitting a CJK run into overlapping n-grams fixes that without a dictionary:
``重建索引之后`` yields ``重建``, ``建索``, ``索引``, ``引之``, ``之后`` ... which
do occur in the indexed text. Single characters are deliberately excluded - one
character matches almost every Chinese line - so the shortest term is a bigram.

Both sides of a match belong here: :func:`extract_terms` describes the query side
and :func:`identifier_parts` the indexed symbol names, so code retrieval and
memory search cannot drift apart.

The module is dependency-free and deterministic: the same text always yields the
same terms in the same order, which is what the benchmark's reproducibility
depends on.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

#: ASCII identifiers/words (2+ characters) and CJK runs, matched in one pass.
TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u3400-\u9fff]+")

#: CJK n-gram lengths. Bigrams carry recall, trigrams carry precision.
CJK_NGRAM_SIZES = (2, 3)

#: Latency guard for the retrieval line scan. A pasted Chinese document would
#: otherwise produce thousands of terms, every one of them scanned against every
#: indexed line. Terms past the cap are dropped in emission order (ASCII first,
#: then CJK), deterministically. Set-based callers such as memory search pass
#: ``limit=None``: intersecting two sets is not a per-line scan, so a cap there
#: would only ever drop matches.
MAX_TERMS = 200

_CJK_START = "\u3400"
_CJK_END = "\u9fff"


def _is_cjk(run: str) -> bool:
    return _CJK_START <= run[0] <= _CJK_END


def _ngrams(run: str) -> list[str]:
    grams: list[str] = []
    for size in CJK_NGRAM_SIZES:
        if len(run) < size:
            continue
        grams.extend(run[index : index + size] for index in range(len(run) - size + 1))
    return grams


def extract_terms(text: str, limit: int | None = MAX_TERMS) -> list[str]:
    """Return the lowercased lookup terms of ``text``, deduplicated and capped.

    ASCII terms come first so the cap can only ever drop CJK n-grams, never an
    identifier the caller named explicitly.
    """
    ascii_terms: list[str] = []
    cjk_terms: list[str] = []
    for match in TERM_RE.finditer(text):
        run = match.group(0)
        if _is_cjk(run):
            cjk_terms.extend(_ngrams(run))
        else:
            ascii_terms.append(run)
    ordered = ascii_terms + cjk_terms
    unique = list(dict.fromkeys(term.lower() for term in ordered))
    return unique[:limit] if limit is not None else unique


def content_pattern(query_terms: Sequence[str]) -> re.Pattern[str] | None:
    """Compile ``query_terms`` into a single "does this line hit any term" regex.

    Only the number of matching lines is ever used, never which term matched, so
    one alternation scan in C replaces a Python loop of up to ``MAX_TERMS``
    containment tests per line. ``re.escape`` keeps matching literal, and the
    longest-first order makes the pattern deterministic.
    """
    unique = list(dict.fromkeys(term for term in query_terms if term))
    if not unique:
        return None
    ordered: Iterable[str] = sorted(unique, key=len, reverse=True)
    return re.compile("|".join(re.escape(term) for term in ordered))


#: Identifier word parts: snake_case separators and camelCase boundaries.
IDENTIFIER_PART_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def identifier_parts(name: str) -> set[str]:
    """Lowercased word parts of an identifier, plus the whole name.

    Symbol matching has to read an identifier the way a developer does. Plain
    substring matching let the term ``json`` match ``_write_jsonl`` and turned
    long descriptive test names into symbol hits, which inflated code and test
    fragments ahead of the docs that actually answer the question. Word parts keep
    ``token`` matching ``validate_token`` and ``TokenValidator`` while dropping
    those accidents; adding the whole lowercased name means a prompt that spells
    an identifier out (``file_state``) still matches exactly.
    """
    parts = {part.lower() for part in IDENTIFIER_PART_RE.findall(name)}
    parts.add(name.lower())
    return parts
