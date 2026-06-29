from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.models.managed_key import ManagedKeyStatus
from app.schemas.auth import AuthContext
from app.schemas.common import ApiResponse, PageData, success_response
from app.schemas.managed_key import (
    CreateKeyData,
    CreateKeyRequest,
    ManagedKeyDetail,
    ManagedKeyListItem,
    RevokeKeyData,
    RevokeKeyRequest,
    UnblockKeyData,
    UnblockKeyRequest,
)
from app.schemas.openapi import (
    COMMON_ERROR_RESPONSES,
    CONFLICT_RESPONSE,
    UPSTREAM_ERROR_RESPONSE,
)
from app.services.managed_key_service import ManagedKeyService


router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


def get_managed_key_service() -> ManagedKeyService:
    return ManagedKeyService()


@router.post(
    "",
    response_model=ApiResponse[CreateKeyData],
    status_code=status.HTTP_201_CREATED,
    summary="创建托管 Key",
    description=(
        "创建 MaaS 托管的 LiteLLM key。请求必须携带 Bearer token 和 "
        "`x-user-id`，服务端根据 user_id 生成 team_id。raw key 只会在"
        "本接口响应中返回一次，不会落库存储。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **UPSTREAM_ERROR_RESPONSE},
)
async def create_key(
    request: CreateKeyRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.create_key(db, auth, request)
    return success_response(data.model_dump())


@router.get(
    "",
    response_model=ApiResponse[PageData[ManagedKeyListItem]],
    summary="查询托管 Key 列表",
    description=(
        "分页查询当前 `x-user-id` 所属 team 下的 managed keys。支持按状态和"
        "名称过滤，不返回 raw key。"
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def list_keys(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[
        ManagedKeyStatus | None,
        Query(alias="status"),
    ] = None,
    name: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    data = await service.list_keys(
        db,
        auth,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        name=name,
    )
    return success_response(data.model_dump())


@router.get(
    "/{key_id}",
    response_model=ApiResponse[ManagedKeyDetail],
    summary="查询托管 Key 详情",
    description=(
        "查询单个 managed key 的详情、spending limits 和 usage_summary。"
        "`key_id` 为 LiteLLM key hash id，不是 raw key。"
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def get_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.get_key(db, auth, key_id)
    return success_response(data.model_dump())


@router.patch(
    "/{key_id}/revoke",
    response_model=ApiResponse[RevokeKeyData],
    summary="吊销托管 Key",
    description=(
        "将 managed key 标记为 revoked，并通过 lag-proxy 调用 LiteLLM block "
        "能力。已吊销 key 再次吊销会返回冲突错误。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **CONFLICT_RESPONSE, **UPSTREAM_ERROR_RESPONSE},
)
async def revoke_key(
    key_id: str,
    request: Annotated[
        RevokeKeyRequest,
        Body(default_factory=RevokeKeyRequest),
    ],
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.revoke_key(db, auth, key_id, request)
    return success_response(data.model_dump())


@router.patch(
    "/{key_id}/unblock",
    response_model=ApiResponse[UnblockKeyData],
    summary="解封托管 Key",
    description=(
        "将 blocked key 恢复为 active。按 PLAN 要求，解封前会调用 LiteLLM "
        "`reset_spend`，避免旧 spend 立即再次触发预算限制。"
    ),
    responses={**COMMON_ERROR_RESPONSES, **CONFLICT_RESPONSE, **UPSTREAM_ERROR_RESPONSE},
)
async def unblock_key(
    key_id: str,
    request: Annotated[
        UnblockKeyRequest,
        Body(default_factory=UnblockKeyRequest),
    ],
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.unblock_key(db, auth, key_id, request)
    return success_response(data.model_dump())
