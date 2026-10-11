# Harness Intelligence Layer

面向 OpenClaw、Cline、Codex 等 Harness 的共享项目智能层。它不替代 Agent Loop、Shell、文件编辑或会话管理，只提供可复用的项目上下文与工程记忆。

## 评估结论

原方案可以提升 token 使用效率，但需要缩小第一阶段范围：

- **值得做**：跨 Harness 共享的代码检索、符号级片段、工程事实与固定 token 预算打包。目前这些信息通常由每个 Harness 重复搜索、重复解释。
- **不应重复做**：OpenClaw 已有上下文引擎、压缩、裁剪和记忆检索；Cline 已有自动压缩、任务交接和子代理研究。V0.1 不再实现通用会话压缩或 Harness 内部记忆。
- **Embedding 延后**：先以 `ripgrep + 符号提取 + Git + 词法排序` 建立可测基线。只有当 Context Recall 不达标时，才引入向量模型和数据库。
- **优化不是无条件成立**：小仓库、明确单文件任务可能因额外工具调用而增加 token。默认仅在跨文件任务、陌生仓库或重复任务中使用。

参见 [项目总览](docs/overview.md)、[项目计划](docs/roadmap.md)和[使用说明](docs/usage.md)。

## 当前 V0.1

已提供四个 MCP 工具，接口保持精简：

- `index_project(project_root)`
- `get_project_context(task, project_root, token_budget)`
- `search_project_memory(query, project_root, limit)`
- `record_project_memory(category, title, content, project_root, tags)`

索引保存在 `.hil/index.json`，可共享事实保存在 `.ai-memory/<category>/*.json`。两者都在项目目录内，不依赖某个 Harness 的私有会话数据库。

索引范围由项目自己决定：仓库根的 `.hilignore` 每行写一条规则（例如 `benchmarks/results/`），匹配的文件不会被索引。评测产物、生成报告这类派生文件据此留在索引之外——实测把它们纳入索引会挤掉源码片段：一个 6 KB 的基线文件就吃掉 1.9 个百分点召回。

索引会自愈：`.hil/index.json` 带有 schema 版本和文件集指纹（相对路径 + 大小 + mtime），每次检索前会与工作树比对，版本或文件集不匹配时自动重建，并在 `get_project_context` 返回的 `index` 字段里说明是否发生了重建、原因是什么。因此"索引陈旧导致静默漏召回"不再是默认行为，陈旧只会在显式跳过检查时才会出现，并会在 `notice` 中明确告警。

## 快速开始

HIL 是 `dependency-light` 项目，官方依赖只有 `mcp`。**推荐路径不需要安装**，直接在仓库根目录运行：

```powershell
Set-Location -LiteralPath "D:\MY\My Projects\HarnessIntelligenceLayer"
$env:PYTHONPATH = "src"

python -m harness_intelligence.cli index .
python -m harness_intelligence.cli context "定位索引重建逻辑" . --budget 3000
python run_hil_mcp.py   # MCP stdio 服务端，由 Harness 拉起
```

`pip install -e .` 是可选路径，只有在需要 `hil` / `hil-mcp` 两个命令时才使用；它需要可用的构建后端（`hatchling`）和网络，并且会把 `mcp` 安装到当前 Python 环境：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\hil index .
.venv\Scripts\hil-mcp
```

未安装时 `hil` / `hil-mcp` 命令不存在，这是预期行为，不是配置错误。

## Harness 接入

MCP 服务使用 stdio。把 `python run_hil_mcp.py`（或安装后的 `hil-mcp`）配置到 OpenClaw/Cline/Codex 的 MCP Server 列表，字段名以各 Harness 的配置格式为准，要点是三条：

- `command` 指向解释器绝对路径，`args` 指向 `run_hil_mcp.py` 绝对路径；
- `env.HIL_PROJECT_ROOT` 指定默认目标项目，未传参时四个工具都用它；
- `cwd` 设为 HIL 仓库根目录，`requestTimeoutMs` 建议不小于 60000。

```json
{
  "command": "C:\\Python314\\python.exe",
  "args": ["D:\\MY\\My Projects\\HarnessIntelligenceLayer\\run_hil_mcp.py"],
  "env": { "HIL_PROJECT_ROOT": "D:\\MY\\My Projects\\YourProject" },
  "cwd": "D:\\MY\\My Projects\\HarnessIntelligenceLayer",
  "requestTimeoutMs": 60000
}
```

调用策略建议：

1. 跨文件、陌生仓库或诊断类任务开始时调用一次 `get_project_context`，不要同时全量遍历仓库。
2. **把已知的英文标识符写进 `task`**：文件名、符号名、配置项、错误码。这是当前召回率最大的影响因素（见下方实测）。
3. 新增、删除或重命名文件后不必手动重建索引，检索会自愈；只有需要显式确认时再调用 `index_project`。
4. 只有确定为可复用工程事实时才调用 `record_project_memory`。
5. 单文件、路径明确的任务直接读取文件，避免增加一次 MCP 往返。
6. 如果 `get_project_context` 返回 `sufficient: false`，说明本次没有任何片段命中，应改用 Harness 原生搜索；`fallback` 字段会说明原因，不要把空包当成"项目里没有相关内容"。
7. 可选语义重排默认关闭（`HIL_EMBEDDINGS`，或 CLI `--embedding`）。它只在配置了本地多语言模型或 HTTP 端点时才有意义，任何不可用都会回退本地词法检索；其召回收益必须先由 `benchmarks/measure.py --embedding auto` 量化。

V0.1 的词法检索对任务表达敏感，实测（`benchmarks/`，26 个真实任务、1500 token 预算、同一索引）：

| 任务表达 | 平均召回 | 达标题数（≥90%） |
|---|---|---|
| 只写中文自然语言 | 47.8% | 7 / 26 |
| 中文 + 英文标识符 | 69.9% | 15 / 26 |

所以请把 `get_project_context` 的 `task` 写成"一句话 + 相关标识符"，例如 `定位索引重建与陈旧检测（load_index、staleness_reason、INDEX_VERSION）`，而不是只写"索引是怎么更新的"。两种写法都还没达到 90%：纯中文提问与英文实现之间缺少词面重叠（跨语言匹配，词法检索解决不了），文档类任务则会与测试文件争夺预算。缺口归因与后续选择见 `docs/roadmap.md` §4。

## 验证

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v      # 128 项单元测试，含 MCP stdio 端到端往返、跨 Harness 记忆复用

# Phase 0 评测：任务集召回、包体积、延迟、重复片段
python benchmarks/measure.py --budget 1500 --label baseline --variant raw
python benchmarks/measure.py --budget 1500 --label baseline --variant hinted
python benchmarks/measure.py --budget 1500 --label baseline --variant hinted --embedding auto

# 跨阶段验证与回归门（任务集一致性、两条文件发现路径一致、包不变量与真实行号、
# 分类召回、相对基线的回归门、索引覆盖、跨 Harness 复用、--compare 的退出码自检）
python benchmarks/verify.py

# Phase 4 证据门：四条「按证据扩展」触发条件是否成立
python benchmarks/evidence.py
```

`.github/workflows/ci.yml` 在 Python 3.11 / 3.13 上运行单元测试、Phase 0 任务集和 `verify.py` 回归门（基线为 `benchmarks/results/baseline.json`；`SKIP` 表示该环境无法运行某项检查，不计为通过）。token 节省比例只能在 Harness 真实会话中按 `benchmarks/README.md` 的 A/B 流程测量，本仓库不提供预设数字。

