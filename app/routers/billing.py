from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.schemas.auth import AuthContext
from app.schemas.billing import (
    BillingGroupBy,
    BillingPageData,
    BillingSummaryGroupBy,
    BillingSummaryPageData,
)
from app.schemas.common import ApiResponse, success_response
from app.services.billing_service import BillingService


router = APIRouter(prefix="/api/v1", tags=["billing"])


def get_billing_service() -> BillingService:
    return BillingService()


@router.get("/keys/{key_id}/billing", response_model=ApiResponse[BillingPageData])
async def get_key_billing(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: Annotated[BillingGroupBy, Query()] = "date",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    data = await service.get_key_billing(
        db,
        auth,
        key_id,
        start_date=start_date,
        end_date=end_date,
        group_by=group_by,
        page=page,
        page_size=page_size,
    )
    return success_response(data.model_dump())


@router.get("/billing/summary", response_model=ApiResponse[BillingSummaryPageData])
async def get_billing_summary(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[BillingService, Depends(get_billing_service)],
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: Annotated[BillingSummaryGroupBy, Query()] = "key",
    key_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    data = await service.get_billing_summary(
        db,
        auth,
        start_date=start_date,
        end_date=end_date,
        group_by=group_by,
        key_id=key_id,
        page=page,
        page_size=page_size,
    )
    return success_response(data.model_dump())
