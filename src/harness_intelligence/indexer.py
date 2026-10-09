from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


INDEX_VERSION = 2
DEFAULT_EXCLUDES = {
    ".ai-memory", ".git", ".hil", ".venv", "node_modules", "dist", "build", "__pycache__"
}
#: Per-project ignore file, read from the project root. Patterns are applied to
#: both discovery paths in Python, so ripgrep and the os.walk fallback cannot
#: disagree about what this project considers source.
IGNORE_FILE = ".hilignore"
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".jsx", ".json", ".kt", ".md", ".php", ".py",
    ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".vue",
    ".xml", ".yaml", ".yml",
}

SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)")),
    ("type", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)")),
    ("type", re.compile(r"^\s*(?:public\s+)?(?:class|interface|record|enum)\s+([A-Za-z_]\w*)")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),
]


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line: int


#: Give up on ripgrep after this many seconds and fall back to os.walk. A wedged
#: child must never take the MCP server down with it.
RG_TIMEOUT_SECONDS = 60


def _rg_files(root: Path) -> list[Path] | None:
    """File discovery through ripgrep, or ``None`` to use the os.walk fallback.

    ``stdin`` is pinned to ``DEVNULL`` on purpose. ripgrep reads standard input
    when it is not a terminal and no path is given (to support piping), and the
    MCP server's stdin is the client's JSON-RPC pipe - which has no EOF while the
    session lives. Inheriting it made ripgrep block forever: ``index_project``
    hung, and every later tool call timed out behind it. A closed stdin plus a
    timeout keeps discovery bounded no matter who launches the server.
    """
    try:
        result = subprocess.run(
            [
                "rg", "--files", "--hidden", "-g", "!.git/**", "-g", "!.hil/**",
                "-g", "!.ai-memory/**",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=RG_TIMEOUT_SECONDS,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    return [root / line for line in result.stdout.splitlines() if line]


def ignore_patterns(root: Path) -> list[str]:
    """Read ``.hilignore`` from the project root; a missing file means no rules."""
    try:
        lines = (root / IGNORE_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    patterns = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(relative: str, patterns: list[str]) -> bool:
    """Match a repository-relative POSIX path against the project's rules.

    A trailing slash marks a directory and everything under it. Any other
    pattern is matched against the whole relative path and against its last
    segment, so ``baseline.json`` and ``benchmarks/results/`` both read the way
    a person expects.
    """
    name = relative.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                return True
        elif fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def discover_files(root: Path) -> Iterable[Path]:
    patterns = ignore_patterns(root)
    rg_files = _rg_files(root)
    if rg_files is not None:
        candidates = rg_files
    else:
        candidates = []
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in DEFAULT_EXCLUDES]
            candidates.extend(Path(current) / name for name in files)
    for path in candidates:
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if is_ignored(relative, patterns):
            continue
        yield path


def read_text(path: Path, max_bytes: int = 2_000_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def file_state(root: Path, paths: Iterable[Path]) -> tuple[int, str]:
    """Cheap fingerprint of the candidate file set: (count, hash of path|size|mtime).

    Only metadata is read, so a freshness check costs one directory walk instead
    of re-reading every file.
    """
    parts = []
    for path in paths:
        try:
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        parts.append(f"{relative}|{stat.st_size}|{stat.st_mtime_ns}")
    parts.sort()
    return len(parts), hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def extract_symbols(text: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.match(line)
            if match:
                symbols.append(Symbol(match.group(1), kind, number))
                break
    return symbols


def index_project(project_root: str | Path) -> dict:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    candidates = list(discover_files(root))
    candidate_files, fingerprint = file_state(root, candidates)
    entries = []
    for path in candidates:
        try:
            text = read_text(path)
            if text is None:
                continue
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "line_count": text.count("\n") + 1,
                "symbols": [asdict(symbol) for symbol in extract_symbols(text)],
            }
        )
    payload = {
        "version": INDEX_VERSION,
        "root": str(root),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "candidate_files": candidate_files,
        "fingerprint": fingerprint,
        "files": entries,
    }
    index_dir = root / ".hil"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "root": str(root),
        "indexed_at": payload["indexed_at"],
        "indexed_files": len(entries),
        "candidate_files": candidate_files,
        "symbol_count": sum(len(entry["symbols"]) for entry in entries),
        "index": str(index_dir / "index.json"),
    }


def load_index(project_root: str | Path, create: bool = True, refresh: bool = True) -> dict:
    """Load the index, rebuilding it when the schema or the working tree drifted.

    A stored index is only reused when its schema version matches AND its file
    fingerprint matches the current tree, so a stale snapshot can no longer be
    served silently. The returned payload carries two in-memory-only keys:
    ``refreshed`` (a rebuild happened during this call) and ``stale_reason``
    (why the stored index did not match, or ``None`` when it was current).
    """
    root = Path(project_root).resolve()
    path = root / ".hil" / "index.json"
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        return _payload_after_rebuild(root, "index missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not create:
            raise FileNotFoundError(path) from exc
        return _payload_after_rebuild(root, f"index unreadable ({exc.__class__.__name__})")
    reason = staleness_reason(root, payload)
    if reason and refresh:
        return _payload_after_rebuild(root, reason)
    payload["refreshed"] = False
    payload["stale_reason"] = reason
    return payload


def _payload_after_rebuild(root: Path, reason: str) -> dict:
    index_project(root)
    payload = json.loads((root / ".hil" / "index.json").read_text(encoding="utf-8"))
    payload["refreshed"] = True
    payload["stale_reason"] = reason
    return payload


def staleness_reason(root: Path, payload: dict) -> str | None:
    """Explain why a stored index does not describe the current tree."""
    if payload.get("version") != INDEX_VERSION:
        return f"schema version {payload.get('version')} != {INDEX_VERSION}"
    fingerprint = payload.get("fingerprint")
    if not fingerprint:
        return "index has no fingerprint"
    candidate_files, current = file_state(root, discover_files(root))
    if current != fingerprint:
        return (
            f"file set changed (indexed {payload.get('candidate_files', '?')} files, "
            f"found {candidate_files})"
        )
    return None
