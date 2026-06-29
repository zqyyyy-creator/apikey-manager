from typing import Annotated

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.schemas.auth import AuthContext
from app.schemas.common import ApiResponse, success_response
from app.schemas.spending_limit import (
    CreateSpendingLimitRequest,
    SpendingLimitData,
    SpendingLimitListData,
    UpdateSpendingLimitRequest,
)
from app.schemas.openapi import (
    COMMON_ERROR_RESPONSES,
    CONFLICT_RESPONSE,
    UPSTREAM_ERROR_RESPONSE,
)
from app.services.spending_limit_service import SpendingLimitService


router = APIRouter(prefix="/api/v1/keys/{key_id}/limits", tags=["spending-limits"])


def get_spending_limit_service() -> SpendingLimitService:
    return SpendingLimitService()


@router.post(
    "",
    response_model=ApiResponse[SpendingLimitData],
    status_code=status.HTTP_201_CREATED,
    summary="创建消费阈值",
    description=(
        "为指定 managed key 创建 daily、weekly、monthly 或 total 阈值。"
        "阈值金额按 CNY 处理，并会同步到 LiteLLM budget 配置。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **CONFLICT_RESPONSE, **UPSTREAM_ERROR_RESPONSE},
)
async def create_spending_limit(
    key_id: str,
    request: CreateSpendingLimitRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[
        SpendingLimitService,
        Depends(get_spending_limit_service),
    ],
) -> dict[str, object]:
    data = await service.create_limit(db, auth, key_id, request)
    return success_response(data.model_dump())


@router.get(
    "",
    response_model=ApiResponse[SpendingLimitListData],
    summary="查询消费阈值列表",
    description="查询指定 managed key 下已配置的 spending limits。",
    responses=COMMON_ERROR_RESPONSES,
)
async def list_spending_limits(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[
        SpendingLimitService,
        Depends(get_spending_limit_service),
    ],
) -> dict[str, object]:
    data = await service.list_limits(db, auth, key_id)
    return success_response(data.model_dump())


@router.patch(
    "/{limit_id}",
    response_model=ApiResponse[SpendingLimitData],
    summary="更新消费阈值",
    description=(
        "更新指定 spending limit 的金额或启用状态。更新后会同步 LiteLLM "
        "budget 配置。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **UPSTREAM_ERROR_RESPONSE},
)
async def update_spending_limit(
    key_id: str,
    limit_id: int,
    request: UpdateSpendingLimitRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[
        SpendingLimitService,
        Depends(get_spending_limit_service),
    ],
) -> dict[str, object]:
    data = await service.update_limit(db, auth, key_id, limit_id, request)
    return success_response(data.model_dump())


@router.delete(
    "/{limit_id}",
    response_model=ApiResponse[None],
    summary="删除消费阈值",
    description=(
        "删除指定 spending limit，并同步 LiteLLM budget 配置。删除后如果没有"
        "启用阈值，会清空 LiteLLM max_budget。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **UPSTREAM_ERROR_RESPONSE},
)
async def delete_spending_limit(
    key_id: str,
    limit_id: int,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[
        SpendingLimitService,
        Depends(get_spending_limit_service),
    ],
) -> dict[str, object]:
    await service.delete_limit(db, auth, key_id, limit_id)
    return success_response(None)
