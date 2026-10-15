# Harness Intelligence Layer — 最终报告

日期：2026-10-15　|　版本：V0.1　|　索引 schema：3　|　分支：`main`

本报告是项目的**收官总结**：交付了什么、最终指标是多少、哪些做法被证据证明有效、哪些被证伪，以及怎么复现与正确使用。所有数字都可由 `benchmarks/` 下的脚本重新产出；本报告不含任何未经测量的收益声明。

---

## 1. 一句话结论

HIL 是一个**跨 Harness 共享的项目上下文与工程记忆层**，V0.1 已完整可用：在"调用方写出一句话 + 已知标识符"的正常用法下，50 个真实任务的平均 Context Recall 达到 **97.5%（47/50 达标）**；而在"纯中文提问"下为 **74.3%（23/50）**。**后者是本版本唯一未达标的指标（目标 ≥90%），且经四个独立实验证明不是工程手段能补齐的**（见 §5）。系统对 token 的节省与成功率、跨 Harness 复用均已由真实 A/B 验证，但**召回门槛未过**，因此本仓库**不宣称**任何整体 token 节省比例。

---

## 2. 交付物

| 交付物 | 说明 |
|---|---|
| 4 个 MCP 工具 | `index_project` / `get_project_context` / `search_project_memory` / `record_project_memory`（接口有意保持精简） |
| 轻量索引 | ripgrep + `os.walk` 双路径发现、正则符号提取（含模块常量）、schema 版本 + 文件集指纹、**检索时自愈**、**增量重建** |
| 词法检索 | 路径/符号/文本命中排序、token 预算选窗、中英 n-gram 词项、查询侧中英术语桥、Git recency |
| 可选语义层 | 三种后端（本地 `sentence-transformers` / OpenAI 兼容 `http` / 离线 `hash`），默认关闭，任意失败回退词法 |
| 工程记忆 | 目标项目内的 JSON 事实库，跨 Harness 共享 |
| 评测与门 | `benchmarks/tasks.jsonl`（50 题）· `measure.py` · `verify.py` · `evidence.py` · 回归基线 · GitHub Actions CI |
| A/B 基础设施 | `ab_run.py`（跑真实 Harness 臂）· `judge_success.py`（按 `success_criteria` 判定）· 100 条可比结果 |
| 文档 | `README.md` · `docs/overview.md` · `docs/roadmap.md` · `docs/usage.md` · `benchmarks/README.md` |

---

## 3. 最终指标

**运行条件**：50 题真实任务、token 预算 1500、索引 schema 3、**受控（空）记忆库**（见 §7）。

| 变体 | 平均 Context Recall | 达标（≥90%） | 中位包体积 | 重复片段 |
|---|---|---|---|---|
| `raw`（纯中文提问） | **74.3%** | 23 / 50 | 1481 | 0 |
| `hinted`（中文 + 标识符） | **97.5%** | 47 / 50 | 1478 | 0 |

- 检索延迟（词法）：p50 ≈ 240 ms，p95 ≈ 240 ms，远低于 1 s 退出标准。
- 语义开启（`bge-m3`，热缓存）：p50 534 ms / p95 578 ms。
- 记录于 `benchmarks/results/baseline.json`（2026-10-15）。

---

## 4. 按阶段的完成情况

| 阶段 | 状态 | 结果 |
|---|---|---|
| **Phase 0** 评测基线 | ✅ | 50 题任务集 + 判据 + 来源标注；统计脚本；A/B 表**已填 100 行**（OpenClaw 50 + Cline 50）。Codex 未做 |
| **Phase 1** 轻量 V0.1 | ✅ | 4 个 MCP 工具、索引自愈、CLI、`.ai-memory` 与代码索引去重、中文 token 估算 |
| **Phase 2** 索引质量与检索 | ✅ | 四轮词法修正（中文词项切分、片段级评分、路径匹配精确化、点名符号窗口优先）+ 结构项：增量重建、预算淘汰摘要、Git recency；**按证据不做**：文件监听、Tree-sitter、import/调用关系、schema 迁移框架 |
| **Phase 3** 跨 Harness A/B | ⚠️ 召回门槛未过 | 100 条真实对照；token/成功率/重试/复用四项 PASS，**Context Recall 69.5% FAIL**（见 §6） |
| **Phase 4** 按证据扩展 | 部分 | ① 可选语义重排**已实现并量化**（默认关）；② Unified Validator → 定义已写、实施 gated；③ Model Router 触发**已 FIRED**（100 条）但未实现；④ 向量库未触发 |
| **Phase 5** 跨语言召回 | ✅（但未达标） | 7.1 术语桥 `raw` 50.8%→70.5%；7.2 自举词典**证伪**；7.2a 窗口修正；7.3 文案兜底；7.4 语义量化 |
| **Phase 6** 候选 | 部分 | 记忆库预算（→ 在 8.6 完成）、词形匹配（候选）、文档一致性（已关闭）、Validator 定义（已写） |
| **Phase 7** 可用的语义层 | ✅（延迟解决） | 向量磁盘缓存 + 文本截断：语义重排 p95 从 4.3 s 降到 491 ms（热缓存）；新增 `confidence` 可信度信号 |
| **Phase 8** 召回与工程优化 | ✅ | 见下表 |

