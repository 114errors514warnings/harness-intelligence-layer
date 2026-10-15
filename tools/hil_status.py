#!/usr/bin/env python3
"""Write a short HIL status report into each local project's ``.hil/``.

This is an operator tool, not part of the four-tool MCP surface. It walks a set of
roots, finds project directories that contain a ``.hil/`` directory, inspects each
index and memory store, runs a read-only connectivity probe, and writes
``<project>/.hil/hil-status.md``.

Rules it follows:

* **Read-only on the project.** The probe does not refresh the index, so a status
  check never rebuilds someone's tree; staleness is *reported* instead. The only
  file written is the report itself, and ``.hil/`` is already excluded from the
  index by both discovery paths.
* **No secrets, no transcripts.** The report contains counts, timestamps and a
  probe result - never memory contents.
* **Comparable across projects.** Every project gets the same fixed probe query, so
  the reports can be read side by side.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness_intelligence import __version__ as HIL_VERSION  # noqa: E402
from harness_intelligence.indexer import (  # noqa: E402
    INDEX_VERSION,
    load_index,
    staleness_reason,
)
from harness_intelligence.retrieval import get_project_context  # noqa: E402

#: One fixed probe so reports are comparable. ASCII identifiers make it reachable in
#: an English-only project; the CJK terms reach Chinese docs. It is a *connectivity*
#: check ("does the pipeline answer at all"), never a recall measurement.
PROBE = "项目结构 入口 配置 index config entry"
PROBE_BUDGET = 1200

REPORT_NAME = "hil-status.md"
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build",
    "__pycache__", ".archify", ".tox", ".mypy_cache", ".pytest_cache",
}


def find_projects(roots: list[Path], max_depth: int, exclude_temp: bool = True) -> list[Path]:
    """Project directories under ``roots`` that already contain ``.hil``.

    ``exclude_temp`` skips anything under the OS temp directory: those are scratch
    trees from tests and A/B runs, not projects anyone maintains.
    """
    temp_root = Path(tempfile.gettempdir()).resolve()
    found: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            continue
        for current, dirs, _files in os.walk(root):
            here = Path(current)
            depth = len(here.relative_to(root).parts)
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            if depth >= max_depth:
                dirs[:] = []
            if (here / ".hil").is_dir():
                if not exclude_temp:
                    found.add(here)
                else:
                    try:
                        here.resolve().relative_to(temp_root)
                    except ValueError:
                        found.add(here)
                dirs[:] = []  # do not descend into a project looking for nested ones
    return sorted(found, key=lambda path: str(path).lower())


def memory_summary(root: Path) -> dict:
    store = root / ".ai-memory"
    facts: list[Path] = []
    if store.is_dir():
        facts = sorted(store.glob("*/*.json"))
    by_category: dict[str, int] = {}
    newest = ""
    for path in facts:
        by_category[path.parent.name] = by_category.get(path.parent.name, 0) + 1
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        newest = max(newest, stamp)
    return {"total": len(facts), "by_category": by_category, "newest": newest}


def age_text(stamp: str) -> str:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return "未知"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 90:
        return f"{int(seconds)} 秒前"
    if seconds < 5400:
        return f"{int(seconds / 60)} 分钟前"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} 小时前"
    return f"{seconds / 86400:.1f} 天前"


def inspect(root: Path) -> dict:
    """Collect the report facts for one project (read-only)."""
    project = root.resolve()
    index_path = project / ".hil" / "index.json"
    facts: dict = {
        "project": str(project),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hil_version": HIL_VERSION,
        "index_schema": INDEX_VERSION,
        "indexed": False,
        "issues": [],
    }
    if not index_path.exists():
        facts["issues"].append("只有 `.hil/` 目录、没有 `index.json`：本项目尚未建立索引。")
        return facts

    payload = load_index(project, refresh=False)
    entries = payload.get("files", [])
    facts["indexed"] = True
    facts["indexed_at"] = payload.get("indexed_at", "")
    facts["index_age"] = age_text(payload.get("indexed_at", ""))
    facts["files"] = len(entries)
    facts["symbols"] = sum(len(entry.get("symbols", [])) for entry in entries)
    facts["schema"] = payload.get("version")
    reason = staleness_reason(project, payload)
    facts["fresh"] = reason is None
    facts["stale_reason"] = reason or ""
    if reason:
        facts["issues"].append(
            f"索引与工作树不一致（{reason}）：下次检索会自动重建，或手动调用 `index_project`。"
        )
    if not entries:
        facts["issues"].append("索引存在但没有任何文件：项目里可能没有可索引的文本文件。")
    if facts.get("schema") != INDEX_VERSION:
        facts["issues"].append(
            f"索引 schema 为 {facts.get('schema')}、当前为 {INDEX_VERSION}：重建后才会用新符号规则。"
        )

    facts["memory"] = memory_summary(project)

    try:
        result = get_project_context(PROBE, project, PROBE_BUDGET, refresh_index=False)
    except Exception as exc:  # noqa: BLE001 - a broken project must still get a report
        facts["probe_error"] = f"{exc.__class__.__name__}: {exc}"
        facts["issues"].append(f"检索探针抛错（{exc.__class__.__name__}）：{exc}")
        return facts
    facts["probe_fragments"] = len(result.get("fragments", []))
    facts["probe_tokens"] = result.get("estimated_tokens", 0)
    facts["probe_memories"] = len(result.get("memories", []))
    facts["probe_sufficient"] = bool(result.get("sufficient"))
    facts["probe_confidence"] = result.get("confidence")
    facts["probe_mode"] = (result.get("retrieval") or {}).get("mode")
    if not facts["probe_sufficient"]:
        facts["issues"].append(
            "检索探针返回空包（`sufficient: false`）：调用方应回退原生搜索，而不是当成"
            "\"项目里没有相关内容\"。"
        )
    facts["memory_dir_env"] = os.environ.get("HIL_MEMORY_DIR", "")
    facts["embedding_env"] = os.environ.get("HIL_EMBEDDINGS", "off")
    return facts


def render(facts: dict) -> str:
    lines: list[str] = []
    lines.append("# HIL 运行状态报告")
    lines.append("")
    lines.append(f"- 生成时间：{facts['generated_at']}")
    lines.append(f"- 项目：`{facts['project']}`")
    lines.append(f"- HIL 版本：{facts['hil_version']}（索引 schema {facts['index_schema']}）")
    lines.append("")
    lines.append("## 索引")
    if not facts["indexed"]:
        lines.append("- 尚未建立索引。")
        lines.append("")
        lines.append("## 问题")
        for item in facts["issues"]:
            lines.append(f"- {item}")
        lines.append("")
        return "\n".join(lines)
    freshness = "与工作树一致" if facts["fresh"] else f"已漂移（{facts['stale_reason']}）"
    lines.append(f"- 索引时间：{facts['indexed_at']}（{facts['index_age']}）")
    lines.append(f"- 文件：{facts['files']} 个 | 符号：{facts['symbols']} 个")
    lines.append(f"- 新鲜度：{freshness}")
    lines.append("")
    memory = facts["memory"]
    lines.append("## 工程记忆")
    if memory["total"]:
        detail = "、".join(f"{name} {count}" for name, count in sorted(memory["by_category"].items()))
        lines.append(f"- 事实：{memory['total']} 条（{detail}）")
        lines.append(f"- 最近更新：{memory['newest']}（{age_text(memory['newest'])}）")
    else:
        lines.append("- 暂无事实（`.ai-memory/` 为空或不存在）。")
    lines.append("")
    lines.append("## 检索连通性自检（只读，不刷新索引）")
    if facts.get("probe_error"):
        lines.append(f"- 探针抛错：{facts['probe_error']}")
    else:
        lines.append(f"- 探针查询：`{PROBE}`（固定不变，便于横向比较；**不是**召回率）")
        lines.append(
            f"- 结果：片段 {facts['probe_fragments']} 个 / 约 {facts['probe_tokens']} token / "
            f"记忆 {facts['probe_memories']} 条 / confidence={facts['probe_confidence']} / "
            f"模式={facts['probe_mode']}"
        )
    lines.append("")
    lines.append("## 配置")
    lines.append(f"- 记忆库读取：`HIL_MEMORY_DIR` = {facts['memory_dir_env'] or '（未设置，读项目自身 .ai-memory）'}")
    lines.append(f"- 语义重排：`HIL_EMBEDDINGS` = {facts['embedding_env'] or 'off'}")
    lines.append("")
    lines.append("## 结论")
    if facts["issues"]:
        for item in facts["issues"]:
            lines.append(f"- ⚠️ {item}")
    else:
        lines.append("- ✅ 索引可用、与工作树一致，检索探针正常返回。")
    lines.append("")
    lines.append(
        "> 说明：本报告由 `HIL/tools/hil_status.py` 生成，只读检查、不修改索引；"
        "不含记忆正文。召回口径与门槛见 `HIL/docs/final-report.md`。"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    # The Windows console is often GBK; the report carries CJK and a few marks, so
    # print through UTF-8 rather than crashing on an unencodable character.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Write HIL status reports into local projects")
    default_roots = os.environ.get("HIL_STATUS_ROOTS", "")
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="root to scan; repeatable (default: the repository's grandparent, "
        "or HIL_STATUS_ROOTS separated by the platform path separator)",
    )
    parser.add_argument("--max-depth", type=int, default=4, help="directory depth to scan")
    parser.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    roots = [Path(item) for item in args.root]
    if not roots:
        roots = [Path(item) for item in default_roots.split(os.pathsep) if item]
    if not roots:
        roots = [REPO_ROOT.parent.parent]
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        print("no usable root to scan")
        return 2

    projects = find_projects(roots, args.max_depth)
    print(f"scanning: {', '.join(str(root) for root in roots)}")
    print(f"projects with .hil: {len(projects)}")
    rows = []
    for project in projects:
        facts = inspect(project)
        text = render(facts)
        status = "OK" if not facts["issues"] else f"{len(facts['issues'])} issue(s)"
        if facts["indexed"]:
            rows.append(
                (str(project), facts["files"], facts["symbols"], facts["memory"]["total"], status)
            )
        else:
            rows.append((str(project), 0, 0, facts["memory"]["total"], status))
        if args.dry_run:
            print("-" * 60)
            print(text)
        else:
            target = project / ".hil" / REPORT_NAME
            target.write_text(text, encoding="utf-8")
            print(f"wrote {target}  [{status}]")

    print()
    print(f"{'project':<52} {'files':>6} {'symbols':>8} {'facts':>6}  status")
    for path, files, symbols, facts_count, status in rows:
        print(f"{path:<52} {files:>6} {symbols:>8} {facts_count:>6}  {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
