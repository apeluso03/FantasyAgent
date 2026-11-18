import json

import httpx

from fantasy_agent.mock_draft.adp import build_board, load_rookie_seed, pool_for_mode, rookie_player_id
from fantasy_agent.mock_draft.sleeper_import import import_league, roster_slots_from_positions
from fantasy_agent.rankings.schemas import RankedPlayer
from fantasy_agent.sleeper.client import SleeperClient


def _row(pid, first, last, pos, team, redraft=None, dynasty=None, exp=3):
    stats = {}
    if redraft is not None:
        stats["adp_2qb"] = redraft
    if dynasty is not None:
        stats["adp_dynasty_2qb"] = dynasty
    return {
        "player_id": pid,
        "team": team,
        "stats": stats,
        "player": {"first_name": first, "last_name": last, "position": pos, "team": team, "years_exp": exp},
    }


ROWS = [
    _row("1", "Old", "Vet", "RB", "DAL", redraft=1.0, dynasty=20.0, exp=9),
    _row("2", "Young", "Star", "WR", "CIN", redraft=4.0, dynasty=2.0, exp=2),
    _row("3", "Franchise", "Qb", "QB", "BUF", redraft=3.0, dynasty=1.0),
    _row("4", "Redraft", "Only", "RB", "NYG", redraft=10.0, exp=11),
    _row("5", "Nobody", "Drafts", "WR", "NYJ"),
    _row("HOU", "Houston", "Texans", "DEF", "HOU", redraft=150.0, dynasty=280.0),
]


def _fp(pid, name, pos, team, rank):
    return RankedPlayer.model_validate(
        {"player_id": pid, "player_name": name, "player_position_id": pos, "player_team_id": team, "rank_ecr": rank}
    )


def test_board_blends_and_orders_each_mode():
    board = build_board(ROWS, [], [], include_rookies=False)
    by_id = {b.player_id: b for b in board}
    assert "5" not in by_id  # no ADP anywhere
    # Redraft: Old Vet first. Dynasty: QB first, old vet behind the young WR.
    assert by_id["1"].adp_redraft == 1.0
    assert by_id["3"].adp_dynasty == 1.0
    assert by_id["2"].adp_dynasty < by_id["1"].adp_dynasty
    # 2027 is a blend: the young QB/WR pass the 9-year vet.
    assert by_id["3"].adp_2027 < by_id["1"].adp_2027
    assert by_id["2"].adp_2027 < by_id["1"].adp_2027
    # Ordinal ADP: every board is 1..N with no gaps.
    assert sorted(b.adp_2027 for b in board) == [float(i) for i in range(1, len(board) + 1)]


def test_fantasypros_rank_is_averaged_into_dynasty():
    without = {b.player_id: b for b in build_board(ROWS, [], [], include_rookies=False)}
    # FP has the old vet as the #1 dynasty asset -> averaged with Sleeper's 20, passes the young WR.
    rows = ROWS + [_row("6", "Mid", "Guy", "WR", "LV", redraft=30.0, dynasty=8.0)]
    without = {b.player_id: b for b in build_board(rows, [], [], include_rookies=False)}
    assert without["6"].adp_dynasty < without["1"].adp_dynasty  # Sleeper alone: 8 vs 20
    fp = [_fp(99, "Old Vet", "RB", "DAL", 1)]
    with_fp = {b.player_id: b for b in build_board(rows, fp, [], include_rookies=False)}  # (20+1)/2 = 10.5
    assert with_fp["1"].adp_dynasty == without["1"].adp_dynasty  # 10.5 still behind 8
    fp = [_fp(99, "Old Vet", "RB", "DAL", 1), _fp(98, "Mid Guy", "WR", "LV", 30)]
    with_fp = {b.player_id: b for b in build_board(rows, fp, [], include_rookies=False)}  # 10.5 vs 19
    assert with_fp["1"].adp_dynasty < with_fp["6"].adp_dynasty
    assert "fantasypros_dynasty_sf" in with_fp["1"].sources


def test_rookies_merge_into_board_with_synthetic_ids():
    rookies = [{"rank": 1, "name": "Jeremiah Smith", "position": "WR", "college": "Ohio State"}]
    board = build_board(ROWS, [], rookies)
    rookie = next(b for b in board if b.is_rookie)
    assert rookie.player_id == rookie_player_id("Jeremiah Smith") == "r27-jeremiah-smith"
    assert rookie.college == "Ohio State" and rookie.team is None
    # Offset curve: rookie goes behind the handful of top vets in this tiny board.
    assert rookie.adp_2027 == len([b for b in board if not b.is_rookie and b.adp_2027 < rookie.adp_2027]) + 1


