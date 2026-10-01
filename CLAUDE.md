# FantasyAgent Web Migration Spec: React Frontend + FastAPI Backend

## 1. Overview

FantasyAgent currently runs as a Python package with a Typer CLI and two Tkinter desktop GUIs (a dev build and a user edition), packaged as Windows .exe files with PyInstaller. This spec covers moving it to a web app:

- **Backend:** a FastAPI service that exposes the existing data pipelines and the agent as a JSON API.
- **Frontend:** a React + TypeScript single-page app that replaces both Tkinter GUIs.

**Why:** a web app can be shared with a link, runs on any device (including phones), and turns the project into a full-stack portfolio piece. It also adds frontend skills (React, TypeScript) on top of the backend work the project already shows.

**The core rule of this migration:** the domain layer does not get rewritten. `keeper.py`, `trade.py`, `draft.py`, `power_rankings.py`, `my_roster.py`, `player_analysis.py`, `sync.py`, `rankings/`, `sleeper/`, and `db/` stay as they are, and the existing test suite must stay green the whole way through. The web layer is a new front door to the same code, the same way the CLI and the two GUIs already are.

---

## 2. Current State (what exists today)

| Piece | Where | Notes |
|---|---|---|
| Data sync | `sync.py` | `sync_all()`, `sync_rankings_all()`; Sleeper players dump gated by a TTL |
| Pure pipelines | `keeper.py`, `trade.py`, `draft.py`, `power_rankings.py`, `my_roster.py` | Deterministic, unit-tested, return dataclasses |
| Player detail | `player_analysis.py` | Last N games of PPR scoring + trend blurb, live from Sleeper |
| Agent | `agent/core.py`, `agent/tools.py` | Manual tool-calling loop on OpenAI's Responses API, 9 tools, single-turn, returns a string, logs the trace |
| Storage | `db/` | SQLAlchemy 2.0, SQLite, lazy engine; tables already keyed by `league_id` |
| Config | `config.py` (env), `user_config.py` (AppData JSON) | Global `settings` singleton, mutated at runtime by the user edition |
| UI | `gui.py`, `gui_user.py`, `gui_screens.py`, `gui_theme.py` | Tabs: Console/Chat, My Roster, Power Rankings, Best Available |
| Packaging | `launcher*.py`, `*.spec`, `*.bat` | Windows-only |

Things worth knowing before starting:

- Every pipeline function already accepts `league_id` and `owner_user_id` as optional arguments and only falls back to `settings` when they are missing. This makes the API layer straightforward.
- The global `settings` singleton is fine for a single-league deployment but is not safe to mutate per request on a server. See Section 9.
- Keeper costs and trade evaluation have no UI today outside the CLI and the agent. The web app is a chance to give them real screens.

---

## 3. Target Architecture

```
  Browser (React + TypeScript, Vite)
        |
        |  HTTPS, JSON (/api/*)
        v
  FastAPI app (backend/app)
   - routers: league, roster, rankings, keepers, trade, draft, players, sync, agent
   - Pydantic response models
   - DB session dependency
        |
        |  plain Python function calls
        v
  fantasy_agent package (unchanged domain layer)
   - pipelines, sync, rankings, sleeper client, agent loop
        |
        v
  SQLite (local dev)  /  PostgreSQL (deployed)
```

Outside services stay the same: Sleeper API, FantasyPros rankings page, OpenAI Responses API, and Sleeper's CDN for player headshots.

---

## 4. Repo Layout

Keep one repo. Add two top-level folders and leave `src/fantasy_agent` where it is.

```
FantasyAgent/
  src/fantasy_agent/          # unchanged domain layer (small additions noted below)
  tests/                      # existing tests, unchanged
  backend/
    app/
      main.py                 # FastAPI app, CORS, router registration, startup init_db()
      deps.py                 # get_db() session dependency
      schemas.py              # Pydantic response/request models
      jobs.py                 # in-memory sync job tracking (Phase 2)
      routers/
        auth.py
        league.py
        roster.py
        rankings.py
        keepers.py
        trade.py
        draft.py
        players.py
        sync.py
        agent.py
    tests/
      conftest.py             # TestClient + in-memory SQLite + dependency overrides
      test_routes_*.py
    Dockerfile
  frontend/
    src/
      api/                    # typed API client + generated types
      components/
      pages/
      hooks/
      App.tsx
      main.tsx
    index.html
    package.json
    vite.config.ts
  docker-compose.yml          # backend + postgres for local full-stack runs
```

