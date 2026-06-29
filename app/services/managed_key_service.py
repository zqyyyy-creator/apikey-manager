from datetime import datetime, timezone

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import AppException, ErrorCode
from app.litellm_integration.client import LagProxyError, LiteLLMClient
from app.models.managed_key import ManagedKey, ManagedKeyStatus
from app.schemas.auth import AuthContext
from app.schemas.common import PageData
from app.schemas.managed_key import (
    CreateKeyData,
    CreateKeyRequest,
    ManagedKeyDetail,
    ManagedKeyListItem,
    RevokeKeyData,
    RevokeKeyRequest,
    SpendingLimitItem,
    UnblockKeyData,
    UnblockKeyRequest,
    UsageSummary,
)
from app.services.billing_service import BillingService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ManagedKeyService:
    def __init__(
        self,
        litellm_client: LiteLLMClient | None = None,
        billing_service: BillingService | None = None,
    ) -> None:
        self.litellm_client = litellm_client or LiteLLMClient()
        self.billing_service = billing_service or BillingService()

    async def create_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        request: CreateKeyRequest,
    ) -> CreateKeyData:
        try:
            generated_key = await self.litellm_client.generate_key(
                team_id=auth.team_id,
                user_id=auth.user_id,
                access_token=auth.access_token,
                name=request.name,
                description=request.description,
            )
        except LagProxyError as exc:
            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to generate key",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        managed_key = ManagedKey(
            key_hash_id=generated_key.key_hash_id,
            team_id=auth.team_id,
            name=request.name,
            description=request.description,
            key_alias=generated_key.key_alias,
            status=ManagedKeyStatus.ACTIVE,
        )
        db.add(managed_key)
        await db.commit()
        await db.refresh(managed_key)

        return CreateKeyData(
            id=managed_key.key_hash_id,
            name=managed_key.name,
            description=managed_key.description,
            key=generated_key.key,
            key_alias=managed_key.key_alias,
            status=managed_key.status.value,
            created_at=managed_key.created_at,
        )

    async def list_keys(
        self,
        db: AsyncSession,
        auth: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        status_filter: ManagedKeyStatus | None = None,
        name: str | None = None,
    ) -> PageData[ManagedKeyListItem]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)

        filters = [ManagedKey.team_id == auth.team_id]
        if status_filter is not None:
            filters.append(ManagedKey.status == status_filter)
        if name:
            filters.append(ManagedKey.name.like(f"%{name}%"))

        total = await db.scalar(select(func.count()).select_from(ManagedKey).where(*filters))
        result = await db.execute(
            select(ManagedKey)
            .where(*filters)
            .order_by(ManagedKey.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        keys = result.scalars().all()

        return PageData[ManagedKeyListItem](
            items=[self._to_list_item(key) for key in keys],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def get_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
    ) -> ManagedKeyDetail:
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        usage_summary = await self.billing_service.get_key_usage_summary(
            auth,
            managed_key.key_hash_id,
        )
        return self._to_detail(managed_key, usage_summary=usage_summary)

    async def revoke_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        request: RevokeKeyRequest,
    ) -> RevokeKeyData:
        managed_key = await self._get_owned_key(db, auth, key_id)

        if managed_key.status == ManagedKeyStatus.REVOKED:
            raise AppException(
                code=ErrorCode.KEY_ALREADY_REVOKED,
                message="Key already revoked",
                status_code=status.HTTP_409_CONFLICT,
            )

        try:
            await self.litellm_client.block_key(
                key=managed_key.key_hash_id,
                user_id=auth.user_id,
                access_token=auth.access_token,
                reason=request.reason,
            )
        except LagProxyError as exc:
            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to revoke key",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        managed_key.status = ManagedKeyStatus.REVOKED
        managed_key.revoked_at = _utcnow()
        await db.commit()
        await db.refresh(managed_key)

        return RevokeKeyData(
            id=managed_key.key_hash_id,
            status="revoked",
            revoked_at=managed_key.revoked_at,
        )

    async def unblock_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        request: UnblockKeyRequest,
    ) -> UnblockKeyData:
        managed_key = await self._get_owned_key(db, auth, key_id)

        if managed_key.status == ManagedKeyStatus.REVOKED:
            raise AppException(
                code=ErrorCode.KEY_REVOKED_CANNOT_UNBLOCK,
                message="Key already revoked, cannot unblock",
                status_code=status.HTTP_409_CONFLICT,
            )

        if managed_key.status != ManagedKeyStatus.BLOCKED:
            raise AppException(
                code=ErrorCode.KEY_NOT_BLOCKED,
                message="Key is not blocked",
                status_code=status.HTTP_409_CONFLICT,
            )

        try:
            await self.litellm_client.reset_key_spend(
                key=managed_key.key_hash_id,
                user_id=auth.user_id,
                access_token=auth.access_token,
            )
        except LagProxyError as exc:
            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to reset key spend",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        managed_key.status = ManagedKeyStatus.ACTIVE
        managed_key.blocked_reason = None
        managed_key.blocked_at = None
        await db.commit()
        await db.refresh(managed_key)

        return UnblockKeyData(
            id=managed_key.key_hash_id,
            status="active",
        )

    async def _get_owned_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        *,
        with_limits: bool = False,
    ) -> ManagedKey:
        statement = select(ManagedKey).where(
            ManagedKey.key_hash_id == key_id,
            ManagedKey.team_id == auth.team_id,
        )
        if with_limits:
            statement = statement.options(selectinload(ManagedKey.spending_limits))

        result = await db.execute(statement)
        managed_key = result.scalar_one_or_none()
        if managed_key is None:
            raise AppException(
                code=ErrorCode.KEY_NOT_FOUND,
                message="Key not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return managed_key

    def _to_list_item(self, managed_key: ManagedKey) -> ManagedKeyListItem:
        return ManagedKeyListItem(
            id=managed_key.key_hash_id,
            name=managed_key.name,
            description=managed_key.description,
            team_id=managed_key.team_id,
            key_alias=managed_key.key_alias,
            status=managed_key.status.value,
            created_at=managed_key.created_at,
            blocked_reason=managed_key.blocked_reason,
            blocked_at=managed_key.blocked_at,
            revoked_at=managed_key.revoked_at,
        )

    def _to_detail(
        self,
        managed_key: ManagedKey,
        *,
        usage_summary: UsageSummary | None = None,
    ) -> ManagedKeyDetail:
        return ManagedKeyDetail(
            **self._to_list_item(managed_key).model_dump(),
            spending_limits=[
                SpendingLimitItem(
                    id=limit.id,
                    limit_type=limit.limit_type.value,
                    amount=limit.amount,
                    currency=limit.currency,
                    enabled=limit.enabled,
                )
                for limit in managed_key.spending_limits
            ],
            usage_summary=usage_summary,
        )
