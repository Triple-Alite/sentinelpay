from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Merchant, MerchantSettings, User
from app.schemas import (
    MerchantResponse,
    MerchantSettingsResponse,
    MerchantSettingsUpdateRequest,
    MerchantUpdateRequest,
)

router = APIRouter(prefix="/api/v1/merchants", tags=["merchants"])


async def get_merchant(db: AsyncSession, user_id) -> Merchant:
    merchant = await db.scalar(select(Merchant).where(Merchant.user_id == user_id))
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant profile not found")
    return merchant


@router.get("/me", response_model=MerchantResponse)
async def read_merchant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    return await get_merchant(db, user.id)


@router.patch("/me", response_model=MerchantResponse)
async def update_merchant(
    body: MerchantUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    merchant = await get_merchant(db, user.id)
    updates = body.model_dump(exclude_unset=True)
    if "website" in updates and updates["website"] is not None:
        updates["website"] = str(updates["website"])
    for field, value in updates.items():
        if value is not None:
            setattr(merchant, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(merchant)
    return merchant


@router.get("/settings", response_model=MerchantSettingsResponse)
async def read_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MerchantSettings:
    merchant = await get_merchant(db, user.id)
    settings = await db.scalar(select(MerchantSettings).where(MerchantSettings.merchant_id == merchant.id))
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant settings not found")
    return settings


@router.patch("/settings", response_model=MerchantSettingsResponse)
async def update_settings(
    body: MerchantSettingsUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MerchantSettings:
    merchant = await get_merchant(db, user.id)
    settings = await db.scalar(select(MerchantSettings).where(MerchantSettings.merchant_id == merchant.id))
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant settings not found")
    updates = body.model_dump(exclude_unset=True)
    low_threshold = updates.get("low_risk_threshold", settings.low_risk_threshold)
    high_threshold = updates.get("high_risk_threshold", settings.high_risk_threshold)
    if low_threshold >= high_threshold:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Low risk threshold must be less than high risk threshold")
    for field, value in updates.items():
        setattr(settings, field, value)
    await db.commit()
    await db.refresh(settings)
    return settings