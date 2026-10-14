"""Optional git-recency signal (``docs/roadmap.md`` §4 Phase 2).

A file touched by the last few commits is a weak, non-semantic hint that it is
closer to the current task. It is deliberately optional and bounded:

* Not a git checkout, no ``git`` on PATH, or any git error yields **no signal** and
  retrieval is exactly as if this module did not exist.
* The result is one bounded ``git log`` call, cached for a short TTL so an MCP
  session does not spawn git on every query.

Like every other signal here it is a *hint*, never a claim: which weight it earns
is decided by ``benchmarks/measure.py``, not by this module.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

#: A wedged git must never take the MCP server down with it.
GIT_TIMEOUT_SECONDS = 5
#: How long a computed answer is reused within one process.
CACHE_TTL_SECONDS = 60.0
#: How far back "recent" reaches.
DEFAULT_RECENT_COMMITS = 50

_cache: dict[str, tuple[float, frozenset[str]]] = {}


def reset_cache() -> None:
    """Drop memoised results (used by tests that create a repository)."""
    _cache.clear()


def recent_paths(
    root: str | Path, commits: int = DEFAULT_RECENT_COMMITS
) -> frozenset[str]:
    """Repository-relative paths touched by the last ``commits`` commits.

    Returns an empty set whenever the signal is unavailable, so callers never have
    to special-case a non-git tree.
    """
    key = str(Path(root).resolve())
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    paths = _git_recent(root, commits)
    _cache[key] = (now, paths)
    return paths


def _git_recent(root: str | Path, commits: int) -> frozenset[str]:
    try:
        result = subprocess.run(
            [
                "git", "log", f"-n{commits}", "--name-only", "--relative",
                "--pretty=format:",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())
