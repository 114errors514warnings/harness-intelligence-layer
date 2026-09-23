# Repository expectations

- Keep the MCP surface limited to project intelligence; do not add generic shell, file editing, sessions, or agent-loop tools.
- Preserve a dependency-light core. Optional retrieval backends must degrade to local lexical retrieval.
- Run `python -m unittest discover -s tests -v` after Python changes.
- Treat `.ai-memory` as curated engineering facts, not a transcript store.
- Any claimed token reduction must be supported by the benchmark described in `docs/roadmap.md`.

