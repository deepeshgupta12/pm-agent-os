from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import RegisterIn, LoginIn, UserOut
from app.core.security import (
    create_access_token,
    ACCESS_COOKIE_NAME,
    ACCESS_COOKIE_PATH,
    ACCESS_COOKIE_HTTPONLY,
    get_current_user_from_cookie,
)
from app.core.refresh_tokens import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_COOKIE_HTTPONLY,
    generate_refresh_token,
    store_refresh_token,
    rotate_refresh_token,
    revoke_refresh_token,
)
from app.core.config import settings
from app.core.security_passwords import hash_password, verify_password  # NEW file below

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=ACCESS_COOKIE_HTTPONLY,
        secure=bool(settings.COOKIE_SECURE),
        samesite=settings.COOKIE_SAMESITE,
        path=ACCESS_COOKIE_PATH,
        max_age=settings.ACCESS_EXPIRES_MINUTES * 60,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=REFRESH_COOKIE_HTTPONLY,
        secure=bool(settings.COOKIE_SECURE),
        samesite=settings.COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_EXPIRES_DAYS * 24 * 60 * 60,
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(key=ACCESS_COOKIE_NAME, path=ACCESS_COOKIE_PATH)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.post("/register", response_model=UserOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserOut(id=str(user.id), email=user.email)


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user_id=user.id, email=user.email)
    refresh_token = generate_refresh_token()

    store_refresh_token(db, user_id=user.id, token=refresh_token)

    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)

    return UserOut(id=str(user.id), email=user.email)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Rotate refresh token and mint a new access token.
    """
    old_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not old_refresh:
        raise HTTPException(status_code=401, detail="No refresh token")

    user_id, new_refresh = rotate_refresh_token(db, old_refresh)
    if not user_id or not new_refresh:
        _clear_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, user_id)
    if not user:
        _clear_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access_token = create_access_token(user_id=user.id, email=user.email)

    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, new_refresh)

    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        revoke_refresh_token(db, refresh_token)

    _clear_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserOut(id=str(user.id), email=user.email)