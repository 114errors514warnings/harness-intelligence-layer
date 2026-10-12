# Phase 0 评测基线

本目录实现 `docs/roadmap.md` §2（Phase 0：建立评测基线）的交付物：任务集、统计脚本和对照实验说明。

| 文件 | 作用 |
|---|---|
| `tasks.jsonl` | 26 个带标注的项目任务（单文件、跨模块、故障定位、架构问答） |
| `hints.jsonl` | 同一批任务的标识符化表达，用于把"表达质量"与"检索质量"分开测量 |
| `measure.py` | HIL 侧机械测量 + A/B 结果校验（仅用标准库） |
| `evidence.py` | Phase 4 证据门：报告四条「按证据扩展」触发条件是否成立（不实现任何组件） |
| `verify.py` | 跨阶段验证与回归门：任务集、发现路径、包不变量、回归门、索引覆盖、跨 Harness 复用、节省门自检，输出 PASS / FAIL / SKIP，退出码 1 = 有断言失败 |
| `results/` | 入库证据：`ab.jsonl`（人工填写）、`baseline.json`（回归基线）、可选的 `reuse.json`（跨 Harness 复用回执）与 `quality.json`（人工判定修改集合） |

每次运行的报告写入 `.hil/results/`（`.hil/` 已被两条文件发现路径排除），因此跑评测不会改变下一次评测读到的索引。

## 1. 诚实性原则

- 本目录**不产生**任何"节省 X%"的结论。token 节省只能来自 Harness 真实会话用量，`measure.py` 在 A/B 表未填满时**拒绝**输出节省比例（退出码 3）。
- `tasks.jsonl` 的任务来自本仓库真实工作与已确认事实（每条记录带 `provenance` 字段），不是凭空构造的样本，也不是从 Harness 日志批量导出的历史任务。
- HIL 侧指标不含模型：它只衡量"检索是否覆盖必要文件与符号、包体积、延迟、重复片段"，因此可在任何机器上复现。
- 为了提高样本质量，不要只保留对 HIL 有利的任务；新增任务时按同样格式追加即可。

## 2. 任务集格式

`tasks.jsonl` 每行一个 JSON 对象：

```json
{"id": "HIL-005", "category": "architecture", "prompt": "四个 MCP 工具在哪个函数里注册？",
 "required_files": ["src/harness_intelligence/server.py"], "required_symbols": ["create_server"],
 "success_criteria": "指出 create_server 内部的 FastMCP 实例和四个 mcp.tool 装饰器。",
 "provenance": "code-contract:src/harness_intelligence/server.py"}
```

- `category`：`single-file`、`cross-module`、`bug-localization`、`architecture`；
- `required_files`：回答该任务必须检索到的文件（相对仓库根）；
- `required_symbols`：必须出现在返回片段正文中的符号，可为空数组；
- `success_criteria`：人工判定"任务是否真正完成"的判据，A/B 表的 `success` 以它为准；
- `provenance`：该任务从何而来，便于复核。

## 3. 运行 HIL 侧测量

```powershell
Set-Location -LiteralPath "<hil-root>"
$env:PYTHONPATH = "src"
python benchmarks/measure.py --budget 1500 --label hil
```

脚本会先重建索引，再逐条执行任务，输出每条的召回率、包体积、延迟和重复片段数，并写入 `.hil/results/hil_<label>_<variant>_<UTC>.json`。常用参数：

| 参数 | 说明 |
|---|---|
| `--budget N` | 每条任务的 token 预算，默认 1500 |
| `--limit N` | 只跑前 N 条，用于快速验证 |
| `--label NAME` | 结果文件标签，例如 `openclaw`、`cline` |
| `--variant raw\|hinted` | 任务表达：原始表达 vs 标识符化表达，默认 `raw` |
| `--out PATH` | 报告输出路径，默认 `.hil/results/`（该目录不在索引范围内） |
| `--worksheet PATH` | 生成空白 A/B 表并退出（每行写入随机 `seed` 与两臂执行 `order`） |
| `--seed N` | `--worksheet` 的随机化种子，默认 0，可复现同一分组 |
| `--embedding off\|auto\|on\|hash` | 可选语义重排臂，默认跟随 `HIL_EMBEDDINGS`（未设置即 `off`）；不可用时回退本地词法 |
| `--compare PATH` | 校验已填写的 A/B 表并按 roadmap §5 五道门槛判定 |
| `--reuse-file PATH` | 跨 Harness 复用回执，提供后纳入复用门判定 |

