# FantasyAgent MCP server

Lets Claude Desktop (or any MCP client) use FantasyAgent's tools directly:
league info, rosters, rankings, keeper values, trade evaluation, best available,
power rankings, and recent game logs. It reuses the same tools the built-in agent
uses, so there is only one copy of each tool to maintain.

Code: `src/fantasy_agent/mcp_server.py`. Tests: `tests/test_mcp_server.py`.

## 1. Install

`mcp` is a regular dependency in `pyproject.toml` (pinned `>=1.2,<2` on
purpose: the 2.x SDK changed its server API, and most docs and examples still
use 1.x), and `fantasy-agent-mcp` is a console script. Reinstall to pick both up:

```
pip install -e .
```

## 2. Run the tests

```
pytest tests/test_mcp_server.py
```

## 3. Connect it to Claude Desktop

Run `fantasy-agent sync` first so the local database has data.

Open Claude Desktop, go to Settings > Developer > Edit Config, and add:

```json
{
  "mcpServers": {
    "fantasy-agent": {
      "command": "C:\\full\\path\\to\\FantasyAgent\\.venv\\Scripts\\fantasy-agent-mcp.exe",
      "env": {
        "SLEEPER_LEAGUE_ID": "your league id",
        "SLEEPER_OWNER_USER_ID": "your user id",
        "DATABASE_URL": "sqlite:///C:/full/path/to/FantasyAgent/data/fantasy_agent.db"
      }
    }
  }
}
```

Restart Claude Desktop and ask something like "who are the top keeper
candidates on my team?"

**Why the full paths:** the `.env` file and the database are found relative
to the folder the program starts in. Claude Desktop starts the server from a
different folder, so without full paths it would make a new empty database and
every tool would say "No cached league data."

No `OPENAI_API_KEY` is needed here: the MCP client's own model does the
reasoning, and the server only runs the tools.

## How it works

- `list_tools` turns each entry in `TOOL_SCHEMAS` into an MCP tool.
- `call_tool` opens a database session, runs the matching handler from
  `TOOL_HANDLERS`, and returns the result as JSON.
- Expected problems (unknown team, player not on roster, no synced data) come
  back as clear error messages the model can read and fix, like "No team
  matches 'Bob'. Teams in this league: ...".
- Unexpected crashes are logged in full on the server side, and the client
  gets a short friendly message instead of a stack trace.
- Every call is logged with the tool name, status, and how long it took.
  Logs go to stderr because stdout is used for the MCP messages themselves.
