# Harness Intelligence Layer

面向 OpenClaw、Cline、Codex 等 Harness 的共享项目智能层。它不替代 Agent Loop、Shell、文件编辑或会话管理，只提供可复用的项目上下文与工程记忆。

## 评估结论

原方案可以提升 token 使用效率，但需要缩小第一阶段范围：

- **值得做**：跨 Harness 共享的代码检索、符号级片段、工程事实与固定 token 预算打包。目前这些信息通常由每个 Harness 重复搜索、重复解释。
- **不应重复做**：OpenClaw 已有上下文引擎、压缩、裁剪和记忆检索；Cline 已有自动压缩、任务交接和子代理研究。V0.1 不再实现通用会话压缩或 Harness 内部记忆。
- **Embedding 延后**：先以 `ripgrep + 符号提取 + Git + 词法排序` 建立可测基线。只有当 Context Recall 不达标时，才引入向量模型和数据库。
- **优化不是无条件成立**：小仓库、明确单文件任务可能因额外工具调用而增加 token。默认仅在跨文件任务、陌生仓库或重复任务中使用。

详细依据见 [docs/assessment.md](docs/assessment.md)，执行路线见 [docs/plan.md](docs/plan.md)。

## 当前 V0.1

已提供四个 MCP 工具：

- `index_project(project_root)`
- `get_project_context(task, project_root, token_budget)`
- `search_project_memory(query, project_root, limit)`
- `record_project_memory(category, title, content, project_root, tags)`

索引保存在 `.hil/index.json`，可共享事实保存在 `.ai-memory/<category>/*.json`。两者都在项目目录内，不依赖某个 Harness 的私有会话数据库。

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
hil index .
hil context "定位认证失败的根因" . --budget 4000
hil-mcp
```

不安装依赖也可直接运行 CLI：

```powershell
$env:PYTHONPATH = "src"
python -m harness_intelligence.cli index .
python -m harness_intelligence.cli context "查找上下文构建逻辑" . --budget 3000
```

## Harness 接入

MCP 服务使用 stdio。把命令 `hil-mcp`（或 `python -m harness_intelligence.server`）配置到 OpenClaw/Cline/Codex 的 MCP Server 列表，并设置工作目录为目标仓库。建议让 Harness 遵循以下调用策略：

1. 陌生仓库或索引过期时调用 `index_project`。
2. 跨文件任务开始时调用一次 `get_project_context`，不要同时全量遍历仓库。
3. 只有确定为可复用工程事实时才调用 `record_project_memory`。
4. 单文件、路径明确的任务直接读取文件，避免增加一次 MCP 往返。

## 验证

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

