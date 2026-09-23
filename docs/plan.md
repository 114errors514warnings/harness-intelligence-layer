# 执行计划

## Phase 0：基线与任务集（1–2 天）

- 选取 20–30 个历史真实任务，标注必须文件/符号与成功判据。
- 分别记录 OpenClaw、Cline 原生执行的输入/输出 token、轮次、耗时和成功率。
- 按单文件、跨模块、故障定位、架构问答分层。

交付：`benchmarks/tasks.jsonl`、原生基线报告、可重复的 token 统计口径。

## Phase 1：轻量 V0.1（当前已创建）

- 使用 ripgrep 文件发现，轻量语法规则提取常见语言符号。
- 使用路径、符号、文本命中和稀有度打分。
- 在 token 预算内返回片段，而不是整个文件。
- 以 JSON 文件保存可审阅的项目工程事实。
- 通过 stdio MCP 暴露四个工具。

退出条件：功能测试通过，可由至少一个 Harness 调用。

## Phase 2：质量与增量索引（3–5 天）

- 引入 Tree-sitter，替换正则符号提取。
- 增加 import/call 关系和 Git 最近变更权重。
- 只重建变更文件；增加 schema/version 与迁移。
- 输出选择原因和被预算淘汰的候选摘要。

退出条件：Context Recall ≥ 90%，P95 检索 < 1 秒。

## Phase 3：跨 Harness 集成与 A/B（3–5 天）

- OpenClaw：先 MCP；稳定后提供 Context Engine 插件适配。
- Cline：MCP 配置和最小 Rule，避免重复全库搜索。
- Codex：项目级 `.codex/config.toml` 示例，保持 MCP 工具结果简洁。
- 对同一任务随机使用 native/control 与 HIL/treatment，记录净输入 token。

退出条件：中位输入 token 下降 ≥ 20%，成功率基本持平。

## Phase 4：按证据扩展

- Recall 不足且词法无法解决：增加可选 Embedding/Reranker。
- 质量不可比：增加 Unified Validator。
- 已积累至少 100 个同类任务结果：再实现 Model Router。

## 明确不做

- 新 Agent Loop、Shell、编辑器、Session Manager、Sub-Agent 框架；
- 自动摄取完整聊天记录；
- V0.1 强依赖 Qdrant、云 Embedding 或 Cross-Encoder；
- 没有 A/B 数据时宣称固定节省比例。