## 4. 任务表达对照（调用策略）

`hints.jsonl` 保存同一批任务的"标识符化表达"，用于把检索质量与任务表达质量分开测量。规则：hint 只允许加入开发者本来就会提到的英文术语与标识符，**不得包含仓库文件路径**（写出答案文件等于测量标注，而不是测量检索）。

```powershell
python benchmarks/measure.py --budget 1500 --label baseline --variant raw
python benchmarks/measure.py --budget 1500 --label baseline --variant hinted
```

2026-10-11 实测（**50 题**、1500 token 预算、索引 schema 3、34 个文件；中位包体积取整到 10 token——它会随索引内容在十几 token 内抖动，取整可避免每次文档编辑都要改表）。这是**完成三轮检索修正后**的当前基数：

| 变体 | 平均 Recall | 达标（≥90%） | 中位包体积 | 未召回文件 | p50 / p95 延迟（预热后，指示性） |
|---|---|---|---|---|---|
| `raw`（原始中文表达） | 70.5% | 20 / 50 | ≈1480 | 3 | 49 / 74 ms |
| `hinted`（中文 + 标识符） | 98.5% | 48 / 50 | ≈1440 | 1 | 58 / 83 ms |

`hinted` 已达到 90% 退出标准，且**没有任何必召回文件被漏掉**；`raw` 的剩余缺口是"中文提问 vs 英文实现"的跨语言匹配，词法检索解决不了。两轮修正的完整记录（第一轮 `raw` 47.8% / `hinted` 69.9%）见 `docs/roadmap.md` §4。第二轮把窗口收窄、每个文件只保留一个窗口，让同一份预算覆盖更多文件，因此中位包体积与延迟反而同时下降。

评测产物与索引的关系（2026-10-05 第一轮修正后的隔离实测）：派生 JSON 一旦进入索引，就会与源码片段争夺同一份 token 预算。只切换 `benchmarks/results/baseline.json` 是否被索引、其余不变：

| 状态 | 索引文件数 | `hinted` 平均 Recall | 达标 | 中位包体积 |
|---|---|---|---|---|
| 排除（`.hilignore` 生效） | 29 | 69.9% | 15 / 26 | ≈1470 |
| 纳入（移除规则） | 30 | 69.9% | 15 / 26 | ≈1460 |

历史对照：同一实验在检索修正前测得 `hinted` 65.7% → 63.8%、达标 12 → 11，即一个 6 KB 派生文件吃掉 1.9 个百分点召回与 1 个达标任务，而中位包体积不变——说明是"内容挤出"而非"体积膨胀"。修正后这个挤出在当前语料上不再复现（小派生文件不再能把整份预算挤出某条任务），但规则仍然保留：**排除的语义是"测量语料里不含测量产物"**，这是测量卫生的前提，不依赖当前语料恰好测不出差异。因此：每次运行的报告写入 `.hil/results/`，入库的 `results/` 由仓库根 `.hilignore` 显式排除，`verify.py` 断言基线不被索引。

测量环境说明：`.ai-memory/` 在 `.gitignore` 中（工程记忆是本地资产，不入库），而检索会把记忆片段计入同一条预算。因此**本地实测与 CI 跑出的召回数值会因记忆库内容不同而有差异**，回归门的 8pp 容差覆盖这类环境差；比较数值时应连同 `indexed files` 与记忆库规模一起记录。

## 5. A/B 对照实验

A/B 表的 token 数必须从 Harness 会话用量中读取，`measure.py` 无法替你生成。先生成空白表：

```powershell
python benchmarks/measure.py --worksheet benchmarks/results/ab.jsonl `
  --harness openclaw --harness cline --seed 20261011
```

`--worksheet` 会为每行记录随机化结果：`seed` 是本次种子，`order` 是该题两个臂的执行顺序（`native` 与 `hil` 随机先后）。行序也被打乱，使某个 Harness 的学习或缓存效应不会固定落在后执行的臂上；用同一 `--seed` 重跑可复现同一分组。

逐行填写后形如（**下面是格式示例，不是真实数据**）：

```json
{"id": "HIL-005", "harness": "openclaw", "seed": 20261011, "order": ["hil", "native"],
 "prompt": "四个 MCP 工具在哪个函数里注册？",
 "native": {"input_tokens": 0, "success": false, "retries": 0,
            "tool_result_tokens": 0, "cache_read_tokens": 0, "model": "<模型名>",
            "evidence": "<取数位置与日期>"},
 "hil":    {"input_tokens": 0, "success": false, "retries": 0,
            "tool_result_tokens": 0, "cache_read_tokens": 0, "model": "<模型名>",
            "evidence": "<取数位置与日期>"}}
