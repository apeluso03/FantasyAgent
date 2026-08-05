import httpx
import pytest

from fantasy_agent import player_analysis
from fantasy_agent.sleeper.client import SleeperClient


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    # _stats_cache is a module-level, process-lifetime cache by design (see
    # player_analysis.py) -- tests must not leak entries between each other.
    player_analysis._stats_cache.clear()
    yield
    player_analysis._stats_cache.clear()


def _client_for(path_to_json: dict[str, object], call_log: list[str] | None = None) -> SleeperClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if call_log is not None:
            call_log.append(path)
        if path in path_to_json:
            return httpx.Response(200, json=path_to_json[path])
        return httpx.Response(200, text="null", headers={"content-type": "application/json"})

    return SleeperClient(base_url="https://sleeper.test", transport=httpx.MockTransport(handler))


def test_regular_season_scans_completed_weeks_most_recent_first():
    client = _client_for(
        {
            "/state/nfl": {"week": 5, "season": "2026", "season_type": "regular"},
            "/stats/nfl/regular/2026/4": {"p1": {"pts_ppr": 20.0, "rush_att": 15, "rush_yd": 90, "rush_td": 1}},
            "/stats/nfl/regular/2026/3": {"p1": {"pts_ppr": 10.5, "rush_att": 10, "rush_yd": 40}},
            "/stats/nfl/regular/2026/2": {"p1": {"pts_ppr": 15.0, "rush_att": 12, "rush_yd": 60}},
            "/stats/nfl/regular/2026/1": {"p1": {"pts_ppr": 8.0, "rush_att": 8, "rush_yd": 20}},
        }
    )
    analysis = player_analysis.get_player_analysis("p1", position="RB", client=client)

    assert analysis.season == "2026"
    assert [g.week for g in analysis.games] == [4, 3, 2, 1]
    assert analysis.games[0].points_ppr == 20.0
    assert "rush yd" in analysis.games[0].stat_line
    assert analysis.avg_points == pytest.approx((20.0 + 10.5 + 15.0 + 8.0) / 4)


def test_bye_week_is_skipped_not_counted_as_a_game():
    client = _client_for(
        {
            "/state/nfl": {"week": 4, "season": "2026", "season_type": "regular"},
            "/stats/nfl/regular/2026/3": {},  # bye week -- no entry for p1
            "/stats/nfl/regular/2026/2": {"p1": {"pts_ppr": 12.0}},
            "/stats/nfl/regular/2026/1": {"p1": {"pts_ppr": 9.0}},
        }
    )
    analysis = player_analysis.get_player_analysis("p1", position="WR", client=client)

    assert [g.week for g in analysis.games] == [2, 1]


def test_preseason_falls_back_to_previous_season_end():
    client = _client_for(
        {
            "/state/nfl": {"week": 1, "season": "2027", "season_type": "pre", "previous_season": "2026"},
            "/stats/nfl/regular/2026/18": {"p1": {"pts_ppr": 22.0}},
            "/stats/nfl/regular/2026/17": {"p1": {"pts_ppr": 18.0}},
        }
    )
    analysis = player_analysis.get_player_analysis("p1", position="TE", client=client)

    assert analysis.season == "2026"
    assert [g.week for g in analysis.games] == [18, 17]


def test_no_games_found_gives_empty_analysis_not_a_crash():
    client = _client_for({"/state/nfl": {"week": 3, "season": "2026", "season_type": "regular"}})
    analysis = player_analysis.get_player_analysis("ghost", position="RB", client=client)

    assert analysis.games == []
    assert analysis.avg_points is None
    assert "No recent game logs" in analysis.blurb


def test_week_stats_are_cached_across_calls():
    calls: list[str] = []
    client = _client_for(
        {
            "/state/nfl": {"week": 3, "season": "2026", "season_type": "regular"},
            "/stats/nfl/regular/2026/2": {"p1": {"pts_ppr": 10.0}, "p2": {"pts_ppr": 5.0}},
            "/stats/nfl/regular/2026/1": {"p1": {"pts_ppr": 8.0}, "p2": {"pts_ppr": 4.0}},
        },
        call_log=calls,
    )
    player_analysis.get_player_analysis("p1", position="RB", client=client)
    calls_after_first = len([c for c in calls if c.startswith("/stats/")])
    player_analysis.get_player_analysis("p2", position="RB", client=client)
    calls_after_second = len([c for c in calls if c.startswith("/stats/")])

    # The second lookup reuses the same two cached weekly dumps -- no new
    # /stats/ requests should have been made.
    assert calls_after_second == calls_after_first


def test_trend_blurb_mentions_direction():
    client = _client_for(
        {
            "/state/nfl": {"week": 3, "season": "2026", "season_type": "regular"},
            "/stats/nfl/regular/2026/2": {"p1": {"pts_ppr": 25.0}},
            "/stats/nfl/regular/2026/1": {"p1": {"pts_ppr": 5.0}},
        }
    )
    analysis = player_analysis.get_player_analysis("p1", position="RB", client=client)
    assert "trending up" in analysis.blurb
