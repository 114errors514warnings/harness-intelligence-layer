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

- 使用 ripgrep 发现文件，并遵循常见忽略规则与项目根 `.hilignore` 的自定规则（两条发现路径共用同一套规则，避免"装不装 ripgrep 换一套文件集"）；
- 使用轻量语法规则提取常见语言符号；
- 使用路径、符号和文本命中进行词法排序；
- 中文查询通过一份小型中英词表桥接为英文查询词（只扩展查询侧；桥接词不享受路径加成、内容命中按半权计）；
- 使用中英文兼容的保守 token 估算；
- 使用 JSON 文件保存工程记忆；
- 使用 FastMCP 提供 STDIO MCP Server；
- 索引带 schema 版本与文件集指纹，检索前自动比对并在漂移时重建，返回值中报告陈旧原因；
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
├─ .hilignore                   # 可选：项目自定义的"不进索引"规则
├─ .hil/
│  ├─ index.json                # 代码与符号索引
│  └─ results/                  # 评测每次运行产生的报告（不进索引）
└─ .ai-memory/
   ├─ architecture/             # 架构事实
   ├─ decisions/                # 技术决策
   ├─ bugs/                     # Bug 根因
   ├─ conventions/              # 工程约定
   ├─ experiments/              # 实验结论
   └─ tasks/                    # 重要任务事实
```

`.ai-memory` 只保存可复用工程事实，不保存完整聊天记录、临时推理或秘密信息。`.hilignore` 里列出的派生文件（例如 `benchmarks/results/`）同样不进入索引，因此它们被重新生成时不会让索引失效。

## 6. 当前部署状态

截至 2026-10-05：

- 索引文件为 `.hil/index.json`，schema 版本 2，覆盖 29 个文本文件、223 个符号；
- 索引自愈与陈旧可见性已实现，并有单元测试覆盖；跨阶段回归门由 `benchmarks/verify.py` 与 `benchmarks/results/baseline.json` 把关；
- 工程知识库已建立，包含架构、技术决策与缺陷记录；
- OpenClaw CLI 2026.9.5、Cline CLI 3.0.64、Cline VS Code 扩展 4.1.20 均已注册 `hil`；
- OpenClaw 实际探测到 4 个 HIL 工具且无诊断错误；
- 101 项 Python 单元测试通过，其中包含 MCP 四工具注册与 stdio 端到端往返；
- GitHub Actions 在 Python 3.11 与 3.13 上运行单元测试、Phase 0 任务集与回归门；
- Phase 0 任务集（26 条）与统计脚本已建立，并已完成 Phase 2 的两处检索修正与跨语言词面桥接：中文词项切分与片段级评分把 `raw` 从 26.9% 提升到 47.8%，中英词表桥接再把 `raw` 提升到 68.9%、`hinted` 由 69.9% 微降到 68.9%（均仍未达到 90% 目标，缺口归因见 `docs/roadmap.md` §4）。

## 7. 重要边界

- HIL 不监听文件变化；索引在检索时自愈，因此自愈发生在"访问那一刻"，而不是"文件被修改那一刻"。
- 当前索引只针对指定的 `project_root`，不会自动覆盖其他业务仓库。
- 当前 V0.1 是词法检索基线（中文查询经小型中英词表桥接），关键修改前仍应核对真实文件和符号。
- 文档类问题（`docs/*.md`）：Phase 2 修正后文档片段已能与代码片段竞争（`raw` 变体下 `HIL-017`、`HIL-018` 由 0% 升至 100%），但补充标识符对文档类任务没有帮助（`hinted` 下这两条仍为 0%）；实测与归因见 `docs/roadmap.md` §4。
- 尚未通过正式 A/B 任务集证明固定 token 节省比例，因此不能宣称确定的节省百分比。
## 8. References

- [OpenClaw Context Engine](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context-engine.md)
- [OpenClaw Context](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context.md)
- [OpenClaw Memory](https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-builtin.md)
- [Cline Task Management](https://github.com/cline/cline/blob/main/docs/core-workflows/task-management.mdx)
- [Cline Subagents](https://github.com/cline/cline/blob/main/docs/features/subagents.mdx)
- [Cline Tools](https://github.com/cline/cline/blob/main/docs/tools-reference/all-cline-tools.mdx)
