# Harness Intelligence Layer 使用说明

## 1. 为目标项目建立知识库

HIL 将项目知识分为两个部分：

- **代码索引**：保存文件、符号和位置等可重新生成的数据，位于目标项目的 `.hil/index.json`。
- **工程知识库**：保存经过确认、可长期复用的架构、决策、缺陷根因和工程约定，位于目标项目的 `.ai-memory/`。

两者共同构成 HIL 的项目知识基础，但生命周期不同：代码索引可以随时重建；工程知识需要人工确认后记录，不应由聊天记录自动生成。

### 1.1 确定目标项目

以下示例假设：

```powershell
$hilRoot = "<hil-root>"
$targetProject = "<project-root>"
```

如果要索引 HIL 项目本身，则将 `$targetProject` 设置为 `$hilRoot`。目标项目必须是本机可访问的目录，建议使用绝对路径，避免不同 Harness 的工作目录不一致。

### 1.2 首次建立代码索引

首次建立索引有两种方式。推荐直接在 OpenClaw 或 Cline 对话中触发，不需要手动执行命令行。

#### 推荐方式：由 OpenClaw/Cline 自动执行

在 Harness 对话中发送：

```text
请调用 HIL 的 index_project，为以下项目建立知识库索引：

<project-root>
```

OpenClaw/Cline 会自动启动 HIL MCP Server、调用 `index_project`，并在目标项目内生成 `.hil/index.json`。用户不需要提前运行 `run_hil_mcp.py`，也不需要保持额外的终端窗口。

需要注意，V0.1 不会在打开新项目时自动建立索引。每个新项目首次使用时，仍需通过上述对话指令触发一次。

索引建立之后会自愈：每次检索前，HIL 会把索引中的 schema 版本与文件集指纹（相对路径、大小、mtime）同工作树比对，发现新增、删除或修改文件就自动重建，并在返回值的 `index` 字段里说明是否重建、原因是什么。因此项目结构变化后通常不需要手动刷新索引；只有需要显式确认或排查问题时，才再次调用 `index_project`。

#### 可选方式：使用本地管理 CLI

如果希望绕过 Harness 直接初始化索引，可进入 HIL 项目目录并执行：

```powershell
Set-Location -LiteralPath $hilRoot
$env:PYTHONPATH = Join-Path $hilRoot "src"
python -m harness_intelligence.cli index $targetProject
```

成功后会返回索引根目录、文件数量和索引文件位置。确认目标项目中已经生成：

```text
YourProject/
└─ .hil/
   └─ index.json
```

索引只包含受支持的文本与源代码文件，并排除 `.git`、`.hil`、`.ai-memory`、依赖目录和常见构建产物。

### 1.3 用户需要执行哪些操作

完成一次 MCP 配置后，日常使用不需要手动启动 HIL。用户只需要在以下场景通过对话触发相应工具：

| 场景 | 用户需要做什么 |
|---|---|
| 当前项目已有有效索引 | 直接要求 Harness 调用 `get_project_context` |
| 新项目首次使用 | 要求 Harness 调用一次 `index_project` |
| 文件结构或重要符号大幅变化 | 通常不需要操作，检索时会自动重建；需要确认时调用 `index_project` |
| 需要保存长期工程事实 | 明确要求调用 `record_project_memory` |
| 只修改 `.ai-memory` | 不需要重建代码索引 |

不需要执行的操作包括：

- 不需要手动启动 `run_hil_mcp.py`；
- 不需要启动常驻服务；
- 不需要配置监听端口；
- 不需要每次对话都重新建立索引；
- 不需要手动把聊天记录整理进知识库。

准确地说，HIL 是"无需手动启动、首次建库后自动保持索引新鲜（访问时自愈）"，但仍不监听文件变化：自愈发生在检索那一刻，而不是文件被修改的瞬间。

### 1.4 初始化工程知识

工程知识不是首次索引的必填项。只应记录已经确认、未来仍有复用价值的事实。

记录架构事实：

```powershell
python -m harness_intelligence.cli memory-record `
  architecture `
  "Authentication boundary" `
  "Authentication is owned by the identity service; other modules must use its public API." `
  $targetProject `
  --tag authentication `
  --tag architecture
```

