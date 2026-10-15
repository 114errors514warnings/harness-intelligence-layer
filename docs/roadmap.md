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

状态：**OpenClaw 侧已完成**（`benchmarks/results/ab.jsonl` 50 行、native 与 hil 两臂均已填）；Cline/Codex 侧待 Phase 3（D）。任务集、统计脚本与调用策略对照实验已完成。

工作内容：

1. 选择 20–30 个真实历史任务。
2. 按单文件、跨模块、故障定位、架构问答分类。
3. 为每个任务标注必须召回的文件、符号和成功判据。
4. 分别记录 OpenClaw、Cline 原生执行时的输入/输出 token、工具调用数、耗时、重试次数和成功率。
5. 固化任务集和统计口径，避免只选对 HIL 有利的样本。

交付物：

- `benchmarks/tasks.jsonl`：**已完成**，Phase 0 时 26 条、后扩建到 **50 条**真实任务，按单文件、跨模块、故障定位、架构问答分类，逐条标注必须召回的文件、符号与成功判据；
- token 与任务成功率统计脚本：**已完成**，`benchmarks/measure.py`（HIL 侧召回、包体积、延迟、重复片段；A/B 表校验与门槛判定）；
- 可重复的对照实验说明：**已完成**，`benchmarks/README.md`；
- 原生执行基线：**OpenClaw 与 Cline 两侧均已填**（`ab.jsonl` 共 **100** 行，见 §5/§11）；Codex 侧未做。A/B 表未填写完整时，脚本仍会拒绝输出任何节省比例（退出码 3）。

已完成测量（HIL 侧，26 题 × 1500 token 预算，索引 schema 2，26 个文件 / 182 个符号；下表是 **Phase 0 当时的 V0.1 词法检索**，Phase 2 修正后的当前值见 §4）：

| 任务表达 | 平均 Context Recall | 达标（≥90%）题数 | 中位包体积 | 未召回符号 | 延迟 p50 / p95（预热后，指示性） |
|---|---|---|---|---|---|
| 中文自然语言（`--variant raw`） | 26.9% | 4 / 26 | ≈1380 token | 13 | 149 / 206 ms |
| 中文 + 英文标识符（`--variant hinted`） | 65.7% | 12 / 26 | ≈1470 token | 2 | 152 / 175 ms |

结论：召回不足的主因是任务表达与词法分词，而不是索引陈旧；索引自愈后剩余缺口集中在 `docs/*.md` 等文档文件。其中"连续中文串被当作单一词项"已作为 Phase 2 的第一项修正在 §4 中量化并修正，因此上表只作为 Phase 0 的历史记录保留（当前基线以 `benchmarks/results/baseline.json` 为准）。

（2026-10-05 复测：修正了 `HIL-009` 的 hint（原文写出了答案文件名，等于测量标注而非测量检索），并把每次运行的评测报告移出索引范围，随后整体重测，上表为重测值。评测产物对索引的量化影响见 `benchmarks/README.md` §4 的隔离实验。）

## 3. Phase 1：轻量 V0.1

状态：核心功能已完成（收口于 2026-10-14）。

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
- MCP 连接探测和 6 项单元测试；
- 索引自愈：schema 版本 + 文件集指纹（相对路径、大小、mtime）比对后自动重建索引；
- 陈旧可见：`get_project_context` 返回 `index` 状态块（`staleness` 三态取值 `current` / `rebuilt` / `stale`，以及 `refreshed`、`stale_reason`）并在 `notice` 中显式告警，`stale` 时 `fallback` 说明空包不可信；
- CLI `context --no-refresh`，以及把参数错误转为退出码 2 的 usage error；
- 测试扩展到 72 项：索引新鲜度、CLI 命令面、MCP 四工具注册与 stdio 端到端往返、评测门阈值与三种退出码、任务语料自洽性、`.hilignore` 排除规则；
- 跨阶段验证脚本 `benchmarks/verify.py`：8 类断言（任务集一致性、两条文件发现路径一致、包不变量与真实行号、分类召回、相对基线的回归门、延迟报告、索引覆盖、节省门退出码自检），`SKIP` 不计为通过；
- 回归基线 `benchmarks/results/baseline.json` 与仓库根 `.hilignore`（派生评测产物不进索引）；
- GitHub Actions CI（Python 3.11 / 3.13）运行单元测试、Phase 0 任务集与 `verify.py` 回归门。

仍需完成（收口于 2026-10-14）：

- ~~在 OpenClaw 和 Cline 中分别完成端到端对照任务，并填写 A/B 表~~ → **已并入 Phase 3（§5）**：OpenClaw 侧已完成，Cline/Codex 侧属 D；
- ~~记录实际 token、失败案例与重试次数~~ → **已并入 Phase 3（§5）**；
- ~~修正文档类文件的召回缺口（见 Phase 2 进入条件评估）~~ → **已完成**（Phase 2 修正后 `HIL-017`/`HIL-018` 由 0% 升至 100%，见 §4）。

## 4. Phase 2：索引质量与增量更新

进入条件：V0.1 检索存在可量化的召回不足，且问题不是查询表达或调用策略造成的。

进入条件评估（2026-10-05，数据来自 `benchmarks/`）：

- **已量化（修正前）**：中文自然语言任务平均 Context Recall 为 26.9%，补充英文标识符后为 65.7%，均低于 90% 目标；`hinted` 下未召回符号降到 2 个，但仍有 14 / 26 条任务达不到 90%，且分类差异明显（`benchmarks/verify.py` 逐类报告，`cross-module` 明显低于 `bug-localization`）。
- **表达因素已单独测量（修正前）**：仅改变任务表达即可挽回约 39 个百分点（26.9% → 65.7%），说明表达是主要影响因素之一，但剩余缺口与表达方式无关。
- **剩余缺口可归因于两处检索实现问题**：中文连续串被整体当作单一词项，无法与源文件中的局部词匹配；文档文件不声明符号且行较长，在 `score / token_cost` 排序下必然输给代码片段。
- **结论**：进入 Phase 2 是合理的，但优先级应是先做最小可验证的检索修正（中文词项切分、文档片段排序），验证有效后再投入 Tree-sitter 与增量索引。

### Phase 2 第一步：两处最小检索修正（已完成）

新增 `src/harness_intelligence/terms.py`（代码检索与记忆检索共用同一份词项定义），并改写 `retrieval.py` 的评分与选窗：

1. **中文词项切分**：连续中文串不再整体作为一个词项，而是拆成重叠的 2 字与 3 字 n-gram（`重建索引之后` → `重建`、`建索`、`索引`…）。单字不参与匹配（单字几乎命中所有中文行）；词项数上限 200，使粘贴长文时每行扫描次数仍有界（集合式调用方如记忆检索可显式关闭该上限）。
2. **片段级评分**：得分不再按"整个文件的命中行数"计算后套给该文件的所有窗口，而是按"该片段自身包含的命中行数"计算。窗口受 token 上限约束、同文件互不重叠，并按证据密度挑选要发射的窗口（原先只取文件里最靠前的 3 个窗口，且密集命中会合并成一个数百 token 的整段）。路径与符号命中作为文件级加成保留，但各自饱和计数；查询直接写出的标识符（`discover_files`）权重高于只与标识符中某个词相同的情况（`memory` ∈ `test_index_excludes_memory_store`），两者不再等价。

同批做的两处工程性调整：符号名按 `snake_case` / `camelCase` 词部件匹配（`json` 不再命中 `_write_jsonl`）；行命中改为一条预编译正则扫描（原来每行对每个词项做一次 Python 包含判断），使中文任务在词项数变多后延迟不退化。

同一任务集、同预算复测（2026-10-05，26 题 × 1500 token、索引 schema 2）：

| 变体 | 修正前 Recall | 修正后 Recall | 达标（≥90%） | 中位包体积 | 重复片段 |
|---|---|---|---|---|---|
| `raw`（中文自然语言） | 26.9% | 47.8% | 4 → 7 / 26 | ≈1470 token | 0 |
| `hinted`（中文 + 标识符） | 65.7% | 69.9% | 12 → 15 / 26 | ≈1480 token | 0 |

