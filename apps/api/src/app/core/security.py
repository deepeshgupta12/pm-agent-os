from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from fastapi import Request
from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User

ACCESS_COOKIE_NAME = "pm_agent_os_access"
ACCESS_COOKIE_PATH = "/"
ACCESS_COOKIE_HTTPONLY = True


def _ensure_bcrypt_limit(password: str) -> bytes:
    """
    bcrypt only uses the first 72 bytes of the password. To avoid silent truncation,
    we reject passwords that exceed 72 bytes when UTF-8 encoded.
    """
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        raise ValueError("Password too long for bcrypt (max 72 bytes)")
    return pw_bytes


def hash_password(password: str) -> str:
    pw_bytes = _ensure_bcrypt_limit(password)
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pw_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw_bytes = _ensure_bcrypt_limit(password)
    except ValueError:
        return False
    return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))


def create_access_token(*, user_id: uuid.UUID, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.JWT_EXPIRES_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])


def get_token_from_request(request: Request) -> Optional[str]:
    return request.cookies.get(ACCESS_COOKIE_NAME)


def get_current_user_from_cookie(db: Session, request: Request) -> Optional[User]:
    token = get_token_from_request(request)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        return db.get(User, uuid.UUID(user_id))
    except Exception:
        return None