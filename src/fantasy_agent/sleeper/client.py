"""Thin wrapper around Sleeper's public, unauthenticated REST API.

Docs: https://docs.sleeper.com/
"""

from __future__ import annotations

import time
from types import TracebackType

import httpx

from .schemas import Draft, DraftPick, League, Player, Roster, SleeperUser

DEFAULT_BASE_URL = "https://api.sleeper.app/v1"


class SleeperAPIError(RuntimeError):
    """Raised when Sleeper returns a non-2xx response or unparsable body."""


class SleeperClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._max_retries = max_retries

    def __enter__(self) -> "SleeperClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> object:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.get(path)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SleeperAPIError(
                            f"GET {path} returned non-JSON body: {exc}"
                        ) from exc
                if response.status_code == 404:
                    raise SleeperAPIError(f"GET {path} -> 404 (not found)")
                if response.status_code < 500:
                    raise SleeperAPIError(
                        f"GET {path} -> {response.status_code}: {response.text[:200]}"
                    )
                last_error = SleeperAPIError(
                    f"GET {path} -> {response.status_code}: {response.text[:200]}"
                )
            if attempt < self._max_retries:
                time.sleep(0.5 * attempt)  # small linear backoff for transient 5xx/timeouts
        raise SleeperAPIError(f"GET {path} failed after {self._max_retries} attempts") from last_error

    def get_league(self, league_id: str) -> League:
        return League.model_validate(self._get(f"/league/{league_id}"))

    def get_rosters(self, league_id: str) -> list[Roster]:
        data = self._get(f"/league/{league_id}/rosters")
        return [Roster.model_validate(r) for r in data]

    def get_users(self, league_id: str) -> list[SleeperUser]:
        data = self._get(f"/league/{league_id}/users")
        return [SleeperUser.model_validate(u) for u in data]

    def get_user(self, username_or_id: str) -> SleeperUser:
        """Resolve a Sleeper username (or user_id) to a user_id -- used by the
        setup wizard so a new user can type their username instead of hunting
        down their numeric user_id."""
        data = self._get(f"/user/{username_or_id}")
        if data is None:
            # Sleeper returns HTTP 200 with a JSON `null` body for an unknown
            # username -- not a 404 -- so this has to be checked explicitly.
            raise SleeperAPIError(f"No Sleeper user found for '{username_or_id}'")
        return SleeperUser.model_validate(data)

    def get_players(self) -> dict[str, Player]:
        """Full NFL player database. Several MB — cache locally, don't call per-request."""
        data = self._get("/players/nfl")
        return {player_id: Player.model_validate(p) for player_id, p in data.items()}

    def get_matchups(self, league_id: str, week: int) -> list[dict]:
        return self._get(f"/league/{league_id}/matchups/{week}")

    def get_league_drafts(self, league_id: str) -> list[Draft]:
        data = self._get(f"/league/{league_id}/drafts")
        return [Draft.model_validate(d) for d in data]

    def get_draft_picks(self, draft_id: str) -> list[DraftPick]:
        data = self._get(f"/draft/{draft_id}/picks")
        return [DraftPick.model_validate(p) for p in data]