验证：`benchmarks/verify.py` 全绿（唯一 `SKIP` 为本机未装 ripgrep，**SKIP 不算通过**）、95 项单元测试通过、基线已随本次改动用 `--write-baseline` 重录并一起 review。逐类召回（informational，不作门）：`hinted` 架构 86.1%、故障定位 87.5%、跨模块 62.5%、单文件 50.0%。

### Phase 2 第二步：排序精度与预算分配修正（2026-10-11，已完成）

第一步的复测暴露出两处仍在拖后腿的实现问题，都不是"符号没被提取"，而是**排序把预算引向了错误的文件**：

1. **路径匹配用子串包含**：`term in path.lower()` 让 `git` 命中 `.github/`、`ai` 命中 `openai.yaml`，给与问题无关的文件一个平摊到它每个窗口的高权重加分。改为按路径段与文件名的词部件匹配，并对短于 4 字符的词项关闭前缀匹配（`token` 仍命中 `tokens.py`，`index` 仍命中 `indexer.py`）。
2. **文件级加成被窗口体积稀释**：排序键是 `score / token_cost`，而路径/符号加成是按窗口平摊加进 `score` 的，于是"小但无关"的窗口凭平摊加成压过"大却相关"的窗口；同时 `hit_lines = content_hits or [...]` 让内容命中多的文件**不再把查询点名的符号定义行当作窗口中心**，点名的 `DEFAULT_EXCLUDES` 因此被丢弃。
3. **窗口越大，覆盖的文件越少**：召回只问"文件是否出现"，不问出现多少，因此把每文件窗口上限从 3 降到 1、窗口 token 上限从 220 降到 60，让同一份预算覆盖更多文件。
4. **点名的标识符窗口没有发射优先级**：即使符号定义行已进入窗口中心候选，发射哪一个窗口仍只看"命中密度"，于是查询点名 `DEFAULT_EXCLUDES` 时发出去的常常是同文件里更密的那一段。改为**查询点名的标识符所在窗口优先发射**（`named_symbol`，且覆盖更多点名标识符的窗口更优先），只有在没有点名标识符时才比较密度。
5. **模块常量不是符号**：`MAX_TERMS`、`DEFAULT_EXCLUDES`、`RECALL_TOLERANCE_PP` 这类模块级常量并未被符号提取覆盖，查询点名它们时命中不了"点名窗口优先"规则。新增 `constant` 提取模式（`^[A-Z][A-Z0-9_]{2,}\s*[:=]`），并把 `INDEX_VERSION` 升到 3 以强制旧索引重建。

第 4、5 两条都是**真实 A/B 的数据逼出来的**（见 §5），不是离线调参的产物。

任务集从 26 题扩到 50 题后复测（2026-10-11，50 题 × 1500 token、索引 schema 3、34 个文件；扩建的目的是让 2pp 的成功率预算可分辨）：

| 变体 | 平均 Recall | 达标（≥90%） | 中位包体积 | 未召回文件 | p50 / p95 |
|---|---|---|---|---|---|
| `raw`（中文自然语言） | **70.5%** | 20 / 50 | ≈1480 token | 3 | 49 / 74 ms |
| `hinted`（中文 + 标识符） | **98.5%** | 48 / 50 | ≈1440 token | 1 | 58 / 83 ms |

`hinted` 下只剩 1 个必召回文件（`docs/overview.md`）和 1 个符号（`DEFAULT_EXCLUDES`）未召回。

**退出标准：`hinted` 已达到**（98.5% ≥ 90%，包不变量与 p95 < 1s 同时满足）；`raw`（纯中文表达）经 §7 Phase 5 的 7.1 术语桥后为 **70.5%**，仍低于门槛。剩余缺口只剩一类，且不是"符号提取"问题：

- **中文提问 vs 英文代码**：标注要求召回的是英文实现文件，而纯中文提问只在中文文档与中文工程记忆里有词面命中（例如 `HIL-024` 要求 `indexer.py`，中文提问实际召回的是几篇提到"排除目录"的中文文档）。这是跨语言匹配，词法检索无法解决，对应 §6 的 Embedding 触发条件。

第一步记录的"同类候选之间的排序"缺口已由本步修复：路径匹配精确化、文件级加成不再被窗口体积稀释、点名的标识符窗口优先发射、单位预算覆盖更多文件，`hinted` 的文档类任务（`HIL-017`、`HIL-018`）现在都能召回。实测脚本、回归门与基线随之用 `--write-baseline` 重录（本次为**有意的检索改动**）。

曾一度**放弃**、这次**重新采纳并验证有效**的一条规则：为"查询直接写出的标识符所在窗口"保留发射名额。第一步只做了"保留名额"，它在 26 题上零可测效果，于是被删；第二步改为"优先于密度发射"后，26 题上 `hinted` 由 92.3% 升到 96.2%，并在真实 A/B 里救回了 4 道原本答错的题；扩到 50 题、再把模块常量纳入符号后为 98.5%（§5）。差别在于：保留名额不等于赢得排序。

计划内容：

状态：上面两处词法层缺陷已修正并量化；下列结构性改动尚未开始。

- 使用 Tree-sitter 替换正则符号提取；
- 构建 import、引用和调用关系；
- 加入 Git 最近变更和历史相关性；
- 增加索引 schema/version 迁移；
- 增加变更文件增量索引（检索时自愈 + 只重建漂移文件），**不引入文件监听**（裁决与依据见本节末"Phase 2 决策记录"）；
- 返回上下文选择原因及预算淘汰摘要；
- 保留本地词法检索作为强制回退路径。

退出标准：

- Context Recall 不低于 90%；
- 首次索引之外的检索 P95 小于 1 秒；
- 索引更新不会阻塞正常 Harness 工作流。

### Phase 2 决策记录：文件监听 vs 检索时自愈（2026-10-14）

冲突：`docs/overview.md` §7 声明"HIL 不监听文件变化"，而本节的计划项又把"文件监听"列入待做。需裁决。

实测（本仓库，37 个可索引文件、Windows、Python 3.14；取多次运行最小值）：

| 操作 | 耗时 |
|---|---|
| `discover_files`（ripgrep `--files`） | **134 ms**（几乎全是子进程启动） |
| `file_state`（stat 全部候选） | 6 ms |
| `staleness_reason`（发现 + stat） | 139 ms |
| `load_index(refresh=True)`（树新鲜） | 141 ms |
| `index_project`（全量重建） | 205 ms |
| `os.walk`（仅目录遍历） | 2.3 ms |

结论（三维度）：

- **检索质量**：自愈在**每次查询前**比对指纹（路径 + size + mtime），因此查询那一刻索引必然与磁盘一致；监听只是把这件事提前，不可能比自愈更准，反而多一个失败模式——编辑器原子写/重命名导致的漏事件会**静默陈旧**。→ **自愈 ≥ 监听**。
- **token 消耗**：两者都不直接消耗模型 token。间接地，"陈旧索引"会让返回包漏文件，迫使模型改用原生搜索，从而**增加输入 token**；自愈保证查询时不陈旧，是对 token 的**保护**，而监听一旦漏事件就会漏掉这层保护。→ **自愈 ≥ 监听**。
- **性能与工作流阻塞**：自愈每次查询付 ~140 ms（几乎全是 ripgrep 启动），发生重建的那次多付 ~65 ms（总计 205 ms）；监听的唯一收益是把这 ~140 ms 移出查询路径。但 205 ms ≪ 本节退出标准的 1 s，且监听需要**常驻进程**（HIL 是 per-call 的 STDIO MCP Server，没有 daemon 生命周期）并在 Windows 上更脆弱。→ 收益不抵成本。

**裁决：保留检索时自愈，删除"文件监听"**（与 overview §7 边界一致）。真正值得优化的是每次调用的自愈开销与重建代价，而不是引入监听：

