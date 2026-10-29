"""Pulls Sleeper data into the local cache.

League/roster/user data is small and re-synced every run. players/nfl is a
multi-MB dump Sleeper asks callers not to poll frequently, so it's gated
behind PLAYERS_CACHE_TTL_HOURS via SyncMeta.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
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
from .rankings.pages import DERIVED_ROS_SUPERFLEX, ROS_1QB, SOURCE_PAGES, WEEKLY_SUPERFLEX, derive_superflex_order
from .sleeper.client import SleeperClient

logger = logging.getLogger(__name__)


def get_last_synced(session: Session, resource: str) -> dt.datetime | None:
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
    last_synced = get_last_synced(session, "players")
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
        record.injury_status = player.injury_status
        record.injury_body_part = player.injury_body_part
        record.injury_notes = player.injury_notes
        record.injury_start_date = player.injury_start_date
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
    last_synced = get_last_synced(session, resource)
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


def derive_ros_superflex(session: Session) -> RankingsSyncResult | None:
    """Build the rest-of-season superflex page FantasyPros doesn't publish: the
    1-QB rest-of-season ranking, with QBs re-slotted using the weekly superflex
    page's QB-vs-skill-player spacing (see pages.derive_superflex_order).
    No network -- works purely off the two already-synced source pages."""
    base = (
        session.query(RankingRecord)
        .filter_by(source="fantasypros", page=ROS_1QB)
        .order_by(RankingRecord.rank_ecr)
        .all()
    )
    reference = (
        session.query(RankingRecord.position)
        .filter_by(source="fantasypros", page=WEEKLY_SUPERFLEX)
        .order_by(RankingRecord.rank_ecr)
        .all()
    )
    if not base or not reference:
        logger.warning("Can't derive %s: %s and %s must both be synced", DERIVED_ROS_SUPERFLEX, ROS_1QB, WEEKLY_SUPERFLEX)
        return None

    by_fp_id = {r.fp_player_id: r for r in base}
    order = derive_superflex_order([(r.fp_player_id, r.position) for r in base], [pos for (pos,) in reference])

    session.query(RankingRecord).filter_by(source="fantasypros", page=DERIVED_ROS_SUPERFLEX).delete()
    for rank, fp_id in enumerate(order, start=1):
        src = by_fp_id[fp_id]
        session.add(
            RankingRecord(
                source="fantasypros",
                page=DERIVED_ROS_SUPERFLEX,
                fp_player_id=fp_id,
                sleeper_player_id=src.sleeper_player_id,
                name=src.name,
                team=src.team,
                position=src.position,
                rank_ecr=rank,
                pos_rank=src.pos_rank,  # order within a position is unchanged
                tier=None,  # FantasyPros tiers don't survive re-slotting
                match_method=src.match_method,
            )
        )
    _touch_sync_meta(session, f"rankings:{DERIVED_ROS_SUPERFLEX}")
    matched = sum(1 for r in base if r.sleeper_player_id)
    return RankingsSyncResult(page=DERIVED_ROS_SUPERFLEX, total=len(order), matched=matched)


# Pause between consecutive FantasyPros page fetches in one sync run -- a full
# sync scrapes several pages, and there's no reason to hit them back to back.
_SCRAPE_DELAY_SECONDS = 5.0


def sync_rankings_all(page: str | None = None, *, force: bool = False) -> list[RankingsSyncResult]:
    """Sync one page, or (page=None) every page in pages.SOURCE_PAGES plus the
    derived rest-of-season superflex page. Each page is TTL-gated on its own;
    returns results only for pages that were actually refreshed."""
    init_db()
    pages = [page] if page else list(SOURCE_PAGES)
    results: list[RankingsSyncResult] = []
    with FantasyProsClient() as client:
        for p in pages:
            if results:
                time.sleep(_SCRAPE_DELAY_SECONDS)
            with get_session() as session:
                result = sync_rankings(session, client, p, force=force)
            if result is not None:
                results.append(result)

    if page is None or page in (ROS_1QB, WEEKLY_SUPERFLEX):
        with get_session() as session:
            derived_missing = get_last_synced(session, f"rankings:{DERIVED_ROS_SUPERFLEX}") is None
            if results or derived_missing:
                derived = derive_ros_superflex(session)
                if derived is not None:
                    results.append(derived)
    return results


@dataclass
class RefreshResult:
    """What `fantasy-agent refresh` (and a GUI's refresh-on-open) actually
    did -- each cache is only touched if its own TTL says it's stale, so this
    distinguishes "skipped, still fresh" from "just refreshed" for both."""

    players_refreshed: bool
    players_age: dt.timedelta | None
    players_synced_count: int | None  # None when skipped
    rankings_refreshed: bool
    rankings_age: dt.timedelta | None  # the *stalest* rankings page's age
    rankings_results: list[RankingsSyncResult] = field(default_factory=list)  # pages actually refreshed


def refresh_caches() -> RefreshResult:
    """Pull the players and rankings caches if either is stale, each
    respecting its own TTL (PLAYERS_CACHE_TTL_HOURS / RANKINGS_CACHE_TTL_HOURS)
    -- safe to call on a schedule (the CLI's `refresh` command, or a
    background thread when a GUI opens), since a still-fresh cache is just a
    no-op. Deliberately narrower than sync_all(): just the two TTL-gated
    pieces that go stale on their own clock, not league/roster/user/draft
    history (those are small and re-synced every `fantasy-agent sync` run
    regardless, so there's nothing for a scheduled refresh to gate there).
    """
    init_db()
    now = dt.datetime.now(dt.timezone.utc)

    with get_session() as session:
        players_last_synced = get_last_synced(session, "players")
        rankings_synced = [get_last_synced(session, f"rankings:{p}") for p in SOURCE_PAGES]

    players_age = now - players_last_synced if players_last_synced else None
    rankings_age = None if None in rankings_synced else now - min(rankings_synced)
    players_stale = players_age is None or players_age >= dt.timedelta(hours=settings.players_cache_ttl_hours)
    rankings_stale = rankings_age is None or rankings_age >= dt.timedelta(hours=settings.rankings_cache_ttl_hours)

    players_count: int | None = None
    if players_stale:
        with SleeperClient(base_url=settings.sleeper_base_url) as client, get_session() as session:
            players_count = sync_players(session, client, force=False)

    # Each page is TTL-gated individually inside sync_rankings_all, so this
    # only re-scrapes the pages that are actually stale.
    rankings_results = sync_rankings_all(force=False) if rankings_stale else []

    return RefreshResult(
        players_refreshed=players_stale,
        players_age=players_age,
        players_synced_count=players_count,
        rankings_refreshed=rankings_stale,
        rankings_age=rankings_age,
        rankings_results=rankings_results,
    )
