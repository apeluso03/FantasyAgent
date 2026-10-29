"""Typed views over Sleeper API responses.

Sleeper's API is undocumented-by-contract and adds fields over time, so every
model allows extras rather than rejecting unknown keys — we only pull out the
fields the agent actually needs.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _none_to_empty_list(value: object) -> object:
    # Sleeper sends JSON null (not []) for empty roster slots like reserve/taxi.
    return [] if value is None else value


def _none_to_empty_dict(value: object) -> object:
    # The single-user lookup endpoint (/user/{username}) sends metadata: null,
    # unlike the league-members endpoint which always has a metadata object.
    return {} if value is None else value


class League(BaseModel):
    model_config = ConfigDict(extra="allow")

    league_id: str
    name: str
    season: str
    sport: str = "nfl"
    status: str | None = None
    total_rosters: int
    roster_positions: list[str] = Field(default_factory=list)
    scoring_settings: dict = Field(default_factory=dict)
    # Contains keeper/waiver/playoff rules, e.g. settings["keeper_count"], "round penalty" is
    # league-specific and usually encoded in league metadata or roster settings, not a fixed key.
    settings: dict = Field(default_factory=dict)
    previous_league_id: str | None = None


class SleeperUser(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    display_name: str | None = None
    metadata: dict = Field(default_factory=dict)

    _coerce_metadata = field_validator("metadata", mode="before")(_none_to_empty_dict)

    @property
    def team_name(self) -> str:
        return self.metadata.get("team_name") or self.display_name or self.user_id


class Roster(BaseModel):
    model_config = ConfigDict(extra="allow")

    roster_id: int
    league_id: str | None = None
    owner_id: str | None = None
    players: list[str] = Field(default_factory=list)
    starters: list[str] = Field(default_factory=list)
    reserve: list[str] = Field(default_factory=list)
    taxi: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)

    _coerce_lists = field_validator("players", "starters", "reserve", "taxi", mode="before")(
        _none_to_empty_list
    )


class Draft(BaseModel):
    model_config = ConfigDict(extra="allow")

    draft_id: str
    league_id: str | None = None
    season: str | None = None
    status: str | None = None  # "pre_draft" | "drafting" | "complete"
    type: str | None = None
    settings: dict = Field(default_factory=dict)

    @property
    def rounds(self) -> int | None:
        return self.settings.get("rounds")


class DraftPick(BaseModel):
    model_config = ConfigDict(extra="allow")

    draft_id: str
    player_id: str
    round: int
    pick_no: int
    roster_id: int | None = None
    is_keeper: bool | None = None


class NFLState(BaseModel):
    """Current point in the NFL calendar (/state/nfl) -- tells us which week's
    stats are the most recent completed ones, and what to fall back to during
    the offseason/preseason when the current season has no games yet."""

    model_config = ConfigDict(extra="allow")

    week: int
    season: str
    season_type: str = "regular"  # "pre" | "regular" | "post"
    previous_season: str | None = None


class Player(BaseModel):
    model_config = ConfigDict(extra="allow")

    player_id: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    team: str | None = None
    position: str | None = None
    fantasy_positions: list[str] = Field(default_factory=list)
    status: str | None = None
    age: int | None = None
    years_exp: int | None = None
    active: bool | None = None
    # Distinct from `status` above (Active/Inactive/...) -- these describe a
    # specific injury designation. See trade.py's INJURY_VALUE_MULTIPLIERS for
    # the real-world values observed (Questionable, Doubtful, Out, IR, PUP,
    # Sus, NA, plus rare ones like COV/DNR).
    injury_status: str | None = None
    injury_body_part: str | None = None
    injury_notes: str | None = None
    injury_start_date: str | None = None

    _coerce_positions = field_validator("fantasy_positions", mode="before")(_none_to_empty_list)

    @model_validator(mode="after")
    def _fill_full_name(self) -> "Player":
        # Sleeper omits full_name for many entries (esp. team defenses); derive it
        # so downstream name-matching (FantasyPros join) always has something to work with.
        if not self.full_name:
            parts = [p for p in (self.first_name, self.last_name) if p]
            if parts:
                self.full_name = " ".join(parts)
        return self