```

字段要求：

- `input_tokens`：该次任务会话的模型输入 token 总量（必填正整数）；
- `success`：按 `success_criteria` 判定任务是否真正完成（必填布尔）；
- `evidence`：取数位置与日期，缺失即视为未填写，脚本拒绝统计（必填）；
- `retries`：该次任务的修复轮次（可选，缺省 0，纳入门槛）；
- `tool_result_tokens`：工具结果累计体积（可选，**只记录不设门槛**）；
- `cache_read_tokens`：prompt cache 命中读取量（可选，**只记录不设门槛**），用于判断 token 下降是否其实来自缓存而非检索；
- `model`：Harness 使用的模型标识（可选），用于分辨模型差异。

跨 Harness 复用回执（可选）形如：

```json
{"generated_at": "<UTC>", "success": true,
 "pairs": [{"writer": "cline", "reader": "openclaw", "query": "<查询>",
            "found": true, "evidence": "<取数位置与日期>"}]}
```

`success` 为布尔、`pairs` 非空且每对都带 `found` 与 `evidence`，否则脚本以退出码 3 拒绝统计。

判定：

```powershell
python benchmarks/measure.py --compare benchmarks/results/ab.jsonl `
  --recall-file benchmarks/results/hil_openclaw_<UTC>.json `
  --reuse-file benchmarks/results/reuse.json
