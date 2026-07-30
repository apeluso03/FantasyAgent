from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sleeper_league_id: str = "1312255990598483968"
    sleeper_base_url: str = "https://api.sleeper.app/v1"
    database_url: str = "sqlite:///data/fantasy_agent.db"
    players_cache_ttl_hours: int = 24

    # "apel03" (apel's unnamed team) — used to default keeper/trade tools to your roster.
    sleeper_owner_user_id: str = "1038585800163909632"

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

    # Agent (Claude tool-calling loop). API key only required when `fantasy-agent ask` runs.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_max_tokens: int = 4096


settings = Settings()
