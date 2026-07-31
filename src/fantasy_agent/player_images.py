"""Player headshot fetching/caching, sourced from Sleeper's public media CDN.

Sleeper doesn't require auth for these -- same as the rest of its API -- but
does ask that clients not hammer it, so every image is cached to disk
permanently after the first fetch (headshots don't change). A "no photo"
result (kickers/DEF/some rookies, or a network hiccup) is negative-cached too
via an empty `.missing` marker, so a player without a photo doesn't get
re-requested on every roster-tab open.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .config import settings

_THUMB_URL = "https://sleepercdn.com/content/nfl/players/thumb/{player_id}.jpg"


def image_cache_dir() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        base = Path(url.removeprefix("sqlite:///")).parent
    else:
        base = Path("data")
    cache_dir = base / "player_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_player_image_path(player_id: str) -> Path | None:
    """Return a local cached path to this player's headshot, downloading it on
    first use. Returns None (never raises) if Sleeper has no photo for this
    player or the request fails -- callers should fall back to a placeholder.
    """
    cache_dir = image_cache_dir()
    image_path = cache_dir / f"{player_id}.jpg"
    if image_path.exists():
        return image_path

    marker_path = cache_dir / f"{player_id}.missing"
    if marker_path.exists():
        return None

    try:
        response = httpx.get(_THUMB_URL.format(player_id=player_id), timeout=5.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        marker_path.touch()
        return None

    image_path.write_bytes(response.content)
    return image_path
