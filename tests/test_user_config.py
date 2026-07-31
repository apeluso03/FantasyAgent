import pytest

from fantasy_agent import user_config
from fantasy_agent.config import settings


@pytest.fixture(autouse=True)
def _isolated_appdata(monkeypatch, tmp_path):
    """Point config_dir() at a throwaway temp dir instead of the real APPDATA,
    so tests never touch (or depend on) the actual user's app-data folder."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _restore_shared_settings():
    """apply_user_config() mutates the process-wide `settings` singleton, which
    every other test file also reads -- snapshot and restore it so these tests
    can't leak state into anything that runs after them."""
    fields = ["sleeper_league_id", "sleeper_owner_user_id", "openai_api_key", "openai_model", "database_url"]
    original = {name: getattr(settings, name) for name in fields}
    yield
    for name, value in original.items():
        setattr(settings, name, value)


def test_load_user_config_returns_none_when_absent():
    assert user_config.load_user_config() is None


def test_save_and_load_round_trip():
    config = user_config.UserConfig(
        platform="sleeper",
        league_id="12345",
        openai_api_key="sk-test",
        sleeper_username="apel03",
        sleeper_owner_user_id="1038585800163909632",
    )
    user_config.save_user_config(config)

    loaded = user_config.load_user_config()

    assert loaded == config


def test_config_path_lives_under_appdata(tmp_path):
    assert user_config.config_path() == tmp_path / "FantasyAgent" / "config.json"


def test_database_url_points_under_appdata_and_creates_parent(tmp_path):
    url = user_config.database_url()

    expected_dir = tmp_path / "FantasyAgent" / "data"
    assert expected_dir.exists()
    assert str(expected_dir.as_posix()) in url
    assert url.startswith("sqlite:///")


def test_apply_user_config_mutates_shared_settings():
    config = user_config.UserConfig(
        platform="sleeper",
        league_id="99999",
        openai_api_key="sk-live",
        openai_model="gpt-5.6-luna",
        sleeper_owner_user_id="42",
    )

    user_config.apply_user_config(config)

    assert settings.sleeper_league_id == "99999"
    assert settings.sleeper_owner_user_id == "42"
    assert settings.openai_api_key == "sk-live"
    assert settings.database_url.startswith("sqlite:///")
    assert "FantasyAgent" in settings.database_url


def test_apply_user_config_treats_empty_api_key_as_none():
    config = user_config.UserConfig(platform="sleeper", league_id="1", openai_api_key="")

    user_config.apply_user_config(config)

    assert settings.openai_api_key is None