记录技术决策：

```powershell
python -m harness_intelligence.cli memory-record `
  decisions `
  "Database migration policy" `
  "Production migrations must be backward-compatible for one deployment cycle." `
  $targetProject `
  --tag database `
  --tag deployment
```

允许的知识分类：

| 分类 | 用途 |
|---|---|
| `architecture` | 系统边界、模块职责和关键数据流 |
| `decisions` | 已接受的技术决策及约束 |
| `bugs` | 已确认的缺陷根因和修复原则 |
| `conventions` | 编码、测试和交付约定 |
| `experiments` | 有复用价值的实验结论 |
| `tasks` | 需要跨会话保留的重要任务事实 |

不要记录完整聊天记录、未验证的猜测、短期执行状态、密钥或隐私数据。

### 1.5 验证知识库

检查工程知识检索：

```powershell
python -m harness_intelligence.cli memory-search `
  "authentication architecture" `
  $targetProject
```

检查代码与工程知识的联合检索：

```powershell
python -m harness_intelligence.cli context `
  "定位认证入口、令牌验证逻辑和相关架构约束" `
  $targetProject `
  --budget 1200
```

验收时应确认：

- `project_root` 指向预期目标项目；
- `estimated_tokens` 不超过预算；
- `fragments` 包含关键文件或符号；
- `memories` 返回相关工程事实；
- `index.staleness` 为 `"current"` 或 `"rebuilt"`（索引与工作树一致，或本次已自动重建）；只有显式 `--no-refresh` 跳过检查时才可能为 `"stale"`，此时结果可能漏文件；
- `notice` 中没有 `WARNING: index is stale`；
- 无关片段比例可以接受。

## 2. 运作方式

### 2.1 不需要提前启动服务

HIL 使用 STDIO MCP。OpenClaw、Cline CLI 和 Cline VS Code 扩展都是 MCP 客户端，它们会在需要调用 HIL 时自动启动 MCP Server。

当前配置的启动命令为：

```powershell
<python.exe> `
  "<hil-root>\run_hil_mcp.py"
```

正常工作流程为：

```text
用户向 OpenClaw/Cline 提交任务
              │
              ▼
Harness 决定调用 HIL MCP 工具
              │
              ▼
Harness 自动启动 run_hil_mcp.py
              │
              ▼
HIL 读取目标项目的 .hil 与 .ai-memory
              │
              ▼
通过 STDIO 返回结构化结果
```

因此不需要提前运行脚本、保持单独终端窗口、启动 HTTP 服务或监听端口。Harness 会管理 MCP 子进程的启动和关闭。

如果手动运行 `run_hil_mcp.py`，程序会等待 stdin 上的 MCP 协议消息，看起来像停滞。这是 STDIO Server 的正常行为，但不是推荐启动方式。

### 2.2 CLI 与 MCP 的关系

这里有两类 CLI：

1. `python -m harness_intelligence.cli ...` 是 HIL 的本地管理 CLI，用于直接建索引、检索和维护知识。
2. `openclaw`、`cline` 是 Harness CLI。它们作为 MCP 客户端直接调用 HIL，并按需自动启动 MCP Server。

日常使用 OpenClaw/Cline 时，不需要先执行 HIL 管理 CLI。只有在需要主动初始化或刷新索引，且不希望让 Harness 调用 `index_project` 时，才需要直接使用 HIL 管理 CLI。

### 2.3 一次 MCP 调用的处理过程

以 `get_project_context` 为例：

1. Harness 提交任务描述、目标项目路径和 token 预算。
2. HIL 从 `.hil/index.json` 读取文件与符号元数据。
3. HIL 读取候选文件，计算路径、符号和文本相关性。
4. HIL 从 `.ai-memory` 检索相关工程事实。
5. HIL 在预算内选择价值较高的代码片段和记忆。
6. Harness 接收 Context Package，并继续完成分析或修改任务。

