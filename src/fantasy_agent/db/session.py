from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base


def _ensure_sqlite_dir(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)


# Lazily built on first use (not at import time) so `settings.database_url` can be
# reconfigured at runtime before the first call -- the user-edition GUI points
# this at a per-user AppData path chosen during its setup wizard, which happens
# after this module is already imported.
_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _get_session_factory() -> sessionmaker:
    global _engine, _session_factory
    if _session_factory is None:
        _ensure_sqlite_dir(settings.database_url)
        # FastAPI runs sync routes in a worker thread pool, and SQLite's default
        # same-thread check would reject a connection used from a different
        # thread than the one that created it -- harmless for the CLI/GUI,
        # which are single-threaded, but required once the web backend is in
        # the picture (see CLAUDE.md section 5.2).
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _session_factory


def reset_engine() -> None:
    """Drop the cached engine/session factory so the next get_session()/
    init_db() call rebuilds against whatever settings.database_url is *now*
    (not whatever it was the first time the DB was touched).

    Needed for switching between per-profile databases at runtime (see
    profiles.py): _get_session_factory() caches its engine forever once
    built, so without this, changing settings.database_url after the app has
    already opened one profile's DB would be silently ignored -- every query
    would keep hitting the first profile's file no matter what the settings
    object says.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db() -> None:
    _get_session_factory()  # ensures _engine is built
    Base.metadata.create_all(_engine)


@contextmanager
def get_session() -> Iterator[Session]:
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
