from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user_from_cookie
from app.db.models import User


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user