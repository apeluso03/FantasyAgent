"""Pydantic response models mirroring the domain layer's dataclasses.

The domain layer (fantasy_agent) never imports FastAPI or Pydantic -- these
models live here in the backend so that separation holds, per CLAUDE.md
section 5.5. `from_attributes=True` lets model_validate() read straight off
the dataclass/ORM instances the pipelines already return.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class HealthOut(BaseModel):
    status: str
    version: str


class LeagueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    league_id: str
    name: str
    season: str
    total_rosters: int
    roster_positions: list[str]
    scoring_settings: dict
    settings: dict


class TeamOut(BaseModel):
    owner_user_id: str
    team_name: str
    roster_id: int


class RosterPlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: str
    name: str
    position: str | None
    team: str | None
    rank_ecr: int | None
    pos_rank: str | None
    group: str
    slot: str | None = None


class MyRosterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_name: str
    owner_user_id: str
    players: list[RosterPlayerOut]


class InjuryNoteOut(BaseModel):
    """Mirrors trade.InjuryNote -- shared by power rankings and trade results
    so an injured/unavailable player's status, value multiplier, and a short
    human-readable reason show up the same way in both."""

    model_config = ConfigDict(from_attributes=True)

    player_id: str
    name: str
    injury_status: str
    multiplier: float
    reason: str


class StarterSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot: str
    player_id: str | None
    name: str | None
    position: str | None
    rank_ecr: int | None
    value: float
    injury_status: str | None = None


class TeamPowerRankingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    team_name: str
    owner_user_id: str
    starting_lineup_value: float
    average_starter_rank: float | None
    starters: list[StarterSlotOut]
    positional_value: dict[str, float]
    positional_rank: dict[str, int]
    injured_players: list[InjuryNoteOut] = Field(default_factory=list)


class KeeperCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class RankingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank_ecr: int
    name: str
    position: str
    team: str | None
    pos_rank: str | None
    sleeper_player_id: str | None


class PlayerSearchResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: str
    full_name: str | None
    position: str | None
    team: str | None


class SyncStatusEntryOut(BaseModel):
    resource: str
    last_synced_at: str


class BestAvailablePlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: str
    name: str
    position: str
    team: str | None
    rank_ecr: int
    pos_rank: str | None
    reasoning: str


class GameLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: int
    points_ppr: float | None
    stat_line: str


class PlayerAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: str
    season: str
    games: list[GameLineOut]
    avg_points: float | None
    blurb: str


class TradeEvaluateIn(BaseModel):
    side_a_owner: str
    side_a_gives: list[str]
    side_b_owner: str
    side_b_gives: list[str]
    league_id: str | None = None


class TradeSideResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner_user_id: str
    team_name: str
    gives: list[str]
    receives: list[str]
    value_given: float
    value_received: float
    net_value: float
    position_counts_before: dict[str, int]
    position_counts_after: dict[str, int]
    reasoning: str
    injured_players_given: list[InjuryNoteOut] = Field(default_factory=list)
    injured_players_received: list[InjuryNoteOut] = Field(default_factory=list)


class TradeEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    side_a: TradeSideResultOut
    side_b: TradeSideResultOut
    verdict: str


class SyncRequestIn(BaseModel):
    force_players: bool = False
    league_id: str | None = None


class RankingsSyncRequestIn(BaseModel):
    force: bool = False
    page: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    error: str | None = None


class AgentHistoryTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentAskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    history: list[AgentHistoryTurnIn] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _cap_history(cls, value: list[AgentHistoryTurnIn]) -> list[AgentHistoryTurnIn]:
        # Keep only the last 10 turns -- the server stays stateless, so a long
        # client-side chat history shouldn't balloon every request indefinitely.
        return value[-10:]


class AgentStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool_name: str
    arguments: dict
    output_preview: str
    error: bool


class AgentUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    input_tokens: int
    cached_tokens: int
    output_tokens: int


class AgentResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    steps: list[AgentStepOut]
    usage: AgentUsageOut


class SignupIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address.")
        return value.strip().lower()


class LoginIn(BaseModel):
    email: str
    password: str


class AccountUpdateIn(BaseModel):
    default_league_id: str | None = None
    default_owner_user_id: str | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    default_league_id: str | None
    default_owner_user_id: str | None


class AuthResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    account: AccountOut
