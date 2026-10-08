# Phase 0 评测基线

本目录实现 `docs/roadmap.md` §2（Phase 0：建立评测基线）的交付物：任务集、统计脚本和对照实验说明。

| 文件 | 作用 |
|---|---|
| `tasks.jsonl` | 26 个带标注的项目任务（单文件、跨模块、故障定位、架构问答） |
| `hints.jsonl` | 同一批任务的标识符化表达，用于把"表达质量"与"检索质量"分开测量 |
| `measure.py` | HIL 侧机械测量 + A/B 结果校验（仅用标准库） |
| `verify.py` | 跨阶段验证与回归门：8 类断言，输出 PASS / FAIL / SKIP，退出码 1 = 有断言失败 |
| `results/` | 入库证据：`ab.jsonl`（人工填写）与 `baseline.json`（回归基线） |

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
Set-Location -LiteralPath "D:\MY\My Projects\HarnessIntelligenceLayer"
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
| `--worksheet PATH` | 生成空白 A/B 表并退出 |
| `--compare PATH` | 校验已填写的 A/B 表并按 roadmap §5 门槛判定 |

## 4. 任务表达对照（调用策略）

`hints.jsonl` 保存同一批任务的"标识符化表达"，用于把检索质量与任务表达质量分开测量。规则：hint 只允许加入开发者本来就会提到的英文术语与标识符，**不得包含仓库文件路径**（写出答案文件等于测量标注，而不是测量检索）。

```powershell
python benchmarks/measure.py --budget 1500 --label baseline --variant raw
python benchmarks/measure.py --budget 1500 --label baseline --variant hinted
```

2026-10-08 实测（26 题、1500 token 预算、索引 schema 2、29 个文件 / 223 个符号；中位包体积取整到 10 token——它会随索引内容在十几 token 内抖动，取整可避免每次文档编辑都要改表）。表中是**完成 Phase 2 两处检索修正与跨语言词面桥接后**的数值；修正前的数值（`raw` 26.9% → 47.8%、`hinted` 65.7% → 69.9%）见 `docs/roadmap.md` §2/§4：

| 变体 | 平均 Recall | 达标（≥90%） | 中位包体积 | 未召回符号 | p50 / p95 延迟（预热后，指示性） |
|---|---|---|---|---|---|
| `raw`（原始中文表达） | 68.9% | 11 / 26 | ≈1470 | 5 | 126 / 161 ms |
| `hinted`（中文 + 标识符） | 68.9% | 14 / 26 | ≈1470 | 3 | 140 / 177 ms |

结论与后续动作见 `docs/roadmap.md` 的 Phase 2 修正记录与缺口归因。跨语言桥接把 `raw` 从 47.8% 抬到 68.9%（+21.1pp），`hinted` 微降 1.0pp（桥接词在有标识符时是冗余噪声，仍在回归门容差内）；两种表达的差异因此基本消失，说明"必须会写英文标识符"这一门槛主要是词面缺口，而不是检索质量本身。相对 Phase 2 的 `p95 < 1000 ms` 退出标准仍有余量。

评测产物与索引的关系（已隔离实测）：派生 JSON 一旦进入索引，就会与源码片段争夺同一份 token 预算。只切换 `benchmarks/results/baseline.json` 是否被索引、其余不变：

| 状态 | 索引文件数 | `hinted` 平均 Recall | 达标 | 中位包体积 |
|---|---|---|---|---|
| 排除（`.hilignore` 生效） | 29 | 69.9% | 15 / 26 | ≈1470 |
| 纳入（移除规则） | 30 | 69.9% | 15 / 26 | ≈1460 |

历史对照：同一实验在检索修正前测得 `hinted` 65.7% → 63.8%、达标 12 → 11，即一个 6 KB 派生文件吃掉 1.9 个百分点召回与 1 个达标任务，而中位包体积不变——说明是"内容挤出"而非"体积膨胀"。修正后这个挤出在当前语料上不再复现（小派生文件不再能把整份预算挤出某条任务），但规则仍然保留：**排除的语义是"测量语料里不含测量产物"**，这是测量卫生的前提，不依赖当前语料恰好测不出差异。因此：每次运行的报告写入 `.hil/results/`，入库的 `results/` 由仓库根 `.hilignore` 显式排除，`verify.py` 断言基线不被索引。

测量环境说明：`.ai-memory/` 在 `.gitignore` 中（工程记忆是本地资产，不入库），而检索会把记忆片段计入同一条预算。因此**本地实测与 CI 跑出的召回数值会因记忆库内容不同而有差异**，回归门的 8pp 容差覆盖这类环境差；比较数值时应连同 `indexed files` 与记忆库规模一起记录。

## 5. A/B 对照实验

A/B 表的 token 数必须从 Harness 会话用量中读取，`measure.py` 无法替你生成。先生成空白表：

```powershell
python benchmarks/measure.py --worksheet benchmarks/results/ab.jsonl --harness openclaw --harness cline
```

逐行填写后形如（**下面是格式示例，不是真实数据**）：

```json
{"id": "HIL-005", "harness": "openclaw", "prompt": "四个 MCP 工具在哪个函数里注册？",
 "native": {"input_tokens": 0, "success": false, "evidence": "<取数位置与日期>"},
 "hil":    {"input_tokens": 0, "success": false, "evidence": "<取数位置与日期>"}}
```

字段要求：

- `input_tokens`：该次任务会话的模型输入 token 总量（正整数）；
- `success`：按 `success_criteria` 判定任务是否真正完成（布尔）；
- `evidence`：取数位置与日期，缺失即视为未填写，脚本拒绝统计。

判定：

```powershell
python benchmarks/measure.py --compare benchmarks/results/ab.jsonl `
  --recall-file benchmarks/results/hil_openclaw_<UTC>.json
```

门槛来自 `docs/roadmap.md` §5：中位输入 token 降低 ≥ 20%、Context Recall ≥ 90%、成功率下降 ≤ 2 个百分点。任一不达标时退出码为 1。

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
| 节省门自检 | 用合成数据验证 `--compare` 的三种退出码：3 数据不可用、1 未达门槛、0 全部通过 |

容差说明：26 题中单题翻转 ≈ 3.8pp，因此回归门允许约两题的合法漂移。这种漂移不只来自检索改动：**被引用的文档本身也在索引里**，所以修改这些数字所在的文档就会移动数值——实测一次文档更新让 `raw` 掉 3.9pp（≈ 1 题）、`hinted` 涨 1.9pp（≈ 1 题）。8pp 的容差刚好覆盖这类合法漂移，而真正的退化（例如中文词项切分失效）会远超这个幅度。基线只能通过 `--write-baseline` 更新，并应与触发数值变动的提交一起 review。

## 7. 当前状态

- 任务集：已完成（26 条，含成功判据与来源标注）；
- HIL 侧测量：可直接复现（29 个文件 / 223 个符号、`raw` 与 `hinted` 两次运行）；
- 检索修正：Phase 2 的两处词法层缺陷已修正（`raw` 26.9% → 47.8%、`hinted` 65.7% → 69.9%），随后完成跨语言词面桥接（`raw` → 68.9%、`hinted` → 68.9%），**仍未达到 90% 退出标准**，缺口归因见 `docs/roadmap.md` §4；
- 调用策略对照：已完成，桥接前标识符化表达把平均召回从 47.8% 提升到 69.9%，桥接后两种表达接近持平（均为 68.9%）；
- 回归门：已建立（`verify.py` + `results/baseline.json`），并接入 CI；
- 原生执行基线：**尚未填写**，因此本仓库不得宣称任何 token 节省比例。
