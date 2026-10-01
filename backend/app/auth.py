"""Password hashing + session token helpers backing the account system
(routers/auth.py). Web-only concern -- the domain layer never imports this
or bcrypt."""

from __future__ import annotations

import datetime as dt
import secrets

import bcrypt
from fantasy_agent.db.models import AccountRecord, SessionRecord
from sqlalchemy.orm import Session

SESSION_TTL = dt.timedelta(days=30)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session(db: Session, account: AccountRecord) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        SessionRecord(
            token=token,
            account_id=account.id,
            expires_at=dt.datetime.now(dt.timezone.utc) + SESSION_TTL,
        )
    )
    db.flush()
    return token


def get_account_for_token(db: Session, token: str) -> AccountRecord | None:
    session_record = db.get(SessionRecord, token)
    if session_record is None:
        return None

    expires_at = session_record.expires_at
    # SQLite doesn't persist tzinfo, so timestamps come back naive.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
    if expires_at < dt.datetime.now(dt.timezone.utc):
        return None

    return db.get(AccountRecord, session_record.account_id)
