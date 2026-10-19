#!/usr/bin/env python3
"""Render a single-file HTML dashboard for the HIL projects on this machine.

Two kinds of data, clearly separated:

* **Snapshot** (from ``hil_status``): index age/size, symbol count, memory facts,
  freshness — the state of each project right now.
* **Usage** (from ``harness_intelligence.metrics``): how often the retrieval tool
  was actually called, latency, package size, fallback and confidence rates. These
  come from ``<project>/.hil/metrics.jsonl`` and contain **no query text**.

The output is one self-contained HTML file (inline CSS, no JS, no external assets) so
it opens anywhere and can be previewed in the app. It is written under ``.hil/``,
which is excluded from indexing.
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import hil_status  # noqa: E402
from harness_intelligence import __version__ as HIL_VERSION  # noqa: E402
from harness_intelligence import metrics  # noqa: E402

WINDOW_DAYS = 7
CHART_DAYS = 14


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def recent(rows: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = []
    for row in rows:
        try:
            moment = datetime.fromisoformat(row.get("t", ""))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment >= cutoff:
            kept.append(row)
    return kept


def summarise_usage(rows: list[dict]) -> dict:
    if not rows:
        return {"calls": 0}
    latencies = [float(row.get("latency_ms") or 0) for row in rows]
    tokens = [float(row.get("tokens") or 0) for row in rows]
    calls = len(rows)
    return {
        "calls": calls,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "tokens": sum(tokens) / calls,
        "fallback": 100 * sum(1 for row in rows if not row.get("sufficient")) / calls,
        "low_confidence": 100 * sum(1 for row in rows if row.get("confidence") == "low") / calls,
        "embedding": 100 * sum(1 for row in rows if row.get("mode") == "embedding") / calls,
    }


def daily_counts(rows: list[dict], days: int) -> list[tuple[str, int]]:
    today = datetime.now(timezone.utc).date()
    buckets = {today - timedelta(days=offset): 0 for offset in range(days - 1, -1, -1)}
    for row in rows:
        try:
            day = datetime.fromisoformat(row.get("t", "")).date()
        except ValueError:
            continue
        if day in buckets:
            buckets[day] += 1
    return [(day.isoformat(), count) for day, count in sorted(buckets.items())]


def bars(values: list[int], width: int = 420, height: int = 64) -> str:
    """Tiny inline SVG bar chart (no JS, no external assets)."""
    if not values:
        return ""
    peak = max(values) or 1
    count = len(values)
    gap = 3
    bar_width = max(2, (width - gap * (count - 1)) / count)
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for index, value in enumerate(values):
        bar_height = 0 if value == 0 else max(2, height * value / peak)
        x = index * (bar_width + gap)
        y = height - bar_height
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" rx="1.5"></rect>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render(projects: list[dict], roots: list[Path], window: int) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total_calls = sum(item["usage"].get("calls", 0) for item in projects)
    all_latencies = [item["usage"]["p50"] for item in projects if item["usage"].get("calls")]
    all_fallback = [item["usage"]["fallback"] for item in projects if item["usage"].get("calls")]
    total_facts = sum(item["facts"]["memory"]["total"] for item in projects)
    total_files = sum(item["facts"].get("files", 0) for item in projects)
    agg_daily = daily_counts([row for item in projects for row in item["recent_rows"]], CHART_DAYS)

    cells = []
    for item in projects:
        facts = item["facts"]
        usage = item["usage"]
        freshness = "✅ 一致" if facts.get("fresh") else "⚠️ 漂移"
        if not facts.get("indexed"):
            freshness = "✗ 未索引"
        calls = usage.get("calls", 0)
        usage_cell = (
            f"{calls} / 7d"
            if calls
            else '<span class="muted">无调用</span>'
        )
        latency = f"{usage['p50']:.0f} / {usage['p95']:.0f} ms" if calls else '<span class="muted">—</span>'
        tokens = f"{usage['tokens']:.0f}" if calls else '<span class="muted">—</span>'
        fallback = f"{usage['fallback']:.0f}%" if calls else '<span class="muted">—</span>'
        lowconf = f"{usage['low_confidence']:.0f}%" if calls else '<span class="muted">—</span>'
        embedding = f"{usage['embedding']:.0f}%" if calls else '<span class="muted">—</span>'
        issues = len(facts.get("issues") or [])
        cells.append(
            "<tr>"
            f'<td><div class="name">{html.escape(Path(facts["project"]).name)}</div>'
            f'<div class="path">{html.escape(facts["project"])}</div></td>'
            f"<td>{facts.get('files', 0)}</td>"
            f"<td>{facts.get('symbols', 0)}</td>"
            f"<td>{facts['memory']['total']}</td>"
            f"<td>{freshness}</td>"
            f"<td>{usage_cell}</td>"
            f"<td>{latency}</td>"
            f"<td>{tokens}</td>"
            f"<td>{fallback}</td>"
            f"<td>{lowconf}</td>"
            f"<td>{embedding}</td>"
            f'<td class="{"warn" if issues else "ok"}">{issues if issues else "—"}</td>'
            "</tr>"
        )

    daily_values = [count for _day, count in agg_daily]
    chart_labels = f"{agg_daily[0][0]} → {agg_daily[-1][0]}" if agg_daily else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HIL Dashboard</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #0f1115; --panel: #171a21; --line: #262b36; --text: #e6e9ef;
    --muted: #8b93a3; --accent: #6aa9ff; --ok: #4cc38a; --warn: #e5b567;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg: #f6f7f9; --panel: #ffffff; --line: #e3e6ec; --text: #1b1f27;
             --muted: #6b7280; --accent: #2563eb; --ok: #15803d; --warn: #b45309; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 28px; background: var(--bg); color: var(--text);
         font: 14px/1.5 ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 22px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px; margin-bottom: 22px; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
           padding: 14px 16px; }}
  .card .k {{ color: var(--muted); font-size: 12px; }}
  .card .v {{ font-size: 22px; font-weight: 650; margin-top: 2px; }}
  .card .v small {{ font-size: 12px; font-weight: 400; color: var(--muted); }}
  .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
            padding: 14px 16px; margin-bottom: 22px; overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
            white-space: nowrap; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 12px; }}
  tr:last-child td {{ border-bottom: none; }}
  .name {{ font-weight: 600; }}
  .path {{ color: var(--muted); font-size: 11px; }}
  .muted {{ color: var(--muted); }}
  .ok {{ color: var(--ok); }}
  .warn {{ color: var(--warn); font-weight: 600; }}
  .chart rect {{ fill: var(--accent); opacity: .85; }}
  .chart {{ width: 100%; max-width: 520px; height: 64px; display: block; margin-top: 10px; }}
  .foot {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
  code {{ background: color-mix(in srgb, var(--line) 55%, transparent);
          padding: 1px 5px; border-radius: 4px; }}
</style>
<body>
  <h1>HIL Dashboard</h1>
  <div class="sub">
    生成于 {html.escape(now)} · HIL {html.escape(HIL_VERSION)} ·
    扫描 {html.escape(", ".join(str(root) for root in roots))}
  </div>

  <div class="cards">
    <div class="card"><div class="k">项目</div><div class="v">{len(projects)}</div></div>
    <div class="card"><div class="k">索引文件 / 符号</div>
      <div class="v">{total_files}<small> 文件</small></div></div>
    <div class="card"><div class="k">工程记忆</div><div class="v">{total_facts}<small> 条</small></div></div>
    <div class="card"><div class="k">近 {window} 天调用</div><div class="v">{total_calls}</div></div>
    <div class="card"><div class="k">中位检索延迟（各项目中位的中位）</div>
      <div class="v">{percentile(all_latencies, 50):.0f}<small> ms</small></div></div>
    <div class="card"><div class="k">平均回退率（近 {window} 天）</div>
      <div class="v">{sum(all_fallback) / len(all_fallback) if all_fallback else 0:.0f}<small> %</small></div></div>
  </div>

  <div class="panel">
    <div class="k" style="color: var(--muted); font-size: 12px;">
      近 {CHART_DAYS} 天调用次数（全部项目合计，{html.escape(chart_labels)}）
    </div>
    {bars(daily_values)}
  </div>

  <div class="panel">
    <table>
      <thead><tr>
        <th>项目</th><th>文件</th><th>符号</th><th>记忆</th><th>新鲜度</th>
        <th>调用</th><th>p50 / p95</th><th>平均 token</th>
        <th>回退率</th><th>low-conf</th><th>语义占比</th><th>问题</th>
      </tr></thead>
      <tbody>
        {''.join(cells) if cells else '<tr><td colspan="12" class="muted">没有找到含 .hil/ 的项目</td></tr>'}
      </tbody>
    </table>
    <div class="foot">
      「调用」只统计 <code>get_project_context</code> 的真实调用；基准脚本会设置
      <code>HIL_METRICS=off</code>，因此不会混入。指标不含查询文本、文件内容或记忆正文。
    </div>
  </div>

  <div class="foot">
    数据来源：各项目 <code>.hil/index.json</code>、<code>.ai-memory/</code>、
    <code>.hil/metrics.jsonl</code>。由 <code>tools/hil_dashboard.py</code> 生成，只读扫描。
  </div>
</body>
</html>
"""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Render an HTML dashboard for local HIL projects")
    parser.add_argument("--root", action="append", default=[], help="root to scan; repeatable")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--window", type=int, default=WINDOW_DAYS, help="usage window in days")
    parser.add_argument("--out", default=str(REPO_ROOT / ".hil" / "dashboard.html"))
    args = parser.parse_args()

    roots = [Path(item) for item in args.root]
    if not roots:
        configured = os.environ.get("HIL_STATUS_ROOTS", "")
        roots = [Path(item) for item in configured.split(os.pathsep) if item]
    if not roots:
        roots = [REPO_ROOT.parent.parent]
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        print("no usable root to scan")
        return 2

    projects = []
    for project in hil_status.find_projects(roots, args.max_depth):
        facts = hil_status.inspect(project)
        rows = metrics.load(project)
        window_rows = recent(rows, args.window)
        projects.append(
            {
                "facts": facts,
                "usage": summarise_usage(window_rows),
                "recent_rows": window_rows,
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(projects, roots, args.window), encoding="utf-8")
    print(f"projects: {len(projects)}")
    for item in projects:
        usage = item["usage"]
        print(
            f"  {item['facts']['project']}  calls(7d)={usage.get('calls', 0)}  "
            f"p50={usage.get('p50', 0):.0f}ms"
        )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
