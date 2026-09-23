# Harness Intelligence Layer 项目总览

## 1. 项目定位

Harness Intelligence Layer（HIL）是面向 OpenClaw、Cline、Codex 等 AI Coding Harness 的共享项目智能层。

它不替代 Harness，也不实现新的 Agent Loop、Shell、文件编辑器、Session Manager 或 Sub-Agent 框架。它只解决不同 Harness 重复理解同一仓库的问题：

- 建立可复用的项目代码索引；
- 返回符号级、片段级上下文，而不是整文件灌入模型；
- 在明确的 token 预算内选择高价值上下文；
- 保存跨 Harness 共用的、经过确认的工程事实；
- 为后续质量验证和成本评测提供统一基础。

## 2. 核心价值

当 OpenClaw、Cline 等工具分别处理同一个项目时，它们通常需要重复搜索文件、读取代码并重新理解架构。HIL 将这些工作收敛为一个共享层：

```text
OpenClaw / Cline / Codex
            │
            │ MCP（STDIO）
            ▼
Harness Intelligence Layer
       ┌────┴────┐
       ▼         ▼
  项目代码索引   工程知识库
       │         │
       └────┬────┘
            ▼
   Token Budget Context Package
```

HIL 适合陌生仓库、跨模块任务、故障定位和重复任务。对于路径明确的单文件修改，直接读取文件通常更高效，不必额外调用 HIL。

## 3. 当前版本

当前版本为 V0.1，采用 dependency-light 方案：

- 使用 ripgrep 发现文件并遵循常见忽略规则；
- 使用轻量语法规则提取常见语言符号；
- 使用路径、符号和文本命中进行词法排序；
- 使用中英文兼容的保守 token 估算；
- 使用 JSON 文件保存工程记忆；
- 使用 FastMCP 提供 STDIO MCP Server；
- 当可选检索后端不可用时，始终保留本地词法检索能力。

当前不包含 Embedding、向量数据库、Tree-sitter、增量文件监听、Unified Validator 和 Model Router。

## 4. MCP 工具

| 工具 | 作用 |
|---|---|
| `index_project` | 建立或刷新项目代码索引 |
| `get_project_context` | 在 token 预算内返回相关代码片段和工程事实 |
| `search_project_memory` | 搜索项目长期工程知识 |
| `record_project_memory` | 写入经过确认、可复用的工程事实 |

MCP 接口有意保持精简，不提供通用 Shell、文件写入、会话或代理调度能力。

## 5. 数据位置

```text
<project_root>/
├─ .hil/
│  └─ index.json                # 代码与符号索引
└─ .ai-memory/
   ├─ architecture/             # 架构事实
   ├─ decisions/                # 技术决策
   ├─ bugs/                     # Bug 根因
   ├─ conventions/              # 工程约定
   ├─ experiments/              # 实验结论
   └─ tasks/                    # 重要任务事实
```

`.ai-memory` 只保存可复用工程事实，不保存完整聊天记录、临时推理或秘密信息。

## 6. 当前部署状态

截至 2026-09-23：

- 当前项目索引已建立，索引文件为 `.hil/index.json`；
- 已索引 14 个项目文件；
- 工程知识库已建立并包含初始架构与检索决策；
- OpenClaw CLI 2026.9.5 已注册 `hil` MCP Server；
- Cline CLI 3.0.64 已安装并注册 `hil`；
- Cline VS Code 扩展 4.1.20 已注册 `hil`；
- OpenClaw 实际探测到 4 个 HIL 工具且无诊断错误；
- 6 项 Python 单元测试通过。

## 7. 重要边界

- HIL 不会自动监控源文件变化；重要代码变化后必须重新索引。
- 当前索引只针对指定的 `project_root`，不会自动覆盖其他业务仓库。
- 当前 V0.1 是词法检索基线，关键修改前仍应核对真实文件和符号。
- 尚未通过正式 A/B 任务集证明固定 token 节省比例，因此不能宣称确定的节省百分比。
## 8. References

- [OpenClaw Context Engine](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context-engine.md)
- [OpenClaw Context](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context.md)
- [OpenClaw Memory](https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-builtin.md)
- [Cline Task Management](https://github.com/cline/cline/blob/main/docs/core-workflows/task-management.mdx)
- [Cline Subagents](https://github.com/cline/cline/blob/main/docs/features/subagents.mdx)
- [Cline Tools](https://github.com/cline/cline/blob/main/docs/tools-reference/all-cline-tools.mdx)
