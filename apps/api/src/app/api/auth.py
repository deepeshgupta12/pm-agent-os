from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import RegisterIn, LoginIn, UserOut
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    ACCESS_COOKIE_NAME,
    ACCESS_COOKIE_PATH,
    ACCESS_COOKIE_HTTPONLY,
    get_current_user_from_cookie,
)
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


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

    token = create_access_token(user_id=user.id, email=user.email)

    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=ACCESS_COOKIE_HTTPONLY,
        secure=bool(settings.COOKIE_SECURE),
        samesite=settings.COOKIE_SAMESITE,  # "lax" for local
        path=ACCESS_COOKIE_PATH,
        max_age=settings.JWT_EXPIRES_MINUTES * 60,
    )

    return UserOut(id=str(user.id), email=user.email)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path=ACCESS_COOKIE_PATH,
    )
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserOut(id=str(user.id), email=user.email)