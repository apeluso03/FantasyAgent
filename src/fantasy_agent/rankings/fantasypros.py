"""Fetches FantasyPros consensus rankings.

FantasyPros' rankings pages embed the full player dataset as a JS variable
(`var ecrData = {...}`) rather than rendering it into DOM table markup, so a
plain HTTP GET + JSON extraction is sufficient — no headless browser needed.
robots.txt disallows `/nfl/ranker/` (the interactive tool) but not
`/nfl/rankings/` pages, and asks for a 5s crawl-delay between requests, which
matters once we're pulling more than one page per run.
"""

from __future__ import annotations

import json

import httpx

from ..config import settings
from .schemas import RankedPlayer

_ECR_DATA_MARKER = "var ecrData"


class FantasyProsScrapeError(RuntimeError):
    """Raised when the rankings page can't be fetched or its embedded data can't be parsed."""


def _extract_balanced_json(text: str, marker: str) -> str:
    """Pull out the `{...}` object assigned right after `marker`, tracking brace
    depth (and skipping braces inside quoted strings) so we get exactly the
    top-level object regardless of what it contains.
    """
    try:
        marker_pos = text.index(marker)
        start = text.index("{", marker_pos)
    except ValueError as exc:
        raise FantasyProsScrapeError(
            f"Could not find '{marker}' on the page — FantasyPros may have changed their markup."
        ) from exc

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise FantasyProsScrapeError(f"Unbalanced braces reading '{marker}' object")


class FantasyProsClient:
    def __init__(
        self,
        base_url: str | None = None,
        user_agent: str | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.fantasypros_base_url).rstrip("/")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent or settings.fantasypros_user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> "FantasyProsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_rankings(self, page: str) -> list[RankedPlayer]:
        """Fetch a rankings page (e.g. "dynasty-superflex") and parse the
        players out of its embedded ecrData JSON."""
        url = f"{self._base_url}/{page}.php"
        response = self._client.get(url)
        if response.status_code != 200:
            raise FantasyProsScrapeError(f"GET {url} -> {response.status_code}")
        # FantasyPros redirects an unknown slug to its redraft cheat sheet
        # (consensus-cheatsheets.php), which parses fine -- so without this the
        # wrong rankings get stored under the requested page's name, silently.
        # This happened: "dynasty-superflex-overall" was never a real page.
        landed_on = response.url.path.rsplit("/", 1)[-1]
        if landed_on != f"{page}.php":
            raise FantasyProsScrapeError(
                f"GET {url} redirected to {response.url} -- '{page}' isn't a FantasyPros rankings page"
            )

        raw_json = _extract_balanced_json(response.text, _ECR_DATA_MARKER)
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise FantasyProsScrapeError(f"ecrData on {url} was not valid JSON: {exc}") from exc

        raw_players = data.get("players")
        if not isinstance(raw_players, list):
            raise FantasyProsScrapeError(f"ecrData on {url} had no 'players' list")

        return [RankedPlayer.model_validate(p) for p in raw_players]
