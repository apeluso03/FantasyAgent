"""Keeper decision logic — pure data pipeline, no LLM.

Sleeper doesn't expose a "keeper cost" field (round-penalty rules are commissioner-
defined and live outside the API), so the cost model here is:

    cost_round = max(1, round_drafted - keeper_round_penalty)

`round_drafted` comes from the most recent *completed* draft in the league's
previous_league_id chain (see sync.sync_draft_history) — the current season's
draft is usually still pre_draft when you're making keeper calls, so last
season's draft is the real cost basis. Players never drafted (waiver/FA adds)
default to the last round of that draft, per league convention.

"Value" of keeping a player is a simple opportunity-cost comparison: a
round-N pick in an N-team league typically nets a player around rank
`cost_round * num_teams` (the last pick of that round). value_surplus is how
many ranking spots better the kept player is than that replacement-level
alternative — a rough but explainable signal, not a precise valuation model.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import settings
from .db.models import DraftPickRecord, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord


@dataclass
class KeeperCandidate:
    player_id: str
    name: str
    position: str
    team: str | None
    rank_ecr: int | None
    pos_rank: str | None
    drafted_round: int
    was_drafted: bool
    cost_round: int
    replacement_rank: int
    value_surplus: int | None
    reasoning: str


def compute_keeper_candidates(
    session: Session,
    league_id: str | None = None,
    owner_user_id: str | None = None,
    *,
    penalty: int | None = None,
    rankings_page: str | None = None,
) -> list[KeeperCandidate]:
    league_id = league_id or settings.sleeper_league_id
    owner_user_id = owner_user_id or settings.sleeper_owner_user_id
    penalty = penalty if penalty is not None else settings.keeper_round_penalty
    rankings_page = rankings_page or settings.fantasypros_ranking_page

    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data — run `fantasy-agent sync` first.")

    roster = (
        session.query(RosterRecord)
        .filter_by(league_id=league_id, owner_id=owner_user_id)
        .one_or_none()
    )
    if roster is None:
        raise RuntimeError(f"No roster found for owner_id={owner_user_id} in league {league_id}.")

    draft_picks = session.query(DraftPickRecord).filter_by(league_id=league_id).all()
    if not draft_picks:
        raise RuntimeError(
            "No cached draft history — run `fantasy-agent sync` (needs a completed draft "
            "somewhere in this league's history to use as a keeper-cost basis)."
        )
    pick_by_player = {p.player_id: p for p in draft_picks}
    total_rounds = max(p.round for p in draft_picks)

    rankings = session.query(RankingRecord).filter_by(source="fantasypros", page=rankings_page).all()
    rank_by_player = {r.sleeper_player_id: r for r in rankings if r.sleeper_player_id}

    players_by_id = {
        p.player_id: p
        for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    }

    num_teams = league.total_rosters
    candidates: list[KeeperCandidate] = []

    for player_id in roster.players:
        player = players_by_id.get(player_id)
        name = (player.full_name if player else None) or player_id
        position = (player.position if player else None) or "?"
        team = player.team if player else None

        pick = pick_by_player.get(player_id)
        was_drafted = pick is not None
        drafted_round = pick.round if pick else total_rounds
        cost_round = max(1, min(total_rounds, drafted_round - penalty))
        replacement_rank = cost_round * num_teams

        ranking = rank_by_player.get(player_id)
        if ranking is None:
            candidates.append(
                KeeperCandidate(
                    player_id=player_id,
                    name=name,
                    position=position,
                    team=team,
                    rank_ecr=None,
                    pos_rank=None,
                    drafted_round=drafted_round,
                    was_drafted=was_drafted,
                    cost_round=cost_round,
                    replacement_rank=replacement_rank,
                    value_surplus=None,
                    reasoning=f"No FantasyPros ranking found for {name} — can't evaluate as a keeper.",
                )
            )
            continue

        value_surplus = replacement_rank - ranking.rank_ecr
        drafted_desc = (
            f"drafted round {drafted_round}" if was_drafted else f"undrafted (defaulted to round {drafted_round})"
        )
        reasoning = (
            f"Ranked #{ranking.rank_ecr} overall ({ranking.pos_rank or position}); costs a round-{cost_round} "
            f"pick to keep ({drafted_desc}, -{penalty} round penalty). A round-{cost_round} pick in a "
            f"{num_teams}-team league typically nets ~rank #{replacement_rank}, so keeping is worth about "
            f"{value_surplus:+d} ranking spots."
        )
        candidates.append(
            KeeperCandidate(
                player_id=player_id,
                name=name,
                position=position,
                team=team,
                rank_ecr=ranking.rank_ecr,
                pos_rank=ranking.pos_rank,
                drafted_round=drafted_round,
                was_drafted=was_drafted,
                cost_round=cost_round,
                replacement_rank=replacement_rank,
                value_surplus=value_surplus,
                reasoning=reasoning,
            )
        )

    candidates.sort(
        key=lambda c: (c.value_surplus is not None, c.value_surplus if c.value_surplus is not None else float("-inf")),
        reverse=True,
    )
    return candidates
