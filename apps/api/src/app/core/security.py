from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Request
from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User

ACCESS_COOKIE_NAME = "pm_agent_os_access"
ACCESS_COOKIE_PATH = "/"
ACCESS_COOKIE_HTTPONLY = True


def create_access_token(*, user_id: uuid.UUID, email: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.ACCESS_EXPIRES_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_access_token(token: str) -> Dict[str, Any]:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    if payload.get("type") != "access":
        raise ValueError("Not an access token")
    return payload


def get_access_token_from_request(request: Request) -> Optional[str]:
    return request.cookies.get(ACCESS_COOKIE_NAME)


def get_current_user_from_cookie(db: Session, request: Request) -> Optional[User]:
    token = get_access_token_from_request(request)
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