- [x] **增量重建（2026-10-14 已完成）**：`index_project` 现在复用 schema 相同、size/mtime 未变的索引条目，只重读漂移文件；`--write-baseline` 无关，召回不变（已加单测 `tests/test_core.py::test_rebuild_reuses_unchanged_entries`）。**实测发现瓶颈不在读文件而在发现**：本仓库 `index_project` 全量 ~130 ms，其中 `discover_files`（ripgrep 启动）约 134 ms、读+解析仅约数十毫秒，因此增量重建对本仓库延迟几乎无改善（对超大仓库才有意义）。
- [ ] **降低每调用发现开销（已评估，暂不改）**：`os.walk` 实测 2 ms 远快于 ripgrep 启动（134 ms），但两条发现路径必须一致（`verify.py` 断言），若让自愈走不同于建索引的路径，可能因 `.gitignore` 语义差异造成指纹永不匹配→反复重建。当前 p95 ~240 ms ≪ 1 s 退出标准，故**不为此改动发现语义**。
- [x] **保持边界**：HIL 不监听文件变化。

### Phase 2 结构项记录（2026-10-14）

逐项实现并测量（50 题、1500 token、受控记忆库；对照为 §7.2a 的 G：raw 70.8%/21、hinted 98.0%/48）：

| 项 | 状态 | 结果 |
|---|---|---|
| 变更文件增量索引 | ✅ 已实现 | 复用未变条目；本仓库延迟收益小（瓶颈在 ripgrep 启动），对超大仓库才有意义 |
| 预算淘汰摘要 | ✅ 已实现 | `get_project_context.selection`（+单测） |
| Git 最近变更相关性 | ✅ 已实现 | 新模块 `history.py`（一次有界 `git log`，带 TTL 缓存；非 git 树返回空）。**仅对纯中文提问启用**：raw **73.3%/22（+2.5pp）**、hinted **98.0%/48（零变化）**；若对所有查询启用则 hinted 回退 −0.5pp，故按查询类型门控（与 §7.2a 同一原则：调用方已写出标识符时，新信号只会成为噪声） |
| schema/version 迁移 | ✅ 决策 | 由版本化重建 + 增量复用覆盖（见下） |
| import/引用/调用关系 | ❌ 未采纳 | 实现并测量（权重 1.0）：raw 72.8%/22、hinted **96.8%/46**，两个方向都变差 → 已回退，未入库 |
| Tree-sitter 符号提取 | ❌ 未采纳 | 实测对比（`tree-sitter 0.26` + `tree-sitter-python 0.25`）：tree-sitter **未发现任何正则漏掉的符号**，正则还额外覆盖模块常量；缺口不在符号提取。保持零依赖正则提取（AGENTS：dependency-light） |

**import/引用/调用关系（决定）**：曾实现"直接命中文件的 import 邻居加一个小权重"（`relations.py`，从索引文本解析 `from/import/require/from"…"`），在同语料受控 A/B 上使 `raw` 与 `hinted` **双双变差**，故回退、模块未入库。结论：在本任务集上结构相邻性不能替代词面证据。

**Tree-sitter（决定）**：实测对比见上表——tree-sitter 提取的是正则结果的子集（还漏掉模块常量），**没有任何正则会漏而 tree-sitter 会补的符号**；剩余缺口是窗口选择（§7.2a）与跨语言（§7.4），不是符号提取。因此**不引入该依赖**，保持 dependency-light 的正则提取。

**schema/version 迁移（决定）**：现有行为是"schema 版本不符 → 全量重建"，加上本次的增量复用（仅当版本相同才复用条目）。索引里的符号由源码派生，因此**改变符号规则只能重读源码**，不存在可原地迁移的 payload-only 变更；为假设中的未来变更预置迁移框架属投机基础设施（§8 精神）。故记录为"由版本化重建 + 增量复用覆盖"，**不引入迁移框架**。

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

### Phase 3 就绪状态（2026-10-11）

采集与判定的机制已就绪，真实 Harness 会话数据仍未填写——**因此本仓库依旧不得宣称任何 token 节省比例**。逐项对照：

| 计划项 | 落地实现 | 验证 |
|---|---|---|
| 随机分配 native / HIL | `measure.py --worksheet` 为每行记录 `seed` 与 `order`（两臂执行顺序随机、行序打乱），`--seed` 可复现 | `tests/test_measure.py::WorksheetRandomisationTests` |
| 记录 token / 工具结果 / 重试 / 正确性 | A/B 表新增可选字段 `retries`、`tool_result_tokens`、`cache_read_tokens`、`model`；`compare()` 报告中位工具结果体积与 prompt-cache 读取量 | `ArmFieldValidationTests`、`Phase3GateTests` |
| 跨 Harness 记忆复用 | `.ai-memory` 存放在目标项目内，两个独立 Harness 进程共享；新增端到端验证 | `tests/test_cross_harness_reuse.py`、`verify.py` 的 `cross-harness memory reuse` 检查 |
| 召回不足时回退原生搜索 | `get_project_context` 返回 `sufficient` 与 `fallback`；空包不再被当作答案 | `tests/test_embeddings.py::FallbackSignalTests` |
| 分离检索收益与 caching / 模型差异 | `cache_read_tokens` 与 `model` 被记录并报告（**不作门槛**，避免把 caching 收益误记为检索收益） | `Phase3GateTests` |

判定门槛全部就位：中位 token 降低 ≥20%、Recall ≥90%、成功率下降 ≤2pp、**平均重试次数不增加**、**跨 Harness 复用成功**（后两项为本次新增）。缺少 `--reuse-file` 时复用门只报告不拦截，以兼容 Phase 3 之前已填写的旧表；一旦提供即纳入判定。

数据状态：**已完成首次真实采集**（2026-10-11）。`benchmarks/results/ab.jsonl` 的 `openclaw` 行由脚本从真实 Harness 会话写入，共 50 组 native/HIL 数据。

### Phase 3 首次真实 A/B（2026-10-11，结论：**未通过——召回门槛失败**）

> **更正（2026-10-12）**：本记录初稿把 `hinted` 召回归档（98.5%）填进了 `--recall-file`，但这 50 组运行实际使用的是 `tasks.jsonl` 的 **`raw` prompt**（用户会自然写出的中文提问）。判定必须与运行口径一致，因此正确值是 `raw` 召回 **50.8%**。用正确口径复算后 **Context Recall 门槛失败**，Phase 3 未通过。这条更正本身也说明：拿 `hinted` 达标去代表整体通过，是把测量口径当成了产品能力。

方法与有效性：

- 被测 Harness 为本机 OpenClaw 网关（`127.0.0.1:18789`）跑 `deepseek-v4-flash`；为让 HIL 臂真实调用，用 `openclaw mcp add` 注册了 `hil`（指向本仓库 `run_hil_mcp.py`）+ `mcp reload`，**未重启网关**，可 `mcp unset hil` 撤销。
- **50 题** × 2 臂，**输入使用 `raw`（纯中文）prompt**，即用户自然提问、不做标识符改写——这是本项目要服务的正常输入；**每次运行使用全新 session id**；token 取自 agent 自己返回的 `usage`，`input_tokens` 记 `input + cacheRead`（总模型输入），`cache_read_tokens` 单独记录以分辨缓存与检索收益。
- 臂有效性经 transcript 的 `toolResult.toolName` 核验：HIL 臂每轮都真的调用了 `get_project_context`，native 臂一次都没有。
- 跨 Harness 复用由两个真实 Harness 双向完成：OpenClaw 经 `hil__record_project_memory` 写入、OpenCode 经自己的 `hil` MCP 读回；反向亦然。回执见 `benchmarks/results/reuse.json`。
- 未做随机分组（固定 native → hil），单轮运行因此 `retries` 恒为 0（该门槛通过但没有信息量）。

判定（`--recall-file` 使用与运行口径一致的 `raw` 召回归档，`--reuse-file benchmarks/results/reuse.json`，**退出码 1**）：

