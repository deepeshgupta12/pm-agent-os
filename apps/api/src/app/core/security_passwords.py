from __future__ import annotations

import bcrypt


def _ensure_bcrypt_limit(password: str) -> bytes:
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