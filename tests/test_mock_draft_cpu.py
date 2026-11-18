import random
from collections import Counter

import pytest

from fantasy_agent.mock_draft import engine as e
from fantasy_agent.mock_draft.cpu import PoolPlayer, autopick, choose_player


def _pool():
    # Realistic-ish superflex board shape: QBs interleaved early, K at the end.
    players = []
    adp = 1
    mix = ["QB", "RB", "WR", "WR", "RB", "QB", "WR", "TE", "RB", "WR"]
    for i in range(40):
        for pos in mix:
            players.append(PoolPlayer(f"{pos}{i}-{adp}", pos, float(adp)))
            adp += 1
    for i in range(20):
        players.append(PoolPlayer(f"K{i}", "K", float(adp)))
        adp += 1
    return players


def _run_full_draft(seed, **settings):
    s = e.DraftSettings(**settings)
    host = e.Participant(participant_id="p1", name="Host", token_hash="x")
    d = e.new_draft("d", "t", s, host=host, now=0.0)
    d.teams[0].participant_id = None  # all CPU
    e.start(d, now=0.0)
    pool = _pool()
    pos_of = {p.player_id: p.position for p in pool}
    rng = random.Random(seed)
    while d.status == "drafting":
        pick = e.current_pick(d)
        taken = e.drafted_ids(d)
        pid = choose_player(d, pick.owner_team_id, [p for p in pool if p.player_id not in taken], position_of=pos_of, rng=rng)
        e.make_pick(d, pid, now=1.0, auto=True)
    return d, pos_of


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_cpu_team_fills_a_legal_superflex_lineup(seed):
    d, pos_of = _run_full_draft(seed)
    for team in d.teams:
        ids = e.team_player_ids(d, team.team_id)
        assert len(ids) == 16
        counts = Counter(pos_of[i] for i in ids)
        assert e.unfilled_starters(counts, d.settings.roster_slots) == {}, (team.team_id, counts)
        assert counts["K"] == 1
        assert counts["QB"] <= 3
        assert counts["TE"] <= 2


def test_kicker_only_in_final_picks():
    d, pos_of = _run_full_draft(7)
    for p in d.picks:
        if pos_of[p.player_id] == "K":
            assert p.round >= 15


def test_extra_traded_picks_still_produce_full_lineups():
    s = e.DraftSettings()
    host = e.Participant(participant_id="p1", name="Host", token_hash="x")
    d = e.new_draft("d", "t", s, host=host, now=0.0)
    d.teams[0].participant_id = None
    for rnd in (1, 2, 3):
        e.set_pick_owner(d, rnd, 5, 6)  # team 6 gets team 5's first three picks
    e.start(d, now=0.0)
    pool = _pool()
    pos_of = {p.player_id: p.position for p in pool}
    rng = random.Random(0)
    while d.status == "drafting":
        pick = e.current_pick(d)
        taken = e.drafted_ids(d)
        pid = choose_player(d, pick.owner_team_id, [p for p in pool if p.player_id not in taken], position_of=pos_of, rng=rng)
        e.make_pick(d, pid, now=1.0)
    assert len(e.team_player_ids(d, 6)) == 19
    assert len(e.team_player_ids(d, 5)) == 13
    counts5 = Counter(pos_of[i] for i in e.team_player_ids(d, 5))
    assert e.unfilled_starters(counts5, s.roster_slots) == {}


def test_zero_randomness_takes_best_adp_at_first_pick():
    s = e.DraftSettings(cpu_randomness=0)
    host = e.Participant(participant_id="p1", name="Host", token_hash="x")
    d = e.new_draft("d", "t", s, host=host, now=0.0)
    e.start(d, now=0.0)
    pool = _pool()
    pos_of = {p.player_id: p.position for p in pool}
    assert choose_player(d, 1, pool, position_of=pos_of, rng=random.Random(0)) == pool[0].player_id


def test_autopick_prefers_queue():
    s = e.DraftSettings()
    host = e.Participant(participant_id="p1", name="Host", token_hash="x")
    d = e.new_draft("d", "t", s, host=host, now=0.0)
    e.start(d, now=0.0)
    pool = _pool()
    pos_of = {p.player_id: p.position for p in pool}
    queued = pool[50].player_id
    assert autopick(d, 1, pool, position_of=pos_of, queue=["gone", queued], rng=random.Random(0)) == queued