V0.1 使用本地词法检索，不依赖云 Embedding 或外部向量数据库。词项按 ASCII 标识符与中文 2/3 字 n-gram 切分（`重建索引之后` → `重建`、`建索`、`索引`…，单字不参与匹配），片段按"该片段自身的命中密度"挑选并受 token 上限约束，因此中文提问也能命中中文文档与工程记忆。中文提问还会经一份小型中英词表桥接为英文查询词（如 索引→index、陈旧→stale），以弥补中文提问与英文实现之间的词面缺口；桥接只扩展查询侧，词表未覆盖的中英对仍是缺口，见 `docs/roadmap.md` §4。

## 3. MCP 工具说明

### `index_project`

建立或完整刷新目标项目索引：

```text
index_project(project_root="<project-root>")
```

### `get_project_context`

在指定 token 预算内返回相关代码片段和工程知识：

```text
get_project_context(
  task="定位订单创建失败的根因（create_order、idempotency_key、retry handler）",
  project_root="<project-root>",
  token_budget=1500
)
```

返回结果中的 `index` 是索引状态块：`version` 为 schema 版本，`indexed_at` 为索引生成时间，`refreshed` 表示本次调用是否触发了自动重建，`stale_reason` 为重建原因（`null` 表示索引本来就是最新的）。`retrieval` 说明本次用了哪条检索路径（`mode`、`backend`、`reranked`）。`sufficient` 为 `false` 时 `fallback` 会给出明确原因，提示应改用 Harness 原生搜索，而不是把空包当成"项目里没有相关内容"。`notice` 会复述同样的信息；只有显式跳过检查时才会出现 `WARNING: index is stale`。

`task` 的写法直接影响召回率，请写成"一句话 + 你已知的英文标识符"。在本仓库 50 个真实任务上的实测结果（2026-10-14，索引 schema 3，含 Phase 5 §7.1 中英术语桥与 §7.2a 窗口修正 + Git recency，受控记忆库）：只写中文自然语言平均召回 73.3%（22/50 达标），补充标识符后 98.0%（48/50 达标）。**只写中文自然语言是用户最自然的输入，它 73.3%——这是当前已知缺陷，不是"不推荐的用法"**；术语桥已把它从 50.8% 提上来，剩余缺口是纯中文提问与英文实现之间缺少词面重叠（跨语言匹配，正在按 `docs/roadmap.md` §7 继续推进）。

### `search_project_memory`

搜索经过确认的项目工程事实：

```text
search_project_memory(
  query="订单状态机约束",
  project_root="<project-root>",
  limit=5
)
```

### `record_project_memory`

记录可长期复用的工程事实。该工具会写入目标项目，应保留人工审批：

```text
record_project_memory(
  category="bugs",
  title="Duplicate order root cause",
  content="The retry handler reused an expired idempotency key.",
  project_root="<project-root>",
  tags=["orders", "idempotency"]
)
```

## 4. 在 OpenClaw 中使用

检查配置和实时连接：

```powershell
openclaw mcp list --json
openclaw mcp probe hil --json
```

正常情况下应发现：

```text
hil__index_project
hil__get_project_context
hil__search_project_memory
hil__record_project_memory
```

修改 MCP 配置后执行：

```powershell
openclaw mcp reload
```

调用示例：

```text
先调用 hil__get_project_context：

task="定位项目索引和 token 预算选择的实现"
project_root="<hil-root>"
token_budget=1000

根据返回的上下文总结相关文件、符号和依赖，不修改代码。
```

OpenClaw 会自动启动 HIL MCP Server，不需要提前执行任何 HIL 启动命令。

## 5. 在 Cline CLI 中使用

确认版本和配置：

```powershell
cline --version
cline config mcp --json
```

当前配置应包含启用状态的 `hil`。首次使用 Cline CLI 且尚未配置模型认证时执行：

```powershell
cline auth
```

进入交互模式：

```powershell
cline
```

调用示例：

```text
不要先全量搜索仓库。请调用 hil 的 get_project_context：

task="分析认证模块入口、令牌校验和调用关系"
project_root="<project-root>"
token_budget=1200

先报告 HIL 找到的文件和符号，再决定是否需要补充读取。
```

Cline CLI 会直接通过 MCP 调用 HIL，并自动管理 STDIO Server 进程。

## 6. 在 Cline VS Code 扩展中使用

MCP 配置变更后，建议执行一次：

```text
Ctrl+Shift+P → Developer: Reload Window
```