**Phase 6 update:** rather than relocating into a `legacy/` folder, the Tkinter GUIs, launchers, `.spec`/`.bat` files, and their GUI-only supporting modules (`gui_screens.py`, `gui_theme.py`, `profile_ui.py`, `profiles.py`, `user_config.py`, `player_images.py`) were removed from the working tree outright — full history is still in `git log` if any of it's ever needed again. See Phase 6 below for why.

Add a `web` optional dependency group in `pyproject.toml`:

```toml
web = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "psycopg[binary]>=3.2", "bcrypt>=4.0"]
```

---

## 5. Backend

### 5.1 App setup

- `main.py` creates the app, calls `init_db()` on startup, registers routers under `/api`, and enables CORS for the frontend origin (`http://localhost:5173` in dev, the deployed frontend URL in prod, read from an env var).
- `deps.py` provides `get_db()`, a `yield` dependency built on the existing session factory in `db/session.py`. It commits on success and rolls back on error, matching `get_session()`.
- Routes that call the pipelines or the agent are written as plain `def` (not `async def`). The pipelines, `httpx` calls, and the OpenAI client are all synchronous, and FastAPI runs `def` routes in a thread pool so they don't block the server.

### 5.2 Required change in `db/session.py`

Because FastAPI runs sync routes in worker threads, SQLite needs `check_same_thread=False`. Add this when building the engine:

```python
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
_engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
```

This is harmless for the CLI and the existing tests.

### 5.3 Config

Phase 1 is a single-league deployment, configured the same way as the dev build: env vars read by `config.py` (`SLEEPER_LEAGUE_ID`, `SLEEPER_OWNER_USER_ID`, `OPENAI_API_KEY`, `DATABASE_URL`). Add two web-only settings:

- `CORS_ORIGINS`: comma-separated list of allowed frontend origins.
- `DEMO_ACCESS_CODE` (optional): if set, `/api/agent/*` and `/api/sync/*` require it in an `X-Access-Code` header. See Section 5.7.

`user_config.py` and the setup wizard are not used by the web app. The OpenAI key lives on the server only and is never sent to the browser.

### 5.4 Endpoints

All responses are JSON. All read endpoints work from the local cache, except where marked live.

| Method | Path | Calls | Notes |
|---|---|---|---|
| GET | `/api/health` | none | Returns status and app version |
| GET | `/api/league` | league record from DB | Name, season, roster positions, scoring type |
| GET | `/api/teams` | users + rosters from DB | Team name, owner user ID, roster ID. Feeds the trade screen's team pickers |
| GET | `/api/my-roster` | `my_roster.get_my_roster()` | Starters, bench, IR, taxi, with slot and rank info |
| GET | `/api/power-rankings` | `power_rankings.compute_power_rankings()` | Includes starting lineup and positional ranks |
| GET | `/api/keepers` | `keeper.compute_keeper_candidates()` | Sorted keeper candidates with cost round and value surplus |
| POST | `/api/trade/evaluate` | `trade.evaluate_trade()` | Body: `side_a_owner`, `side_a_gives[]`, `side_b_owner`, `side_b_gives[]` |
| GET | `/api/draft/best-available?limit=15` | `draft.get_best_available()` | **Live**: polls Sleeper's draft endpoint on every call, same as today |
| GET | `/api/players/search?q=` | player cache query | For autocomplete in the trade screen |
| GET | `/api/players/{player_id}/analysis` | `player_analysis.get_player_analysis()` | **Live**: recent games from Sleeper |
| GET | `/api/rankings?search=` | rankings cache | Mirrors `rankings-show` |
| GET | `/api/sync/status` | `SyncMeta` table | Last synced time per resource |
| POST | `/api/sync` | `sync.sync_all()` | Body: `force_players` (bool). Returns `202` with a `job_id` |
| POST | `/api/rankings/sync` | `sync.sync_rankings_all()` | Returns `202` with a `job_id` |
| GET | `/api/jobs/{job_id}` | job tracker | `pending`, `running`, `done`, or `failed` with an error message |
| POST | `/api/agent/ask` | agent loop | Body: `question`, optional `history`. Returns answer + tool trace |

