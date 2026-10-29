from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No hardcoded league here on purpose: the dev build supplies these via .env
    # (see .env.example); the user-edition GUI collects them at first launch and
    # writes them into its own AppData config instead (see user_config.py) so a
    # distributed build never accidentally ships pointed at anyone's real league.
    sleeper_league_id: str | None = None
    sleeper_base_url: str = "https://api.sleeper.app/v1"
    database_url: str = "sqlite:///data/fantasy_agent.db"
    players_cache_ttl_hours: int = 24

    # Used to default keeper/trade tools to your roster.
    sleeper_owner_user_id: str | None = None

    # Keeper cost = max(1, round_drafted - keeper_round_penalty). Undrafted players
    # (waiver/FA adds) are treated as having been "drafted" in the draft's last round.
    keeper_round_penalty: int = 2

    # Superflex/dynasty overall rankings already carry a pos_rank per player, so
    # one page covers both "best overall" and "best at position" for the MVP.
    fantasypros_base_url: str = "https://www.fantasypros.com/nfl/rankings"
    # Default page for the web routes and CLI views that show a single ranking.
    # The agent's tools don't use this: they pick weekly/ROS/dynasty per
    # question and superflex/1-QB per league (rankings/pages.py).
    fantasypros_ranking_page: str = "dynasty-superflex"
    fantasypros_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    # Lowered from 20 -> 6 so trade/power-rankings values don't lag a whole
    # NFL news cycle. FantasyPros is still scraped politely either way (a few
    # pages per rankings-sync run, 5s apart -- sync._SCRAPE_DELAY_SECONDS) -- this only controls how
    # often `fantasy-agent refresh` is willing to re-scrape. Can be lowered
    # further in-season (e.g. around injury-report days) if needed.
    rankings_cache_ttl_hours: int = 6

    # Injury-adjusted value (trade.py: adjusted_player_value). Deliberately a
    # flat multiplier, not an injury-risk model -- this is a keeper league and
    # FantasyPros' own rankings already partly price in injuries, so these
    # discounts are meant to be modest nudges, not a replacement for that.
    # Keys are lowercased Sleeper injury_status values; anything not listed
    # here (confirmed against a real pull: "NA" plus rare ones like "COV"/
    # "DNR") falls back to a 1.0 multiplier and logs a warning so it can be
    # added here deliberately instead of guessed at.
    injury_value_multipliers: dict[str, float] = Field(
        default_factory=lambda: {
            "questionable": 0.95,
            "doubtful": 0.85,
            "out": 0.75,
            "ir": 0.5,
            "pup": 0.5,
            "sus": 0.5,
        }
    )

    # power_rankings.py: statuses that make a player ineligible to fill a
    # starting-lineup slot (they still count toward positional/whole-roster
    # value -- an injured star still has value, they just aren't starting).
    # Lowercased, matched against PlayerRecord.injury_status.
    unavailable_injury_statuses: list[str] = Field(
        default_factory=lambda: ["out", "ir", "pup", "sus"]
    )

    # Agent (OpenAI Responses API tool-calling loop). API key only required when
    # `fantasy-agent ask` runs.
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"

    # Web backend only (backend/app) -- comma-separated allowed frontend origins.
    cors_origins: str = "http://localhost:5173"
    # Web backend only -- if set, /api/agent/* and /api/sync/* require this value
    # in an X-Access-Code header. A public URL that calls the OpenAI API with
    # your key can otherwise run up a bill from anyone who finds the link.
    demo_access_code: str | None = None


settings = Settings()
