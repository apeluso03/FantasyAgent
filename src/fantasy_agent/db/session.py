from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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


def _add_missing_columns(engine: Engine) -> None:
    """`create_all()` only creates tables that don't exist yet -- it never
    alters a table that's already there, so an existing data/fantasy_agent.db
    file silently stays on its old schema forever when a new nullable column
    (e.g. PlayerRecord.injury_status) is added to a model. A full migration
    tool (Alembic) is overkill for a local-cache SQLite file (see CLAUDE.md
    section 7.2) -- every column this project has added has been nullable
    with no default, which ADD COLUMN handles safely on both SQLite and
    Postgres, so a small startup check covers it instead.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table -- create_all() above already built it with every column
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}"))


def init_db() -> None:
    _get_session_factory()  # ensures _engine is built
    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)


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