打开 Cline 面板的 MCP Servers，确认 `hil` 已启用并显示 4 个工具。之后可以使用与 Cline CLI 相同的提示方式。

VS Code 扩展同样会按需自动启动 HIL，不需要手动运行脚本。

## 7. 在 OpenCode 中使用

OpenCode V2 的 MCP 配置与 Cline 不同：本地 Server 放在 `mcp.servers.<name>`，`command` 是**数组**，环境变量用 `environment`。写入全局配置 `~/.config/opencode/opencode.json`：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "hil": {
        "type": "local",
        "command": [
          "<python.exe>",
          "<hil-root>\\run_hil_mcp.py"
        ]
      }
    }
  }
}
```

检查连接：

```powershell
opencode mcp list          # 期望：hil  connected
```

**有意不设置 `HIL_PROJECT_ROOT`，也不设置 `cwd`**：V2 的本地 Server 默认以工作区为工作目录，因此 HIL 的默认根就是"当前打开的项目"，一份全局配置即可服务所有项目。若写死 `HIL_PROJECT_ROOT`，它只会索引那一个项目。

### 7.1 项目黑名单

全局跟随当前项目带来一个副作用：随手打开一个废弃或临时仓库，也会给它建 `.hil`。为此 HIL 支持一份**本地**黑名单——机制在 `src/harness_intelligence/policy.py`，名单本身放配置目录、不进任何仓库：

```text
C:\Users\<你>\.config\harness-intelligence\denied_projects.txt
```

每行一条**绝对路径**（`#` 注释、空行忽略），父目录会连同整棵子树一起拒绝。被拒时四个 MCP 工具与 CLI 都会报错并指出是哪条规则命中的：

```text
project is on the HIL denylist (D:\path\to\deprecated-project); remove it from
C:\Users\<你>\.config\harness-intelligence\denied_projects.txt or HIL_DENYLIST
```

也可用环境变量 `HIL_DENYLIST`（多条用系统路径分隔符 `;`）临时追加，`HIL_DENYLIST_FILE` 覆盖名单文件位置。黑名单在 Harness 边界（MCP 工具与 CLI）生效，库层不拦截，这样 `benchmarks/` 仍能有意地测量任意目录。

## 8. 索引更新策略

V0.1 没有文件监听，但索引会自愈：每次检索前比对 schema 版本与文件集指纹（相对路径、大小、mtime），发现新增、删除、重命名或修改文件就自动重建。因此以下情况**通常不需要手动处理**：

- 新增、删除或重命名源文件；
- 修改了重要类、函数或接口；
- Git 切换分支后代码变化较大；
- 生成代码或目录结构发生变化。

需要显式调用 `index_project` 的场景：确认索引文件数量、排查索引问题，或需要在固定索引上做对照测量。

如果确实不想让某次检索触发重建（例如只对比同一份索引下的排名），CLI 支持跳过检查：

```powershell
python -m harness_intelligence.cli context "任务" $targetProject --no-refresh
```

跳过时返回值会出现 `WARNING: index is stale (...)`，不要把这种结果当作召回评估依据。

仅增加或修改 `.ai-memory` 时不需要重建代码索引，因为该目录已经从代码索引中排除。如果希望项目里的某些派生文件（评测产物、生成的报告等）完全不进入索引，在项目根目录放一个 `.hilignore`，每行一条规则：`benchmarks/results/` 表示排除该目录及其全部内容，`baseline.json` 表示排除任意层级下的同名文件。规则由两条文件发现路径共同遵守（ripgrep 与回退遍历），不会出现"装了 ripgrep 就换一套文件集"的情况。

## 9. 推荐调用策略

