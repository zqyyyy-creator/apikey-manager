from decimal import Decimal

from app.litellm_integration.client import LiteLLMClient
from app.models.spending_limit import SpendingLimit, SpendingLimitType


class BudgetSyncService:
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
        daily = self._find_limit(enabled_limits, SpendingLimitType.DAILY)
        total = self._find_limit(enabled_limits, SpendingLimitType.TOTAL)

        if daily is not None and total is not None:
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                clear_max_budget=True,
                clear_budget_duration=True,
                budget_limits=[
                    {
                        "budget_duration": "1d",
                        "max_budget": str(daily.amount),
                    },
                    {
                        "budget_duration": "30d",
                        "max_budget": str(total.amount),
                    },
                ],
            )
            return

        if daily is not None:
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                max_budget=Decimal(daily.amount),
                budget_duration="1d",
                budget_limits=[],
            )
            return

        if total is not None:
            await self.litellm_client.update_key(
                key=key_hash_id,
                user_id=user_id,
                access_token=access_token,
                max_budget=Decimal(total.amount),
                clear_budget_duration=True,
                budget_limits=[],
            )
            return

        await self.litellm_client.update_key(
            key=key_hash_id,
            user_id=user_id,
            access_token=access_token,
            clear_max_budget=True,
            clear_budget_duration=True,
            budget_limits=[],
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
