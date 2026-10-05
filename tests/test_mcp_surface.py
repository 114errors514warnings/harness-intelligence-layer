from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from harness_intelligence.server import create_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "run_hil_mcp.py"
EXPECTED_TOOLS = {
    "index_project",
    "get_project_context",
    "search_project_memory",
    "record_project_memory",
}
CALL_TIMEOUT = timedelta(seconds=60)


def _payload(result) -> dict | list:
    """Return the JSON body of a tool call, whether it arrives structured or as text."""
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


class McpSurfaceTests(unittest.TestCase):
    """The MCP surface is a product contract, so it gets its own tests."""

    def test_server_exposes_exactly_the_four_tools(self) -> None:
        names = {tool.name for tool in asyncio.run(self._list_tools())}
        self.assertEqual(names, EXPECTED_TOOLS)

    def test_tool_schemas_keep_budget_and_root_optional(self) -> None:
        tools = {tool.name: tool for tool in asyncio.run(self._list_tools())}
        context_schema = tools["get_project_context"].inputSchema
        self.assertEqual(context_schema["required"], ["task"])
        self.assertIn("project_root", context_schema["properties"])
        self.assertIn("token_budget", context_schema["properties"])
        memory_schema = tools["record_project_memory"].inputSchema
        self.assertEqual(
            set(memory_schema["required"]), {"category", "title", "content"}
        )

    @staticmethod
    async def _list_tools():
        server = create_server()
        return await server.list_tools()


class McpStdioBridgeTests(unittest.TestCase):
    """End-to-end check through the same stdio entry point harnesses launch."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "auth.py").write_text(
            "def validate_token(token):\n    return token == 'valid'\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_stdio_server_round_trip(self) -> None:
        names, indexed, context, found = asyncio.run(self._round_trip())
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(indexed["indexed_files"], 1)
        self.assertIn("auth.py", {item["path"] for item in context["fragments"]})
        self.assertLessEqual(context["estimated_tokens"], 600)
        self.assertEqual(found[0]["title"], "Round trip fact")
        self.assertIn("mcp-test", found[0]["tags"])

    async def _round_trip(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ENTRY_POINT)],
            env={**os.environ, "HIL_PROJECT_ROOT": str(self.root)},
            cwd=str(PROJECT_ROOT),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=CALL_TIMEOUT
            ) as session:
                await session.initialize()
                listed = await session.list_tools()
                indexed = _payload(
                    await session.call_tool(
                        "index_project", {"project_root": str(self.root)}
                    )
                )
                context = _payload(
                    await session.call_tool(
                        "get_project_context",
                        {
                            "task": "validate_token authentication",
                            "project_root": str(self.root),
                            "token_budget": 600,
                        },
                    )
                )
                await session.call_tool(
                    "record_project_memory",
                    {
                        "category": "decisions",
                        "title": "Round trip fact",
                        "content": "Written through the MCP stdio bridge.",
                        "project_root": str(self.root),
                        "tags": ["mcp-test"],
                    },
                )
                found = _payload(
                    await session.call_tool(
                        "search_project_memory",
                        {"query": "round trip fact", "project_root": str(self.root)},
                    )
                )
        return (
            {tool.name for tool in listed.tools},
            indexed,
            context,
            [item for item in found if item["title"] == "Round trip fact"],
        )


if __name__ == "__main__":
    unittest.main()