```

门槛来自 `docs/roadmap.md` §5：中位输入 token 降低 ≥ 20%、Context Recall ≥ 90%、成功率下降 ≤ 2 个百分点、**平均重试次数不增加**，提供回执时再加**跨 Harness 复用成功**。任一不达标时退出码为 1；数据不足或不可追溯时为退出码 3。未提供 `--reuse-file` 时复用门只报告不拦截，以兼容 Phase 3 之前已填写的旧表。

## 6. 验证与回归门

单元测试证明代码契约；`verify.py` 证明单元测试证明不了的事：真实目录上产出的包是否自洽、两条文件发现路径是否一致、召回是否相对基线退化、索引是否与源码集对齐、节省门是否仍然拒绝不完整数据。

```powershell
$env:PYTHONPATH = "src"
python benchmarks/verify.py                              # 全部检查；退出码 1 = 有断言失败
python benchmarks/verify.py --limit 6 --variant hinted   # 快速本地迭代（回归门会 SKIP）
python benchmarks/verify.py --write-baseline             # 有意改变检索后重建基线
```

每项检查只输出三种结果：`PASS`（此刻成立）、`FAIL`（不成立，退出码 1）、`SKIP`（本机无法运行，例如未装 ripgrep）。**SKIP 不算通过**，所以"全绿"意味着"已在此环境验证过"，而不是"假定没问题"。

| 检查 | 断言 |
|---|---|
| 任务集 | `tasks.jsonl` 与 `hints.jsonl` 的 id 集合完全相等；四个分类齐全；每条任务都有 `provenance` |
| 文件发现 | ripgrep 与 `os.walk` 回退得到同一文件集（未装 ripgrep 时 SKIP，不静默通过） |
| 包不变量 | 每条任务 `estimated_tokens ≤ budget` 且"记忆 + 片段恰等于总量"；记忆片 ≤ budget/4；每个片段的 `lines` 与磁盘真实行一致（正文首行编号 = 起始行） |
| 分类召回 | 按 category 分别报告（**不作门**：单题翻转即 20 多个百分点，会变成噪声） |
| 回归门 | 相对 `results/baseline.json`：平均召回 ≥ 基线 − 8pp、达标题数 ≥ 基线 − 2、重复片段不增加、中位包体积 ≤ 基线 × 1.05 + 50 token |
| 延迟 | 预热后报告 p50 / p95，**不作门**（同机冷启动实测摆动 2.6 倍，单次数字是假信号） |
| 索引覆盖 | 索引文件集 == 可发现文本文件集（含 `.hilignore` 规则），且不含 `hil_*.json` 每次运行报告与 `results/baseline.json` |
| 跨 Harness 复用 | 在临时项目里写入一条署名为 `cline` 的事实，再经记忆检索与 `get_project_context` 读回；断言事实存放在目标项目而非 Harness 私有存储，且 `.ai-memory` 不被当作源码重建索引 |
| 节省门自检 | 用合成数据验证 `--compare` 的四种退出码场景：3 数据不可用、1 未达门槛（token / 重试 / 复用各自一个用例）、0 全部通过 |

容差说明：50 题中单题翻转 = 2.0pp，因此回归门允许约四题的合法漂移（8pp）。这种漂移不只来自检索改动：**被引用的文档本身也在索引里**，所以修改这些数字所在的文档就会移动数值。8pp 的容差刚好覆盖这类合法漂移，而真正的退化（例如中文词项切分失效）会远超这个幅度。基线只能通过 `--write-baseline` 更新，并应与触发数值变动的提交一起 review。

## 7. 当前状态

- 任务集：已完成（50 条，含成功判据与来源标注；Phase 0 时 26 条，后扩建以便让 2pp 的成功率预算可分辨）；
- HIL 侧测量：可直接复现（本次运行 34 个文件、`raw` 与 `hinted` 两次运行，另可用 `--embedding` 增加语义重排臂）；
- 检索修正：四轮。前三轮见 `docs/roadmap.md` §4；**第四轮（Phase 5 §7.1）为查询侧中英术语桥**（`glossary.py`，只做可达性、不参与排序）。50 题上 `raw` 50.8% → **70.5%**、`hinted` 保持 **98.5%**（零回退）。`hinted` 已达 90% 退出标准；`raw` 仍低于门槛，剩余缺口为跨语言，归因见 `docs/roadmap.md` §4/§7；
- 调用策略对照：已完成，标识符化表达在当前检索下把平均召回从 70.5% 提升到 98.5%（达标 20 → 48 / 50）；
- **首次真实跨 Harness A/B（2026-10-11，OpenClaw + deepseek-v4-flash，50 题 × 2 臂，输入为 `raw` 纯中文提问，双臂有效性经 transcript 核验）**：中位输入 token 降低 **43.1%**、成功率 100% → 100%、平均重试 0→0、跨 Harness 复用 2/2 达标；但 **Context Recall 50.8% < 90%，门槛失败**，`--compare` 退出码 1。注意该 token 下降不能归因于检索质量（模型自带探索也能答对），见 `docs/roadmap.md` §5。数据与回执见 `results/ab.jsonl` 与 `results/reuse.json`；
- Phase 3 就绪：判定机制已就绪（随机分组 + seed、五道门槛、工具结果与 prompt-cache 记录、跨 Harness 复用回执），见 `docs/roadmap.md` §5「Phase 3 就绪状态」；`hinted` 召回已达标，HIL 臂具备采集条件；
- Phase 4 证据门：已建立（`evidence.py`），可选语义重排已实现并默认为关，见 §8；
- 回归门：已建立（`verify.py` + `results/baseline.json`），并接入 CI；本轮为**有意的检索改动**，基线已用 `--write-baseline` 重录；
- 原生执行基线：**尚未填写**（`ab.jsonl` 的 52 行两臂仍为 `null`），因此本仓库不得宣称任何 token 节省比例。

> 基线说明：本轮是**有意的检索改动**，因此基线用 `--write-baseline` 重录并随提交一起 review——这是唯一允许改写基线的路径。此前记录的"改文档会移动召回数值"现象仍然成立：被引用的源码与文档本身都在索引里，所以继续编辑本文档也会让数值在 8pp 容差内小幅漂移。

## 8. Phase 4 证据门

```powershell
$env:PYTHONPATH = "src"
python benchmarks/evidence.py
```

读取 `results/baseline.json`（召回）、`results/ab.jsonl`（可比结果数）、可选的 `results/quality.json`（人工判定修改集合）与 `.hil/results/` 最新报告的 p95 延迟，逐条报告 `docs/roadmap.md` §6 的四个触发条件是 `FIRED`（证据已成立）、`NOT FIRED`（证据表明暂不需要）还是 `NOT EVIDENCED`（尚无证据）。退出码恒为 0：这是决策报告而不是构建门，`FIRED` 只表示"roadmap 要求的证据出现了"，不代表必须开工，也不代表任何收益已被测量。