| 门槛 | 结果 | 判定 |
|---|---|---|
| 中位输入 token 降低 ≥ 20% | **43.1%** | PASS |
| Context Recall ≥ 90% | **50.8%**（`raw`，运行时口径；§7.1 术语桥后同一 50 题为 70.5%，仍 FAIL） | **FAIL** |
| 平均重试次数不增加 | 0.00 → 0.00 | PASS（单轮，无信息量） |
| Task Success Rate 下降 ≤ 2pp | 100% → 100%（0.0pp） | PASS |
| 跨 Harness 记忆复用 | 2/2 事实被另一个 Harness 读回 | PASS |

参考量：中位工具结果体积 12317 → 3895 token；中位 prompt-cache 读取量 150592 → 89216（用 `cache_read_tokens` 记录，避免把缓存收益误记为检索收益）。

**为什么"成功率 100%"不等于"检索可用"**：两臂都在 1M 上下文、自带文件工具的 agent 上运行。`raw` 提问下 HIL 只召回 50.8%，但模型自己探索也能答对。所以本次 token 下降**不能归因于检索质量**——它主要来自"HIL 臂被要求先取上下文再作答"这一调用差异（§5 计划里要分离的正是这个）。召回门槛失败说明：**对用户正常写出的中文提问，HIL 目前并不真正够用。**

过程与修复（这些修复仍然有效，但它们服务的是含标识符的表达）：首轮 26 题时 HIL 臂答错 5 题（成功率掉 19.2pp），根因是"只发射最密的那个窗口"，模型拿到文件却拿不到要点；改为**点名标识符窗口优先发射**后回到 96.2%。扩建到 50 题后又有 2 题失败（`HIL-011` 的 CLI 退出码 2、`HIL-035` 的 `MAX_TERMS`），根因是**模块常量没有被提取成符号**；新增 `constant` 提取模式并把 `INDEX_VERSION` 升到 3 后两题均答对。这些修复把 `hinted` 召回推到 98.5%，但**对 `raw`（50.8%）没有帮助**——`raw` 的缺口是跨语言，由 §7 **Phase 5** 的 7.1 术语桥处理（已把 `raw` 提到 70.5%，仍低于门槛）。

**样本量说明**：50 题的粒度是 2.0pp/题，因此 2pp 预算现在可分辨（此前 26 题是 3.85pp/题，无法分辨）。


## 6. Phase 4：按证据扩展

只有出现对应证据时才实施：

- 词法检索无法满足 Recall：增加可选 Embedding 和 Reranker；
- 代码修改质量无法统一比较：增加 Unified Validator（**已移入 §10.4 Phase 6 待做**：先定义"质量"与生成判定集，再据证据决定是否实施）；
- 已积累至少 100 个可比任务结果：增加 Model Router；
- 本地索引性能成为瓶颈：评估 FAISS、Qdrant 或其他向量存储。

### Phase 4 证据门（2026-10-11）

`benchmarks/evidence.py` 把四条触发条件变成可从已记录证据判定的报告，避免凭"想要"开工：

| 触发条件 | 证据来源 | 当前判定 |
|---|---|---|
| 词法 Recall 不达标 → Embedding + Reranker | `results/baseline.json` 的两变体召回 | **FIRED**：`hinted` 98.5% 已达 90% 门槛，但 `raw` 70.5% 仍低于门槛（跨语言缺口）。**2026-10-14 已量化**：真实多语言重排（`intfloat/multilingual-e5-small`）`raw` 70.8% → 71.8%（+1.0pp）、`hinted` 不回退，但 p50 ≈ 3.7 s / p95 ≈ 4.3 s **超 1 s 门槛**，故保持可选、默认关闭（见 §7.4） |
| 代码修改质量不可统一比较 → Unified Validator | `results/quality.json`（人工判定的修改集合） | 未举证：尚无该文件（已移入 §10.4：先定义质量与判定集，再据证据决定是否实施） |
| ≥100 个可比任务结果 → Model Router | `results/ab.jsonl` 已填写的行数 | **FIRED（2026-10-15）**：已填 **100 条**（OpenClaw 50 + Cline 50）。`evidence.py` 现报 FIRED；触发只表示证据出现，不代表必须开工 |
| 本地检索成为瓶颈 → FAISS / Qdrant | `.hil/results/` 最新报告的 p95 延迟 | 未举证：p95 约 80–120 ms，远低于 1000 ms |

触发条件①的缺口现在只剩 `raw`（跨语言），具体优化方案见 §7 **Phase 5**——先做轻量、可审计的跨语言桥（7.1 术语表 / 7.2 语料自举），只有它们仍不足时才回到本条引入模型。已实现的**可选**语义重排（`src/harness_intelligence/embeddings.py`）是这条重解法的管道：

- 三种后端：`sentence-transformers`（本地多语言模型）、`http`（OpenAI 兼容 `/embeddings`）、`hash`（离线确定性，仅用于打通链路与测试，**不是语义模型**）；
- 默认 `HIL_EMBEDDINGS=off`，核心检索不引入任何新依赖；
- 任何一环失败（未装包、端点不可达、响应格式异常、查询中途抛错）都回退本地词法排序，调用不会因此失败；
- 只对词法排序后的前 40 个候选重排，权重 0.5，词法分仍是主要证据；
- **不作召回声明**：`hash` 后端在本仓库 50 题上实测与纯词法完全一致（`hinted` 98.5%、达标 48/50），因此它只证明链路可用；真正的语义收益需要用 `benchmarks/measure.py --embedding auto` 在装有对应模型的环境里量化后才能提及。**2026-10-14 已在装有 `intfloat/multilingual-e5-small` 的机器上量化：`raw` +1.0pp、`hinted` 不回退、p50 ≈ 3.7 s（超 1 s 门槛）**，见 §7.4。

其余三条保持"未触发/未举证"，不预置基础设施。


## 7. Phase 5：跨语言召回（待做）

进入条件：Phase 3 的**召回门槛失败**，原因正是 **`raw`（纯中文、用户自然写出的提问）首次测得 50.8%**（7.1 术语桥后为 70.5%，仍低于门槛）。`raw` 不是"可选写法"——它是用户真正会用的输入；`hinted`（把标识符写进查询）只是诊断用的上限参考，不能当作产品能力。根因已定位（§4）：中文提问与英文实现之间缺少词面重叠。Phase 4 ①（可选 Embedding + Reranker）是这条缺口的"重"解法；Phase 5 先做**轻、可审计、可回退**的跨语言桥，用最低代价把**正常使用**补齐。

目标（与 Phase 2/3 同一口径）：

- `raw` 平均 Recall ≥ 90%（7.1 后当前 70.5%）；
- `hinted` 不回退（当前 98.5%）；
- 检索 p95 < 1s（当前约 82 ms）；
- 不引入强制依赖；任何新增后端不可用时回退本地词法检索；
- 每项改动都要有 `benchmarks/measure.py` 的 `raw` / `hinted` 前后对照，且 `benchmarks/verify.py` 全绿。

方法（按代价从低到高，逐项验证有效再进入下一项）：

### 7.1 项目内中英术语桥（无依赖，优先做）

- 新增一份**人工维护、可 review** 的中英术语表（例如 `src/harness_intelligence/glossary.py`）：`索引→index`、`陈旧→stale`、`重建→rebuild`、`预算→budget`、`片段→fragment`、`符号→symbol`、`记忆→memory`、`检索→retrieval`、`回退→fallback`、`指纹→fingerprint` 等。
- 查询时对中文词项做**双语扩展**：命中术语表的中文串同时产出对应英文词/标识符，并入检索词集；扩展词的权重不高于原始词项，避免压过 `hinted` 已正确的排序。
- 术语表只允许收录**开发者本来就会写出的术语与标识符**，不得包含仓库文件路径（与 `hints.jsonl` 同一条规则）。
- 风险：覆盖有限；错误映射会引入噪声。用回归门 + 逐题诊断把关。

**7.1 状态（2026-10-12，已完成）**：新增 `src/harness_intelligence/glossary.py`——人工维护、可 review 的中英术语表（约 100 条，`索引→index`、`陈旧→stale`、`预算→budget`、`检索→retrieval`…），并在查询侧接入（`retrieval.query_terms` / `memory.search_memory`），内容侧不扩展。50 题实测：

