from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.managed_key import ManagedKey, ManagedKeyStatus
from app.models.spending_limit import SpendingLimit, SpendingLimitType
from app.schemas.auth import AuthContext
from app.schemas.internal import (
    BudgetSyncData,
    BudgetSyncKeyData,
    BudgetSyncWindowData,
)
from app.services.billing_service import BillingService
from app.services.resource_key_mapping_service import ResourceKeyMappingService


class BudgetSpendSyncService:
    PERIODIC_DURATIONS = {
        SpendingLimitType.DAILY: "1d",
        SpendingLimitType.WEEKLY: "1w",
        SpendingLimitType.MONTHLY: "1mo",
    }

    def __init__(
        self,
        billing_service: BillingService | None = None,
        resource_key_mapping: ResourceKeyMappingService | None = None,
    ) -> None:
        self.billing_service = billing_service or BillingService()
        self.resource_key_mapping = resource_key_mapping or ResourceKeyMappingService()

    async def build_sync_payload(self, db: AsyncSession) -> BudgetSyncData:
        result = await db.execute(
            select(ManagedKey)
            .options(selectinload(ManagedKey.spending_limits))
            .where(ManagedKey.status != ManagedKeyStatus.REVOKED)
        )
        keys = list(result.scalars().all())

        items = []
        for managed_key in keys:
            enabled_limits = [
                limit for limit in managed_key.spending_limits if limit.enabled
            ]
            if not enabled_limits:
                continue
            items.append(await self._build_key_sync_data(managed_key, enabled_limits))

        return BudgetSyncData(items=items)

    async def _build_key_sync_data(
        self,
        managed_key: ManagedKey,
        limits: list[SpendingLimit],
    ) -> BudgetSyncKeyData:
        auth = AuthContext(
            client_id="internal",
            user_id=self._user_id_from_team_id(managed_key.team_id),
            team_id=managed_key.team_id,
            access_token="",
        )
        today = date.today()
        total_limit = self._find_limit(limits, SpendingLimitType.TOTAL)
        periodic_limits = [
            limit for limit in limits if limit.limit_type in self.PERIODIC_DURATIONS
        ]

        total_spend = await self._sum_cost_for_range(
            auth=auth,
            key_id=managed_key.key_hash_id,
            start_date=managed_key.created_at.date(),
            end_date=today,
        )
        windows = []
        for limit in periodic_limits:
            start_date = self._period_start(today, limit.limit_type)
            spend = await self._sum_cost_for_range(
                auth=auth,
                key_id=managed_key.key_hash_id,
                start_date=start_date,
                end_date=today,
            )
            windows.append(
                BudgetSyncWindowData(
                    budget_duration=self.PERIODIC_DURATIONS[limit.limit_type],
                    max_budget=limit.amount,
                    spend=spend,
                )
            )

        if len(windows) == 1 and total_limit is None:
            only_window = windows[0]
            return BudgetSyncKeyData(
                key_hash_id=managed_key.key_hash_id,
                spend=only_window.spend,
                max_budget=only_window.max_budget,
                budget_duration=only_window.budget_duration,
                blocked=managed_key.status == ManagedKeyStatus.BLOCKED,
            )

        return BudgetSyncKeyData(
            key_hash_id=managed_key.key_hash_id,
            spend=total_spend,
            max_budget=total_limit.amount if total_limit is not None else None,
            budget_duration=None,
            budget_limits=windows or None,
            blocked=managed_key.status == ManagedKeyStatus.BLOCKED,
        )

    async def _sum_cost_for_range(
        self,
        *,
        auth: AuthContext,
        key_id: str,
        start_date: date,
        end_date: date,
    ) -> Decimal:
        resource_uuids = await self.resource_key_mapping.get_resource_uuids_for_key(
            key_id
        )
        rows = await self.billing_service._query_key_billing_rows(
            auth=auth,
            key_id=key_id,
            resource_uuids=resource_uuids,
            start_date=start_date,
            end_date=end_date,
            group_by="date",
        )
        return sum((Decimal(str(row["cost"])) for row in rows), Decimal("0"))

    def _find_limit(
        self,
        limits: list[SpendingLimit],
        limit_type: SpendingLimitType,
    ) -> SpendingLimit | None:
        for limit in limits:
            if limit.limit_type == limit_type:
                return limit
        return None

    def _period_start(
        self,
        today: date,
        limit_type: SpendingLimitType,
    ) -> date:
        if limit_type == SpendingLimitType.DAILY:
            return today
        if limit_type == SpendingLimitType.WEEKLY:
            return today - timedelta(days=today.weekday())
        if limit_type == SpendingLimitType.MONTHLY:
            return today.replace(day=1)
        return date(1970, 1, 1)

    def _user_id_from_team_id(self, team_id: str) -> str:
        for prefix in ("AI_PRD_", "AI_TEST_", "AI_DEV_"):
            if team_id.startswith(prefix):
                return team_id.removeprefix(prefix)
        return team_id
