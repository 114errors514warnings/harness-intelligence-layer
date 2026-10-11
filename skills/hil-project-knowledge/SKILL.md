---
name: hil-project-knowledge
description: Initialize, refresh, query, and curate a project's shared Harness Intelligence Layer index and engineering memory. Use when a user asks to build a project knowledge base, retrieve token-budgeted project context through HIL, refresh a stale HIL index, or preserve a verified engineering fact for reuse across OpenClaw, Cline, and other MCP clients. Do not use for ordinary single-file reads that do not benefit from project retrieval.
---

# HIL Project Knowledge

Use HIL as a shared project-intelligence layer, not as a replacement for the host Harness.

## Resolve the target

- Use an explicit `project_root` supplied by the user.
- Otherwise use the active workspace root.
- Prefer an absolute path when calling HIL so different Harness working directories resolve the same project.
- Do not assume the HIL implementation repository is the target project.

## Choose the operation

### Initialize or refresh

Call `index_project(project_root)` when:

- the user asks to create or initialize project knowledge;
- the target has no `.hil/index.json`;
- the user asks to refresh the index;
- the user wants an explicit confirmation of indexed file count.

Do not rebuild the index before every query. V0.1 has no file watcher, but retrieval is now self-healing: `load_index` compares the stored schema version and file-set fingerprint against the working tree and rebuilds automatically when they differ, reporting `refreshed` and `stale_reason` in the `index` block of `get_project_context`. So a stale index no longer degrades results silently — it is repaired on access.

### Retrieve project context

Call `get_project_context(task, project_root, token_budget)` before broad repository exploration when the task is unfamiliar, cross-file, architectural, or diagnostic.

Write the `task` string as one sentence **plus the identifiers you already know**: file names, symbol names, configuration keys, error codes, CLI flags. Measured on the repository's task set (50 real tasks, 1500 token budget), identifier-rich task strings raised mean context recall from 50.8% to 98.5%, which meets the 90% target with almost no required file missed; a Chinese-only question still reaches only 50.8%, because it shares no literal form with the English implementation files. Never omit an identifier you already have.

Use the smallest useful budget:

- 800 tokens for a focused symbol or entry-point lookup;
- 1200–2000 tokens for ordinary cross-file work;
- up to 3000 tokens for architecture or broad dependency analysis.

Inspect the returned `fragments`, `memories`, selection reasons, estimated token count, and the `index` status block. Treat V0.1 lexical results as a reading shortlist, not proof that no other relevant code exists. Verify critical code before editing.

Documentation questions ("what does the roadmap say", "why was this decision made") are the weakest case in V0.1: docs declare no symbols and their lines are long, so they lose to code fragments under the token-budget ranking. Read `docs/*` directly for those.

Skip HIL for a simple task whose exact file and location are already known unless the user explicitly requests HIL.

### Search engineering memory

Call `search_project_memory(query, project_root, limit)` when prior architecture decisions, conventions, bug causes, constraints, or experiment results could affect the task.

Memory is curated project knowledge, not conversation history. Do not treat an absent result as evidence that no constraint exists.

### Record engineering memory

Call `record_project_memory(...)` only when the user asks to preserve knowledge or the requested workflow clearly includes documenting a verified durable fact.

Use the narrowest matching category:

- `architecture`
- `decisions`
- `bugs`
- `conventions`
- `experiments`
- `tasks`

Record concise facts with useful tags and a source when one is known. Never store secrets, credentials, personal data, raw chat transcripts, speculative conclusions, or transient progress. Do not convert every completed task into memory.

Record facts about the project that *owns* the store. `.ai-memory` sits inside the project it describes, so a fact about a different repository is noise for this project's queries and is spent against the same token budget; each record carries the owning project path (`project`) so a misfiled fact is checkable instead of a guess. Do not copy another project's facts into this store.

Changes limited to `.ai-memory` do not require rebuilding the code index because the memory store is intentionally excluded from `.hil/index.json`. Project-level rules work the same way: a derived file listed in the project's `.hilignore` (for example a generated report under `benchmarks/results/`) is never indexed, so regenerating it does not invalidate the index.

## MCP lifecycle

Do not manually start `run_hil_mcp.py`. OpenClaw, Cline, and other configured MCP clients launch the STDIO server when a HIL tool is called and manage its lifetime.

If HIL tools are unavailable:

1. Report that the MCP server is not available in the current client.
2. When local shell execution is allowed and the HIL repository is available, use its management CLI as a fallback:

   ```powershell
   $env:PYTHONPATH = "<hil-root>\src"
   python -m harness_intelligence.cli index "<project-root>"
   python -m harness_intelligence.cli context "<task>" "<project-root>" --budget 1200
   ```

3. Do not install packages, edit global Harness configuration, or start a persistent service unless the user requests that setup.

## Report results

After initialization, report the resolved project root, indexed file count, and index path.

After retrieval, report the most relevant files or symbols, the estimated token usage versus budget, relevant memory facts, and any material recall uncertainty.

Do not claim a percentage token reduction from a single lookup. Token-efficiency claims require the repository's documented A/B benchmark.
