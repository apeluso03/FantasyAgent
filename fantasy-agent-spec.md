# Fantasy Football Draft/Trade Analyzer Agent — Project Spec

## 1. Overview

An AI agent that helps manage a 12-team PPR superflex keeper league on Sleeper (league ID: `1312255990598483968`). It answers questions like "should I keep Player X or draft new," "is this trade fair," and "who should I start this week" by pulling live league/player data and reasoning over it, not just spitting out a static value chart.

**Why this project:** it's something you'll actually use every week this season, which means real usage, real edge cases, and a real story for interviews ("here's a bug I hit in week 4 and how I fixed it") instead of a synthetic demo.

**Resume framing:** an agentic tool that uses tool-calling over a live third-party API (Sleeper), reasons over structured + unstructured data (rankings, news, matchups), and produces explainable recommendations — not a chatbot wrapper.

---

## 2. Scope for MVP (few-week build)

In scope:
- Pull your actual league from Sleeper (rosters, keeper rules, scoring settings)
- Keeper decision helper: given your keeper slots and cost rules, recommend who to keep
- Draft assistant: live big-board + "best available" suggestions during your draft, aware of already-drafted players and your roster needs
- Trade analyzer: evaluate a proposed trade for both sides and give a verdict with reasoning
- CLI or simple web UI (FastAPI) — no need for a polished frontend in v1

Out of scope for MVP (stretch goals, see section 8):
- Weekly start/sit optimizer
- In-season waiver wire suggestions
- Multi-league support
- Notifications/automation (auto-posting to league chat, etc.)

---

## 3. Tech Stack

Leaning on what you already know so you can move fast, plus one or two new pieces:

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Your strongest language |
| API framework | FastAPI | You already know it from FileFlow |
| LLM | Anthropic API (Claude), tool-calling | You have hands-on LLM API experience |
| Data source | Sleeper API (public, no auth needed) | Free, well-documented, matches your league |
| Player rankings/projections | FantasyPros or similar public rankings feed (scraped or CSV import) | Sleeper doesn't give you expert rankings, just league/roster data |
| Storage | PostgreSQL (or even SQLite for MVP) | You know Postgres from FileFlow; SQLite is fine to move faster |
| Caching/async jobs | Redis + Celery — optional for MVP | Only needed if you add scheduled polling; can skip for v1 and add later as a resume-worthy upgrade |
| Containerization | Docker | Keep it consistent with FileFlow, easy to demo |

**New skill area for you:** working with a real-time public sports API and structuring an agent's tool-calling loop around it (as opposed to a single-shot LLM call).

---

## 4. Architecture (MVP)

```
                    ┌─────────────────┐
                    │   You (CLI/Web)  │
                    └────────┬─────────┘
                             │ question ("should I keep Bijan or draft fresh?")
                             ▼
                    ┌─────────────────┐
                    │   Agent Core     │  (Claude + tool-calling loop)
                    └────────┬─────────┘
                 ┌───────────┼────────────┐
                 ▼           ▼            ▼
         ┌─────────────┐ ┌─────────┐ ┌──────────────┐
         │ Sleeper API  │ │ Rankings│ │ League Rules │
         │  tool        │ │  tool   │ │  tool        │
         └─────────────┘ └─────────┘ └──────────────┘
                 │           │            │
                 └───────────┴────────────┘
                             ▼
                    ┌─────────────────┐
                    │  Postgres/SQLite │ (cached player + league data)
                    └─────────────────┘
```

The agent doesn't just do one API call and hand it to the LLM — it decides *which* tools it needs (roster lookup, rankings lookup, matchup history) based on the question, calls them, and reasons over the combined result before answering. That tool-selection logic is the core "agentic" piece worth highlighting on a resume.

---

## 5. Data Sources

**Sleeper API** (base: `https://api.sleeper.app/v1/`) — free, no auth required:
- `league/{league_id}` — league settings, scoring, keeper rules
- `league/{league_id}/rosters` — current rosters
- `league/{league_id}/users` — team owners
- `players/nfl` — full player database (large, cache locally and refresh daily/weekly)
- `league/{league_id}/matchups/{week}` — weekly matchup/score data (useful later for start/sit)

