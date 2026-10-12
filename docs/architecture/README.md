# 架构图（Archify）

本目录是可交互的 [Archify](https://github.com/tt-a1i/archify) 架构图成品与它的 Typed Source：

| 文件 | 说明 |
|---|---|
| `hil-runtime.html` | 自包含的交互式架构图（内联 SVG、深浅主题、路径/焦点/导出）。用浏览器直接打开即可，无需安装 Archify。 |
| `hil-runtime.architecture.json` | 生成该图的 Typed JSON Source；修改它并用 Archify CLI 重新 `finalize` 即可迭代。 |

## 图中描述的内容

图的运行时主线是：`AI Coding Harness → HIL MCP Server → get_project_context → .hil/index.json`，
以及分支上的 `工程记忆 memory.py → .ai-memory/` 与可选的语义重排后端。图的说明卡片补齐了
MCP 工具面、检索实现、Phase 3 门槛、Phase 4 证据门与测量卫生。

该图由仓库代码生成，并固定到 `hil-runtime.architecture.json` 的 `meta.repository.revision`
所指的提交；每个关键组件都带有 `sources`（文件与行号）。`meta.repository.link_mode` 为
`local-only`，因为本仓库的 origin 是 SSH 地址，不生成可点击的 Web 源码链接。

## 重新生成

需要 Node.js ≥ 18 与 Archify 3.x。先冻结当前提交（Archify 只按已提交的字节核验源码证据）：

```powershell
git add -A; git commit -m "Describe the change"
node <archify>/bin/archify.mjs finalize architecture `
  docs/architecture/hil-runtime.architecture.json `
  .archify/architecture-rebuild/hil-runtime.html `
  --repo-root . --quality showcase --json
```

`finalize` 会依次跑 `validate`、`deliver`、严格 `check` 与真实浏览器 `browser-check`；
任一非零退出都不算成功。修订 `candidate.json` 后请更新 `meta.repository.revision` 并重跑。

## 为什么排除在代码索引之外

`.html` 与 `.json` 都是被索引的后缀，而渲染后的图是一个近 750 KB 的内联 SVG 文件。
把它放进索引会与真实源码争夺同一份 token 预算——这正是 `benchmarks/results/` 被排除的同一个
原因。因此仓库根的 `.hilignore` 排除了 `docs/architecture/` 与 `.archify/`。
