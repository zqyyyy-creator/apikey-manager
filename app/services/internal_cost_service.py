import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.litellm_integration.cost_calculator import CostCalculator
from app.models.managed_key import ManagedKey
from app.schemas.internal import InternalKeyCostData


class _TTLCache:
    def __init__(self, ttl_seconds: int, max_size: int = 4096) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: dict[str, tuple[object, float]] = {}

    def get(self, key: str) -> object | None:
        item = self._items.get(key)
        if item is None:
            return None

        value, expires_at = item
        if expires_at <= time.time():
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: str, value: object) -> None:
        if len(self._items) >= self.max_size:
            oldest_key = next(iter(self._items))
            self._items.pop(oldest_key, None)
        self._items[key] = (value, time.time() + self.ttl_seconds)

    def invalidate(self, key: str) -> None:
        self._items.pop(key, None)


class InternalCostService:
    def __init__(self, cost_calculator: CostCalculator | None = None) -> None:
        settings = get_settings()
        self.cost_calculator = cost_calculator or CostCalculator()
        self._managed_cache = _TTLCache(settings.cost_cache_managed_ttl)

    async def get_key_cost(
        self,
        db: AsyncSession,
        *,
        key_hash_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> InternalKeyCostData:
        if not await self._is_managed_key(db, key_hash_id):
            return InternalKeyCostData(managed=False)

        calculated_cost = await self.cost_calculator.calculate(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_tokens=cache_tokens,
        )
        return InternalKeyCostData(
            managed=True,
            cost=calculated_cost.total,
            currency="CNY",
            charge_detail=calculated_cost.charge_detail,
        )

    async def _is_managed_key(self, db: AsyncSession, key_hash_id: str) -> bool:
        cache_key = f"managed:{key_hash_id}"
        cached = self._managed_cache.get(cache_key)
        if isinstance(cached, bool):
            return cached

        result = await db.execute(
            select(ManagedKey.key_hash_id).where(ManagedKey.key_hash_id == key_hash_id)
        )
        is_managed = result.scalar_one_or_none() is not None
        self._managed_cache.set(cache_key, is_managed)
        return is_managed

