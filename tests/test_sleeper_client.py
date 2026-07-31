import httpx
import pytest

from fantasy_agent.sleeper.client import SleeperAPIError, SleeperClient

LEAGUE_ID = "1312255990598483968"

FAKE_LEAGUE = {
    "league_id": LEAGUE_ID,
    "name": "Test League",
    "season": "2026",
    "sport": "nfl",
    "status": "in_season",
    "total_rosters": 12,
    "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"],
    "scoring_settings": {"rec": 1.0},
    "settings": {"keeper_count": 3},
}

FAKE_ROSTERS = [
    {
        "roster_id": 1,
        "owner_id": "u1",
        "players": ["1001", "1002"],
        "starters": ["1001"],
        "reserve": [],
        "taxi": [],
        "settings": {"wins": 5, "losses": 3},
    }
]

FAKE_USERS = [
    {"user_id": "u1", "display_name": "alex", "metadata": {"team_name": "The Robots"}},
]

FAKE_PLAYERS = {
    "1001": {
        "player_id": "1001",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "team": "KC",
        "position": "QB",
        "fantasy_positions": ["QB"],
        "status": "Active",
        "active": True,
    },
    # Defenses commonly omit first/last name entirely.
    "SEA": {
        "player_id": "SEA",
        "team": "SEA",
        "position": "DEF",
        "fantasy_positions": ["DEF"],
        "active": True,
    },
}


def _handler_for(path_to_json: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in path_to_json:
            return httpx.Response(200, json=path_to_json[path])
        return httpx.Response(404, json={"error": "not found"})

    return handler


def make_client(path_to_json: dict[str, object], **kwargs) -> SleeperClient:
    transport = httpx.MockTransport(_handler_for(path_to_json))
    return SleeperClient(base_url="https://sleeper.test", transport=transport, **kwargs)


def test_get_league_parses_response():
    client = make_client({f"/league/{LEAGUE_ID}": FAKE_LEAGUE})
    league = client.get_league(LEAGUE_ID)
    assert league.league_id == LEAGUE_ID
    assert league.total_rosters == 12
    assert league.settings["keeper_count"] == 3


def test_get_rosters_parses_list():
    client = make_client({f"/league/{LEAGUE_ID}/rosters": FAKE_ROSTERS})
    rosters = client.get_rosters(LEAGUE_ID)
    assert len(rosters) == 1
    assert rosters[0].owner_id == "u1"
    assert rosters[0].players == ["1001", "1002"]


def test_get_users_team_name_falls_back_to_metadata():
    client = make_client({f"/league/{LEAGUE_ID}/users": FAKE_USERS})
    users = client.get_users(LEAGUE_ID)
    assert users[0].team_name == "The Robots"


def test_get_players_derives_full_name_and_keys_by_id():
    client = make_client({"/players/nfl": FAKE_PLAYERS})
    players = client.get_players()
    assert players["1001"].full_name == "Patrick Mahomes"
    # Team defenses have no first/last name; full_name should stay unset rather than error.
    assert players["SEA"].full_name is None


def test_404_raises_sleeper_api_error():
    client = make_client({})
    with pytest.raises(SleeperAPIError):
        client.get_league("does-not-exist")


def test_get_user_resolves_username_to_user_id():
    client = make_client(
        {"/user/apel03": {"user_id": "1038585800163909632", "display_name": "apel03", "metadata": None}}
    )
    user = client.get_user("apel03")
    assert user.user_id == "1038585800163909632"
    # metadata: null (as Sleeper actually sends for this endpoint) shouldn't crash validation.
    assert user.metadata == {}


def test_get_user_unknown_username_raises():
    # Sleeper returns HTTP 200 with a literal `null` body for an unknown username,
    # not a 404 -- this must still surface as a clear SleeperAPIError. (httpx's
    # MockTransport `json=None` sends an empty body, not literal "null", so this
    # needs its own handler to accurately simulate the real response.)
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="null", headers={"content-type": "application/json"})

    client = SleeperClient(base_url="https://sleeper.test", transport=httpx.MockTransport(handler))
    with pytest.raises(SleeperAPIError, match="No Sleeper user found"):
        client.get_user("nobody")


def test_5xx_retries_then_raises():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    client = SleeperClient(base_url="https://sleeper.test", transport=transport, max_retries=2)
    with pytest.raises(SleeperAPIError):
        client.get_league(LEAGUE_ID)
    assert calls["count"] == 2
