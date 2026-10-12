"""Cross-harness memory reuse: a fact written through one harness must be
readable through another.

The roadmap's Phase 3 asks to "verify that a fact Cline wrote can be retrieved
by OpenClaw, and the reverse". HIL's answer is structural - facts live in the
target project's ``.ai-memory/`` rather than in one harness's private session
store - but a structural claim without a test is exactly the kind of assumption
this repository refuses to make. So this spawns two independent stdio server
processes with different harness environments against one project directory,
writes through the first and reads through the second.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "run_hil_mcp.py"
CALL_TIMEOUT = timedelta(seconds=60)
FACT_TITLE = "Cross harness cache boundary"


def _payload(result) -> dict | list:
    structured = getattr(result, "structuredContent", None)
    if structured:
        if set(structured) == {"result"} and isinstance(structured["result"], (dict, list)):
            return structured["result"]
        return structured
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"tool result carried no JSON payload: {result!r}")


@asynccontextmanager
async def _session(harness: str, root: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ENTRY_POINT)],
        env={**os.environ, "HIL_PROJECT_ROOT": str(root), "HIL_HARNESS": harness},
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=CALL_TIMEOUT) as session:
            await session.initialize()
            yield session


class CrossHarnessReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "auth.py").write_text(
            "def validate_token(token):\n    return token == 'valid'\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_fact_written_by_one_harness_is_found_by_another(self) -> None:
        written, found, context = asyncio.run(self._handoff())
        self.assertEqual(written["title"], FACT_TITLE)
        self.assertTrue(
            any(item["title"] == FACT_TITLE for item in found),
            f"the second harness could not read the fact: {found}",
        )
        self.assertTrue(
            any(item["title"] == FACT_TITLE for item in context["memories"]),
            "get_project_context did not surface the reused fact",
        )

    async def _handoff(self):
        async def write_session():
            async with _session("cline", self.root) as session:
                indexed = _payload(
                    await session.call_tool("index_project", {"project_root": str(self.root)})
                )
                self.assertEqual(indexed["indexed_files"], 1)
                return _payload(
                    await session.call_tool(
                        "record_project_memory",
                        {
                            "category": "decisions",
                            "title": FACT_TITLE,
                            "content": "Shared caches are owned by the identity service.",
                            "project_root": str(self.root),
                            "tags": ["cache", "boundary"],
                            "source": "cline",
                        },
                    )
                )

        async def read_session():
            async with _session("openclaw", self.root) as session:
                found = _payload(
                    await session.call_tool(
                        "search_project_memory",
                        {
                            "query": "shared cache boundary identity service",
                            "project_root": str(self.root),
                        },
                    )
                )
                context = _payload(
                    await session.call_tool(
                        "get_project_context",
                        {
                            "task": "who owns the shared cache boundary",
                            "project_root": str(self.root),
                            "token_budget": 600,
                        },
                    )
                )
                return found, context

        written = await write_session()
        found, context = await read_session()
        return written, found, context


if __name__ == "__main__":
    unittest.main()