- 陌生仓库、跨模块任务和故障定位：先调用 `get_project_context`。
- **把已知的英文标识符写进 `task`**：文件名、符号名、配置项、错误码、CLI 参数。这是当前召回率的最大影响因素：本仓库 50 个真实任务中，纯中文表达平均召回 73.3%，补充标识符后为 98.0%（已达 90% 目标）。
- 新仓库首次使用：调用一次 `index_project`；此后的文件变化无需手动刷新。
- 已知路径的单文件任务：直接读取文件，避免额外 MCP 往返。
- 文档类问题（例如"roadmap 怎么写"）：文档片段已能与代码片段竞争，`HIL-017`、`HIL-018` 在 `raw` 与 `hinted` 两个变体下都已能召回；第二轮修正（路径匹配精确化、文件级加成不再被窗口体积稀释、每文件一个窄窗口）正是为了消除测试文件挤占文档预算的问题。直接读取文档仍然是更快的做法，但不再是必需。
- 默认 token 预算从 800–2000 开始，根据召回情况调整。
- HIL 返回结果用于缩小阅读范围，关键修改前仍需核对真实代码。
- 只有明确为长期事实的内容才写入 `.ai-memory`。`.ai-memory` 位于它所描述的项目内，属于另一个项目的事实对本次检索只是噪声、还要占同一条 token 预算，因此记录时只收本项目事实；每条记录会带上所属项目路径（`project` 字段），让误写可以被检查而不是靠猜。

## 10. 测试与故障排查

运行项目测试：

```powershell
Set-Location -LiteralPath "<hil-root>"
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v   # 154 项，含 MCP stdio 端到端往返、跨 Harness 记忆复用、可选语义后端回退
python benchmarks/verify.py               # 跨阶段验证与回归门；SKIP 表示本机无法运行，不计为通过
python benchmarks/evidence.py             # Phase 4 证据门；报告四条触发条件是否成立
```

`benchmarks/verify.py` 的检查清单与容差见 `benchmarks/README.md` §6。它覆盖单元测试覆盖不到的部分：真实包的行号自洽、两条文件发现路径得到同一文件集、相对基线 `benchmarks/results/baseline.json` 的召回回归、索引与源码集对齐、以及 `--compare` 的三种退出码（3 数据不可用 / 1 未达门槛 / 0 全部通过）。

建议按以下顺序排查：

1. 确认目标项目的 `.hil/index.json` 存在。
2. 确认请求中的 `project_root` 指向正确项目。
3. 运行 `openclaw mcp probe hil --json`、`cline config mcp --json` 或 `opencode mcp list`。
4. 如果报 "project is on the HIL denylist"，从 `~/.config/harness-intelligence/denied_projects.txt`（或 `HIL_DENYLIST`）里移除该项目。
5. 确认 `<python.exe>` 与 `run_hil_mcp.py` 存在。
6. 在 Harness 中显式要求调用 `get_project_context`。
7. 查看返回值的 `index` 字段：`refreshed` 为 `true` 说明本次已自动重建；若 `notice` 出现 `WARNING: index is stale`，说明该次调用跳过了检查，请去掉 `--no-refresh` 或调用 `index_project`。
8. 召回明显偏低时，先把 `task` 改写成"一句话 + 英文标识符"再重试，并对照 `benchmarks/` 的基线判断是否属于已知的文档召回缺口。
9. 如果 Cline VS Code 未显示工具，重新加载 VS Code 窗口；OpenCode 中则用 `opencode mcp list` 确认连接状态。

## 11. Token 优化验证

HIL 能减少重复搜索，但不能在没有对照数据时保证固定节省比例。正式评估应对同一批任务比较：

- 原生 Harness 执行；
- 先使用 HIL Context Package 的执行。

至少记录输入 token、工具调用次数、读取文件数量、重试次数和最终正确性。只有在任务质量保持稳定时，token 减少才构成有效优化。

本仓库已经把该流程脚本化：任务集在 `benchmarks/tasks.jsonl`，统计与门槛判定在 `benchmarks/measure.py`，填写与判定步骤见 `benchmarks/README.md`。当前状态：

- HIL 侧指标可直接复现（召回、包体积、延迟、重复片段），并可用 `--embedding auto|hash` 增加一条语义重排对照臂；
- A/B 判定覆盖 roadmap §5 的五道门槛（token、Recall、成功率、重试次数、跨 Harness 复用），随机分组种子与两臂执行顺序都会记录；
- 原生基线：**OpenClaw 侧已完成**（`ab.jsonl` 50 行已填），Cline/Codex 侧待补；A/B 表未填满时脚本会拒绝输出节省比例（退出码 3）；
- 因此本仓库目前不宣称任何固定节省百分比。
