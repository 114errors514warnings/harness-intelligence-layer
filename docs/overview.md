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
- 使用中英文兼容的保守 token 估算；
- 使用 JSON 文件保存工程记忆；
- 使用 FastMCP 提供 STDIO MCP Server；
- 索引带 schema 版本与文件集指纹，检索前自动比对并在漂移时重建，返回值中报告陈旧原因；
- `get_project_context` 返回 `sufficient` 与 `fallback`，空包会显式要求 Harness 回退原生搜索，而不是把空结果当作答案；
- 提供**可选**的语义重排后端（`HIL_EMBEDDINGS` / CLI `--embedding`），默认关闭；任何后端不可用或中途失败时，检索始终回退到本地词法排序。

当前不包含向量数据库、Tree-sitter、增量文件监听、Unified Validator 和 Model Router。语义重排是可选层而非必需依赖：`hash` 后端仅用于打通链路，本地多语言模型或 HTTP 端点需自行配置，且其收益必须由 `benchmarks/measure.py` 量化后才可提及。

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

截至 2026-10-11：

- 索引文件为 `.hil/index.json`，schema 版本 2，覆盖 33 个文本文件（本次新增 `embeddings.py`、`evidence.py` 与测试文件后的计数）；
- 索引自愈与陈旧可见性已实现，并有单元测试覆盖；跨阶段回归门由 `benchmarks/verify.py` 与 `benchmarks/results/baseline.json` 把关；
- 工程知识库已建立，包含架构、技术决策与缺陷记录；
- OpenClaw CLI 2026.9.5、Cline CLI 3.0.64、Cline VS Code 扩展 4.1.20 均已注册 `hil`；
- OpenClaw 实际探测到 4 个 HIL 工具且无诊断错误，MCP 工具面仍严格保持四个；
- 132 项 Python 单元测试通过，其中包含 MCP 四工具注册、stdio 端到端往返、跨 Harness 记忆复用、路径匹配精度与可选语义后端的回退路径；
- GitHub Actions 在 Python 3.11 与 3.13 上运行单元测试、Phase 0 任务集与回归门；
- Phase 0 任务集（26 条）与统计脚本已建立；Phase 2 已完成两轮检索修正：第一轮中文词项切分 + 片段级排序，第二轮路径匹配精确化、文件级加成不再被窗口体积稀释、点名的标识符窗口优先发射、每文件一个窄窗口以覆盖更多文件。`raw` 26.9% → 47.8% → **59.3%**、`hinted` 65.7% → 69.9% → **96.2%**：`hinted` 已达到 90% 退出标准（且无必召回文件被漏掉），`raw` 的剩余缺口是跨语言匹配（见 `docs/roadmap.md` §4）；
- **首次真实跨 Harness A/B 已完成**（2026-10-11，OpenClaw + `deepseek-v4-flash`，26 题 × 2 臂，双臂有效性经 transcript 核验）：中位输入 token 降低 **45.9%**、召回 96.2%、平均重试 0→0 均达标，但**成功率 100% → 96.2%（−3.8pp，预算 2pp）未达标**，因此 Phase 3 仍未通过；26 题的粒度是 3.85pp/题，2pp 预算在该样本量上无法分辨。详见 `docs/roadmap.md` §5；
- Phase 3 判定机制已就绪（随机分组、五道门槛、跨 Harness 复用回执），Phase 4 证据门（`benchmarks/evidence.py`）已建立并报告"词法 Recall 不达标"这一触发条件成立；可选语义重排已实现且默认关闭，尚无召回收益声明。详见 `docs/roadmap.md` §5/§6。

## 7. 重要边界

- HIL 不监听文件变化；索引在检索时自愈，因此自愈发生在"访问那一刻"，而不是"文件被修改那一刻"。
- 当前索引只针对指定的 `project_root`，不会自动覆盖其他业务仓库。
- 当前 V0.1 是词法检索基线，关键修改前仍应核对真实文件和符号。
- 文档类问题（`docs/*.md`）：Phase 2 修正后文档片段已能与代码片段竞争（`raw` 变体下 `HIL-017`、`HIL-018` 由 0% 升至 100%），但补充标识符对文档类任务没有帮助（`hinted` 下这两条仍为 0%）；实测与归因见 `docs/roadmap.md` §4。
- 尚未通过正式 A/B 任务集证明固定 token 节省比例，因此不能宣称确定的节省百分比。
- 可选语义重排默认关闭；即使开启，`hash` 后端也**不是**语义模型，其与词法检索在本仓库语料上召回一致。只有配置了多语言模型或 HTTP 端点后，其收益才可能成立，且必须先经 `benchmarks/measure.py --embedding auto` 量化。
- `get_project_context` 的 `sufficient: false` 与 `fallback` 是给 Harness 的明确信号：本次没有检索到任何片段，应改用原生搜索，不要把空包当成"项目里没有相关内容"。
## 8. References

- [OpenClaw Context Engine](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context-engine.md)
- [OpenClaw Context](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context.md)
- [OpenClaw Memory](https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-builtin.md)
- [Cline Task Management](https://github.com/cline/cline/blob/main/docs/core-workflows/task-management.mdx)
- [Cline Subagents](https://github.com/cline/cline/blob/main/docs/features/subagents.mdx)
- [Cline Tools](https://github.com/cline/cline/blob/main/docs/tools-reference/all-cline-tools.mdx)