Admin-style commands (`rankings-unmatched`, `rankings-alias`) stay CLI-only for now.

### 5.5 Response models

Every pipeline already returns a dataclass (`KeeperCandidate`, `TradeEvaluation`, `BestAvailablePlayer`, `TeamPowerRanking`, `MyRoster`, `PlayerAnalysis`). For each one, add a matching Pydantic model in `backend/app/schemas.py` with `model_config = ConfigDict(from_attributes=True)` and convert in the router with `Model.model_validate(result)`.

Do not change the dataclasses themselves. Keeping the Pydantic models in the backend means the domain layer never imports FastAPI, which is the same separation the project already uses for the LLM provider.

These models also drive FastAPI's OpenAPI schema, which the frontend uses to generate TypeScript types (Section 6.4).

### 5.6 Sync jobs

`sync_all()` can take a while because of the multi-MB Sleeper players dump, so it should not run inside a normal request.

- **Phase 2 (simple):** use FastAPI `BackgroundTasks`. Store job state in an in-memory dict in `jobs.py` keyed by a UUID. Reject a new sync with `409` if one is already running.
- **Stretch:** move this to Celery + Redis, matching FileFlow's setup. This is a natural "why" story for interviews: the in-memory tracker loses state on restart and doesn't work across multiple server processes.

Keep the existing TTL rules. A sync request with `force_players=false` still respects `PLAYERS_CACHE_TTL_HOURS`.

### 5.7 Agent endpoint

**Small additions to `agent/core.py`** (keep `run_agent()` working so the CLI and tests are untouched):

1. Add an `AgentStep` dataclass: `tool_name`, `arguments` (dict), `output_preview` (first ~500 chars), `error` (bool).
2. Add an `AgentResult` dataclass: `answer` (str), `steps` (list of `AgentStep`), `usage` (input, cached, and output token counts).
3. Add `run_agent_with_trace(question, session, *, history=None, model=None) -> AgentResult`. It runs the same loop as today but records each tool call and result into `steps` alongside the existing log lines.
4. Rewrite `run_agent()` as a thin wrapper that calls `run_agent_with_trace()` and returns `.answer`.
5. `history` is a list of `{role, content}` pairs for prior user and assistant turns, added to the front of `input_list`. Only plain text turns are passed back, not old tool calls, to keep requests small.

**Endpoint behavior:**

- `POST /api/agent/ask` returns `{ answer, steps, usage }`.
- The frontend keeps the chat history in state and sends it with each question. The server stays stateless.
- Cap `history` at the last 10 turns and `question` at 1,000 characters (validated in the Pydantic request model).
- If `OPENAI_API_KEY` is missing, return `503` with a clear message instead of a stack trace.

**Cost protection.** A public URL that calls the OpenAI API with your key can run up a bill. Before deploying, do at least one of:

- Set `DEMO_ACCESS_CODE` so only people you give the code to can use chat and sync.
- Add a simple per-IP rate limit (for example, `slowapi`, around 10 questions per hour).

The read-only screens can stay fully public since they only hit the local cache and Sleeper.

### 5.8 Errors

- `ToolError` and "league not synced yet" conditions map to `409` with a message like "No data yet. Run a sync first."
- Sleeper or FantasyPros network failures map to `502`.
- All errors return `{ "detail": "..." }` so the frontend has one shape to handle.

### 5.9 Backend tests

- `backend/tests/conftest.py` builds a `TestClient`, points the app at an in-memory SQLite database, and overrides `get_db`.
- Reuse the existing `httpx.MockTransport` approach for anything that would hit Sleeper live (`best-available`, player analysis). This may mean letting the routers accept an injected `SleeperClient` through a dependency, which the pipeline functions already support via their `client` argument.
- Mock the OpenAI client for `/api/agent/ask` the same way `test_agent_core.py` does.
- Add a unit test for `run_agent_with_trace()` that checks `steps` is populated in order.
- The existing `tests/` folder must pass unchanged.

### 5.10 Accounts

