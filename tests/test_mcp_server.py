"""Tests for the MCP server: it exposes every agent tool, and turns tool
failures into readable error results instead of crashing the connection."""

import asyncio

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from fantasy_agent.agent.tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolError
from fantasy_agent.mcp_server import server


def _run(coro):
    return asyncio.run(coro)


async def _list_tools():
    async with connect(server) as client:
        return (await client.list_tools()).tools


async def _call(name, args):
    async with connect(server) as client:
        return await client.call_tool(name, args)


def test_every_agent_tool_is_exposed_with_its_schema():
    tools = {t.name: t for t in _run(_list_tools())}
    assert set(tools) == {t["name"] for t in TOOL_SCHEMAS}
    for schema in TOOL_SCHEMAS:
        assert tools[schema["name"]].inputSchema == schema["parameters"]


@pytest.fixture
def fake_tool(monkeypatch):
    """Swap in a handler we control so tests don't need a synced database."""
    calls = {}

    def install(behavior):
        def handler(session, **args):
            calls["args"] = args
            return behavior(args)

        monkeypatch.setitem(TOOL_HANDLERS, "get_rankings", handler)
        monkeypatch.setattr("fantasy_agent.mcp_server.get_session", _dummy_session)
        return calls

    return install


class _dummy_session:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def test_successful_call_returns_json(fake_tool):
    calls = fake_tool(lambda args: {"rankings": [{"name": "Josh Allen"}]})
    result = _run(_call("get_rankings", {"position": "QB"}))
    assert not result.isError
    assert "Josh Allen" in result.content[0].text
    assert calls["args"] == {"position": "QB"}


def test_tool_error_message_reaches_the_client(fake_tool):
    def fail(args):
        raise ToolError("No team matches 'Bob'.")

    fake_tool(fail)
    result = _run(_call("get_rankings", {}))
    assert result.isError
    assert "No team matches 'Bob'." in result.content[0].text


def test_unexpected_crash_returns_friendly_error(fake_tool):
    def crash(args):
        raise KeyError("internal detail")

    fake_tool(crash)
    result = _run(_call("get_rankings", {}))
    assert result.isError
    assert "unexpected error" in result.content[0].text
    assert "internal detail" not in result.content[0].text


def test_unknown_tool_is_an_error_not_a_crash():
    result = _run(_call("not_a_tool", {}))
    assert result.isError