| 变体 | 7.1 前 | 7.1 后 | 达标 |
|---|---|---|---|
| `raw`（纯中文） | 50.8% | **70.5%** | 20 / 50（仍 < 90%） |
| `hinted`（含标识符） | 98.5% | **98.5%** | 48 / 50（**零回退**） |

关键设计：**术语桥只做"可达性"，不参与排序**（`EXPANSION_HIT_WEIGHT = 0.0`）。实测任何正权重都会回退 `hinted`（0.1–0.3 时 98.0%、0.4 时 97.5%），因为它让词典猜测去和调用方亲口写出的标识符竞争，而只换来约 +3pp 的 `raw`。因此扩展词只影响"某个文件是否可能被找到"（路径/符号命中、以及无字面命中时的窗口中心），不抬高片段密度分。新增 `tests/test_glossary.py`（含"英文查询不受影响""词表不得含路径""表必须小到可 review"）。

结论：7.1 **有效但不足以达标**（`raw` 70.5% < 90%），按计划进入 **7.2 语料自举双语词典**；`hinted` 保持 98.5%。

**§7.2a 状态（2026-10-14，已完成）：不让窗口选择在纯扩展命中下退化**

诊断：`raw` 31 题失败中 **27 题只是 `missing_symbols`（文件已召回）**；根因是 `retrieval._entry_candidates` 的窗口排序键 `(named_hits, weighted_hits, span)`，而 `weighted_hits` 在 `EXPANSION_HIT_WEIGHT=0.0` 下对纯中文提问恒为 0，排序退化到"最小/最靠前的窗口"，常发射**一行空行**（HIL-013 曾发射 `memory.py [74,74]`，标签 `expanded_hits:0.0`）。

同语料受控 A/B（50 题、1500 token、**受控记忆库**；对照为当前语料上的 HEAD 代码 raw 68.8%/19、hinted 98.0%/48）：

| 配置 | raw | hinted |
|---|---|---|
| HEAD（对照） | 68.8% / 19 | 98.0% / 48 |
| A：仅把"非空行"放进排序键 | 68.8% / 20 | 96.5% / 47 |
| B：扩展命中无条件驱动窗口 | 70.8% / 23 | 94.0% / 45 |
| D：符号定义无条件分层优先 | 73.3% / 26 | 93.0% / 43 |
| E：条件化（仅无字面命中的文件） | 71.5% / 21 | 96.5% / 47 |
| F：符号/扩展按权重计入窗口分 | 70.3% / 22 | 94.0% / 45 |
| H：仅过滤纯空白窗口 | 70.5% / 21 | 98.0% / 48 |
| **G（采纳）= H + 条件加权** | **70.8% / 21** | **98.0% / 48** |

结论：真正有效的是 **"绝不发射纯空白窗口"**（H 单独已得 +1.7pp）；无条件的符号/扩展优先级会回退 `hinted`（B/D/F：−2.5 ~ −5pp）。采纳 **G**：`hinted` 零变化、`raw` **+2.0pp**（新增 `tests/test_bridge_window.py`）。**远未达 90%**，剩余缺口需 §7.2（扩大术语覆盖面）与 §7.4（语义模型）。因是**有意的检索改动**，基线本应 `--write-baseline` 重录；但本地记忆库漂移（§10.1）会污染基线，故**暂缓重录**直至 §10.1 的受控记忆库测量落地（CI 无记忆库，回归门仍可判）。

### 7.2 语料自举的双语词典（无依赖）

- 从仓库自身的**中英混排文本**（中文注释/文档里夹英文标识符）挖掘共现：同一窗口内出现的 CJK n-gram 与英文标识符统计成候选映射，落成**可 review、可版本化的数据文件**。
- 与 7.1 的分工：7.1 是人写的，精确但覆盖小；7.2 是机器统计，覆盖大但需要阈值与人工抽检。
- 风险：过拟合到本仓库语料；必须在 50 题上验证，并抽检错误映射。

**7.2 状态（2026-10-14）：已实现并评估，结论是"不采纳"**

- 已实现 `benchmarks/mine_bilingual.py`：与索引同一条发现路径；CJK 侧复用 `terms.extract_terms`（键与查询一致）；英文侧取 `terms.identifier_parts`；**邻近约束** `PROXIMITY=10`（英文词须靠近中文 n-gram）＋专有词停用表；`--holdout` 可排除指定任务依赖的文件。
- 生成两版并人工审查：**整行共现**（噪声大，如 `文件→hil`、`项目→hil`、`中文→raw`）与**邻近约束**（仍以元讨论/函数词为主，如 `中位输→token`、`以请把→get_project_context`、`只写→version`）。根因：中文文档大量讨论项目专有英文词。
- 接入并测量（50 题、受控记忆库）：

| 术语表 | raw | hinted |
|---|---|---|
| 无自举表（= §7.2a 的 G） | 70.8% / 21 | **98.0% / 48** |
| 整行共现表 | 72.3% / 22 | 95.0% / 46 |
| 邻近约束表 | 72.3% / 21 | 97.0% / 47 |

- 结论：`raw` 仅 +1.5pp，`hinted` 回退 −1.0 ~ −3.0pp，违反"`hinted` 不回退"；且 §7.1 人工表**已覆盖有用领域词**，自举表只额外引入元讨论噪声。按"错误映射比没有映射更有害"，**不采纳**——`glossary_auto.json` 不入库、`glossary.py` 接入已回退，脚本保留为离线审查工具。→ 按计划进入 §7.3 与 §7.4。

### 7.3 调用策略侧的兜底（不改检索）

- 在 `notice` 与文档中明确"纯中文提问请补标识符"。这一步不提升 `raw` 的机械召回，只是把已知限制讲清楚，避免把 `raw` 的表现误当成系统缺陷。

**7.3 状态（2026-10-14，已完成）**：`get_project_context` 的 `notice` 现在在**纯中文提问**（查询词项里没有任何 ASCII 标识符）时追加一句 "Chinese-only question: recall is lower; add known identifiers (file or symbol names)… - see docs/usage.md"；带标识符的查询不追加。新增 `tests/test_bridge_window.py` 两条断言。文档侧（README/`docs/usage.md`）此前已写明该限制。

### 7.4 若 7.1 / 7.2 仍不足：回到 Phase 4 ①

- 把 §6 ① 的触发证据正式落到"`raw` 未达标"，再评估引入可选多语言模型（`sentence-transformers` 或 HTTP embedding 端点）。**更正（2026-10-14）**：本机实测可联网（`https://pypi.org/simple/` HTTP 200）、`sentence-transformers` 可安装，因此"无网络不可执行"的旧表述作废，7.4 在本机**可执行**。

**7.4 状态（2026-10-14，已量化）**：安装 `sentence-transformers 6.1.0` + `torch 2.14.1`（Python 3.14），用默认多语言模型 `intfloat/multilingual-e5-small` 跑 `measure.py --embedding auto`（50 题、受控记忆库）：

| 臂 | raw | hinted | p50 / p95 延迟 |
|---|---|---|---|
| 词法（§7.2a 的 G） | 70.8% / 21 | 98.0% / 48 | ~0.21 / 0.24 s |
| 语义重排（e5-small） | **71.8% / 22** | **98.0% / 48** | **3.7 / 4.3 s** |

结论：真实多语言语义重排对 `raw` 仅 **+1.0pp**、`hinted` 不回退，但延迟 **p50 ≈ 3.7 s / p95 ≈ 4.3 s**，**远超"检索 p95 < 1 s"的退出标准**。因此：① 语义后端维持**可选、默认关闭**（符合 §8）；② **小多语言模型不足以补齐 `raw` 缺口**——对本任务集而言跨语言缺口不只是词面问题，模型也未能大幅挽回；③ 若要在本机作为可用特性，必须先解决延迟（缓存候选向量、批量化、更小/量化模型）再重新量化。

待做项（按顺序）：

**Phase 5 §7.1（已完成，2026-10-12）**

