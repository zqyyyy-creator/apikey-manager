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
from app.services.managed_key_service import ManagedKeyService


router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


def get_managed_key_service() -> ManagedKeyService:
    return ManagedKeyService()


@router.post(
    "",
    response_model=ApiResponse[CreateKeyData],
    status_code=status.HTTP_201_CREATED,
)
async def create_key(
    request: CreateKeyRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.create_key(db, auth, request)
    return success_response(data.model_dump())


@router.get("", response_model=ApiResponse[PageData[ManagedKeyListItem]])
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


@router.get("/{key_id}", response_model=ApiResponse[ManagedKeyDetail])
async def get_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[ManagedKeyService, Depends(get_managed_key_service)],
) -> dict[str, object]:
    data = await service.get_key(db, auth, key_id)
    return success_response(data.model_dump())


@router.patch("/{key_id}/revoke", response_model=ApiResponse[RevokeKeyData])
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


@router.patch("/{key_id}/unblock", response_model=ApiResponse[UnblockKeyData])
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
