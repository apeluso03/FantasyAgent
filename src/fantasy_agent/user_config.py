"""Per-user settings for the production/user-edition GUI (gui_user.py).

Unlike the dev build, which reads a checked-out .env file, the user edition
is meant to be handed to someone else -- so its config lives outside the repo
entirely, in the OS's per-user app-data directory, written by its setup
wizard rather than hand-edited. This also means one machine can run the dev
build (pointed at a developer's own league via .env) and the user edition
(pointed at anyone's league) side by side without either one clobbering the
other's cache or settings.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Platform = Literal["sleeper", "espn", "yahoo"]

# Only Sleeper has a working data-layer integration today (see fantasy-agent-spec.md
# discussion / README "Adding a new league platform"); ESPN and Yahoo are exposed in
# the UI as disabled options so the picker doesn't need to change shape later --
# ESPN's auth is session cookies from a logged-in browser, Yahoo's is a full OAuth2
# app-registration flow, neither of which can be wired up without real test accounts.
IMPLEMENTED_PLATFORMS: tuple[Platform, ...] = ("sleeper",)
ALL_PLATFORMS: tuple[Platform, ...] = ("sleeper", "espn", "yahoo")


@dataclass
class UserConfig:
    platform: Platform
    league_id: str
    openai_api_key: str
    openai_model: str = "gpt-5.6-luna"
    # Sleeper-specific: resolved once at setup time from the username the user typed,
    # so the rest of the app can keep using a stable numeric ID.
    sleeper_username: str | None = None
    sleeper_owner_user_id: str | None = None


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "FantasyAgent"


def config_path() -> Path:
    return config_dir() / "config.json"


def database_path() -> Path:
    return config_dir() / "data" / "fantasy_agent.db"


def database_url() -> str:
    db_path = database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def load_user_config() -> UserConfig | None:
    path = config_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return UserConfig(**data)


def save_user_config(config: UserConfig) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


def apply_user_config(config: UserConfig) -> None:
    """Point the shared `settings` singleton at this user's config. Every
    pipeline module (sync, keeper, trade, draft, power_rankings, the agent)
    reads `settings.*` at call time rather than at import time, so mutating
    it here -- before any of those are called -- is all that's needed; none
    of them need to know this GUI exists.
    """
    from .config import settings

    settings.sleeper_league_id = config.league_id
    settings.sleeper_owner_user_id = config.sleeper_owner_user_id
    settings.openai_api_key = config.openai_api_key or None
    settings.openai_model = config.openai_model
    settings.database_url = database_url()
