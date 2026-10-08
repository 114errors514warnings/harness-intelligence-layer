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

#: Query-side bridge for the Chinese-question/English-source gap.
#:
#: N-gram splitting makes a Chinese prompt match Chinese text, but the code that
#: answers it is written in English: the run "索引陈旧检测" becomes 索引/陈旧/... and
#: never overlaps ``indexer.py`` or ``staleness_reason``. Measured on the Phase 0
#: task set, that is the single largest remaining recall gap (lexical retrieval
#: cannot bridge two languages by word overlap alone).
#:
#: This is deliberately a *query* expansion, never a document one. Documents stay
#: matched literally, so a Chinese query gains English lookups while no indexed
#: file is silently rewritten - the small, reviewable list below is the entire
#: cross-language behaviour. Keys are the Chinese phrases a developer writes;
#: values are the English words the code actually uses. Keep both discriminative:
#: a value that occurs in nearly every file (return, file, call) buys noise, not
#: recall, and is spent against the same token budget.
GLOSSARY: dict[str, tuple[str, ...]] = {
    "索引": ("index",),
    "重建": ("rebuild",),
    "记忆": ("memory",),
    "检索": ("search", "retrieval"),
    "搜索": ("search",),
    "查询": ("query",),
    "符号": ("symbol",),
    "提取": ("extract",),
    "排除": ("exclude",),
    "目录": ("directory",),
    "文档": ("docs", "document"),
    "配置": ("config",),
    "字段": ("field",),
    "分类": ("category",),
    "校验": ("validate",),
    "评分": ("score",),
    "打分": ("score",),
    "陈旧": ("stale",),
    "过期": ("stale",),
    "版本": ("version",),
    "升级": ("upgrade",),
    "预算": ("budget",),
    "片段": ("fragment",),
    "工具": ("tool",),
    "函数": ("function",),
    "注册": ("register",),
    "服务": ("server",),
    "入口": ("entry",),
    "指纹": ("fingerprint",),
    "元数据": ("metadata",),
    "检测": ("detect",),
    "依赖": ("depend",),
    "声明": ("declare",),
    "模式": ("pattern",),
    "语言": ("language",),
    "门槛": ("threshold",),
    "阈值": ("threshold",),
    "实验": ("experiment",),
    "对比": ("compare",),
    "阶段": ("phase",),
    "边界": ("boundary",),
    "根因": ("cause",),
}

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


def bridged_terms(text: str) -> list[str]:
    """English lookups a Chinese prompt should also be matched against.

    Only the query side calls this: the glossary turns the Chinese a developer
    writes into the English identifiers the code uses, so a Chinese-only task can
    reach ``indexer.py`` without the caller spelling ``index``. It is not applied
    to the indexed text, which keeps document matching literal and keeps the
    bridge a single reviewable list (see :data:`GLOSSARY`).
    """
    found: list[str] = []
    for phrase, english in GLOSSARY.items():
        if phrase in text:
            found.extend(english)
    return list(dict.fromkeys(found))


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
