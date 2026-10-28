"""MCP server for FantasyAgent.

Exposes the same tools the built-in agent uses (agent/tools.py) over the Model
Context Protocol, so any MCP client (Claude Desktop, Claude Code, an IDE) can
call them. TOOL_SCHEMAS and TOOL_HANDLERS stay the single source of truth:
adding a tool there makes it show up here too, with no copy to keep in sync.

Run it with:  fantasy-agent-mcp     (talks MCP over stdin/stdout)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .agent.tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolError
from .db.session import get_session, init_db

log = logging.getLogger("fantasy_agent.mcp")

server = Server("fantasy-agent")


def _text(payload: Any) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    # Our schemas are in OpenAI's function-tool shape; MCP wants inputSchema.
    return [
        types.Tool(name=t["name"], description=t["description"], inputSchema=t["parameters"])
        for t in TOOL_SCHEMAS
    ]


def _run_tool(name: str, args: dict) -> dict:
    """Run one handler in its own DB session (sync code, called off the event loop)."""
    handler = TOOL_HANDLERS[name]
    with get_session() as session:
        return handler(session, **args)


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    if name not in TOOL_HANDLERS:
        raise ValueError(f"Unknown tool '{name}'. Available: {', '.join(TOOL_HANDLERS)}")

    start = time.perf_counter()
    try:
        result = await asyncio.to_thread(_run_tool, name, arguments or {})
    except ToolError as exc:
        # Expected, fixable problems (unknown team, no synced data). The message is
        # written for the model to read and recover from, so pass it through as-is.
        log.info("tool=%s status=tool_error ms=%.0f msg=%s", name, (time.perf_counter() - start) * 1000, exc)
        raise ValueError(str(exc)) from exc
    except Exception:
        # Anything else is a bug: log the full trace for us, keep the reply friendly.
        log.exception("tool=%s status=crash", name)
        raise ValueError(f"'{name}' hit an unexpected error. Details are in the server log.")

    log.info("tool=%s status=ok ms=%.0f", name, (time.perf_counter() - start) * 1000)
    return _text(result)


async def _serve() -> None:
    init_db()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    # stdout carries the MCP protocol itself, so logs must go to stderr
    # (basicConfig's default stream). Configured here, not at import time, so
    # importing this module (e.g. from tests) doesn't reconfigure global logging.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
