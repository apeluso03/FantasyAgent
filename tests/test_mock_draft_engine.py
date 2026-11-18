import pytest

from fantasy_agent.mock_draft import engine as e
from fantasy_agent.mock_draft.engine import DraftError, DraftSettings, Keeper, Participant


def _draft(num_teams=4, rounds=3, draft_type="snake", **kw):
    settings = DraftSettings(num_teams=num_teams, rounds=rounds, draft_type=draft_type, **kw)
    host = Participant(participant_id="p1", name="Host", token_hash="x", is_host=True)
    return e.new_draft("d1", "Test", settings, host=host, now=0.0)


def _order(picks, rnd):
    return [p.original_team_id for p in picks if p.round == rnd]


def test_defaults_are_superflex_ppr_16_rounds():
    s = DraftSettings()
    assert s.num_teams == 12
    assert s.scoring == "ppr"
    assert s.roster_slots["SUPER_FLEX"] == 1
    assert s.roster_slots["QB"] == 1 and s.roster_slots["RB"] == 2 and s.roster_slots["WR"] == 3
    assert s.roster_slots["TE"] == 1 and s.roster_slots["FLEX"] == 1 and s.roster_slots["K"] == 1
    assert s.rounds == sum(s.roster_slots.values()) == 16


def test_host_is_seated_at_first_team():
    d = _draft()
    assert d.teams[0].participant_id == "p1"
    assert [t.team_id for t in d.teams] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "draft_type,expected",
    [
        ("snake", [[1, 2, 3, 4], [4, 3, 2, 1], [1, 2, 3, 4], [4, 3, 2, 1]]),
        ("linear", [[1, 2, 3, 4]] * 4),
        ("3rr", [[1, 2, 3, 4], [4, 3, 2, 1], [4, 3, 2, 1], [1, 2, 3, 4]]),
    ],
)
def test_round_orders(draft_type, expected):
    d = _draft(rounds=4, draft_type=draft_type)
    picks = e.build_picks(d)
    assert [_order(picks, r) for r in range(1, 5)] == expected
    assert [p.overall for p in picks] == list(range(1, 17))


def test_traded_pick_moves_to_new_owner_at_original_slot():
    d = _draft()
    # Team 4 acquires Team 1's and Team 2's 2nd-rounders.
    e.set_pick_owner(d, 2, 1, 4)
    e.set_pick_owner(d, 2, 2, 4)
    r2 = [p for p in e.build_picks(d) if p.round == 2]
    assert [(p.original_team_id, p.owner_team_id) for p in r2] == [(4, 4), (3, 3), (2, 4), (1, 4)]
    assert sum(1 for p in r2 if p.owner_team_id == 4) == 3
    assert not any(p.owner_team_id in (1, 2) for p in r2)


def test_trading_back_to_original_clears_override():
    d = _draft()
    e.set_pick_owner(d, 2, 1, 4)
    e.set_pick_owner(d, 2, 1, 1)
    assert d.pick_ownership == {}


def test_removed_pick_is_skipped_and_numbering_stays_contiguous():
    d = _draft()
    e.set_pick_owner(d, 1, 3, None)
    picks = e.build_picks(d)
    assert len(picks) == 11
    assert _order(picks, 1) == [1, 2, 4]
    assert [p.overall for p in picks] == list(range(1, 12))


def test_reordering_teams_carries_their_picks():
    d = _draft()
    e.set_pick_owner(d, 1, 1, 3)
    e.set_team_order(d, [2, 1, 3, 4])
    r1 = [p for p in e.build_picks(d) if p.round == 1]
    assert [(p.slot, p.original_team_id, p.owner_team_id) for p in r1][:2] == [(1, 2, 2), (2, 1, 3)]


def test_keeper_fills_teams_pick_in_its_round():
    d = _draft()
    e.set_keepers(d, [Keeper(team_id=2, player_id="k1", round=2)])
    e.start(d, now=0.0)
    kept = next(p for p in d.picks if p.player_id == "k1")
    assert kept.round == 2 and kept.owner_team_id == 2 and kept.is_keeper


def test_keeper_without_pick_in_round_blocks_start():
    d = _draft()
    e.set_pick_owner(d, 2, 2, 1)
    e.set_keepers(d, [Keeper(team_id=2, player_id="k1", round=2)])
    assert e.validate_for_start(d)
    with pytest.raises(DraftError):
        e.start(d, now=0.0)


