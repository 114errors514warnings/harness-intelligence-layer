"""Dependency-light entry point for MCP clients that sanitize PYTHONPATH."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from harness_intelligence.server import main  # noqa: E402


if __name__ == "__main__":
    main()
