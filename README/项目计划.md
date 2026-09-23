# Harness Intelligence Layer 项目计划

## 1. 总体目标

通过共享项目索引、工程知识和 token 预算打包，减少 OpenClaw、Cline、Codex 在同一仓库内的重复搜索与重复上下文输入，同时保持任务成功率。

核心验收指标：

- Context Recall：关键文件和符号是否被召回；
- Context Precision：返回上下文中的无关内容比例；
- Input Token Reduction：相同任务的输入 token 减少量；
- Task Success Rate：任务最终正确完成率；
- Retry Count：平均修复轮次；
- Cost per Successful Task：完成正确任务的总成本；
- Cross-Harness Reuse：一个 Harness 写入的知识能否被另一个复用。

## 2. Phase 0：建立评测基线

状态：待执行。

工作内容：

1. 选择 20–30 个真实历史任务。
2. 按单文件、跨模块、故障定位、架构问答分类。
3. 为每个任务标注必须召回的文件、符号和成功判据。
4. 分别记录 OpenClaw、Cline 原生执行时的输入/输出 token、工具调用数、耗时、重试次数和成功率。
5. 固化任务集和统计口径，避免只选对 HIL 有利的样本。

交付物：

- `benchmarks/tasks.jsonl`；
- 原生执行基线；
- token 与任务成功率统计脚本；
- 可重复的对照实验说明。

## 3. Phase 1：轻量 V0.1

状态：核心功能已完成。

已完成：

- ripgrep 文件发现；
- 常见语言的轻量符号提取；
- 路径、符号和文本命中排序；
- token 预算选择；
- JSON 工程记忆；
- 4 个 MCP 工具；
- OpenClaw、Cline CLI 和 Cline VS Code 扩展接入；
- `.ai-memory` 与代码索引去重；
- 中英文 token 估算测试；
- MCP 连接探测和 6 项单元测试。

仍需完成：

- 建立 Phase 0 的真实任务集；
- 在 OpenClaw 和 Cline 中分别完成端到端对照任务；
- 记录实际 token、召回率和失败案例。

## 4. Phase 2：索引质量与增量更新

进入条件：V0.1 检索存在可量化的召回不足，且问题不是查询表达或调用策略造成的。

计划内容：

- 使用 Tree-sitter 替换正则符号提取；
- 构建 import、引用和调用关系；
- 加入 Git 最近变更和历史相关性；
- 增加索引 schema/version 迁移；
- 增加变更文件增量索引和文件监听；
- 返回上下文选择原因及预算淘汰摘要；
- 保留本地词法检索作为强制回退路径。

退出标准：

- Context Recall 不低于 90%；
- 首次索引之外的检索 P95 小于 1 秒；
- 索引更新不会阻塞正常 Harness 工作流。

## 5. Phase 3：跨 Harness A/B 验证

计划内容：

- 对相同任务随机分配 native/control 与 HIL/treatment；
- 记录每轮模型输入 token、工具结果体积、重试次数和最终正确性；
- 验证 Cline 写入的事实可以被 OpenClaw 检索，反向亦然；
- 建立失败回退：HIL 召回不足时允许 Harness 使用原生搜索；
- 分离检索收益与 prompt caching、模型差异造成的收益。

建议成功门槛：

- 中位输入 token 至少降低 20%；
- Context Recall 不低于 90%；
- Task Success Rate 下降不超过 2 个百分点；
- 平均重试次数不增加；
- 跨 Harness 记忆复用成功。

若未达到门槛，应先修正检索与调用策略，不直接增加复杂基础设施。

## 6. Phase 4：按证据扩展

只有出现对应证据时才实施：

- 词法检索无法满足 Recall：增加可选 Embedding 和 Reranker；
- 代码修改质量无法统一比较：增加 Unified Validator；
- 已积累至少 100 个可比任务结果：增加 Model Router；
- 本地索引性能成为瓶颈：评估 FAISS、Qdrant 或其他向量存储。

## 7. 明确不做

- 新 Agent Loop；
- 通用 Shell 或文件编辑工具；
- Session Manager；
- Sub-Agent 框架；
- 自动保存完整聊天流水账；
- V0.1 强制依赖云 Embedding、Qdrant 或 Cross-Encoder；
- 在没有 A/B 数据时宣传固定 token 节省比例。

## 8. 下一步优先级

1. 建立真实任务数据集。
2. 为 OpenClaw/Cline 各完成至少 10 个 native 与 HIL 对照任务。
3. 汇总未召回文件、重复片段和无关上下文。
4. 决定是否进入 Tree-sitter 与增量索引阶段。
5. 达到数据量门槛后再讨论 Validator 和 Model Router。

