from decimal import Decimal

from app.litellm_integration.client import LiteLLMClient
from app.models.spending_limit import SpendingLimit, SpendingLimitType


class BudgetSyncService:
    PERIODIC_BUDGET_DURATIONS = {
        SpendingLimitType.DAILY: "1d",
        SpendingLimitType.WEEKLY: "1w",
        SpendingLimitType.MONTHLY: "1mo",
    }

    def __init__(self, litellm_client: LiteLLMClient | None = None) -> None:
        self.litellm_client = litellm_client or LiteLLMClient()

    async def sync_limits(
        self,
        *,
        key_hash_id: str,
        user_id: str,
        access_token: str,
        limits: list[SpendingLimit],
    ) -> None:
        enabled_limits = [limit for limit in limits if limit.enabled]
        periodic_limits = [
            limit
            for limit in enabled_limits
            if limit.limit_type in self.PERIODIC_BUDGET_DURATIONS
        ]
        total = self._find_limit(enabled_limits, SpendingLimitType.TOTAL)

        if len(periodic_limits) > 1 or (periodic_limits and total is not None):
            budget_limits = [
                {
                    "budget_duration": self.PERIODIC_BUDGET_DURATIONS[limit.limit_type],
                    "max_budget": str(limit.amount),
                }
                for limit in periodic_limits
            ]
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                max_budget=Decimal(total.amount) if total is not None else None,
                clear_max_budget=total is None,
                clear_budget_duration=True,
                budget_limits=budget_limits,
            )
            return

        if len(periodic_limits) == 1:
            limit = periodic_limits[0]
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                max_budget=Decimal(limit.amount),
                budget_duration=self.PERIODIC_BUDGET_DURATIONS[limit.limit_type],
            )
            return

        if total is not None:
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                max_budget=Decimal(total.amount),
                clear_budget_duration=True,
            )
            return

        await self.litellm_client.update_key(
            key=key_hash_id,
            user_id=user_id,
            access_token=access_token,
            clear_max_budget=True,
            clear_budget_duration=True,
        )

    def _find_limit(
        self,
        limits: list[SpendingLimit],
        limit_type: SpendingLimitType,
    ) -> SpendingLimit | None:
        for limit in limits:
            if limit.limit_type == limit_type:
                return limit
        return None