def test_pick_flow_and_turn_order():
    d = _draft(num_teams=2, rounds=2)
    e.start(d, now=100.0)
    assert e.current_pick(d).owner_team_id == 1
    assert d.deadline == 160.0  # host is human, default 60s timer
    e.make_pick(d, "a", now=101.0)
    assert e.current_pick(d).owner_team_id == 2
    assert d.deadline is None  # team 2 is CPU
    with pytest.raises(DraftError):
        e.make_pick(d, "a", now=102.0)
    e.make_pick(d, "b", now=102.0)
    e.make_pick(d, "c", now=103.0)  # snake: team 2 again
    e.make_pick(d, "d", now=104.0)
    assert d.status == "complete"
    assert e.team_player_ids(d, 1) == ["a", "d"]


def test_undo_reopens_completed_draft_and_skips_keepers():
    d = _draft(num_teams=2, rounds=1)
    e.set_keepers(d, [Keeper(team_id=2, player_id="k", round=1)])
    e.start(d, now=0.0)
    e.make_pick(d, "a", now=1.0)
    assert d.status == "complete"
    undone = e.undo_last_pick(d, now=2.0)
    assert undone.player_id is None and d.status == "drafting"
    with pytest.raises(DraftError):
        e.undo_last_pick(d, now=3.0)


def test_pause_resume_keeps_remaining_time():
    d = _draft(num_teams=2, rounds=1)
    e.start(d, now=0.0)
    e.pause(d, now=30.0)
    with pytest.raises(DraftError):
        e.make_pick(d, "a", now=31.0)
    e.resume(d, now=100.0)
    assert d.deadline == 130.0


def test_mid_draft_pick_trade_only_for_unmade_picks():
    d = _draft(num_teams=2, rounds=2)
    e.start(d, now=0.0)
    e.make_pick(d, "a", now=1.0)
    with pytest.raises(DraftError):
        e.set_pick_owner(d, 1, 1, 2)
    e.set_pick_owner(d, 2, 1, 2)
    assert next(p for p in d.picks if p.round == 2 and p.original_team_id == 1).owner_team_id == 2


def test_shrinking_team_count_keeps_seated_people():
    d = _draft(num_teams=4)
    d.teams[3].participant_id = "p2"
    e.update_settings(d, DraftSettings(num_teams=2, rounds=3))
    assert {t.participant_id for t in d.teams} == {"p1", "p2"}


def test_state_round_trips_through_dict():
    d = _draft()
    e.set_pick_owner(d, 2, 1, 4)
    e.set_pick_owner(d, 3, 2, None)
    e.start(d, now=0.0)
    e.make_pick(d, "x", now=1.0)
    again = e.DraftState.from_dict(d.to_dict())
    assert again.to_dict() == d.to_dict()


def test_unfilled_starters_superflex():
    slots = e.DEFAULT_ROSTER_SLOTS
    assert e.unfilled_starters({}, slots) == {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "K": 1, "FLEX": 1, "SUPER_FLEX": 1}
    # A second QB fills SUPER_FLEX; a 3rd RB fills FLEX.
    assert e.unfilled_starters({"QB": 2, "RB": 3, "WR": 3, "TE": 1}, slots) == {"K": 1}


def test_assign_lineup():
    players = [("q1", "QB"), ("r1", "RB"), ("q2", "QB"), ("r2", "RB"), ("r3", "RB"), ("w1", "WR")]
    lineup = dict()
    for slot, pid in e.assign_lineup(players, {"QB": 1, "RB": 2, "WR": 1, "FLEX": 1, "SUPER_FLEX": 1, "BN": 2}):
        lineup.setdefault(slot, []).append(pid)
    assert lineup == {"QB": ["q1"], "RB": ["r1", "r2"], "WR": ["w1"], "FLEX": ["r3"], "SUPER_FLEX": ["q2"]}


def test_replace_teams_applies_imported_trades():
    d = _draft(num_teams=4)
    e.replace_teams(d, [(1, "A"), (2, "B"), (3, "C")], traded_picks=[(2, 1, 3)], rounds=5)
    assert d.settings.num_teams == 3 and d.settings.rounds == 5
    assert d.teams[0].participant_id == "p1"
    assert d.pick_ownership == {"2:1": 3}
