from datetime import UTC, datetime, timedelta
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.dependencies import ACCESS_COOKIE, REFRESH_COOKIE, get_current_user
from app.models import AuthSession, Merchant, MerchantSettings, User
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.security import create_token, decode_token, hash_password, hash_token_id, is_expired, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    secure = settings.app_env.lower() == "production"
    same_site = "none" if secure else "lax"
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/api/v1/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    secure = settings.app_env.lower() == "production"
    same_site = "none" if secure else "lax"
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure, httponly=True, samesite=same_site)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth", secure=secure, httponly=True, samesite=same_site)


async def create_auth_session(db: AsyncSession, user_id: uuid.UUID) -> tuple[str, str, uuid.UUID]:
    settings = get_settings()
    session_id = uuid.uuid4()
    access_token, _, _ = create_token(
        subject=user_id,
        session_id=session_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_minutes),
    )
    refresh_token, refresh_jti, refresh_expiry = create_token(
        subject=user_id,
        session_id=session_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_days),
    )
    db.add(
        AuthSession(
            id=session_id,
            user_id=user_id,
            refresh_jti_hash=hash_token_id(refresh_jti),
            expires_at=refresh_expiry,
        )
    )
    return access_token, refresh_token, session_id


def auth_response(user: User, merchant: Merchant) -> AuthResponse:
    return AuthResponse(user=UserResponse.model_validate(user), merchant=merchant)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    normalized_email = str(body.email).strip().lower()
    if await db.scalar(select(User.id).where(User.email == normalized_email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    user = User(
        full_name=body.full_name.strip(),
        email=normalized_email,
        password_hash=hash_password(body.password),
        role="merchant",
    )
    merchant = Merchant(
        business_name=body.business_name.strip(),
        country=body.country.upper(),
        website=str(body.website) if body.website else None,
    )
    merchant.settings = MerchantSettings()
    user.merchant = merchant
    db.add(user)
    await db.flush()
    access_token, refresh_token, _ = await create_auth_session(db, user.id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists") from None

    await db.refresh(merchant)
    set_auth_cookies(response, access_token, refresh_token)
    return auth_response(user, merchant)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    normalized_email = str(body.email).strip().lower()
    user = await db.scalar(
        select(User).where(User.email == normalized_email).options(selectinload(User.merchant))
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role != "merchant" or user.merchant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant account required")

    access_token, refresh_token, _ = await create_auth_session(db, user.id)
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)
    return auth_response(user, user.merchant)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session required")
    try:
        claims = decode_token(token, "refresh")
        session_id = uuid.UUID(claims["sid"])
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh session") from None

    auth_session = await db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
    supplied_hash = hash_token_id(claims["jti"])
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or is_expired(auth_session.expires_at)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session has expired or been revoked")
    if auth_session.refresh_jti_hash != supplied_hash:
        auth_session.revoked_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected")

    settings = get_settings()
    access_token, _, _ = create_token(
        subject=user_id,
        session_id=session_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_minutes),
    )
    refresh_token, refresh_jti, refresh_expiry = create_token(
        subject=user_id,
        session_id=session_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_days),
    )
    auth_session.refresh_jti_hash = hash_token_id(refresh_jti)
    auth_session.expires_at = refresh_expiry
    await db.commit()
    set_auth_cookies(response, access_token, refresh_token)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            claims = decode_token(token, "refresh")
            session_id = uuid.UUID(claims["sid"])
            auth_session = await db.get(AuthSession, session_id)
            if auth_session and auth_session.refresh_jti_hash == hash_token_id(claims["jti"]):
                auth_session.revoked_at = datetime.now(UTC)
                await db.commit()
        except (jwt.InvalidTokenError, KeyError, ValueError):
            pass
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> AuthResponse:
    fresh_user = await db.scalar(
        select(User).where(User.id == user.id).options(selectinload(User.merchant))
    )
    if fresh_user is None or fresh_user.merchant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant profile not found")
    return auth_response(fresh_user, fresh_user.merchant)