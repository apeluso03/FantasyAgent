from pydantic import BaseModel, ConfigDict, Field


class RankedPlayer(BaseModel):
    """One player entry from FantasyPros' embedded `ecrData` JSON blob."""

    model_config = ConfigDict(extra="allow")

    fp_player_id: int = Field(alias="player_id")
    name: str = Field(alias="player_name")
    team: str | None = Field(default=None, alias="player_team_id")
    position: str = Field(alias="player_position_id")
    bye_week: str | None = Field(default=None, alias="player_bye_week")
    rank_ecr: int
    pos_rank: str | None = None
    tier: int | None = None
