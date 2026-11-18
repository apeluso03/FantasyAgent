"""Persisting and refreshing the mock draft ADP board."""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import MockAdpRecord, RankingRecord, SyncMeta
from ..rankings.fantasypros import FantasyProsClient, FantasyProsScrapeError
from ..rankings.schemas import RankedPlayer
from ..sleeper.client import SleeperAPIError, SleeperClient
from .adp import BoardPlayer, build_board, fetch_sleeper_projections, load_rookie_seed

log = logging.getLogger(__name__)

RESOURCE = "mock_adp"
FP_DYNASTY_SF_PAGE = "dynasty-superflex"


@dataclass
class BoardRefreshResult:
    players: int
    rookies: int
    adp_season: str
    sources: dict[str, int]
    warnings: list[str]


def _current_season(client: SleeperClient) -> str:
    try:
        return str(client.get_nfl_state().season)
    except (SleeperAPIError, AttributeError):
        return str(dt.date.today().year)


def _fp_dynasty_from_cache(session: Session) -> list[RankedPlayer]:
    rows = session.query(RankingRecord).filter_by(source="fantasypros", page=FP_DYNASTY_SF_PAGE).all()
    return [
        RankedPlayer.model_validate(
            {
                "player_id": r.fp_player_id,
                "player_name": r.name,
                "player_team_id": r.team,
                "player_position_id": r.position,
                "rank_ecr": r.rank_ecr,
                "pos_rank": r.pos_rank,
            }
        )
        for r in rows
    ]


def refresh_board(
    session: Session,
    *,
    adp_season: str | None = None,
    sleeper_transport: httpx.BaseTransport | None = None,
    fantasypros: FantasyProsClient | None = None,
    rookie_seed: Path | None = None,
) -> BoardRefreshResult:
    """Rebuild the board from live sources. Each source degrades on its own:
    FantasyPros falls back to the rankings cache, and a season with no
    Sleeper ADP yet falls back to the previous season."""
    warnings: list[str] = []

    if adp_season is None:
        with SleeperClient(base_url=settings.sleeper_base_url, transport=sleeper_transport) as client:
            adp_season = _current_season(client)

    rows = fetch_sleeper_projections(adp_season, transport=sleeper_transport)
    has_adp = any((r.get("stats") or {}).get("adp_2qb", 999) < 999 for r in rows)
    if not has_adp:
        fallback = str(int(adp_season) - 1)
        warnings.append(f"Sleeper has no {adp_season} ADP yet; used {fallback}.")
        adp_season = fallback
        rows = fetch_sleeper_projections(adp_season, transport=sleeper_transport)

    owns_fp = fantasypros is None
    fp_client = fantasypros or FantasyProsClient()
    try:
        fp_players = fp_client.fetch_rankings(FP_DYNASTY_SF_PAGE)
    except (FantasyProsScrapeError, httpx.HTTPError) as exc:
        fp_players = _fp_dynasty_from_cache(session)
        warnings.append(f"FantasyPros fetch failed ({exc}); used {len(fp_players)} cached rankings.")
    finally:
        if owns_fp:
            fp_client.close()

    rookies = load_rookie_seed(rookie_seed)
    board = build_board(rows, fp_players, rookies)
    if not board:
        raise RuntimeError("ADP sources returned no players -- board not replaced.")

    now = dt.datetime.now(dt.timezone.utc)
    session.query(MockAdpRecord).delete()
    session.add_all(
        MockAdpRecord(
            player_id=b.player_id,
            name=b.name,
            position=b.position,
            team=b.team,
            adp_2027=b.adp_2027,
            adp_dynasty=b.adp_dynasty,
            adp_redraft=b.adp_redraft,
            is_rookie=b.is_rookie,
            college=b.college,
            years_exp=b.years_exp,
            sources=b.sources,
            built_at=now,
        )
        for b in board
    )
    meta = session.get(SyncMeta, RESOURCE)
    if meta is None:
        session.add(SyncMeta(resource=RESOURCE, last_synced_at=now))
    else:
        meta.last_synced_at = now
    session.flush()

    source_counts: dict[str, int] = {}
    for b in board:
        for s in b.sources:
            source_counts[s] = source_counts.get(s, 0) + 1
    for w in warnings:
        log.warning(w)
    return BoardRefreshResult(
        players=len(board),
        rookies=sum(1 for b in board if b.is_rookie),
        adp_season=adp_season,
        sources=source_counts,
        warnings=warnings,
    )


_ensure_lock = threading.Lock()


def ensure_board(
    session_scope: Callable[[], AbstractContextManager[Session]],
    *,
    max_age_hours: float | None = None,
) -> BoardRefreshResult | None:
    """Build the board if it's missing (or older than `max_age_hours`), in
    its own committed transaction, one build at a time per process.

    Callers must not do this inside a request's own session: the rebuild
    deletes and rewrites every row, and holding that open while the same
    request writes elsewhere deadlocks SQLite. The lock also stops the
    startup refresh and the first draft creation on a fresh database from
    both building at once -- whoever gets second finds the board ready.
    """
    with _ensure_lock:
        with session_scope() as session:
            built = board_built_at(session)
            if built is not None and built.tzinfo is None:
                built = built.replace(tzinfo=dt.timezone.utc)  # SQLite drops tzinfo
            has_rows = session.query(MockAdpRecord.player_id).first() is not None
            fresh = has_rows and built is not None and (
                max_age_hours is None
                or dt.datetime.now(dt.timezone.utc) - built <= dt.timedelta(hours=max_age_hours)
            )
            if fresh:
                return None
            return refresh_board(session)


def load_board(session: Session) -> list[BoardPlayer]:
    return [
        BoardPlayer(
            player_id=r.player_id,
            name=r.name,
            position=r.position,
            team=r.team,
            adp_2027=r.adp_2027,
            adp_dynasty=r.adp_dynasty,
            adp_redraft=r.adp_redraft,
            is_rookie=bool(r.is_rookie),
            college=r.college,
            years_exp=r.years_exp,
            sources=list(r.sources or []),
        )
        for r in session.query(MockAdpRecord).order_by(MockAdpRecord.adp_2027).all()
    ]


def board_built_at(session: Session) -> dt.datetime | None:
    meta = session.get(SyncMeta, RESOURCE)
    return meta.last_synced_at if meta else None
