from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import AppException, ErrorCode
from app.litellm_integration.budget_sync import BudgetSyncService
from app.litellm_integration.client import LagProxyError
from app.models.managed_key import ManagedKey
from app.models.spending_limit import SpendingLimit, SpendingLimitType
from app.schemas.auth import AuthContext
from app.schemas.spending_limit import (
    CreateSpendingLimitRequest,
    SpendingLimitData,
    SpendingLimitListData,
    UpdateSpendingLimitRequest,
)


class SpendingLimitService:
    def __init__(self, budget_sync: BudgetSyncService | None = None) -> None:
        self.budget_sync = budget_sync or BudgetSyncService()

    async def create_limit(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        request: CreateSpendingLimitRequest,
    ) -> SpendingLimitData:
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        limit_type = SpendingLimitType(request.limit_type)
        self._ensure_amount_positive(request.amount)

        if any(limit.limit_type == limit_type for limit in managed_key.spending_limits):
            raise AppException(
                code=ErrorCode.LIMIT_TYPE_ALREADY_EXISTS,
                message="Spending limit type already exists",
                status_code=status.HTTP_409_CONFLICT,
            )

        limit = SpendingLimit(
            key_hash_id=managed_key.key_hash_id,
            limit_type=limit_type,
            amount=request.amount,
            currency=request.currency,
            enabled=request.enabled,
        )
        db.add(limit)
        await db.flush()
        managed_key.spending_limits.append(limit)
        await self._sync_or_raise(auth, managed_key)
        await db.commit()
        await db.refresh(limit)
        return self._to_data(limit)

    async def list_limits(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
    ) -> SpendingLimitListData:
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        return SpendingLimitListData(
            items=[self._to_data(limit) for limit in managed_key.spending_limits],
        )

    async def update_limit(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        limit_id: int,
        request: UpdateSpendingLimitRequest,
    ) -> SpendingLimitData:
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        limit = self._find_limit(managed_key, limit_id)

        if request.amount is not None:
            self._ensure_amount_positive(request.amount)
            limit.amount = request.amount
        if request.enabled is not None:
            limit.enabled = request.enabled

        await db.flush()
        await self._sync_or_raise(auth, managed_key)
        await db.commit()
        await db.refresh(limit)
        return self._to_data(limit)

    async def delete_limit(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        limit_id: int,
    ) -> None:
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        limit = self._find_limit(managed_key, limit_id)

        managed_key.spending_limits.remove(limit)
        await db.delete(limit)
        await db.flush()
        await self._sync_or_raise(auth, managed_key)
        await db.commit()

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

    async def _sync_or_raise(self, auth: AuthContext, managed_key: ManagedKey) -> None:
        try:
            await self.budget_sync.sync_limits(
                key_hash_id=managed_key.key_hash_id,
                user_id=auth.user_id,
                access_token=auth.access_token,
                limits=list(managed_key.spending_limits),
            )
        except LagProxyError as exc:
            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Failed to sync spending limit to LiteLLM",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

    def _find_limit(self, managed_key: ManagedKey, limit_id: int) -> SpendingLimit:
        for limit in managed_key.spending_limits:
            if limit.id == limit_id:
                return limit
        raise AppException(
            code=ErrorCode.LIMIT_NOT_FOUND,
            message="Spending limit not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    def _ensure_amount_positive(self, amount) -> None:  # noqa: ANN001
        if amount <= 0:
            raise AppException(
                code=ErrorCode.LIMIT_AMOUNT_INVALID,
                message="Spending limit amount must be greater than 0",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def _to_data(self, limit: SpendingLimit) -> SpendingLimitData:
        return SpendingLimitData(
            id=limit.id,
            key_id=limit.key_hash_id,
            limit_type=limit.limit_type.value,
            amount=limit.amount,
            currency=limit.currency,
            enabled=limit.enabled,
            created_at=limit.created_at,
            updated_at=limit.updated_at,
        )
