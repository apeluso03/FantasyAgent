"""Local cache of Sleeper data.

We cache rather than hitting Sleeper on every question: league/roster data
changes rarely, and players/nfl is a multi-MB dump Sleeper asks callers not
to poll frequently (see sync.sync_players for the TTL gate).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class LeagueRecord(Base):
    __tablename__ = "leagues"

    league_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    season: Mapped[str] = mapped_column(String)
    total_rosters: Mapped[int] = mapped_column(Integer)
    roster_positions: Mapped[list] = mapped_column(JSON, default=list)
    scoring_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    rosters: Mapped[list["RosterRecord"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )
    users: Mapped[list["UserRecord"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )


class UserRecord(Base):
    __tablename__ = "league_users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.league_id"))
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    team_name: Mapped[str | None] = mapped_column(String, nullable=True)

    league: Mapped["LeagueRecord"] = relationship(back_populates="users")


class RosterRecord(Base):
    __tablename__ = "rosters"
    __table_args__ = (UniqueConstraint("league_id", "roster_id", name="uq_roster_league_rosterid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.league_id"))
    # roster_id is only unique within a league, so the surrogate `id` above is the PK
    # and (league_id, roster_id) is the natural unique key.
    roster_id: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    players: Mapped[list] = mapped_column(JSON, default=list)
    starters: Mapped[list] = mapped_column(JSON, default=list)
    reserve: Mapped[list] = mapped_column(JSON, default=list)
    taxi: Mapped[list] = mapped_column(JSON, default=list)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    league: Mapped["LeagueRecord"] = relationship(back_populates="rosters")


class PlayerRecord(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    fantasy_positions: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool | None] = mapped_column(nullable=True)


class SyncMeta(Base):
    """Last-sync timestamp per resource — governs cache freshness (mainly for players/nfl)."""

    __tablename__ = "sync_meta"

    resource: Mapped[str] = mapped_column(String, primary_key=True)
    last_synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class RankingRecord(Base):
    """A cached FantasyPros ranking entry, joined to a Sleeper player where matched.

    We never scrape on-demand mid-conversation — the agent only reads from this
    cache, which sync.sync_rankings refreshes on a schedule (see rankings_cache_ttl_hours).
    """

    __tablename__ = "rankings"
    __table_args__ = (UniqueConstraint("source", "page", "fp_player_id", name="uq_ranking_source_page_player"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, default="fantasypros")
    page: Mapped[str] = mapped_column(String)
    fp_player_id: Mapped[int] = mapped_column(Integer)
    sleeper_player_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str] = mapped_column(String)
    rank_ecr: Mapped[int] = mapped_column(Integer)
    pos_rank: Mapped[str | None] = mapped_column(String, nullable=True)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_method: Mapped[str] = mapped_column(String, default="unmatched")
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DraftPickRecord(Base):
    """Which round each currently-rostered player was drafted in, used as the cost
    basis for keeper decisions.

    Sleeper doesn't track "round drafted" as a per-roster field — it only lives in
    the (season-specific) draft's pick list. A keeper league's current-season draft
    is often still pre_draft when you're making keeper decisions, so this is sourced
    from the most recent *completed* draft in the league's previous_league_id chain
    (see sync.sync_draft_history), not necessarily the current league_id's own draft.
    """

    __tablename__ = "draft_picks"

    league_id: Mapped[str] = mapped_column(String, ForeignKey("leagues.league_id"), primary_key=True)
    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_draft_id: Mapped[str] = mapped_column(String)
    source_season: Mapped[str | None] = mapped_column(String, nullable=True)
    round: Mapped[int] = mapped_column(Integer)
    pick_no: Mapped[int] = mapped_column(Integer)
    roster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PlayerAlias(Base):
    """Manual override for FantasyPros -> Sleeper player-ID matches that automatic
    matching gets wrong or can't resolve. Always takes priority over automatic matching.
    """

    __tablename__ = "player_aliases"

    fp_player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sleeper_player_id: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
