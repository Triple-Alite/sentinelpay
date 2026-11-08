from datetime import UTC, datetime, timedelta
import hashlib
import uuid

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(password, stored_hash)
    except (ValueError, TypeError):
        return False


def hash_token_id(token_id: str) -> str:
    return hashlib.sha256(token_id.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def create_token(*, subject: uuid.UUID, session_id: uuid.UUID, token_type: str, expires_delta: timedelta) -> tuple[str, str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    token_id = uuid.uuid4().hex
    secret = settings.jwt_refresh_secret if token_type == "refresh" else settings.jwt_secret
    token = jwt.encode(
        {
            "sub": str(subject),
            "sid": str(session_id),
            "jti": token_id,
            "typ": token_type,
            "iat": now,
            "exp": expires_at,
        },
        secret,
        algorithm="HS256",
    )
    return token, token_id, expires_at


def decode_token(token: str, token_type: str) -> dict:
    settings = get_settings()
    secret = settings.jwt_refresh_secret if token_type == "refresh" else settings.jwt_secret
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "sid", "jti", "typ", "exp"]})
    if claims.get("typ") != token_type:
        raise jwt.InvalidTokenError("Wrong token type")
    return claims