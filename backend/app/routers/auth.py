from fantasy_agent.db.models import AccountRecord, SessionRecord
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..auth import create_session, hash_password, verify_password
from ..deps import get_current_account, get_db
from ..schemas import AccountOut, AccountUpdateIn, AuthResponseOut, LoginIn, SignupIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponseOut, status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    existing = db.query(AccountRecord).filter_by(email=body.email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    account = AccountRecord(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(account)
    db.flush()
    token = create_session(db, account)
    return {"token": token, "account": account}


@router.post("/login", response_model=AuthResponseOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    account = db.query(AccountRecord).filter_by(email=body.email.strip().lower()).one_or_none()
    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = create_session(db, account)
    return {"token": token, "account": account}


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        session_record = db.get(SessionRecord, token)
        if session_record is not None:
            db.delete(session_record)


@router.get("/me", response_model=AccountOut)
def me(account: AccountRecord = Depends(get_current_account)):
    return account


@router.patch("/me", response_model=AccountOut)
def update_me(
    body: AccountUpdateIn,
    account: AccountRecord = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    account.default_league_id = body.default_league_id
    account.default_owner_user_id = body.default_owner_user_id
    db.add(account)
    return account