**Rankings/projections:** Sleeper doesn't provide expert rankings, so this project will scrape them from FantasyPros using Playwright/Scrapy — directly reusing your EPRI scraping experience, and a stronger resume story than a static CSV import.

- Target FantasyPros' public consensus rankings pages (e.g. overall superflex/dynasty-style rankings and positional rankings). Check current page structure before building since FantasyPros periodically changes markup — inspect with browser devtools first.
- Respect FantasyPros' `robots.txt` and terms of use, and rate-limit requests (a slow, polite scraper that runs on a schedule, not a hammer). Since you only need updated rankings roughly daily during the season and more frequently during draft week, there's no need to scrape aggressively.
- Normalize scraped player names to Sleeper's player IDs — this is the trickiest part, since name formats differ ("Patrick Mahomes II" vs "Patrick Mahomes", defense naming conventions, etc). Plan for a small fuzzy-matching/alias table.
- Cache scraped rankings locally (Postgres/SQLite) so the agent never scrapes on-demand mid-conversation — scrape on a schedule, read from cache when answering questions.

---

## 6. Core Features (MVP detail)

### 6.1 Keeper Decision Helper
- Input: your current roster + your league's keeper cost rules (e.g. round penalty)
- Agent pulls each eligible player's ranking/ADP and projected value relative to their keeper cost
- Output: ranked list of "keep" candidates with a short reasoning string per player (not just a number)

### 6.2 Draft Assistant
- Input: live draft state (who's been picked, your current roster, your pick number)
- Agent tracks already-drafted players (poll Sleeper's draft endpoint or manual input if doing a mock first), cross-references your team's positional needs, and suggests best available + a short "why" for each
- Superflex-aware: needs to understand your league values QBs higher than standard leagues

### 6.3 Trade Analyzer
- Input: proposed trade (players on each side)
- Agent evaluates both sides using rankings/projections + roster context (does this fill a need or create a surplus for each team), gives a verdict with reasoning, not just "Team A wins by X points"

---

## 7. Agent Design Notes

- Use Claude's tool-calling (function calling) to expose the Sleeper lookups, rankings lookups, and league-rules lookups as discrete tools
- Keep tool outputs structured (JSON) so the agent can reason over them cleanly rather than parsing prose
- Cache player + league data locally (refresh daily during season, more frequently during draft week) to avoid hammering the API and to keep responses fast
- Log the agent's tool calls and reasoning somewhere visible (even just console output) — this becomes useful both for debugging and for demoing "here's how it thinks" in an interview

---

## 8. Stretch Goals (post-MVP, good "v2" resume bullets)

- Weekly start/sit optimizer using matchup data
- Waiver wire suggestions based on your league's usage patterns
- Move polling to Celery + Redis for scheduled data refresh (direct callback to your FileFlow experience)
- Slack or Discord bot interface so your league mates can query it too
- Historical trade/keeper decision tracking — did the agent's advice age well?

---

## 9. Suggested Build Order (few-week MVP timeline)

1. **Week 1:** Sleeper API integration — pull and cache your real league (1312255990598483968), rosters, and settings. Get a working data layer before touching the agent.
2. **Week 2:** FantasyPros scraper (Playwright) + player-ID matching against Sleeper's player database + local caching. This is the fiddliest part, so give it real time before layering the agent on top.
3. **Week 3:** Basic keeper decision logic using the joined Sleeper + rankings data (no LLM yet — validate the data pipeline gives sane answers first), then wire in Claude tool-calling for keeper + trade analysis.
4. **Week 4:** Draft-day assistant (live best-available suggestions), since this is time-sensitive to your actual draft.
5. **Ongoing during season:** polish, add start/sit or waiver features as time allows, write up the README with architecture notes for your resume/portfolio.

---

## 10. Success Criteria

- You actually use it for your real keeper decisions and draft this season
- It gives reasoning you'd trust enough to act on (or at least seriously consider)
- README clearly explains the architecture and agent design so it reads well in a portfolio/interview
