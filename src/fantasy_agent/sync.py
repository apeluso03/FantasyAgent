"""Pulls Sleeper data into the local cache.

League/roster/user data is small and re-synced every run. players/nfl is a
multi-MB dump Sleeper asks callers not to poll frequently, so it's gated
behind PLAYERS_CACHE_TTL_HOURS via SyncMeta.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .config import settings
from .db.models import (
    DraftPickRecord,
    LeagueRecord,
    PlayerAlias,
    PlayerRecord,
    RankingRecord,
    RosterRecord,
    SyncMeta,
    UserRecord,
)
from .db.session import get_session, init_db
from .rankings.fantasypros import FantasyProsClient
from .rankings.matching import SleeperPlayerIndex, match_player
from .sleeper.client import SleeperClient

logger = logging.getLogger(__name__)


def _get_last_synced(session: Session, resource: str) -> dt.datetime | None:
    meta = session.get(SyncMeta, resource)
    if meta is None:
        return None
    # SQLite doesn't actually persist tzinfo, so timestamps come back naive —
    # re-attach UTC (what _touch_sync_meta always writes) before comparing.
    if meta.last_synced_at.tzinfo is None:
        return meta.last_synced_at.replace(tzinfo=dt.timezone.utc)
    return meta.last_synced_at


def _touch_sync_meta(session: Session, resource: str) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    meta = session.get(SyncMeta, resource)
    if meta is None:
        session.add(SyncMeta(resource=resource, last_synced_at=now))
    else:
        meta.last_synced_at = now


def sync_league(session: Session, client: SleeperClient, league_id: str) -> LeagueRecord:
    league = client.get_league(league_id)
    record = session.get(LeagueRecord, league.league_id)
    if record is None:
        record = LeagueRecord(league_id=league.league_id)
        session.add(record)
    record.name = league.name
    record.season = league.season
    record.total_rosters = league.total_rosters
    record.roster_positions = league.roster_positions
    record.scoring_settings = league.scoring_settings
    record.settings = league.settings
    logger.info("Synced league %s (%s)", league.league_id, league.name)
    return record


def sync_users(session: Session, client: SleeperClient, league_id: str) -> list[UserRecord]:
    users = client.get_users(league_id)
    existing = {u.user_id: u for u in session.query(UserRecord).filter_by(league_id=league_id).all()}
    records = []
    for user in users:
        record = existing.get(user.user_id)
        if record is None:
            record = UserRecord(user_id=user.user_id, league_id=league_id)
            session.add(record)
        record.display_name = user.display_name
        record.team_name = user.team_name
        records.append(record)
    logger.info("Synced %d users for league %s", len(records), league_id)
    return records


def sync_rosters(session: Session, client: SleeperClient, league_id: str) -> list[RosterRecord]:
    rosters = client.get_rosters(league_id)
    existing = {
        r.roster_id: r for r in session.query(RosterRecord).filter_by(league_id=league_id).all()
    }
    records = []
    for roster in rosters:
        record = existing.get(roster.roster_id)
        if record is None:
            record = RosterRecord(league_id=league_id, roster_id=roster.roster_id)
            session.add(record)
        record.owner_id = roster.owner_id
        record.players = roster.players
        record.starters = roster.starters
        record.reserve = roster.reserve
        record.taxi = roster.taxi
        record.settings = roster.settings
        records.append(record)
    logger.info("Synced %d rosters for league %s", len(records), league_id)
    return records


def sync_players(session: Session, client: SleeperClient, *, force: bool = False) -> int:
    """Pull the full player database, but only if the cache is stale (or forced)."""
    last_synced = _get_last_synced(session, "players")
    ttl = dt.timedelta(hours=settings.players_cache_ttl_hours)
    if not force and last_synced is not None:
        age = dt.datetime.now(dt.timezone.utc) - last_synced
        if age < ttl:
            logger.info("Skipping players sync, cache is %s old (ttl=%s)", age, ttl)
            return 0

    players = client.get_players()
    existing = {r.player_id: r for r in session.query(PlayerRecord).all()}
    count = 0
    for player_id, player in players.items():
        record = existing.get(player_id)
        if record is None:
            record = PlayerRecord(player_id=player_id)
            session.add(record)
        record.full_name = player.full_name
        record.team = player.team
        record.position = player.position
        record.fantasy_positions = player.fantasy_positions
        record.status = player.status
        record.active = player.active
        count += 1
    _touch_sync_meta(session, "players")
    logger.info("Synced %d players", count)
    return count


def sync_draft_history(
    session: Session, client: SleeperClient, league_id: str, *, max_lookback: int = 6
) -> int:
    """Cache picks from the most recent *completed* draft in league_id's
    previous_league_id chain — the cost basis for keeper decisions.

    A keeper league's current-season draft is usually still pre_draft when
    you're deciding keepers, so we walk back through past seasons (Sleeper
    models each season as a new league_id linked via previous_league_id)
    until we find one that's actually finished.
    """
    current_id: str | None = league_id
    for _ in range(max_lookback):
        if current_id is None:
            break
        drafts = client.get_league_drafts(current_id)
        completed = [d for d in drafts if d.status == "complete"]
        if completed:
            draft = completed[0]
            picks = client.get_draft_picks(draft.draft_id)
            session.query(DraftPickRecord).filter_by(league_id=league_id).delete()
            for pick in picks:
                session.add(
                    DraftPickRecord(
                        league_id=league_id,
                        player_id=pick.player_id,
                        source_draft_id=draft.draft_id,
                        source_season=draft.season,
                        round=pick.round,
                        pick_no=pick.pick_no,
                        roster_id=pick.roster_id,
                    )
                )
            logger.info(
                "Synced %d draft picks for %s from draft %s (season %s)",
                len(picks),
                league_id,
                draft.draft_id,
                draft.season,
            )
            return len(picks)
        current_id = client.get_league(current_id).previous_league_id

    logger.warning("No completed draft found in the previous_league_id chain for %s", league_id)
    return 0


def sync_all(league_id: str | None = None, *, force_players: bool = False) -> None:
    league_id = league_id or settings.sleeper_league_id
    init_db()
    with SleeperClient(base_url=settings.sleeper_base_url) as client, get_session() as session:
        sync_league(session, client, league_id)
        sync_users(session, client, league_id)
        sync_rosters(session, client, league_id)
        sync_players(session, client, force=force_players)
        sync_draft_history(session, client, league_id)


@dataclass
class RankingsSyncResult:
    page: str
    total: int
    matched: int
    unmatched: list[tuple[int, str, str]] = field(default_factory=list)  # (fp_player_id, name, position)


def sync_rankings(
    session: Session,
    client: FantasyProsClient,
    page: str | None = None,
    *,
    force: bool = False,
) -> RankingsSyncResult | None:
    """Pull FantasyPros rankings for `page` and match each player to a cached
    Sleeper player. Gated behind rankings_cache_ttl_hours like sync_players,
    since we should never scrape mid-conversation.
    """
    page = page or settings.fantasypros_ranking_page
    resource = f"rankings:{page}"
    last_synced = _get_last_synced(session, resource)
    ttl = dt.timedelta(hours=settings.rankings_cache_ttl_hours)
    if not force and last_synced is not None:
        age = dt.datetime.now(dt.timezone.utc) - last_synced
        if age < ttl:
            logger.info("Skipping rankings sync for %s, cache is %s old (ttl=%s)", page, age, ttl)
            return None

    sleeper_players = session.query(PlayerRecord).all()
    if not sleeper_players:
        raise RuntimeError("No cached Sleeper players — run `fantasy-agent sync` first.")
    index = SleeperPlayerIndex(sleeper_players)
    aliases = {a.fp_player_id: a.sleeper_player_id for a in session.query(PlayerAlias).all()}

    ranked_players = client.fetch_rankings(page)
    existing = {
        r.fp_player_id: r
        for r in session.query(RankingRecord).filter_by(source="fantasypros", page=page).all()
    }

    matched_count = 0
    unmatched: list[tuple[int, str, str]] = []
    for ranked in ranked_players:
        result = match_player(ranked, index, aliases)
        record = existing.get(ranked.fp_player_id)
        if record is None:
            record = RankingRecord(source="fantasypros", page=page, fp_player_id=ranked.fp_player_id)
            session.add(record)
        record.sleeper_player_id = result.sleeper_player_id
        record.name = ranked.name
        record.team = ranked.team
        record.position = ranked.position
        record.rank_ecr = ranked.rank_ecr
        record.pos_rank = ranked.pos_rank
        record.tier = ranked.tier
        record.match_method = result.method
        if result.sleeper_player_id:
            matched_count += 1
        else:
            unmatched.append((ranked.fp_player_id, ranked.name, ranked.position))

    _touch_sync_meta(session, resource)
    logger.info(
        "Synced %d rankings for %s (%d matched, %d unmatched)",
        len(ranked_players),
        page,
        matched_count,
        len(unmatched),
    )
    return RankingsSyncResult(
        page=page, total=len(ranked_players), matched=matched_count, unmatched=unmatched
    )


def sync_rankings_all(
    page: str | None = None, *, force: bool = False
) -> RankingsSyncResult | None:
    init_db()
    with FantasyProsClient() as client, get_session() as session:
        return sync_rankings(session, client, page, force=force)