- [x] **7.1 术语桥**：`glossary.py` 术语表 + 查询侧扩展 + `tests/test_glossary.py`（含"英文查询不受影响""词表不含路径""表小到可 review"）
- [x] **7.1 度量**：`raw` 50.8% → **70.5%**、`hinted` 98.5% 零回退、p95 71 ms、`verify.py` 全绿、140 项测试通过

**Phase 5 §7.2 语料自举双语词典（下一步）**

- [ ] **挖掘脚本** `benchmarks/mine_bilingual.py`：扫描仓库内中英混排行（同一行/同一注释块里同时出现 CJK 与 ASCII 标识符），统计 `CJK n-gram ↔ 英文标识符词` 的共现次数，并保留来源行
- [ ] **产出数据文件** `benchmarks/glossary_auto.json`（是数据、不是代码）：每条 `{"zh": ..., "en": ..., "count": ..., "examples": [...]}`，带最小共现阈值
- [ ] **人工抽检**：抽样约 30 条，剔除明显错误映射——**错误的映射比没有映射更有害**
- [ ] **接入**：术语桥先查人工表、再查自举表；仍保持 `EXPANSION_HIT_WEIGHT = 0.0`（只做可达性、不参与排序）
- [ ] **度量**：`measure.py` 的 `raw` / `hinted` 前后对照 + `verify.py` 全绿；目标 `raw` ≥ 90%，且 `hinted` 不回退
- [ ] **防过拟合**：用"留出任务"验证（例如只用前 40 题的语料建表，在其余 10 题上验收），避免只对本仓库语料有效

**Phase 5 §7.3 / §7.4（兜底与升级）**

- [ ] **7.3 文案**：`notice` 与文档措辞（若 7.2 未达标则必做）
- [ ] **7.4 升级**：若 7.2 后 `raw` 仍 < 90%，把 §6 ① 的证据正式更新为 FIRED，并跑 `measure.py --embedding auto`（**2026-10-14 更正：本机可联网、可安装多语言模型，可执行**）

**Phase 3 收尾（与 Phase 5 并行）**

- [ ] **第二 Harness**：注册并跑 Cline 的 50 题对照，使 `ab.jsonl` 达到 **100 条**可比结果——这会顺带解锁 §6 ③ Model Router 的证据门槛
- [ ] **分离检索贡献与调用差异**：做"只差上下文包"的对照实验——两臂用**同一句指令**，一臂注入 HIL 上下文包、另一臂不注入。否则现有的 43.1% token 下降无法归因（`raw` 召回只有 50.8% 时模型仍 100% 答对，说明主要靠它自己探索）
- [ ] **数据与代码对齐**：现有 `ab.jsonl` 的 HIL 臂是 7.1 之前的检索；若要保持"证据对应同一版检索"，需在 7.2 定稿后重跑 HIL 臂

**复核（每次改动）**

- [ ] `verify.py` 全绿且 `hinted` 不回退；基线随有意的检索改动用 `--write-baseline` 重录，并随提交一起 review

明确不做（沿用 §8）：

- 不引入在线翻译 API，不把词表做成不可 review 的黑盒；
- 不在没有 benchmark 的情况下宣传 `raw` 提升；
- 不为 `raw` 强制依赖云 Embedding、Qdrant 或 Cross-Encoder。

## 8. 明确不做

- 新 Agent Loop；
- 通用 Shell 或文件编辑工具；
- Session Manager；
- Sub-Agent 框架；
- 自动保存完整聊天流水账；
- V0.1 强制依赖云 Embedding、Qdrant 或 Cross-Encoder；
- 在没有 A/B 数据时宣传固定 token 节省比例。

## 9. 下一步优先级

1. **已完成**：三轮检索修正 + Phase 5 的第一步。第一轮——中文词项切分（连续中文串拆为 2/3 字 n-gram）与文档片段排序（片段级评分 + 受 token 上限约束且互不重叠的窗口）。第二轮（2026-10-11）——路径匹配精确化、文件级加成不再被窗口体积稀释、点名的标识符窗口优先发射、每文件一个窄窗口以覆盖更多文件。第三轮（同日晚，由 A/B 失败题推动）——点名标识符窗口优先于密度、模块常量纳入符号、`INDEX_VERSION` 升到 3。第四轮（2026-10-12，Phase 5 §7.1）——查询侧中英术语桥（`glossary.py`），只做可达性、不参与排序。结果：26 题上 `raw` 26.9% → 47.8%、`hinted` 65.7% → 69.9% → 96.2%；扩到 **50 题**后 `raw` 50.8%、`hinted` 98.5%；术语桥后 `raw` → **70.5%**、`hinted` 保持 98.5%。`hinted` 已达 90% 退出标准；**Phase 3 的召回门槛在以 `raw` 为输入的正式对照下失败**（§5），跨语言缺口是当前第一优先。基线已随改动 `--write-baseline` 重录，完整验证见 §4。
2. **两个 Harness 的 50 题 × 2 臂真实对照已完成**：OpenClaw（§5）+ Cline（§11 D）。`ab.jsonl` 达 **100 条**，§6 ③ Model Router 触发随之 **FIRED**。判定：**召回门槛仍 FAIL**（`raw` 69.5% < 90%），token/成功率/重试/复用四项 PASS，`--compare` 退出码 1。跨语言缺口仍是第一优先（§7）。
3. 汇总未召回文件、重复片段和无关上下文（脚本已输出这些字段）。
4. `hinted` 召回已达 90%（98.5%），"是否投入 Tree-sitter 与增量索引"的决策点已经到达。**现有证据仍提示 Tree-sitter 解决不了剩余缺口**：未召回的不是"符号没被提取"，而是纯中文提问与英文实现之间缺少词面重叠（§4）。
5. **Phase 5（跨语言召回，§7）**：7.1 术语桥**已完成**（`raw` 50.8% → **70.5%**，`hinted` 零回退）；下一步 7.2 语料自举双语词典。只有两者仍不足，才回到 Phase 4 ① 引入可选多语言模型（需能安装模型）。
6. 达到数据量门槛（≥100 条可比结果）后再讨论 Validator 和 Model Router。
7. **Phase 6 候选**（§10）：记忆库增长挤占预算导致召回随使用时间下降（§10.1，已记录、待优化）、标识符词形匹配（§10.2）、文档一致性修正（§10.3）、Unified Validator 与质量判定集（§10.4，由 Phase 4 ② 移入）；触发式，不占用 Phase 4/5 的推进顺序。

## 10. Phase 6 候选：上下文预算与记忆配额（待做）

进入条件：出现与"检索实现"无关、却会**稳定压低召回或让召回不可复现**的证据。当前已有一条成立，另有若干条为候补；与 Phase 4 一样是触发式，不预置基础设施。

### 10.1 记忆库增长挤占 token 预算，召回随本地记忆增长而下降（**已记录，待优化**）

证据（2026-10-14 基线复核；工作区干净、未改任何代码）：`python benchmarks/verify.py` 报 2 项 FAIL——`tasks meeting target hold` 对 `raw`（20→17）与 `hinted`（48→45）。受控实验（把 `.ai-memory/` 临时改名后复测再还原）：`raw` 69.5%/19 → **71.5%/22**，`hinted` 94.8%/45 → **98.0%/48**，两项 FAIL 消失且达到/超过记录基线（`raw` 70.5%/20、`hinted` 98.5%/48）。

根因：`.ai-memory/` 片段与源码片段**共用同一条 token 预算**（`retrieval.get_project_context` 的 `memory_cap = token_budget // 4` 与统一 `used` 累加），本地记忆库增长会挤出代码片段。

影响两面：

- 产品面：真实项目的工程记忆会长期增长，不处理则 HIL 召回会**随使用时间下降**，与"越用越准"的预期相反；这正是 acceptance metric「Context Precision」要回答的问题；
- 测量面：`.ai-memory/` 不入库（`.gitignore`），本地与 CI 记忆库规模不同，使同一版代码的召回数值**不可直接跨机比较**（见 `benchmarks/README.md` §6）。

待做（方案未定，属 Phase 6）：

