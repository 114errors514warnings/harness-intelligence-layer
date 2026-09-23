# 方案评估：在 OpenClaw 与 Cline 下的 token 效率

评估日期：2026-09-23。

## 结论

方案有优化空间，但不是原方案中的所有模块都应建设。建议继续开发的最小核心是：

1. 跨 Harness 共用的项目代码索引；
2. 符号/片段级上下文检索；
3. 显式 token 预算下的上下文打包；
4. 项目内、可审阅、可迁移的工程事实库；
5. A/B 评测与任务级成本记录。

Validator 和 Model Router 有长期价值，但不会直接降低首次输入 token，且需要先积累可靠任务数据，因此不属于 V0.1。

## 与现有能力的重叠

### OpenClaw

OpenClaw 已提供：

- 上下文压缩及近期消息保留；
- tool result pruning；
- 本地长期记忆和混合检索；
- 可插拔 Context Engine，可控制 assemble/compact 生命周期；
- token 使用查看与上下文构成诊断。

因此，本项目不再实现“通用对话压缩器”或 OpenClaw 专属记忆后端。更合适的接法是先以薄 MCP 暴露项目检索；数据证明收益后，再做 OpenClaw Context Engine 适配器，让它在 assemble 阶段自动取用 Context Package。

### Cline

Cline 已提供：

- 基于 ripgrep 的代码搜索；
- 自动压缩、`/smol` 与 `/newtask` 交接；
- 子代理并行研究，减少主上下文污染；
- 每任务 token/cost 统计；
- MCP 与插件扩展接口。

Cline 的这些能力主要优化单个任务/单个客户端。共享的符号索引、跨任务工程事实和严格预算打包仍有价值，尤其适用于多 Harness 交替工作和大型仓库。

## token 为什么可能下降

设裸执行需要 Harness 进行 `N` 次搜索/读文件，每次把结果和工具协议写入对话；共享层只返回最终选中的 `K` 个片段。只要：

`ContextPackageTokens + MCPOverhead < AvoidedSearchAndReadTokens`

就产生净收益。预期高收益场景：陌生大型仓库、跨模块改动、同类任务反复出现、多个 Harness 轮换。预期低收益或负收益场景：已知路径的单文件修改、仓库很小、上下文包召回失败导致二次搜索。

## 风险与修正

- **检索失败**：词法检索可能遗漏概念相关代码。先测 Recall，再决定是否增加 Embedding。
- **陈旧索引**：V0.1 记录 mtime/size；后续增加文件监听和 Git commit 指纹。
- **错误记忆**：只允许显式记录，并保存时间、标签和来源字段；不自动保存聊天摘要。
- **提示词膨胀**：MCP 工具说明保持短小；只在适用任务调用，不全局注入代码上下文。
- **重复能力**：OpenClaw 适配优先复用其 Context Engine/Memory 插槽，Cline 适配优先使用 MCP/插件，不修改 Harness 内核。

## 成功门槛

在至少 20 个真实任务上，与原生 OpenClaw/Cline 分别比较：

- 中位输入 token 至少下降 20%；
- Context Recall 不低于 90%；
- Task Success Rate 下降不超过 2 个百分点；
- 平均重试次数不增加；
- MCP 检索 P95 小于 1 秒（不含首次索引）。

未达到门槛时，不进入向量数据库、Router 或 Validator 阶段。

## 核对来源

- [OpenClaw Context Engine](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context-engine.md)
- [OpenClaw Context](https://github.com/openclaw/openclaw/blob/main/docs/concepts/context.md)
- [OpenClaw Memory](https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-builtin.md)
- [Cline Tasks 与 Auto-Compact](https://github.com/cline/cline/blob/main/docs/core-workflows/task-management.mdx)
- [Cline Subagents](https://github.com/cline/cline/blob/main/docs/features/subagents.mdx)
- [Cline Tools](https://github.com/cline/cline/blob/main/docs/tools-reference/all-cline-tools.mdx)
- [OpenAI Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)
