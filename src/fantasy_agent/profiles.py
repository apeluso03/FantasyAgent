"""Multi-league profile support, shared by both GUI editions (gui.py's
header switcher and gui_user.py's sidebar switcher -- see profile_ui.py for
the Tkinter widgets built on top of this).

Each profile is a fully independent league connection: its own platform/
league/API key *and* its own local SQLite cache (see profile_database_url),
so switching from one league to another doesn't require re-typing anything
and, after the first sync, doesn't require re-syncing either -- switching
back to a league you were just on is instant.

Storage lives next to user_config.py's single-config file, in the same
per-user AppData directory, as profiles.json: `{"active_profile_id": ...,
"profiles": {profile_id: {...}}}`. An install that already has the older
single-config file (from before multi-profile support existed) is
transparently migrated into a one-profile store the first time this module
is asked to load one -- see _migrate_legacy_config.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import user_config
from .user_config import Platform

__all__ = [
    "Platform",
    "Profile",
    "ProfileStore",
    "profiles_path",
    "profile_database_url",
    "load_profile_store",
    "save_profile_store",
    "get_active_profile",
    "add_profile",
    "update_profile",
    "remove_profile",
    "set_active_profile",
    "touch_last_synced",
    "apply_profile",
    "create_and_sync_profile",
    "update_and_sync_profile",
    "resync_profile",
]


@dataclass
class Profile:
    profile_id: str
    name: str
    platform: Platform
    league_id: str
    openai_api_key: str
    openai_model: str = "gpt-5.6-luna"
    sleeper_username: str | None = None
    sleeper_owner_user_id: str | None = None
    last_synced_at: str | None = None  # ISO 8601 UTC, set by touch_last_synced


@dataclass
class ProfileStore:
    active_profile_id: str | None
    profiles: dict[str, Profile] = field(default_factory=dict)


def profiles_path() -> Path:
    return user_config.config_dir() / "profiles.json"


def profile_database_url(profile_id: str) -> str:
    db_path = user_config.config_dir() / "data" / f"{profile_id}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def _new_profile_id() -> str:
    return uuid.uuid4().hex[:10]


def _migrate_legacy_config() -> ProfileStore | None:
    legacy = user_config.load_user_config()
    if legacy is None:
        return None
    profile = Profile(
        profile_id=_new_profile_id(),
        name="My League",
        platform=legacy.platform,
        league_id=legacy.league_id,
        openai_api_key=legacy.openai_api_key,
        openai_model=legacy.openai_model,
        sleeper_username=legacy.sleeper_username,
        sleeper_owner_user_id=legacy.sleeper_owner_user_id,
    )
    store = ProfileStore(active_profile_id=profile.profile_id, profiles={profile.profile_id: profile})
    save_profile_store(store)
    return store


def load_profile_store() -> ProfileStore | None:
    path = profiles_path()
    if not path.exists():
        return _migrate_legacy_config()
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = {profile_id: Profile(**pdata) for profile_id, pdata in data.get("profiles", {}).items()}
    return ProfileStore(active_profile_id=data.get("active_profile_id"), profiles=profiles)


def save_profile_store(store: ProfileStore) -> None:
    profiles_path().parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_profile_id": store.active_profile_id,
        "profiles": {profile_id: asdict(p) for profile_id, p in store.profiles.items()},
    }
    profiles_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_active_profile(store: ProfileStore) -> Profile | None:
    if store.active_profile_id is None:
        return None
    return store.profiles.get(store.active_profile_id)


def add_profile(store: ProfileStore, profile: Profile, *, make_active: bool = True) -> None:
    store.profiles[profile.profile_id] = profile
    if make_active or store.active_profile_id is None:
        store.active_profile_id = profile.profile_id
    save_profile_store(store)


def update_profile(store: ProfileStore, profile: Profile) -> None:
    """Overwrite an existing profile's fields in place (e.g. Settings editing
    the active league's API key) -- profile_id must already exist."""
    store.profiles[profile.profile_id] = profile
    save_profile_store(store)


def remove_profile(store: ProfileStore, profile_id: str) -> None:
    store.profiles.pop(profile_id, None)
    if store.active_profile_id == profile_id:
        store.active_profile_id = next(iter(store.profiles), None)
    save_profile_store(store)
    # Deliberately doesn't delete the profile's cached .db file -- an orphaned
    # cache file is harmless, and safer than risking deleting the wrong thing.


def set_active_profile(store: ProfileStore, profile_id: str) -> None:
    if profile_id not in store.profiles:
        raise KeyError(f"No such profile: {profile_id}")
    store.active_profile_id = profile_id
    save_profile_store(store)


