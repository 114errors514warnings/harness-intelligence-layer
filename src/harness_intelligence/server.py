from __future__ import annotations

import os
from pathlib import Path

from .indexer import index_project as build_index
from .memory import record_memory, search_memory
from .policy import ensure_allowed
from .retrieval import get_project_context as build_context


#: Files/directories that mark a directory as a project people work in. Used only to
#: decide whether the process cwd is a safe fallback when HIL_PROJECT_ROOT is unset.
PROJECT_MARKERS = (
    ".git", ".hil", "pyproject.toml", "package.json", "project.godot",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "CMakeLists.txt",
)


def _default_root() -> str:
    """The project a tool call targets when the caller passes no ``project_root``.

    Order: ``HIL_PROJECT_ROOT``, then the process cwd **if it looks like a project**.
    A harness that runs its MCP server from a fixed directory would otherwise make
    every project silently read the same repository; an explicit error is far easier
    to act on than a package that quietly describes the wrong tree.
    """
    configured = os.environ.get("HIL_PROJECT_ROOT", "").strip()
    if configured:
        return configured
    cwd = Path.cwd()
    if any((cwd / marker).exists() for marker in PROJECT_MARKERS):
        return str(cwd)
    raise ValueError(
        "no project root: set HIL_PROJECT_ROOT or pass project_root explicitly "
        f"(the working directory {cwd} does not look like a project)"
    )


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("Install the project first: pip install -e .") from exc

    mcp = FastMCP(
        "Harness Intelligence Layer",
        instructions=(
            "Use project context for unfamiliar or cross-file tasks. Skip it for obvious single-file tasks. "
            "Record only durable, verified engineering facts; never store chat transcripts or secrets."
        ),
    )

    @mcp.tool()
    def index_project(project_root: str = "") -> dict:
        """Build or refresh the lightweight project symbol index."""
        root = project_root or _default_root()
        ensure_allowed(root)
        return build_index(root)

    @mcp.tool()
    def get_project_context(task: str, project_root: str = "", token_budget: int = 4000) -> dict:
        """Return high-value code fragments and project facts within a token budget."""
        root = project_root or _default_root()
        ensure_allowed(root)
        return build_context(task, root, token_budget)

    @mcp.tool()
    def search_project_memory(query: str, project_root: str = "", limit: int = 5) -> list[dict]:
        """Search curated, cross-harness engineering facts for this project."""
        root = project_root or _default_root()
        ensure_allowed(root)
        return search_memory(query, root, limit)

    @mcp.tool()
    def record_project_memory(
        category: str,
        title: str,
        content: str,
        project_root: str = "",
        tags: list[str] | None = None,
        source: str | None = None,
    ) -> dict:
        """Store a verified reusable fact, not a conversation transcript or secret."""
        root = project_root or _default_root()
        ensure_allowed(root)
        return record_memory(category, title, content, root, tags, source)

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()