**Phase 8 明细**

| 项 | 结论 |
|---|---|
| 8.1 向量缓存**键含模型名** | ✅ 修 bug（原先换模型会复用旧向量，静默错排）+ 缓存上限 |
| 8.2 不丢命中符号的**定义窗口** | ✅ **`raw` 71.8% → 74.3%（+2.5pp）**，`hinted` 不回退 |
| 8.3 换更强 embedding（`bge-m3`） | ❌ `raw` 仅 +0.5pp，**不采纳** |
| 8.4 freshness 改走 `os.walk` | ⏭ 评估后不做（会破坏指纹一致性） |
| 8.5 语义模型预热 | 📄 文档化（~36 s/进程，仅长驻有意义） |
| 8.6 **记忆库配额** | ✅ 真实 40 条记忆库下 `hinted` **94.8% → 97.0%** |
| 8.7 `confidence: low` 调用侧兜底 | ✅ skill 明确"先核实/回退" |
| 8.8 一阶段语义召回 | ❌ 无收益（`raw` 73.8%）且更慢，**已回退** |

---

## 5. 关键证据：什么有效、什么是负结果

**有效的（都有前后对照）**

1. **中文词项切分 + 片段级评分**（Phase 2 第一轮）：`raw` 26.9% → 47.8%。
2. **排序与预算修正**（第二/三轮）：路径匹配精确化、点名标识符窗口优先发射、模块常量纳入符号：`hinted` 69.9% → 98.5%（当时语料）。
3. **查询侧中英术语桥**（7.1）：`raw` 50.8% → 70.5%，`hinted` 零回退。关键是**只做可达性、不参与排序**（任何正权重都会让 `hinted` 回退）。
4. **窗口退化修复**（7.2a）：`raw` +2.0pp；根因是术语桥让文件可达后，窗口选择在"纯扩展命中"下退化为一行空行。
5. **命中符号的定义窗口不被丢弃**（8.2）：`raw` +2.5pp，`hinted` 回退被门控消除。
6. **记忆库配额**（8.6）：把记忆配额从 `budget//4` 收到 `min(budget//8, 200)` + 最低重合，真实记忆库下 `hinted` 从 94.8% 回到 97.0%。
7. **语义层延迟工程**（7.1）：向量磁盘缓存 + 截断，热缓存 p95 4.3 s → 491 ms。

**被证伪的（负结果也计入交付）**

| 尝试 | 结果 | 原因 |
|---|---|---|
| 语料自举双语词典（7.2） | `hinted` −1~−3pp，不采纳 | 中文文档里到处是项目专有英文词，挖出来是噪声；人工表已覆盖有用领域词 |
| import/引用/调用关系 | `raw`/`hinted` 双降，回退 | 结构相邻性不能替代词面证据 |
| Tree-sitter 替换正则 | 不采纳 | 实测未发现任何正则漏掉的符号，正则还多覆盖模块常量；不引入依赖 |
| 更强 embedding（`bge-m3`） | `raw` +0.5pp | **重排只能重排词法 top-40 的候选**，初筛漏掉的补不回来 |
| 一阶段语义召回（8.8） | `raw` −0.5pp、更慢 | `raw` 失败 27/31 是 `missing_symbols`（文件已召回），补文件级召回打错目标 |
| 文件监听 | 不做 | 自愈已在查询时保证新鲜；监听多一个"漏事件→静默陈旧"的失败模式 |

**核心结论**：到 74.3% 之后，`raw` 的缺口**不是工程问题**。四次独立实验一致指向：剩余缺口是"中文提问 ↔ 英文实现"的**跨语言语义/标注性质**问题，而非排序、缓存、符号提取或候选生成。

---

## 6. 跨 Harness A/B（Phase 3）

**数据**：`benchmarks/results/ab.jsonl` 共 **100 条**可比结果（OpenClaw 50 + Cline 50），两臂均由真实 Harness 会话产出。

**判定**（`measure.py --compare`，**退出码 1**）：

| 门槛 | 结果 | 判定 |
|---|---|---|
| 中位输入 token 降低 ≥ 20% | **32.2%** | PASS |
| 成功率下降 ≤ 2pp | 96.0% → 95.0%（1.0pp） | PASS |
| **Context Recall ≥ 90%** | **69.5%**（`raw` 运行口径） | **FAIL** |
| 平均重试不增加 | 0 → 0 | PASS |
| 跨 Harness 复用 | 2/2 | PASS |

**方法学声明（必须与数字同时阅读）**

