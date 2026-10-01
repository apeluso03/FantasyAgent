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
    fantasypros_ranking_page: str = "dynasty-superflex-overall"
    fantasypros_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    rankings_cache_ttl_hours: int = 20

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
