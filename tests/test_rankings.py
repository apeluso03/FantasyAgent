import httpx
import pytest

from fantasy_agent.db.models import PlayerRecord
from fantasy_agent.rankings.fantasypros import FantasyProsClient, FantasyProsScrapeError
from fantasy_agent.rankings.matching import (
    MatchResult,
    SleeperPlayerIndex,
    match_player,
    normalize_name,
)
from fantasy_agent.rankings.schemas import RankedPlayer

FAKE_PAGE_HTML = """
<html><head><script>
    const _appSettings = {"some":"unrelated data with a }; inside a string"};
    var ecrData = {"sport":"NFL","players":[
        {"player_id":1,"player_name":"Patrick Mahomes II","player_team_id":"KC","player_position_id":"QB","player_bye_week":"10","rank_ecr":1,"pos_rank":"QB1","tier":1},
        {"player_id":2,"player_name":"Houston Texans","player_team_id":"HOU","player_position_id":"DST","player_bye_week":"8","rank_ecr":150,"pos_rank":"DST1","tier":9}
    ]};
    var sosData = {"ARI":{"qb_stars":1.0}};
</script></head></html>
"""


def _make_client(html: str, status: int = 200) -> FantasyProsClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=html)

    return FantasyProsClient(base_url="https://fp.test/nfl/rankings", transport=httpx.MockTransport(handler))


def test_fetch_rankings_parses_embedded_json_despite_decoy_braces():
    client = _make_client(FAKE_PAGE_HTML)
    players = client.fetch_rankings("dynasty-superflex")
    assert len(players) == 2
    assert players[0].name == "Patrick Mahomes II"
    assert players[0].fp_player_id == 1
    assert players[1].position == "DST"


def test_fetch_rankings_missing_ecr_data_raises():
    client = _make_client("<html>no data here</html>")
    with pytest.raises(FantasyProsScrapeError):
        client.fetch_rankings("dynasty-superflex")


def test_fetch_rankings_http_error_raises():
    client = _make_client("nope", status=500)
    with pytest.raises(FantasyProsScrapeError):
        client.fetch_rankings("dynasty-superflex")


def test_fetch_rankings_redirect_to_another_page_raises():
    # FantasyPros sends unknown slugs to its redraft cheat sheet, which parses
    # fine -- storing it under the requested name would be silently wrong.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/not-a-real-page.php"):
            return httpx.Response(302, headers={"Location": "https://fp.test/nfl/rankings/consensus-cheatsheets.php"})
        return httpx.Response(200, text=FAKE_PAGE_HTML)

    client = FantasyProsClient(base_url="https://fp.test/nfl/rankings", transport=httpx.MockTransport(handler))
    with pytest.raises(FantasyProsScrapeError, match="redirected"):
        client.fetch_rankings("not-a-real-page")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Patrick Mahomes II", "patrick mahomes"),
        ("Patrick Mahomes", "patrick mahomes"),
        ("A.J. Brown", "aj brown"),
        ("Marvin Harrison Jr.", "marvin harrison"),
        ("Odell Beckham Jr", "odell beckham"),
        ("Jaxon Smith-Njigba", "jaxon smith njigba"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def _players() -> list[PlayerRecord]:
    return [
        PlayerRecord(player_id="4046", full_name="Patrick Mahomes", team="KC", position="QB"),
        PlayerRecord(player_id="9001", full_name="Marvin Harrison", team="ARI", position="WR"),
        PlayerRecord(player_id="HOU", full_name="Houston Texans", team="HOU", position="DEF"),
    ]


def test_match_player_exact_name_ignores_suffix():
    index = SleeperPlayerIndex(_players())
    ranked = RankedPlayer(player_id=1, player_name="Patrick Mahomes II", player_team_id="KC", player_position_id="QB", rank_ecr=1)
    result = match_player(ranked, index, aliases={})
    assert result.sleeper_player_id == "4046"
    assert result.method == "exact_name"


def test_match_player_fuzzy_name():
    index = SleeperPlayerIndex(_players())
    ranked = RankedPlayer(player_id=2, player_name="Marvin Harrison Jr", player_team_id="ARI", player_position_id="WR", rank_ecr=50)
    result = match_player(ranked, index, aliases={})
    assert result.sleeper_player_id == "9001"
    assert result.method in ("exact_name", "fuzzy_name")


def test_match_player_defense_by_team_code_with_alias_map():
    index = SleeperPlayerIndex(_players())
    # FantasyPros uses JAC; Sleeper (and our fixture) doesn't have it, so expect unmatched here,
    # but HOU should resolve directly by team code.
    ranked = RankedPlayer(player_id=3, player_name="Houston Texans", player_team_id="HOU", player_position_id="DST", rank_ecr=150)
    result = match_player(ranked, index, aliases={})
    assert result.sleeper_player_id == "HOU"
    assert result.method == "team_code"


def test_match_player_unmatched_when_no_candidate():
    index = SleeperPlayerIndex(_players())
    ranked = RankedPlayer(player_id=4, player_name="Nobody Real", player_team_id="SF", player_position_id="RB", rank_ecr=999)
    result = match_player(ranked, index, aliases={})
    assert result.sleeper_player_id is None
    assert result.method == "unmatched"


def test_match_player_alias_override_wins_over_automatic_match():
    index = SleeperPlayerIndex(_players())
    ranked = RankedPlayer(player_id=1, player_name="Patrick Mahomes II", player_team_id="KC", player_position_id="QB", rank_ecr=1)
    result = match_player(ranked, index, aliases={1: "override-id"})
    assert result.sleeper_player_id == "override-id"
    assert result.method == "alias"