- [ ] **量化**：不同记忆库规模下记忆片段占用的预算与代码片段召回的"挤出曲线"（`raw` / `hinted`）
- [ ] **配额**：让记忆与代码各有独立上限，或让记忆片段按与任务的相关度竞争预算，而不是先占后选
- [ ] **可复现**：让 `measure.py` / `verify.py` 在受控记忆库（清空或固定 fixture）下运行，使数值可跨机比较；`baseline.json` 一并记录记忆库规模
- [ ] **回归门**：把"记忆库规模"写进回归门的前提说明，或改造"达标题数"门使其不被记忆库漂移触发

### 10.2 标识符词形匹配（候选，取决于 Phase 5 §7.2 的取舍）

`terms.identifier_parts` 目前用精确集合交集，因此 `工具→tool` 对不上 `EXPECTED_TOOLS`（parts 为 `tools`）、`排除→exclude` 对不上 `DEFAULT_EXCLUDES`（`excludes`）、`测试→test` 对不上 `CrossHarnessReuseTests`（`tests`）。这是**通用检索**改动（`raw` / `hinted` / 英文查询都受影响），不是跨语言专属：若作为 Phase 5 §7.2 术语桥的补充而做，就留在 Phase 5；若目标是提升整体检索质量，则归 Phase 6。

### 10.3 文档与已更正结论的一致性（候选，属流程而非能力）

2026-10-12 对 §5 的更正（Phase 3 **召回门槛失败**，运行时口径为 `raw` 50.8%、退出码 1）此前未传播到其它文档；**已于 2026-10-14 全部修正**。曾断言"全部通过"的位置：

- `docs/overview.md` §6："首次真实跨 Harness A/B 已通过全部门槛……召回 98.5%……`--compare` 退出码 0"；
- `docs/roadmap.md` §9 第 2 条："五道门槛全部通过（§5）"；
- `benchmarks/README.md` §7："原生执行基线：尚未填写（`ab.jsonl` 的 52 行两臂仍为 `null`）"（实际 `ab.jsonl` 为 **50** 行且两臂已填）；
- `docs/usage.md` 与 `docs/roadmap.md` §2 的"原生基线尚未填写 / 未完成"。

以上各处已于 2026-10-14 全部修正（`overview §6`、`roadmap §2/§3/§9`、`benchmarks/README §7`、`usage.md`），并用实测更正了"本机无网络"的旧表述（§7.4）。**此条关闭。**

### 10.4 Unified Validator（由 Phase 4 §6 ② 移入）与"质量"的定义、判定集

Phase 4 §6 ② 的进入条件是"代码修改质量无法统一比较"，`evidence.py` 目前判定为 **NOT EVIDENCED**（无 `benchmarks/results/quality.json`）。按本次决定把它**从 Phase 4 移入 Phase 6 待做**：先定义质量与判定集，再据证据决定是否实现组件。

#### 10.4.1 "质量"的定义（草案）

对 HIL 而言，"一次代码修改的质量" = 给定 `tasks.jsonl` 的任务与其 `success_criteria`，对该 Harness/模型产出的改动做**统一、与 Harness 无关**的判定。四个维度：

| 维度 | 含义 | 可自动化程度 |
|---|---|---|
| 正确性 Correctness | 改动满足 `success_criteria` | 部分（判据可机检时全自动，否则需评委/人工） |
| 安全性 Safety | 既有测试仍通过、无新增 lint/type 错误、公开契约不变 | 高（跑测试与静态检查） |
| 范围恰当 Scope | 只改必要文件，无无关改动 | 高（diff 涉及文件与 `required_files` 比对） |
| 可追溯 Traceability | 改动引用/命中必召回文件与符号（回指 Context Recall） | 高（diff 与索引交集） |

"统一"的含义：**同一套 rubric + 同一份证据**（`git diff` + 测试/检查结果）应用到每个 Harness 的输出上，使跨 Harness/模型的质量可比——这正是"统一比较"要解决的事。

#### 10.4.2 判定集（`benchmarks/results/quality.json`）从哪来 / 以什么标准生成

路径已由 `evidence.py` 固定，无需新约定。来源按可靠性排序：

1. **真实 A/B 抽取（主来源）**：跑 Phase 3 的 D（第二/第三 Harness 对照）时，为每一步留存该任务的 `git diff` 与测试结果，自然形成 `(task, harness, model, patch, tests)` 记录。
2. **可机检子集（客观、零人工）**：`success_criteria` 能被测试/命令判定的任务（如 CLI 退出码、模块常量取值）直接记 pass/fail。
3. **人工 golden 子集**：对若干 `task × arm` 输出按 §10.4.1 的 rubric 人工打分，用于校准任何自动评分，并提供"质量是否真的不可比"的**证据本体**。
4. **合成对照（负样本）**：注入已知正确/已知错误的补丁（回退某个修复、植入一个 bug）作为正负控制，保证判定器**有区分力**——否则"全过"是假信号。

生成标准（每条必须可复现）：

- 字段：`{task_id, harness, model, patch_hash, patch_ref, tests_passed, lint_clean, files_touched, rubric:{...}, label, evidence}`；
- 规模：≥30 条人工判定 × ≥2 个 Harness × ≥2 个分类，外加 ≥10 条负样本；
- 去偏：人工子集要么 rubric 足够明确，要么 ≥2 名判定者，避免单一判定者偏差；
- 可复现：`patch_hash` + 测试命令 + 结果必须可重放；缺失即视为未填写（与 A/B 表的 `evidence` 同规则）。

验收（何时从"待做"转为"实施"）：只有当判定集能显示**同一任务下不同 Harness 的改动质量确实不可统一比较**时，才实施 ②；否则保持 `NOT EVIDENCED`，不预置组件（与 §5/§6/§8 的纪律一致）。

## 11. 补齐记录（2026-10-14）

按"先补齐前序阶段、再 D→A→B→C"的顺序执行；每步都跑测试并如实记录，未通过处分析原因后改进。

### P1 文档一致性 + Phase 0/1 收口（**已完成**）

- 修正与 §5 更正矛盾/过期的表述：`roadmap §2/§3/§9`、`overview §6`、`benchmarks/README §7`、`usage.md`；并把"本机无网络"更正为**实测可联网**（§7.4）。
- Phase 0 状态改为"OpenClaw 侧已完成"；Phase 1 的"仍需完成"三项收口（第 3 项已完成，前两项并入 Phase 3）。
- 测试：`measure.py --compare --recall-file <raw> --reuse-file reuse.json` → **退出码 1**（召回 69.5% < 90%，与 §5 一致）；单元测试 154 项通过。

### P3 Phase 2 结构项（**已完成**）

- [x] **增量重建**：`index_project` 复用 schema 相同、size/mtime 未变的条目，只重读漂移文件；单测 `test_rebuild_reuses_unchanged_entries`。实测本仓库瓶颈在发现（ripgrep 启动 ~134 ms）而非读文件，故对本仓库延迟收益小、对超大仓库才有意义。
- [x] **预算淘汰摘要**：`get_project_context` 新增 `selection` 元数据（candidates/selected/evicted/evicted_top/memory_*）；单测 `test_selection_summary_accounts_for_the_budget`。
- [x] **文件监听决策**：保留检索时自愈、删除监听（§4 决策记录）。
- [x] **Git 最近变更相关性**：新模块 `history.py`（一次有界 `git log` + TTL 缓存；非 git 树返回空）；**仅对纯中文提问启用** → raw **73.3%/22（+2.5pp）**、hinted **98.0%/48（零变化）**；单测 `tests/test_history.py`。
- [x] **import/引用/调用关系**：实现并测量后**回退**（raw 与 hinted 双双变差，见 §4）。
- [x] **Tree-sitter 符号提取**：实测对比后**不采纳**（tree-sitter 未发现任何正则漏掉的符号，见 §4）。
- [x] **schema/version 迁移**：决策为由版本化重建 + 增量复用覆盖，不引入迁移框架（见 §4）。

### P5 Phase 4（**结论已给出**）

