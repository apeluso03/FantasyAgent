import httpx
import pytest

from fantasy_agent import player_images
from fantasy_agent.config import settings


@pytest.fixture(autouse=True)
def _isolated_db_url(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{(tmp_path / 'data' / 'fantasy_agent.db').as_posix()}")
    yield tmp_path


def test_downloads_and_caches_image(monkeypatch, tmp_path):
    calls = []

    def fake_get(url, timeout=5.0, follow_redirects=True):
        calls.append(url)
        return httpx.Response(200, content=b"fake-jpg-bytes", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    path = player_images.get_player_image_path("1234")
    assert path is not None
    assert path.read_bytes() == b"fake-jpg-bytes"

    # Second call must not hit the network again.
    path2 = player_images.get_player_image_path("1234")
    assert path2 == path
    assert len(calls) == 1


def test_missing_photo_is_negative_cached(monkeypatch):
    calls = []

    def fake_get(url, timeout=5.0, follow_redirects=True):
        calls.append(url)
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    assert player_images.get_player_image_path("nope") is None
    assert player_images.get_player_image_path("nope") is None
    assert len(calls) == 1  # second call hit the negative-cache marker, not the network
