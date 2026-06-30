from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import AppException, ErrorCode
from app.schemas.common import ApiResponse, success_response
from app.schemas.internal import (
    BudgetSyncData,
    InternalKeyCostData,
    InternalKeyManagedData,
)
from app.schemas.openapi import COMMON_ERROR_RESPONSES, UPSTREAM_ERROR_RESPONSE
from app.services.budget_spend_sync_service import BudgetSpendSyncService
from app.services.internal_cost_service import InternalCostService


router = APIRouter(
    prefix="/api/v1/internal",
    tags=["internal"],
    include_in_schema=False,
)


@lru_cache
def get_internal_cost_service() -> InternalCostService:
    return InternalCostService()


@lru_cache
def get_budget_spend_sync_service() -> BudgetSpendSyncService:
    return BudgetSpendSyncService()


async def verify_internal_api_key(
    x_internal_api_key: Annotated[
        str | None,
        Header(alias="x-internal-api-key"),
    ] = None,
) -> None:
    if x_internal_api_key != get_settings().internal_api_key:
        raise AppException(
            code=ErrorCode.FORBIDDEN,
            message="Invalid internal API key",
            status_code=status.HTTP_403_FORBIDDEN,
        )


@router.get(
    "/keys/{key_hash_id}/cost",
    response_model=ApiResponse[InternalKeyCostData],
    dependencies=[Depends(verify_internal_api_key)],
    summary="查询 managed key 实际消费金额",
    description=(
        "供 LiteLLM CustomLogger 内部调用。接口通过 `x-internal-api-key` "
        "认证，不走用户 OAuth2。非 managed key 返回 `managed=false`。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **UPSTREAM_ERROR_RESPONSE},
)
async def get_key_cost(
    key_hash_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[InternalCostService, Depends(get_internal_cost_service)],
    model: Annotated[str, Query(min_length=1)],
    input_tokens: Annotated[int, Query(ge=0)] = 0,
    output_tokens: Annotated[int, Query(ge=0)] = 0,
    cache_tokens: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    data = await service.get_key_cost(
        db,
        key_hash_id=key_hash_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_tokens=cache_tokens,
    )
    return success_response(data.model_dump())


@router.get(
    "/keys/{key_hash_id}/managed",
    response_model=ApiResponse[InternalKeyManagedData],
    dependencies=[Depends(verify_internal_api_key)],
    summary="判断 key 是否为 MaaS managed key",
    description=(
        "供 LiteLLM CustomLogger 内部调用。只判断 key 是否由 MaaS 管理，"
        "不调用外部 billing service。"
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def get_key_managed_status(
    key_hash_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[InternalCostService, Depends(get_internal_cost_service)],
) -> dict[str, object]:
    managed = await service.is_managed_key(db, key_hash_id)
    return success_response(InternalKeyManagedData(managed=managed).model_dump())


@router.get(
    "/budget-sync/keys",
    response_model=ApiResponse[BudgetSyncData],
    dependencies=[Depends(verify_internal_api_key)],
    summary="查询 managed key 的 CK 消费和 LiteLLM budget 同步数据",
    description=(
        "供 LiteLLM Gateway 内部插件定时调用。接口按 ClickHouse 账单计算 "
        "managed key 当前消费，并返回 key 级 max_budget、budget_duration "
        "和多窗口 budget_limits。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **UPSTREAM_ERROR_RESPONSE},
)
async def get_budget_sync_keys(
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[
        BudgetSpendSyncService,
        Depends(get_budget_spend_sync_service),
    ],
) -> dict[str, object]:
    data = await service.build_sync_payload(db)
    return success_response(data.model_dump())
