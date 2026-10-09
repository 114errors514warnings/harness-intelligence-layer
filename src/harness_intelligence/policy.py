"""A local denylist of projects HIL must refuse to touch.

HIL is meant to be configured once per Harness and then follow whatever project
is open. Without a deny list, that convenience would also index a scratch or
abandoned project the moment it is opened. The list is deliberately local: the
mechanism ships here, but which paths are denied lives in the user's config
directory, outside any repository.

Resolution order, both merged:

* ``HIL_DENYLIST`` - project paths separated by ``os.pathsep`` (also newlines),
  useful for a Harness that would rather pass the list inline;
* ``<config>/harness-intelligence/denied_projects.txt`` - one absolute path per
  line, ``#`` comments and blank lines ignored. ``<config>`` is
  ``$XDG_CONFIG_HOME`` or ``~/.config``; ``HIL_DENYLIST_FILE`` overrides the file.

A denied entry denies the path itself and everything under it, compared
case-insensitively so Windows paths behave. Matching is by resolved path, so a
denied directory is still denied when reached through a relative or symlinked
route.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DENYLIST_ENV = "HIL_DENYLIST"
DENYLIST_FILE_ENV = "HIL_DENYLIST_FILE"
CONFIG_DIR_NAME = "harness-intelligence"
DENYLIST_FILE_NAME = "denied_projects.txt"


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / CONFIG_DIR_NAME


def denylist_path() -> Path:
    override = os.environ.get(DENYLIST_FILE_ENV)
    return Path(override) if override else _config_dir() / DENYLIST_FILE_NAME


def _split_env(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in value.replace("\r", "").split("\n"):
        parts.extend(chunk.split(os.pathsep))
    return [part.strip() for part in parts if part.strip()]


def _normalise(path: str | Path) -> str:
    resolved = str(Path(path).expanduser().resolve())
    return resolved.lower() if sys.platform == "win32" else resolved


def denied_paths() -> list[Path]:
    """Every path on the deny list, from the environment and the config file."""
    raw: list[str] = []
    if os.environ.get(DENYLIST_ENV):
        raw.extend(_split_env(os.environ[DENYLIST_ENV]))
    path = denylist_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            raw.append(line)
    # Keep order, drop repeats that differ only by case on Windows.
    seen: set[str] = set()
    out: list[Path] = []
    for item in raw:
        key = _normalise(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(item).expanduser())
    return out


def deny_reason(project_root: str | Path) -> str | None:
    """The entry that denies ``project_root``, or ``None`` when it is allowed."""
    target = _normalise(project_root)
    for entry in denied_paths():
        denied = _normalise(entry)
        if target == denied or target.startswith(denied + os.sep):
            return str(entry)
    return None


def ensure_allowed(project_root: str | Path) -> None:
    """Raise ``ValueError`` when ``project_root`` is on the deny list.

    Called at the Harness-facing boundary (the MCP tools and the CLI), not inside
    the indexing library, so a benchmark can still measure any tree deliberately.
    """
    reason = deny_reason(project_root)
    if reason:
        raise ValueError(
            f"project is on the HIL denylist ({reason}); remove it from "
            f"{denylist_path()} or {DENYLIST_ENV} to allow it"
        )
