# Fantasy Agent

An AI agent that helps manage a 12-team PPR superflex keeper league on Sleeper. It answers
questions like "should I keep Bijan or draft fresh," "is this trade fair," and "who's the best
player available right now" by pulling live league/player data and reasoning over it with
Claude's tool-calling — not a static value chart, and not a chatbot wrapper.

See [fantasy-agent-spec.md](fantasy-agent-spec.md) for the original project spec.

## Status

MVP complete, following the spec's build order:

1. Sleeper API integration + local cache (league, rosters, users, players, draft history)
2. FantasyPros rankings scraper + player-ID matching
3. Keeper decision logic + trade analyzer (validated as pure data pipelines, no LLM)
4. Claude tool-calling agent wired to the above
5. Draft-day best-available assistant (live-polled, superflex-aware)

## Setup

```bash
python -m venv .venv
./.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # defaults already point at the real league
```

`ANTHROPIC_API_KEY` in `.env` is only required for `fantasy-agent ask`. Every other command
works against the local cache with no API key.

## Usage

```bash
# --- Data layer: pull everything into the local cache ---
fantasy-agent sync                          # league, rosters, users, players, draft history
fantasy-agent league                        # cached league settings
fantasy-agent rosters                       # power-rank every team 1-N, with QB/RB/WR/TE breakdown
fantasy-agent rosters --detail              # + each team's best starting lineup
fantasy-agent players --search "mahomes"    # sanity-check the player cache

# --- Rankings: scrape FantasyPros, match to Sleeper player IDs ---
fantasy-agent rankings-sync                 # scrape + match (rate-limited, cached ~20h)
fantasy-agent rankings-show --search "mahomes"
fantasy-agent rankings-unmatched            # players the matcher couldn't resolve
fantasy-agent rankings-alias <fp_id> <sleeper_id>   # manual override for a bad/no match

# --- Pure data-pipeline tools (no LLM) ---
fantasy-agent keepers                       # rank your roster's keeper candidates
fantasy-agent trade --side-a-owner <id> --side-a-gives p1,p2 \
                     --side-b-owner <id> --side-b-gives p3
fantasy-agent best-available                # live draft board (polls Sleeper fresh every call)

# --- The agent itself ---
fantasy-agent ask "should I keep Bijan Robinson or draft fresh?"
```

`players/nfl` is a multi-MB dump Sleeper asks callers not to poll frequently, so it's only
re-pulled when the cache is older than `PLAYERS_CACHE_TTL_HOURS` (default 24h; `sync
--force-players` bypasses that during draft week). FantasyPros rankings are cached the same
way, on `RANKINGS_CACHE_TTL_HOURS`. The agent never scrapes or hits Sleeper live mid-conversation
— with one deliberate exception: `best-available` polls the draft endpoint fresh on every call,
because "who's been picked" can't be allowed to go stale during a live draft.

## Desktop GUI

A small dark-themed Tkinter launcher (`gui.py`) wraps the CLI for point-and-click use — quick
buttons for `sync`/`keepers`/`best-available`/etc., a text box for `ask`, and a live output panel.
No separate install: it's the same `fantasy_agent` package.

```bash
./run_gui.bat          # double-click, or run from a shell -- launches with the venv's pythonw
```

### Standalone .exe (no Python/venv required to run)

```bash
pip install -e ".[build]"     # PyInstaller + hook contrib, one-time
./build_exe.bat                # or: .venv\Scripts\pyinstaller.exe FantasyAgent.spec
```