- [x] **① Embedding + Reranker 的真实收益**：由 §7.4 量化（raw +1.0pp、hinted 不回退、p50 3.7 s 超门槛）→ 保持可选、默认关闭。`evidence.py` 的 FIRED 结论已更新。
- [x] **② Unified Validator 的"质量定义 + 判定集生成标准"**：已在 §10.4 拟定（四维 rubric、`quality.json` 字段/规模/去偏/可复现要求、四类来源）；**实际判定集需在 D（真实对照）中采集**，故组件保持 `NOT EVIDENCED`、不预置。

### P4 Phase 5（**基本完成**）

- [x] **§7.2a**（详见 §7.2a 状态）：`raw` 68.8% → **70.8%**（受控记忆库，+2.0pp，19→21 题），`hinted` 98.0% **零变化**；新增 `tests/test_bridge_window.py`。A–H 共 8 组同语料 A/B，证明了"空白窗口"是主因、无条件优先级会回退 `hinted`。
- [x] **§7.2 语料自举词典**（详见 §7.2 状态）：脚本 `benchmarks/mine_bilingual.py` 已实现；两版数据均以噪声为主并让 `hinted` 回退，**结论不采纳**（数据未入库、接入已回退）。
- [x] **§7.3 文案兜底**：纯中文提问的 `notice` 提示已实现（+测试）。
- [x] **§7.4 语义模型量化**（详见 §7.4 状态）：装 `sentence-transformers 6.1.0` + `torch 2.14.1`，跑 `--embedding auto`（`intfloat/multilingual-e5-small`）：`raw` 71.8% / 22、`hinted` 98.0% / 48，但 p50 ≈ 3.7 s / p95 ≈ 4.3 s **超 1 s 门槛** → 语义后端保持可选、默认关闭。

### 结果与失败分析

- 每阶段的测试命令与数值见各节；未通过项均已记录原因并改进（例：§7.2a 的 B/D/F 回退 `hinted`，改为 G；§7.2 自举表回退 `hinted`，结论不采纳）。
- 当前 `verify.py` 本地唯一 FAIL 为 §10.1 的记忆库漂移；CI 无 `.ai-memory`，回归门不受影响。

### P6 汇总（**已完成**）

- `docs/roadmap.md`（§4/§6/§7/§10/§11）与 `README.md`、`docs/overview.md`、`docs/usage.md`、`benchmarks/README.md` 已同步。

### D/A/B/C

- **A（最终复测）✅**：受控记忆库下 **raw 73.3%/22、hinted 98.0%/48**，`hinted` 零回退。相对改动前（同语料 HEAD 代码：raw 68.8%/19、hinted 98.0%/48），raw **+4.5pp / +3 题**。`verify.py` 本地仅 §10.1 记忆库漂移 FAIL；CI 无 `.ai-memory` 不受影响。
- **C（roadmap 入清单）✅**：§7.2a 已写入 §7、§4 结构项记录、§9 第 7 条。
- **B（文档一致性）✅**：§10.3 的历史矛盾已修正；本轮新结论已回写到 §4/§6/§7 与各文档。
- **D（第二 Harness 对照）✅ 已完成（Cline 侧，2026-10-15）**：选定 **Cline**，切到 **Ollama Cloud/Pro 的 `deepseek-v4.1-flash`**（`--provider ollama --model deepseek-v4.1-flash`，baseUrl `https://ollama.com`），并**在隔离副本中运行**（`--root` + `robocopy` 排除 `.git`/`.hil`），以免被测 agent 修改真实仓库。两臂 × 50 题已采集完成（`.hil/results/ab_ollama_fixed_{hil,native}.jsonl`，0 错误）。上一轮用 `deepseek-v4-flash-vision-exp` 采的数据因换模型**作废**。运行器 `benchmarks/ab_run.py`（`--jobs`/`--timeout`/`--root`/重试）、评委 `benchmarks/judge_success.py`；运行手册见 `benchmarks/README.md` §5.1。

#### D 遇到的问题（2026-10-14，必须记录）

1. **A/B 的 agent 会改动被测评的仓库（最严重）**：Cline 自带 `editor` 工具，被测题时**直接修改了工作树**——新增 `indexer.staleness_state` / `index_staleness_report` 与 `retrieval.index.staleness` 字段，并改了 `skills/hil-project-knowledge/SKILL.md`、`tests/test_index_freshness.py`，还留下 `test_out.txt`。这**同时污染了仓库与被测系统**（A/B 中途改了检索实现）。相关改动已全部回退，工作树现只含本次评审过的改动。**结论：跨 Harness A/B 必须在一次性隔离副本 / `git worktree` 中运行，或禁止编辑类工具，绝不能在真实工作树上跑。**
2. **慢的根因**（HIL 臂 50 题实测）：单题 agent 时长 p50 **16 s** / mean 42 s / max **459 s**；模型迭代 p50 5 / max **27**；工具调用 p50 18 / max **121**；输入 token p50 **88k** / mean 156k / max **842k**；一臂合计约 **35 min**。原因是"多轮工具循环 + 每轮重发整段对话"（上下文近似二次增长），且 HIL 在当前协议下**并未减少探索**（取了上下文包后仍大量使用原生工具）。运行器原为**串行**，单题卡住还会阻塞整臂。
3. **中文题面经 argv 传给 cline 偶发失败**：并行 native 臂出现 `error: Unknown command or unquoted prompt`（题面被拆坏）；串行 HIL 臂 50/50 未复现。应改为把题面写入文件 / 走 stdin 传递。
4. **孤儿进程**：异常退出的运行会残留未清理的 `run_hil_mcp.py`（本次清理了 6 个）。
5. **已做的缓解**：运行器新增 `--jobs`（并发 6）与 `--timeout`；停止后已恢复 Cline 配置（`hil`/`scenario` 均启用，`hil` 用无空格包装器）。

**2026-10-15 重跑结果（Cline + Ollama Pro `deepseek-v4.1-flash`，隔离副本，两臂 × 50 题，0 错误）**：

| 臂 | n | 错误 | 调用 hil | 输入 token p50 | mean | max | 输出 mean |
|---|---|---|---|---|---|---|---|
| HIL | 50 | 0 | 49/50 | **244,045** | 347,234 | 1,634,151 | 4,214 |
| native | 50 | 0 | 0/50 | **370,581** | 420,571 | 2,469,759 | 4,408 |

配对 50 题：**中位输入 token 降低 34.1%**（mean 17.4%）。原始数据：`.hil/results/ab_ollama_fixed_{hil,native}.jsonl`。

**注意偏差**：该下降**不能归因于检索质量**——HIL 臂被要求先取上下文（调用差异），与 OpenClaw 首次 A/B 同一问题（§5/§9）；且 `success` 尚未判定，token 数字本身不能说明任务完成质量。

**2026-10-15 判定（`--compare`，`ab.jsonl` **100 条**：OpenClaw 50 + Cline 50）**：

| 门槛 | 结果 | 判定 |
|---|---|---|
| 中位输入 token 降低 ≥ 20% | **32.2%** | PASS |
| 成功率下降 ≤ 2pp | native 96.0% → hil 95.0%（**1.0pp**） | PASS |
| Context Recall ≥ 90% | **69.5%**（`raw` 口径） | **FAIL** |
| 平均重试不增加 | 0→0 | PASS |
| 跨 Harness 复用 | 2/2 | PASS |

`--compare` **退出码 1**：与首次一致，**Phase 3 仍只卡在召回门槛**。`ab.jsonl` 现已 100 条，§6 ③ Model Router 触发条件随之 **FIRED**。

**方法学声明**：① Cline 的 `success` 由**自动评委**（`deepseek-v4.1-flash`，见 `benchmarks/judge_success.py`，按每题 `success_criteria`）判定，非人工，宜抽检；② HIL 臂被要求"先取上下文"（调用差异），故 token 下降**不能单独归因于检索质量**；③ 两 Harness 用了不同模型（OpenClaw `deepseek-v4-flash`、Cline `deepseek-v4.1-flash`），已在 `--compare` 的 `models seen` 中记录。