def test_seed_file_is_well_formed():
    rookies = load_rookie_seed()
    assert len(rookies) >= 40
    assert [r["rank"] for r in rookies] == list(range(1, len(rookies) + 1))
    assert {r["position"] for r in rookies} <= {"QB", "RB", "WR", "TE"}
    assert len({r["name"] for r in rookies}) == len(rookies)


def test_pool_for_mode_includes_kickers_and_renumbers():
    rows = ROWS + [_row(f"k{i}", "Kick", f"Er{i}", "K", "DAL", redraft=200.0 + i, dynasty=290.0 + i) for i in range(3)]
    board = build_board(rows, [], [])
    pool = pool_for_mode(board, "2027", size=3)
    assert [p["adp"] for p in pool] == [float(i) for i in range(1, len(pool) + 1)]
    assert sum(1 for p in pool if p["position"] == "K") == 3
    assert any(p["pos_rank"] == "K1" for p in pool)


def test_roster_slots_mapping():
    slots, notes = roster_slots_from_positions(["QB", "RB", "RB", "WR", "REC_FLEX", "SUPER_FLEX", "K", "BN", "IR", "DL"])
    assert slots["FLEX"] == 1 and slots["SUPER_FLEX"] == 1 and slots["BN"] == 1 and slots["DEF"] == 0
    assert notes and "DL" in notes[0]


def _league_handler(*, traded, drafts, draft_rounds=3, positions=None):
    positions = positions or ["QB", "RB", "WR", "SUPER_FLEX", "BN"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/traded_picks"):
            return httpx.Response(200, json=traded)
        if path.endswith("/drafts"):
            return httpx.Response(200, json=drafts)
        if path.endswith("/users"):
            return httpx.Response(200, json=[{"user_id": "u1", "display_name": "alice", "metadata": {"team_name": "Alpha"}}])
        if path.endswith("/rosters"):
            return httpx.Response(200, json=[{"roster_id": i, "owner_id": "u1" if i == 1 else None} for i in (1, 2, 3)])
        return httpx.Response(200, json={
            "league_id": "L", "name": "My League", "season": "2026", "total_rosters": 3,
            "roster_positions": positions, "settings": {"draft_rounds": draft_rounds},
        })

    return httpx.MockTransport(handler)


def _tp(rnd, original, owner, season="2027"):
    return {"season": season, "round": rnd, "roster_id": original, "owner_id": owner, "previous_owner_id": original}


def test_import_league_maps_traded_picks():
    transport = _league_handler(
        traded=[_tp(2, 1, 3), _tp(3, 2, 2), _tp(1, 1, 2, season="2028")],
        drafts=[{"draft_id": "d1", "season": "2026", "status": "complete", "settings": {"rounds": 5}}],
    )
    with SleeperClient(base_url="https://sleeper.test", transport=transport) as client:
        imp = import_league(client, "L", season="2027")
    assert imp.traded_picks == [(2, 1, 3)]  # traded-back pick and the 2028 pick aren't trades for 2027
    assert imp.rounds == 5 and imp.num_teams == 3
    assert [t.name for t in imp.teams] == ["Alpha", "Team 2", "Team 3"]


def test_rounds_come_from_real_draft_not_league_draft_rounds():
    # A real keeper league: settings.draft_rounds says 3, but its drafts are 15 rounds.
    transport = _league_handler(
        traded=[_tp(7, 1, 2)],
        draft_rounds=3,
        drafts=[
            {"draft_id": "d2", "season": "2026", "status": "complete", "settings": {"rounds": 15}},
            {"draft_id": "d1", "season": "2025", "status": "complete", "settings": {"rounds": 14}},
        ],
    )
    with SleeperClient(base_url="https://sleeper.test", transport=transport) as client:
        imp = import_league(client, "L", season="2027")
    assert imp.rounds == 15
    assert imp.traded_picks == [(7, 1, 2)]
    assert not any("Skipped" in n for n in imp.notes)


def test_rounds_fall_back_to_roster_size_without_drafts():
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K"] + ["BN"] * 5 + ["IR"]
    transport = _league_handler(traded=[], drafts=[], draft_rounds=3, positions=positions)
    with SleeperClient(base_url="https://sleeper.test", transport=transport) as client:
        imp = import_league(client, "L", season="2027")
    assert imp.rounds == 15  # IR doesn't count


def test_traded_pick_beyond_rounds_extends_draft_instead_of_skipping():
    transport = _league_handler(
        traded=[_tp(2, 1, 3), _tp(18, 2, 1)],
        drafts=[{"draft_id": "d1", "season": "2026", "status": "complete", "settings": {"rounds": 15}}],
    )
    with SleeperClient(base_url="https://sleeper.test", transport=transport) as client:
        imp = import_league(client, "L", season="2027")
    assert imp.rounds == 18
    assert (18, 2, 1) in imp.traded_picks
    assert any("Extended the draft from 15 to 18" in n for n in imp.notes)
