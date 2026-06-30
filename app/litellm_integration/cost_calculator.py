from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.internal import ChargeDetail


class CalculatedCost:
    def __init__(self, *, total: Decimal, charge_detail: ChargeDetail) -> None:
        self.total = total
        self.charge_detail = charge_detail


class CostCalculatorError(RuntimeError):
    pass


class _TTLCache:
    def __init__(self, ttl_seconds: int, max_size: int = 2048) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: dict[str, tuple[dict[str, Decimal], float]] = {}

    def get(self, key: str) -> dict[str, Decimal] | None:
        import time

        item = self._items.get(key)
        if item is None:
            return None

        value, expires_at = item
        if expires_at <= time.time():
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict[str, Decimal]) -> None:
        import time

        if len(self._items) >= self.max_size:
            oldest_key = next(iter(self._items))
            self._items.pop(oldest_key, None)
        self._items[key] = (value, time.time() + self.ttl_seconds)


class CostCalculator:
    """Calls the external billing service for managed-key cost in CNY."""

    def __init__(
        self,
        *,
        billing_service_url: str | None = None,
        cost_path: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.billing_service_url = (
            billing_service_url or settings.billing_service_url
        ).rstrip("/")
        self.cost_path = cost_path or settings.billing_service_cost_path
        self.timeout = timeout or settings.billing_service_timeout
        self.transport = transport
        self._rate_cache = _TTLCache(settings.cost_cache_rate_ttl)

    async def calculate(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> CalculatedCost:
        cached_rates = self._rate_cache.get(model)
        if cached_rates is not None:
            return self._calculate_from_rates(
                rates=cached_rates,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_tokens=cache_tokens,
            )

        response_data = await self._request_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_tokens=cache_tokens,
        )

        direct_cost = self._try_parse_direct_cost(response_data)
        if direct_cost is not None:
            return direct_cost

        rates = self._parse_rates(response_data)
        self._rate_cache.set(model, rates)
        return self._calculate_from_rates(
            rates=rates,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_tokens=cache_tokens,
        )

    async def _request_cost(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_tokens": cache_tokens,
        }
        if not self.billing_service_url:
            raise CostCalculatorError("external billing service URL is not configured")
        url = f"{self.billing_service_url}/{self.cost_path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise CostCalculatorError("external billing service request failed") from exc
        except ValueError as exc:
            raise CostCalculatorError("external billing service returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise CostCalculatorError("external billing service returned non-object JSON")
        return self._unwrap_data(data)

    def _unwrap_data(self, data: dict[str, Any]) -> dict[str, Any]:
        nested = data.get("data")
        if isinstance(nested, dict):
            return nested
        return data

    def _try_parse_direct_cost(self, data: dict[str, Any]) -> CalculatedCost | None:
        charge_detail = data.get("charge_detail")
        if data.get("cost") is None or not isinstance(charge_detail, dict):
            return None

        return CalculatedCost(
            total=self._decimal(data["cost"], "cost"),
            charge_detail=ChargeDetail(
                input_cost=self._decimal(charge_detail.get("input_cost"), "input_cost"),
                output_cost=self._decimal(
                    charge_detail.get("output_cost"), "output_cost"
                ),
                cache_cost=self._decimal(charge_detail.get("cache_cost"), "cache_cost"),
            ),
        )

    def _parse_rates(self, data: dict[str, Any]) -> dict[str, Decimal]:
        return {
            "input_rate": self._decimal(data.get("input_rate"), "input_rate"),
            "output_rate": self._decimal(data.get("output_rate"), "output_rate"),
            "cache_rate": self._decimal(data.get("cache_rate"), "cache_rate"),
        }

    def _calculate_from_rates(
        self,
        *,
        rates: dict[str, Decimal],
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> CalculatedCost:
        input_cost = rates["input_rate"] * Decimal(input_tokens)
        output_cost = rates["output_rate"] * Decimal(output_tokens)
        cache_cost = rates["cache_rate"] * Decimal(cache_tokens)
        total = input_cost + output_cost + cache_cost
        return CalculatedCost(
            total=total,
            charge_detail=ChargeDetail(
                input_cost=input_cost,
                output_cost=output_cost,
                cache_cost=cache_cost,
            ),
        )

    def _decimal(self, value: Any, field_name: str) -> Decimal:
        if value is None:
            raise CostCalculatorError(
                f"external billing service response missing {field_name}"
            )
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise CostCalculatorError(
                f"external billing service response has invalid {field_name}"
            ) from exc
