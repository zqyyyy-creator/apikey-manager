from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_current_auth_context
from app.schemas.auth import AuthContext
from app.schemas.common import ApiResponse, success_response
from app.schemas.openapi import COMMON_ERROR_RESPONSES

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get(
    "/auth",
    response_model=ApiResponse[AuthContext],
    summary="调试当前认证上下文",
    description=(
        "返回 Bearer token introspection 后得到的认证上下文，用于本地和 dev "
        "环境排查 `Authorization` 与 `x-user-id` 映射。"
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def debug_auth(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> dict[str, object]:
    return success_response(auth.model_dump())