Produces `dist/FantasyAgent/FantasyAgent.exe` plus a supporting `_internal/` folder — keep them
together (it's a folder-based build, not a single portable file; see below for why). Copy your
`.env` into `dist/FantasyAgent/` alongside the exe before running.

**Why `--onedir`, not `--onefile`.** The GUI runs every command (`sync`, `ask`, ...) by launching
itself again as a subprocess with CLI arguments — `launcher.py` dispatches on `sys.argv` to decide
whether a given launch is "open the GUI" or "run the CLI." A `--onefile` build re-extracts its
entire bundle to a temp directory on *every* launch, which would make every single button click
pay that extraction cost. `--onedir` runs directly from disk with no such penalty.

## Architecture

```
                    You (CLI: ask "...")
                             |
                    Agent core (agent/core.py)
                    Claude + a manual tool-calling loop
                 -----------------------------------
                 |           |            |         |
          Sleeper cache  Rankings    Keeper/Trade  Live draft
           (sync.py)      cache       pipelines    board (draft.py,
                                    (keeper.py,      polls Sleeper
                                     trade.py)        directly)
                 |           |            |
                 -----------------------------------
                             |
                    SQLite (data/fantasy_agent.db)
```

The agent doesn't do one API call and hand it to Claude — `agent/core.py` runs an explicit
`while stop_reason == "tool_use"` loop (see "Why a manual loop" below). Claude decides which of
the 9 tools in `agent/tools.py` it needs for a given question, the handler runs against the
local cache (or, for `get_best_available`, a live Sleeper call), and the result goes back to
Claude to reason over — possibly triggering more tool calls — before it answers. Every tool call
and result is logged (`INFO fantasy_agent.agent.core`), which is both a debugging aid and the
"here's how it thinks" trace worth showing in an interview.

### Why a manual tool-calling loop, not the SDK's tool runner

The Anthropic SDK ships a beta `tool_runner` that abstracts the request → execute → loop cycle.
This project uses a hand-written loop instead, on purpose: the point of this build is the
agentic tool-selection logic itself, and a manual loop keeps every tool call, its input, and its
result directly visible and logged rather than hidden inside SDK internals.

### Why keeper/trade/draft logic is *not* LLM calls

Per the build order, `keeper.py`, `trade.py`, and `draft.py` are plain Python functions —
deterministic, unit-tested, and validated against the real league *before* any LLM was wired in.
Claude's job is to decide *when* to call them and to explain the result in context, not to
recompute a keeper cost or trade value itself (which an LLM would do inconsistently and
unverifiably). This split — deterministic pipeline underneath, LLM for tool selection and
explanation on top — is the core design decision of the project.

### Data sources and caching

| Source | What | Cache policy |
|---|---|---|
| Sleeper API | league, rosters, users, full player DB, draft history | `sync`; players/nfl gated by TTL (large, rate-sensitive) |
| Sleeper API | current draft's live picks | **never cached** — polled fresh every `best-available` call |
| FantasyPros | dynasty/superflex consensus rankings | `rankings-sync`; TTL-gated, scraped politely (see below) |

**FantasyPros scraping approach.** The spec called for Playwright, matching prior scraping
experience — but FantasyPros' rankings pages embed the full ranked-player list as a JSON blob
directly in a `<script>` tag (`var ecrData = {...}`), so a plain `httpx` GET plus a
balanced-brace JSON extraction (`rankings/fantasypros.py`) gets the same data without a headless
browser. `robots.txt` disallows the interactive `/nfl/ranker/` tool but not `/nfl/rankings/`
pages, and asks for a 5s crawl-delay; the scraper pulls one page per `rankings-sync` run and is
always read from cache during agent conversations, never scraped on demand.

**Player-ID matching** (`rankings/matching.py`) is the fiddly part the spec calls out. FantasyPros
and Sleeper name players differently (suffixes, punctuation, nicknames) and represent defenses
differently (team name vs. bare team code). Matching runs in priority order: manual alias
override → defense-by-team-code → exact normalized-name match → fuzzy match — with unmatched
players surfaced via `rankings-unmatched` rather than silently dropped, and a `rankings-alias`
command to fix them. On the real league this resolves ~98.6% of players automatically; the
holdouts are genuinely ambiguous cases (e.g. "Frank Gore Jr." colliding with a retired "Frank
Gore" already in Sleeper's DB).

**Keeper cost model** (`keeper.py`). Sleeper doesn't expose a keeper-cost field — round-penalty
rules are commissioner-defined and live outside the API. Cost is modeled as
`max(1, round_drafted - KEEPER_ROUND_PENALTY)`, where `round_drafted` comes from the most recent
*completed* draft in the league's `previous_league_id` chain (the current season's draft is
usually still `pre_draft` when you're deciding keepers, so last season's draft is the real cost
basis). Undrafted players (waiver/FA adds) default to the last round. "Value" of keeping a player
is a simple opportunity-cost comparison against the replacement-level player you'd expect at that
draft slot — explainable, not a precise valuation model.

**Trade value model** (`trade.py`). Each player's rank is converted to a comparable value via a
monotonic exponential decay curve, similar in spirit to public dynasty trade charts. Roster-need
impact (does the trade fill a hole or add to a surplus) is computed from before/after position
counts against the league's starter requirements.

**Superflex-awareness in the draft assistant** (`draft.py`) comes from the data source, not extra
logic: rankings are scraped from FantasyPros' *superflex* consensus page, so QBs are already
valued the way a 2-QB/superflex market values them. The draft assistant's own job is narrower —
exclude already-drafted and already-rostered players, and annotate each remaining one with how it
fits your roster's current position counts.

**Power rankings** (`power_rankings.py`). Ranks every team 1..N by the value of its best possible
*starting* lineup, not total roster value (which would just reward bench-hoarding). Filling
FLEX/SUPER_FLEX is a greedy assignment — exact-position slots first with each position's best
remaining player, then FLEX from what's left at RB/WR/TE, then SUPER_FLEX from what's left at
QB/RB/WR/TE — rather than a true optimal-assignment solver; good enough in practice and easy to
explain (and it's what correctly stacks a second elite QB into SUPER_FLEX over a worse flex
option). Alongside the overall rank, each team also gets a QB/RB/WR/TE positional rank computed
from *whole-roster* value at that position — this is what actually answers "where is this team
strong or thin," since a team can have a great starting lineup while sitting on zero bench depth
at a position, or vice versa. Both use the same `trade.player_value` curve as the trade analyzer,
so power rankings and trade values stay on one consistent scale.

## Tests

```bash
pytest
```

All 55 tests are offline — Sleeper and FantasyPros HTTP calls are mocked with
`httpx.MockTransport`, and the Anthropic client is mocked in `test_agent_core.py` (fake
`stop_reason`/tool_use responses), so the suite needs no network access, API key, or live league.
Keeper/trade/draft logic is additionally validated against the real league's live data during
development (see commit history / session notes) — sane, explainable output on real rosters is
the actual bar per the spec, not just green tests.

## Project layout

```
src/fantasy_agent/
  config.py           # env-based settings
  sleeper/             # Sleeper API client + response schemas
  rankings/            # FantasyPros scraper, player-ID matching, response schemas
  db/                  # SQLAlchemy models + session (SQLite cache)
  sync.py              # pulls Sleeper + FantasyPros data into the local cache
  roster_analysis.py    # shared position-count/need helpers (trade.py + draft.py + power_rankings.py)
  keeper.py            # keeper decision logic (pure, no LLM)
  trade.py             # trade analyzer (pure, no LLM)
  draft.py             # live best-available draft assistant (pure, no LLM)
  power_rankings.py    # league-wide power rankings + positional breakdown (pure, no LLM)
  agent/
    tools.py           # tool schemas + handlers exposed to Claude
    core.py            # the manual tool-calling loop
  cli.py                # `fantasy-agent` entrypoint
  gui.py                # Tkinter desktop launcher
tests/
assets/
  icon.ico              # app icon (scripts/make_icon.py regenerates it)
launcher.py              # PyInstaller entry point (dispatches to CLI or GUI)
FantasyAgent.spec        # PyInstaller build config
run_gui.bat               # double-click launcher (dev mode, uses the venv)
build_exe.bat             # builds the standalone .exe
```

## Success criteria (from the spec)

- Actually usable for real keeper decisions and this season's draft
- Reasoning explainable enough to trust — every recommendation cites the specific numbers behind
  it, not just a verdict
- This README as the architecture/portfolio writeup
