from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


INDEX_VERSION = 1
DEFAULT_EXCLUDES = {
    ".ai-memory", ".git", ".hil", ".venv", "node_modules", "dist", "build", "__pycache__"
}
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


def _rg_files(root: Path) -> list[Path] | None:
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
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return [root / line for line in result.stdout.splitlines() if line]


def discover_files(root: Path) -> Iterable[Path]:
    rg_files = _rg_files(root)
    if rg_files is not None:
        candidates = rg_files
    else:
        candidates = []
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in DEFAULT_EXCLUDES]
            candidates.extend(Path(current) / name for name in files)
    for path in candidates:
        if path.suffix.lower() in TEXT_SUFFIXES and path.is_file():
            yield path


def read_text(path: Path, max_bytes: int = 2_000_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


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
    entries = []
    for path in discover_files(root):
        text = read_text(path)
        if text is None:
            continue
        stat = path.stat()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "line_count": text.count("\n") + 1,
                "symbols": [asdict(symbol) for symbol in extract_symbols(text)],
            }
        )
    payload = {"version": INDEX_VERSION, "root": str(root), "files": entries}
    index_dir = root / ".hil"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"root": str(root), "indexed_files": len(entries), "index": str(index_dir / "index.json")}


def load_index(project_root: str | Path, create: bool = True) -> dict:
    root = Path(project_root).resolve()
    path = root / ".hil" / "index.json"
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        index_project(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != INDEX_VERSION:
        return _load_after_reindex(root)
    return payload


def _load_after_reindex(root: Path) -> dict:
    index_project(root)
    return json.loads((root / ".hil" / "index.json").read_text(encoding="utf-8"))
