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
        _engine = create_engine(settings.database_url, future=True)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _session_factory


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