1. Token 下降**不能单独归因于检索质量**——HIL 臂被要求"先取上下文"，存在调用差异。
2. **归因实验**（同一指令、两臂都不调 hil，只差是否把包贴进题面）给出了分离结论：中位 token **−16.1%**，但成功率 **−6.0pp**（90.0% → 84.0%）。即约**一半来自检索内容、一半来自调用差异**；而且注入**不完整的包会主动误导**模型（这正是 `confidence` 信号要解决的）。
3. Cline 的 `success` 由**自动评委**（`judge_success.py`）按 `success_criteria` 判定，非人工，宜抽检。
4. 两 Harness 使用了不同模型（OpenClaw `deepseek-v4-flash`、Cline `deepseek-v4.1-flash`），`--compare` 会记录 `models seen`。

---

## 7. 复现与验证

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests            # 169 项单元测试
python benchmarks/verify.py                      # 跨阶段不变量与回归门（全绿 = 已在此环境验证）
python benchmarks/measure.py --variant raw       # HIL 侧机械指标（召回/包体积/延迟/重复片段）
python benchmarks/measure.py --variant hinted
python benchmarks/measure.py --compare benchmarks/results/ab.jsonl `
  --recall-file <hil_*.json> --reuse-file benchmarks/results/reuse.json
python benchmarks/evidence.py                    # Phase 4 证据门报告
```

**测量可复现性（重要）**：`.ai-memory/` 是 gitignored 的本地资产，且与代码片段共用同一条 token 预算，因此**同一份代码在不同机器上会报出不同召回**。现在 `measure.py` / `verify.py` 默认把读侧记忆库**固定为空目录**（`HIL_MEMORY_DIR`，只影响 `search_memory` 的读取），所以门与基线在任何机器上一致；要计入真实记忆库就传 `--memory-dir <path>`。基线已在受控条件下重录。

**A/B 运行注意**：跨 Harness A/B 必须在**一次性隔离副本**里跑（`ab_run.py --root <copy>`），因为被测 Harness 自带编辑器会修改工作树；题面必须以 ASCII 结尾（否则 Windows 下经 argv 会被偶发截断）。

---

## 8. 已知边界与正确用法

- **推荐用法**：把 `task` 写成"一句话 + 你已知的标识符"（文件名、符号名、配置项、错误码、CLI 参数）→ 召回 ~97%。
- **纯中文提问**：召回 ~74%，**这是已知缺陷，不是"不推荐的写法"**。`notice` 会提示补标识符、`confidence: low` 会提示先核实。
- **`sufficient: false`**：本次没有任何片段命中，应改用 Harness 原生搜索，不要把空包当成"项目里没有"。
- **`confidence: low`**：没有任何你点名的标识符被直接命中，包只是弱 shortlist，先核实再依赖。
- **文档类问题**（`docs/*.md`）：历史最弱；Phase 2 后已能与代码片段竞争，但仍是边界情形，必要时直接读 `docs/*`。
- **索引**：检索时自愈（不监听文件变化）；首次之外的检索 p95 ≪ 1 s。
- **语义层**：可选、默认关闭；启用需自备模型或端点，收益必须先由 `benchmarks/measure.py --embedding ...` 量化。

---

## 9. 明确不做

- 新 Agent Loop、通用 Shell / 文件编辑工具、Session Manager、Sub-Agent 框架；
- 保存完整聊天流水账；
- 把在线翻译 API、云 Embedding、Qdrant 或 Cross-Encoder 变成**强制**依赖；
- 在没有 A/B 数据的情况下宣称固定 token 节省比例。

---

## 10. 仓库状态

- 分支 `main`，工作树干净，与 `origin/main` 一致。
- 收官提交链：`be8c436` → `8ef65c2` → `cfebfbd` → `184cfb0` → `3ebc618` → `b6f5870` → `d6822cf` → `cb81174` → `19b682b` → `6973f1f` → `7f71a59`。
- 回归基线：`benchmarks/results/baseline.json`（2026-10-15，受控记忆库）。
- 评测证据：`benchmarks/results/ab.jsonl`（100 行）、`reuse.json`；每次运行的报告在 `.hil/results/`（不入库、不进索引）。

---

## 11. 若继续：只剩两条路

1. **换更强的模型/机制**：我们已证明"重排"封顶（8.3）、"补文件级召回"打错目标（8.8）。若仍要把 `raw` 推向 90%，需要**更强的多语言模型 + 面向"符号/窗口级"的语义匹配**，且须重新设计成本与回退——预期收益不确定。
2. **接受 74% 为当前能力边界**：把 §7.3 的文案与 `confidence` 信号作为正式产品边界，把精力转向已确定有价值的工程（如把 `ab.jsonl` 的 OpenClaw 臂用当前检索重跑、补齐 Codex 侧、实现 Model Router）。

**唯一确定仍未达成的核心指标：`raw`（纯中文提问）Context Recall 74.3% < 90%。**
