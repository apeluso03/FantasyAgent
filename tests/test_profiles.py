import pytest

from fantasy_agent import profiles, user_config
from fantasy_agent.config import settings
from fantasy_agent.db import session as db_session


@pytest.fixture(autouse=True)
def _isolated_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _restore_shared_settings():
    fields = ["sleeper_league_id", "sleeper_owner_user_id", "openai_api_key", "openai_model", "database_url"]
    original = {name: getattr(settings, name) for name in fields}
    original_engine = db_session._engine
    original_factory = db_session._session_factory
    yield
    for name, value in original.items():
        setattr(settings, name, value)
    db_session._engine = original_engine
    db_session._session_factory = original_factory


def _profile(profile_id="p1", name="Dynasty League", league_id="111") -> profiles.Profile:
    return profiles.Profile(
        profile_id=profile_id,
        name=name,
        platform="sleeper",
        league_id=league_id,
        openai_api_key="sk-test",
        sleeper_username="apel03",
        sleeper_owner_user_id="u1",
    )


def test_load_profile_store_returns_none_when_nothing_exists():
    assert profiles.load_profile_store() is None


def test_legacy_single_config_is_migrated_into_a_profile():
    legacy = user_config.UserConfig(
        platform="sleeper", league_id="99999", openai_api_key="sk-legacy", sleeper_username="apel03",
        sleeper_owner_user_id="u1",
    )
    user_config.save_user_config(legacy)

    store = profiles.load_profile_store()

    assert store is not None
    assert len(store.profiles) == 1
    migrated = profiles.get_active_profile(store)
    assert migrated is not None
    assert migrated.league_id == "99999"
    assert migrated.name == "My League"
    # Migration should persist as profiles.json so it only happens once.
    assert profiles.profiles_path().exists()


def test_add_and_load_round_trip():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile())

    loaded = profiles.load_profile_store()
    assert loaded is not None
    assert loaded.active_profile_id == "p1"
    assert loaded.profiles["p1"].name == "Dynasty League"


def test_second_profile_does_not_become_active_unless_requested():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile("p1", "League A"))
    profiles.add_profile(store, _profile("p2", "League B"), make_active=False)

    assert store.active_profile_id == "p1"
    assert set(store.profiles) == {"p1", "p2"}


def test_update_profile_overwrites_fields():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile())

    edited = _profile()
    edited.name = "Renamed League"
    profiles.update_profile(store, edited)

    loaded = profiles.load_profile_store()
    assert loaded.profiles["p1"].name == "Renamed League"


def test_remove_profile_falls_back_active_id():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile("p1", "League A"))
    profiles.add_profile(store, _profile("p2", "League B"), make_active=False)

    profiles.remove_profile(store, "p1")

    assert "p1" not in store.profiles
    assert store.active_profile_id == "p2"


def test_remove_last_profile_leaves_no_active_profile():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile())

    profiles.remove_profile(store, "p1")

    assert store.active_profile_id is None
    assert store.profiles == {}


def test_set_active_profile_unknown_id_raises():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile())
    with pytest.raises(KeyError):
        profiles.set_active_profile(store, "does-not-exist")


def test_profile_database_url_is_isolated_per_profile():
    url_a = profiles.profile_database_url("p1")
    url_b = profiles.profile_database_url("p2")
    assert url_a != url_b
    assert "p1.db" in url_a
    assert "p2.db" in url_b


def test_touch_last_synced_sets_timestamp():
    store = profiles.ProfileStore(active_profile_id=None, profiles={})
    profiles.add_profile(store, _profile())
    assert store.profiles["p1"].last_synced_at is None

    profiles.touch_last_synced(store, "p1")

    assert store.profiles["p1"].last_synced_at is not None
    loaded = profiles.load_profile_store()
    assert loaded.profiles["p1"].last_synced_at is not None


def test_apply_profile_mutates_settings_and_resets_engine(tmp_path):
    # Simulate the engine already having been built against some prior DB.
    from sqlalchemy import create_engine

    db_session._engine = create_engine("sqlite:///:memory:")
    db_session._session_factory = object()

    profile = _profile(league_id="424242")
    profiles.apply_profile(profile)

    assert settings.sleeper_league_id == "424242"
    assert settings.sleeper_owner_user_id == "u1"
    assert settings.openai_api_key == "sk-test"
    assert "p1.db" in settings.database_url
    # reset_engine() must have cleared the cached engine so the next
    # get_session()/init_db() call rebuilds against the new database_url.
    assert db_session._engine is None
    assert db_session._session_factory is None


def test_switching_profiles_actually_points_at_different_databases(tmp_path):
    profile_a = _profile("a", "League A", league_id="1")
    profile_b = _profile("b", "League B", league_id="2")

    profiles.apply_profile(profile_a)
    with db_session.get_session():
        pass
    db_a_path = db_session._engine.url.database

    profiles.apply_profile(profile_b)
    with db_session.get_session():
        pass
    db_b_path = db_session._engine.url.database

    assert db_a_path != db_b_path