def touch_last_synced(store: ProfileStore, profile_id: str) -> None:
    profile = store.profiles.get(profile_id)
    if profile is None:
        return
    profile.last_synced_at = dt.datetime.now(dt.timezone.utc).isoformat()
    save_profile_store(store)


def apply_profile(profile: Profile) -> None:
    """Point the shared `settings` singleton -- and the SQLAlchemy engine --
    at this profile. Every pipeline module (sync, keeper, trade, draft,
    power_rankings, the agent) reads `settings.*` at call time, so mutating
    it here is enough for them; the engine reset is the part that's easy to
    miss, since db/session.py caches its engine forever once built -- without
    resetting it, switching profiles would update `settings.database_url`
    but every query would keep silently hitting the *previous* profile's
    database file.
    """
    from .config import settings
    from .db.session import reset_engine

    settings.sleeper_league_id = profile.league_id
    settings.sleeper_owner_user_id = profile.sleeper_owner_user_id
    settings.openai_api_key = profile.openai_api_key or None
    settings.openai_model = profile.openai_model
    settings.database_url = profile_database_url(profile.profile_id)
    reset_engine()


def create_and_sync_profile(
    *,
    name: str,
    platform: Platform,
    league_id: str,
    username: str,
    api_key: str,
    on_status=None,
) -> Profile:
    """Validate Sleeper credentials, run the new profile's initial sync, and
    persist it as a new (and active) profile. This does real network I/O and
    should be called from a background thread -- callers on the GUI thread
    must marshal both progress (`on_status`, called with a short string) and
    the return value back via `.after(...)`.
    """
    from .sleeper.client import SleeperClient

    with SleeperClient() as client:
        user = client.get_user(username)
        client.get_league(league_id)  # raises SleeperAPIError if the league doesn't exist

    profile = Profile(
        profile_id=_new_profile_id(),
        name=name,
        platform=platform,
        league_id=league_id,
        openai_api_key=api_key,
        sleeper_username=username,
        sleeper_owner_user_id=user.user_id,
    )
    apply_profile(profile)

    if on_status:
        on_status("Syncing your league...")
    from .sync import sync_all, sync_rankings_all

    sync_all(league_id)
    if on_status:
        on_status("Fetching player rankings...")
    sync_rankings_all()

    store = load_profile_store() or ProfileStore(active_profile_id=None, profiles={})
    add_profile(store, profile, make_active=True)
    touch_last_synced(store, profile.profile_id)
    return profile


def update_and_sync_profile(
    *,
    profile_id: str,
    name: str,
    platform: Platform,
    league_id: str,
    username: str,
    api_key: str,
    on_status=None,
) -> Profile:
    """Re-validate and re-sync an *existing* profile in place (its identity --
    profile_id, and therefore its cached database -- doesn't change even if
    the league_id does). Scoped to editing the currently-active profile (see
    gui_user.py's Settings screen): editing a profile that isn't active would
    leave `settings`/the engine pointed at it without updating which profile
    is marked active, an inconsistent state this deliberately avoids by not
    supporting it.
    """
    from .sleeper.client import SleeperClient

    with SleeperClient() as client:
        user = client.get_user(username)
        client.get_league(league_id)

    profile = Profile(
        profile_id=profile_id,
        name=name,
        platform=platform,
        league_id=league_id,
        openai_api_key=api_key,
        sleeper_username=username,
        sleeper_owner_user_id=user.user_id,
    )
    apply_profile(profile)

    if on_status:
        on_status("Syncing your league...")
    from .sync import sync_all, sync_rankings_all

    sync_all(league_id)
    if on_status:
        on_status("Fetching player rankings...")
    sync_rankings_all()

    store = load_profile_store() or ProfileStore(active_profile_id=profile_id, profiles={})
    update_profile(store, profile)
    touch_last_synced(store, profile_id)
    return profile


def resync_profile(profile: Profile, *, on_status=None) -> None:
    """Autosync entry point for switching *to* an already-existing profile:
    point settings/engine at it, then re-run the same sync pipeline used at
    setup time. Cheap resources (league/users/rosters) always re-fetch;
    expensive ones (players/nfl, FantasyPros rankings) are TTL-gated inside
    sync.py, so switching back to a recently-used league doesn't redundantly
    re-pull everything -- it's safe to call this on every switch.
    """
    apply_profile(profile)

    if on_status:
        on_status(f"Syncing {profile.name}...")
    from .sync import sync_all, sync_rankings_all

    sync_all(profile.league_id)
    sync_rankings_all()

    store = load_profile_store()
    if store is not None:
        touch_last_synced(store, profile.profile_id)