Added in Phase 4 alongside the landing page (Section 6.2) — pulled forward from "later," reversing the earlier call to leave user accounts out of this migration (see Section 10). Every route except `/api/health` and `/api/auth/*` itself now requires a signed-in account; this is enforced server-side, not just hidden behind a frontend screen.

- Two new tables, web-only (the CLI/GUIs never touch them): `AccountRecord` (`accounts` — email, bcrypt `password_hash`, optional `display_name`, plus `default_league_id`/`default_owner_user_id` mirroring the frontend's League override so it *could* follow an account across devices, though Phase 4 only stores these — the frontend doesn't yet read them back) and `SessionRecord` (`sessions` — opaque bearer `token`, `account_id`, `expires_at`). Both live in `fantasy_agent/db/models.py` next to the Sleeper-cache tables, since everything shares one SQLite file; password hashing and session logic itself lives in `backend/app/auth.py`, keeping bcrypt out of the domain layer.
- Sessions are opaque `secrets.token_urlsafe` strings, not JWTs, specifically so logout can revoke one server-side — not just drop it client-side.
- `POST /api/auth/signup` `{email, password, display_name?}` → `201 {token, account}`. `POST /api/auth/login` `{email, password}` → `200 {token, account}` (`401` on bad credentials, generic message — don't reveal which field was wrong). `POST /api/auth/logout` deletes the session row. `GET /api/auth/me` / `PATCH /api/auth/me` read/update the account.
- `get_current_account` (a dependency in `deps.py`) reads `Authorization: Bearer <token>`, looks up the session, and 401s if it's missing, unknown, or expired (30-day TTL). Applied via `dependencies=[Depends(get_current_account)]` at the router level for every data router.
- 401 vs 403 matters here: `get_current_account` 401s ("not authenticated — show the landing page"); `require_access_code` (Section 5.7) was changed to 403 ("authenticated, but missing the separate demo access code — show a message, don't sign the user out"). The frontend's global 401 handler (`api/client.ts`) relies on this split to avoid logging someone out just for forgetting an access code.
- No email verification, password reset, or rate limiting on login attempts — fine for a personal/portfolio deployment, a real gap for anything wider.

---

## 6. Frontend

### 6.1 Stack

| Choice | Why |
|---|---|
| Vite + React + TypeScript | Fast dev server, simple build, pairs cleanly with a separate FastAPI backend |
| React Router | Page routing |
| TanStack Query | Data fetching, caching, loading and error states, polling |
| Tailwind CSS | Quick, consistent styling without writing a lot of custom CSS |
| openapi-typescript | Generates TypeScript types from FastAPI's OpenAPI schema |
| Vitest + React Testing Library | Component tests |

Vite is chosen over Next.js because the backend already exists in Python, so there's no need for a second server runtime. Next.js is a fine alternative if you want that experience on your resume, but it adds complexity this project doesn't need.

### 6.2 Pages

The two Tkinter editions merge into one web app. The dev build's raw tool trace becomes a toggle in the chat view instead of a separate program.

| Page | Replaces | Content |
|---|---|---|
| **Landing** (`/`, signed out) | Nothing — new | First-time/signed-out front door: a "Sign in" / "Create account" toggle over an email+password form. Nothing else in the app is reachable (or fetchable — see Section 5.10) until this succeeds |
| **Chat** (`/`, signed in) | Console tab + Chat tab | Chat bubbles, example question chips, a "Show reasoning" toggle under each answer that expands the tool-call trace |
| **My Roster** (`/roster`) | My Roster tab | Grouped by starters, bench, IR, taxi. Circular headshots. Click a player to open the player panel |
| **Power Rankings** (`/rankings`) | Power Rankings tab | Ranked table of teams. Expand a row to see the starting lineup. Show QB/RB/WR/TE positional ranks as small badges |
| **Keepers** (`/keepers`) | CLI only today | Candidate cards or table with cost round, ECR rank, value surplus, and the reasoning text |
| **Trade Analyzer** (`/trade`) | CLI only today | Two team pickers; picking a team auto-loads *that team's actual roster* as the player picker for its side (tap to add/remove), instead of a free-text search across every NFL player — a trade can only ever send players the side already owns, so the roster list is both easier to use and impossible to submit invalid picks from. Result panel shows each side's value and roster-need notes |
| **Draft Board** (`/draft`) | Best Available tab | Best-available list with a "Live" toggle that polls every 15 seconds |
| **Settings** (`/settings`) | Gear icon / setup wizard | Account info + log out, League override (Section 9), sync status, "Sync league" and "Sync rankings" buttons with job progress |

**Player panel** (shared): a side drawer showing headshot, position, team, ranks, and the last 5 games from `/api/players/{id}/analysis`.

### 6.3 Components and behavior

- **Headshots:** load directly from Sleeper's CDN (`https://sleepercdn.com/content/nfl/players/thumb/{player_id}.jpg`) with an `onError` fallback to the circular initial-letter placeholder. The disk cache in `player_images.py` isn't needed on the web since the browser caches images itself.
- **Theme:** carry over the user edition's Celadon / Hunter Green palette (`#A1CCA5` / `#415D43`) as Tailwind theme colors. Support light and dark mode.
- **Layout:** sidebar navigation on desktop, bottom tab bar on mobile. Every page must be usable on a phone screen, since that's a big reason to move to the web.
- **States:** every data view handles loading (skeletons), empty ("No data yet, run a sync"), and error (message from `detail` plus a retry button).
- **Chat:** disable the input while waiting, show a "Thinking..." indicator, and keep history in component state for the session.
- **Draft Board polling:** use TanStack Query's `refetchInterval`, only while the Live toggle is on and the tab is visible.

### 6.4 API client

- Add a script `npm run gen:types` that runs `openapi-typescript` against the backend's `/openapi.json` and writes `src/api/schema.ts`.
- `src/api/client.ts` is a small typed `fetch` wrapper that reads the base URL from `VITE_API_URL` and throws a typed error on non-2xx responses.
- One hook per endpoint in `src/hooks/` (for example, `useMyRoster()`, `usePowerRankings()`, `useAskAgent()`), so pages never call `fetch` directly.

### 6.5 Frontend tests

- Component tests for the trade form (picking players on both sides, submitting), the chat view (renders answer and toggles trace), and loading/error states.
- Stretch: one or two Playwright end-to-end tests against the full stack running in Docker Compose.

---

## 7. Database and Deployment

### 7.1 Local development

- **Backend:** `uvicorn backend.app.main:app --reload`, using the existing SQLite file.
- **Frontend:** `npm run dev` in `frontend/`, with Vite proxying `/api` to `localhost:8000`.
- **Full stack:** `docker compose up` runs the backend and a PostgreSQL container.

### 7.2 Moving to PostgreSQL for deployment

Most free hosting has a temporary filesystem, so a SQLite file would be wiped on every redeploy. Use PostgreSQL in production. Because the project uses SQLAlchemy, this should mostly be a `DATABASE_URL` change plus the `psycopg` driver.

**Verified in Phase 5** — all three checks below passed against a real `postgres:16` container (`docker run`, then again through `backend/Dockerfile` + `docker-compose.yml`) with no domain-layer changes: a real sync against a real Sleeper league, every pipeline (`get_my_roster`, `compute_power_rankings`, `compute_keeper_candidates`, `evaluate_trade`), and the Phase 4 account tables. The domain layer was already portable — every query goes through the ORM (`.query()`/`.get()`/manual get-or-create), nothing drops to raw SQL or a SQLite-only construct (`rankings/matching.py`'s "case-sensitive" risk doesn't apply either — it matches in pure Python dicts, never a SQL `LIKE`).

- Any SQLite-specific behavior in `sync.py` or `rankings/matching.py` (for example, upsert patterns or case-sensitive string matching). **Checked — none found.**
- That `Base.metadata.create_all()` creates all tables cleanly on Postgres. **Checked — it does**, including the Phase 4 `accounts`/`sessions` tables.
- Note for the `DATABASE_URL` itself: use the `postgresql+psycopg://...` dialect prefix (psycopg **3**, matching the `psycopg[binary]` dependency), not plain `postgresql://` or `+psycopg2`.
- Stretch, still not done: add Alembic for migrations instead of `create_all()`. Fine for now since `create_all()` only ever *adds* missing tables — every schema change so far (Section 5.10's two new tables, the `UserRecord` composite-key fix) has been additive or caught before any deploy existed.

### 7.3 Hosting

| Piece | Option | Status |
|---|---|---|
| Frontend | Vercel or Netlify (static build of `frontend/`) | Config written (`frontend/vercel.json`, `frontend/netlify.toml`, `frontend/public/_redirects` for the SPA fallback) and verified locally (`vite preview`, direct deep-link navigation). **Not deployed** — needs an account on whichever host you pick. |
| Backend | Render, Railway, or Fly.io, using `backend/Dockerfile` | `backend/Dockerfile` written and verified (`docker build` + `docker run` against a real Postgres container, including a live Sleeper sync through it). **Not deployed** — same as above, needs a host account. |
| Database | The host's managed Postgres, or a free tier like Neon or Supabase | Compatibility verified (7.2) against vanilla `postgres:16`; a managed host's Postgres should behave identically. **Not provisioned.** |

None of the "not deployed"/"not provisioned" steps above can happen without actually having (and authorizing) accounts on these hosts — picking providers, connecting the repo, and setting secrets is a call only you can make, so Phase 5 stops at "everything that can be built and verified locally is done" rather than a live URL.

Set env vars on the backend host: `SLEEPER_LEAGUE_ID`, `SLEEPER_OWNER_USER_ID`, `OPENAI_API_KEY`, `DATABASE_URL`, `CORS_ORIGINS`, and `DEMO_ACCESS_CODE`. Set `VITE_API_URL` (the deployed backend's URL) on the frontend host at build time.

**Cost protection, revisited:** Section 5.7's `DEMO_ACCESS_CODE` plus Section 5.10's account system (Phase 4) together satisfy the "done when" bar below — every route needs a signed-in account, and `/api/agent/*`/`/api/sync/*` need the access code on top of that. No per-IP rate limiter (e.g. `slowapi`) has been added; the spec only ever called for one of the two.

Stretch, partially done: `.github/workflows/daily-sync.yml` hits `POST /api/sync` and `POST /api/rankings/sync` on a daily cron (and via manual `workflow_dispatch`). It needs three repo secrets once a backend is actually deployed — `FANTASY_AGENT_API_URL`, `FANTASY_AGENT_AUTH_TOKEN` (a session token from a real login — these expire after 30 days per Section 5.10, so the secret needs periodic renewal; there's no long-lived service-account token in this app), and optionally `FANTASY_AGENT_ACCESS_CODE`.

---

## 8. Build Phases

Each phase ends with something that works. Don't start a phase until the one before it meets its acceptance criteria.

### Phase 1: Read-only API
- Add the `web` dependency group, `backend/app/main.py`, `deps.py`, `schemas.py`.
- Apply the `check_same_thread` change in `db/session.py`.
- Implement `health`, `league`, `teams`, `my-roster`, `power-rankings`, `keepers`, `rankings`, `players/search`, `sync/status`.

**Done when:** every endpoint returns correct data from your real synced league, shows up in the `/docs` page, and has at least one route test. The existing `pytest` suite still passes.

### Phase 2: Actions and live data
- Add `trade/evaluate`, `draft/best-available`, `players/{id}/analysis`.
- Add sync jobs with `BackgroundTasks` and `/api/jobs/{id}`.

**Done when:** a trade evaluated through the API matches the CLI's `fantasy-agent trade` output for the same inputs, and a sync can be started and tracked to completion through the API.

### Phase 3: Agent API
- Add `AgentStep`, `AgentResult`, and `run_agent_with_trace()`; make `run_agent()` a wrapper.
- Add `/api/agent/ask` with history support, input limits, and the access code check.

**Done when:** `fantasy-agent ask` still works, the endpoint returns the answer plus a tool trace that matches the log output, and a follow-up question that depends on the previous answer works.

### Phase 4: Frontend
- Scaffold Vite + React + TS + Tailwind + TanStack Query + React Router.
- Generate API types; build the client and hooks.
- Build pages in this order: My Roster, Power Rankings, Chat, Draft Board, Keepers, Trade Analyzer, Settings.
- Per-request League override (Section 9.1): Settings gets a league ID field + "my team" picker; every league-scoped hook/route accepts the override.
- Trade Analyzer: picking a team auto-loads its actual roster as that side's player picker, instead of a free-text player search (Section 6.2).
- Accounts (Section 5.10): `AccountRecord`/`SessionRecord`, `/api/auth/{signup,login,logout,me}`, `get_current_account` gating every route but `/api/health`. Frontend gets a Landing page (sign in / create account) shown whenever there's no valid session, and an Account section in Settings with the signed-in email and a log-out button.

**Done when:** every page from Section 6.2 works against the local backend, handles loading, empty, and error states, and is usable at phone width. A signed-out visitor can only reach the Landing page (enforced server-side, not just hidden in the UI); creating an account or signing in unlocks the rest of the app and survives a page reload.

### Phase 5: Deploy
- Write `backend/Dockerfile` and `docker-compose.yml`. **Done** — both built and run-tested locally (a real `postgres:16` container, a real Sleeper sync through the containerized backend).
- Switch to Postgres, check the items in Section 7.2. **Done** — verified compatible, no domain-layer changes needed.
- Frontend deploy config for Vercel/Netlify (SPA routing). **Done**, unverified against an actual host.
- Turn on cost protection for the agent endpoint. **Already satisfied** by `DEMO_ACCESS_CODE` (Section 5.7) + the account system (Section 5.10, pulled forward from Phase 4) — just remember to actually set `DEMO_ACCESS_CODE` before the backend is public.
- Deploy backend and frontend to a live URL. **Not done** — needs accounts on actual hosting providers (Vercel/Netlify, Render/Railway/Fly.io, Neon/Supabase/the host's managed Postgres), which only you can create and authorize. Section 7.3 has the checklist for when you're ready to do that part yourself.

**Done when:** the app runs at a public URL, a friend can open it on their phone, and the chat is protected by the access code or a rate limit. *(Everything buildable and locally verifiable without a hosting account is done; the actual deploy — picking providers, connecting the repo, setting secrets — is still open.)*

### Phase 6: Cleanup
- Move the Tkinter GUIs, launchers, `.spec` files, and `.bat` files into `legacy/` (or remove them once you're confident). **Removed, not relocated.** Relocating while keeping them fully runnable would have meant: a new `fantasy_agent.legacy` subpackage, updated relative imports across all 8 GUI/profile/config files, updated `pyproject.toml` console-script entries, fixed-up `.bat`/`.spec` paths, and then re-verifying a PyInstaller build and an actual GUI launch — real surgery for software being retired anyway, with real risk of subtly breaking the frozen `.exe` build in ways that are hard to catch without rebuilding it. Removed instead: `gui.py`, `gui_user.py`, `gui_screens.py`, `gui_theme.py`, `profile_ui.py`, `profiles.py`, `user_config.py`, `player_images.py`, `launcher.py`, `launcher_user.py`, `FantasyAgent.spec`, `FantasyAgentUser.spec`, `build_exe.bat`, `run_gui.bat`, `run_gui_user.bat`, their three test files, `assets/icon.ico`, `scripts/make_icon.py`, the `pyinstaller`/`pillow` dependencies, and both `fantasy-agent-gui*` console-script entries. The domain-layer test suite dropped from 103 to 83 tests (exactly the tests that targeted the removed modules) — nothing else changed. Before any of this, a separate uncommitted feature (multi-profile support, added to these same GUI files before this migration started) was committed as its own commit so it wasn't lost.
- Update the README: new architecture diagram, local setup for both halves, live demo link, screenshots. **Done** — full rewrite; screenshots are real captures (Playwright, against the running local app with a real synced league) committed under `docs/screenshots/`. No live demo link yet (Phase 5 isn't deployed).

**Done when:** a new person can clone the repo and run the full stack by following the README.

---

## 9. Multi-League Support

The user edition already supports "any league, any person." The original plan here (below, now mostly done) was blocked on one real design problem: the global `settings` singleton can't be mutated per request, because two users hitting the server at once would overwrite each other's league.

### 9.1 Done: per-request League override (Phase 4)

Solved by never mutating `settings` at all — every read endpoint and the sync endpoint accept an optional `league_id` (My Roster/Keepers/Draft Board/sync also take `owner_user_id`), falling through to `settings.sleeper_league_id`/`sleeper_owner_user_id` when omitted. This works because the pipeline functions already accepted both as explicit keyword arguments from day one (Section 2) — the routers just had to stop hardcoding the settings default and pass the override through.

- Frontend: `state/LeagueContext.tsx` holds `{ leagueId, ownerUserId } | null` in React state, persisted to `localStorage`, and every hook that calls a league-scoped endpoint takes an optional `leagueId`/`ownerUserId` and forwards it as a query param (or into the request body, for `POST /api/trade/evaluate` and `POST /api/sync`).
- Set from Settings (Section 6.2): a league ID field plus, once that league loads, a "my team" dropdown sourced from `/api/teams?league_id=...`. A `LeagueBanner` shows on every page while an override is active, since it's never supposed to be ambiguous which league is on screen.
- My Roster / Keepers / Draft Board refuse to query with no `ownerUserId` chosen yet (there's no sane default once the configured league is overridden) — they show a "pick your team in Settings" prompt instead.
- Still scoped to the server's single configured league by default: the override only changes what *this browser* is pointed at, nothing server-side. The `AccountRecord` fields added in Section 5.10 (`default_league_id`/`default_owner_user_id`) exist for exactly this override to ride along with a signed-in account instead of living only in one browser's `localStorage`, but Phase 4 didn't wire that sync up — the frontend still reads/writes `localStorage` only.

### 9.2 Still open

- **Agent/tool layer:** `agent/tools.py`'s handlers all read `settings.sleeper_league_id` directly (`_league_id()`), not threaded from the override. Chat always answers for the server's configured league regardless of what Settings is pointed at — the `LeagueBanner` says so. Fixing this means passing a `LeagueContext`-like value into `run_agent_with_trace()` and every tool handler, which is a bigger, more invasive change than the read-route threading above.
- **Cross-device persistence:** wire the League override to actually read/write `AccountRecord.default_league_id`/`default_owner_user_id` (via `GET`/`PATCH /api/auth/me`) instead of only `localStorage`, so it follows a signed-in user across browsers.
- **Discovery:** a username-to-user-ID lookup endpoint (reusing what the user edition's setup wizard does), so Settings can take a Sleeper username instead of requiring the numeric league ID.
- Decide how the OpenAI key works for other people's leagues: keep using yours behind the access code, or let users paste their own key per session.

---

## 10. Out of Scope for This Migration

- ESPN and Yahoo support (still blocked on real auth flows, same as today)
- Streaming agent responses (server-sent events). A good stretch goal once Phase 3 works.
- A native iOS app. The API built here is exactly what a future SwiftUI or React Native client would call, so this work carries over.
- Changes to the keeper, trade, draft, or power ranking logic
- Email verification, password reset, and login-attempt rate limiting for the account system added in Phase 4 (Section 5.10) — real gaps, acceptable for a personal/portfolio deployment

---

## 11. Open Questions

1. Keep the legacy Tkinter GUIs around after the web app reaches parity, or delete them?
2. Access code, rate limit, or both for the deployed chat?
3. Is the player analysis panel's live Sleeper call fast enough per click, or should recent stats be added to the sync and cached?
4. Generate TypeScript types as a committed file, or regenerate in CI?

---

## 12. Interview Talking Points This Migration Adds

- Wrapping an existing, tested domain layer in an HTTP API without rewriting it, and why that separation mattered (same reason the LLM provider swap only touched two files).
- Handling slow work (league sync) outside the request cycle, and the tradeoffs of in-memory jobs vs a real task queue.
- Turning the agent's tool trace into a user-facing feature ("Show reasoning"), not just a log.
- Thread safety: why SQLite needed a config change and why a global settings object doesn't work for multiple users on a server.
- Protecting a public endpoint that spends money on every call.
- Building real account auth (bcrypt + revocable server-side sessions, not a JWT) and enforcing it at the API layer, not just hiding UI behind a frontend check — and the 401-vs-403 split that let the two independent gates (login, demo access code) coexist without one tripping the other.
- Threading a per-request override (the League switcher) through existing functions that already accepted the right arguments, instead of reaching for global mutable state — and where that approach still falls short (the agent's tool layer still reads global settings directly).
