import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuthSession, User
from app.security import decode_token, is_expired

ACCESS_COOKIE = "sentinelpay_access"
REFRESH_COOKIE = "sentinelpay_refresh"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        claims = decode_token(token, "access")
        user_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["sid"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session") from None

    auth_session = await db.get(AuthSession, session_id)
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or is_expired(auth_session.expires_at)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired or been revoked")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user