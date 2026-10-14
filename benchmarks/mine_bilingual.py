#!/usr/bin/env python3
"""Mine a zh -> en dictionary from the repository's own Chinese/English text.

``docs/roadmap.md`` §7.2. §7.1 is a hand-written table: precise but tiny. This
script statistically proposes more pairs from the corpus itself, for a human to
review and prune. A wrong mapping is worse than none, so the output is a
*reviewable data file*, never an unreviewable black box.

Rules that keep it honest:

* **Same corpus as the index.** Files are discovered with the indexer's own path
  (``discover_files`` + ``read_text``), so mined pairs come from what the
  retriever actually sees, not from files it never reads.
* **Same Chinese terms as the query.** The CJK side reuses ``terms.extract_terms``
  (the 2/3-char n-grams a query emits), so every mined key is reachable at query
  time. The English side is ``identifier_parts`` -- the word parts path and symbol
  matching actually use.
* **No paths.** A key or value is never a repository path (same rule as
  ``hints.jsonl``): writing the answer file would measure the annotation instead
  of the retrieval.
* **Holdout.** ``--holdout`` excludes the files the named tasks depend on, so the
  table can be validated on tasks whose evidence it never saw.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_intelligence.glossary import GLOSSARY  # noqa: E402
from harness_intelligence.indexer import discover_files, read_text  # noqa: E402
from harness_intelligence.terms import TERM_RE, extract_terms, identifier_parts  # noqa: E402

#: Co-occurrence thresholds. They are tuned on the training tasks only; the
#: holdout exists so a threshold that merely memorises this repo is visible.
MIN_COUNT = 3
MIN_RATIO = 0.30
MAX_EN_PER_ZH = 5
MAX_ENTRIES = 300
MAX_EXAMPLES = 2

#: How close an English token must sit to a Chinese n-gram to count. This is the
#: single most important precision lever: a Chinese doc mentions project jargon
#: (``hil``, ``phase``, ``raw``) all over, and counting a whole line's co-occurrence
#: paired 文件 with ``hil``. Proximity keeps 版本-schema and 目录-DEFAULT_EXCLUDES
#: while dropping distant accidents.
PROXIMITY = 10

#: Words too generic to be useful bridges: they would match many files at once and
#: hand a flat bonus to all of them. The set includes this repo's own jargon, which
#: co-occurs with every topic in the docs but is not a translation of anything.
JARGON = {
    "hil", "harness", "harnesses", "phase", "raw", "hinted", "docs", "roadmap",
    "benchmarks", "baseline", "verify", "recall", "mcp", "project", "jsonl",
    "openclaw", "cline", "codex", "results", "write", "auto", "hash", "readme",
}
STOPLIST = JARGON | {
    "code", "file", "files", "data", "line", "lines", "name", "names", "value",
    "values", "use", "used", "test", "tests", "self", "return", "true", "false",
    "none", "def", "class", "import", "from", "the", "and", "for", "not", "with",
    "json", "string", "list", "dict", "int", "str",
}


def _is_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _cjk_terms(text: str) -> set[str]:
    return {token for token in extract_terms(text, limit=None) if _is_cjk(token)}


def _line_pairs(line: str) -> tuple[set[str], set[tuple[str, str]]]:
    """``(all cjk n-grams on the line, nearby (zh, en) pairs)``.

    A pair counts only when the English token sits within ``PROXIMITY`` characters
    of the Chinese n-gram, so a line that merely mentions both topics does not
    invent a translation.
    """
    zh_all = _cjk_terms(line)
    pairs: set[tuple[str, str]] = set()
    for match in TERM_RE.finditer(line):
        token = match.group(0)
        if _is_cjk(token):
            continue
        start, end = match.span()
        window = line[max(0, start - PROXIMITY): min(len(line), end + PROXIMITY)]
        nearby = _cjk_terms(window)
        if not nearby:
            continue
        for en in identifier_parts(token):
            if len(en) < 3 or en in STOPLIST:
                continue
            for zh in nearby:
                pairs.add((zh, en))
    return zh_all, pairs


def holdout_paths(root: Path, task_ids: list[str]) -> set[str]:
    """Files the held-out tasks depend on, excluded from the mining corpus."""
    if not task_ids:
        return set()
    wanted = set(task_ids)
    tasks_path = root / "benchmarks" / "tasks.jsonl"
    paths: set[str] = set()
    try:
        lines = tasks_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        task = json.loads(line)
        if task.get("id") in wanted:
            paths.update(task.get("required_files", []))
    return paths


def mine(root: Path, excluded: set[str]) -> list[dict]:
    pair: Counter[tuple[str, str]] = Counter()
    zh_total: Counter[str] = Counter()
    examples: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in discover_files(root):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if relative in excluded:
            continue
        text = read_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            zh_all, pairs = _line_pairs(line)
            if not zh_all:
                continue
            for zh in zh_all:
                zh_total[zh] += 1
            for zh, en in pairs:
                pair[(zh, en)] += 1
                bucket = examples[(zh, en)]
                if len(bucket) < MAX_EXAMPLES:
                    bucket.append(
                        {"path": relative, "line": number, "text": line.strip()[:160]}
                    )
    per_zh: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for (zh, en), count in pair.items():
        ratio = count / zh_total[zh]
        if count < MIN_COUNT or ratio < MIN_RATIO:
            continue
        if en in GLOSSARY.get(zh, ()):  # already covered by the hand table
            continue
        per_zh[zh].append((en, count, ratio))
    rows: list[dict] = []
    for zh in sorted(per_zh):
        ranked = sorted(per_zh[zh], key=lambda item: (-item[1], item[0]))[:MAX_EN_PER_ZH]
        for en, count, ratio in ranked:
            rows.append(
                {
                    "zh": zh,
                    "en": en,
                    "count": count,
                    "ratio": round(ratio, 3),
                    "examples": examples[(zh, en)],
                }
            )
    rows.sort(key=lambda row: (-row["count"], row["zh"], row["en"]))
    return rows[:MAX_ENTRIES]


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine a zh->en glossary from bilingual lines")
    parser.add_argument("--root", default=".", help="repository root to mine")
    parser.add_argument(
        "--out",
        default="src/harness_intelligence/glossary_auto.json",
        help="where to write the reviewable data file",
    )
    parser.add_argument(
        "--holdout",
        default="",
        help="comma-separated task ids whose required files are kept out of the corpus",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    excluded = holdout_paths(root, [item.strip() for item in args.holdout.split(",") if item.strip()])
    rows = mine(root, excluded)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mined {len(rows)} pairs from {root}")
    if excluded:
        print(f"holdout excluded {len(excluded)} files")
    print(f"written: {out}")
    for row in rows[:10]:
        print(f"  {row['zh']} -> {row['en']} (count {row['count']}, ratio {row['ratio']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
