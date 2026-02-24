from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import RefreshToken


REFRESH_COOKIE_NAME = "pm_agent_os_refresh"
REFRESH_COOKIE_PATH = "/"
REFRESH_COOKIE_HTTPONLY = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_dt() -> datetime:
    return _now() + timedelta(days=settings.REFRESH_EXPIRES_DAYS)


def generate_refresh_token() -> str:
    # opaque token, not JWT
    raw = os.urandom(48)
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def hash_refresh_token(token: str) -> str:
    # HMAC with JWT_SECRET to avoid raw token storage
    key = settings.JWT_SECRET.encode("utf-8")
    msg = token.encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return digest


def store_refresh_token(db: Session, *, user_id: uuid.UUID, token: str) -> RefreshToken:
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        expires_at=_expiry_dt(),
        revoked_at=None,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return rt


def revoke_refresh_token(db: Session, token: str) -> None:
    h = hash_refresh_token(token)
    rt = db.execute(select(RefreshToken).where(RefreshToken.token_hash == h)).scalar_one_or_none()
    if not rt:
        return
    rt.revoked_at = _now()
    db.add(rt)
    db.commit()


def validate_refresh_token(db: Session, token: str) -> Optional[RefreshToken]:
    h = hash_refresh_token(token)
    rt = db.execute(select(RefreshToken).where(RefreshToken.token_hash == h)).scalar_one_or_none()
    if not rt:
        return None
    if rt.revoked_at is not None:
        return None
    if rt.expires_at <= _now():
        return None
    return rt


def rotate_refresh_token(db: Session, old_token: str) -> Tuple[Optional[uuid.UUID], Optional[str]]:
    """
    Validates old token, revokes it, issues a new token and stores it.
    Returns (user_id, new_token) or (None, None)
    """
    existing = validate_refresh_token(db, old_token)
    if not existing:
        return None, None

    user_id = existing.user_id

    # revoke old
    existing.revoked_at = _now()
    db.add(existing)
    db.commit()

    # issue new
    new_token = generate_refresh_token()
    store_refresh_token(db, user_id=user_id, token=new_token)
    return user_id, new_token