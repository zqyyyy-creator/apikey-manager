from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.exceptions import AppException, ErrorCode
from app.schemas.common import ApiResponse, success_response
from app.schemas.internal import InternalKeyCostData
from app.services.internal_cost_service import InternalCostService


router = APIRouter(
    prefix="/api/v1/internal",
    tags=["internal"],
    include_in_schema=False,
)


@lru_cache
def get_internal_cost_service() -> InternalCostService:
    return InternalCostService()


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
