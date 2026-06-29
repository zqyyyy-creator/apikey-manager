import json
from decimal import Decimal

import httpx
import pytest

from app.litellm_integration.cost_calculator import CostCalculator, CostCalculatorError


@pytest.mark.anyio
async def test_cost_calculator_uses_direct_external_cost_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cost"
        assert json.loads(request.content) == {
            "model": "deepseek-v3",
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_tokens": 500,
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "cost": "0.052",
                    "charge_detail": {
                        "input_cost": "0.040",
                        "output_cost": "0.010",
                        "cache_cost": "0.002",
                    },
                }
            },
        )

    calculator = CostCalculator(
        billing_service_url="http://billing.local",
        cost_path="/cost",
        transport=httpx.MockTransport(handler),
    )

    cost = await calculator.calculate(
        model="deepseek-v3",
        input_tokens=1000,
        output_tokens=200,
        cache_tokens=500,
    )

    assert cost.total == Decimal("0.052")
    assert cost.charge_detail.input_cost == Decimal("0.040")
    assert cost.charge_detail.output_cost == Decimal("0.010")
    assert cost.charge_detail.cache_cost == Decimal("0.002")


@pytest.mark.anyio
async def test_cost_calculator_caches_external_rate_response() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json={
                "input_rate": "0.000001",
                "output_rate": "0.000002",
                "cache_rate": "0.0000002",
            },
        )

    calculator = CostCalculator(
        billing_service_url="http://billing.local",
        cost_path="/cost",
        transport=httpx.MockTransport(handler),
    )

    first = await calculator.calculate(
        model="deepseek-v3",
        input_tokens=1000,
        output_tokens=200,
        cache_tokens=500,
    )
    second = await calculator.calculate(
        model="deepseek-v3",
        input_tokens=1,
        output_tokens=1,
        cache_tokens=1,
    )

    assert first.total == Decimal("0.0015000")
    assert second.total == Decimal("0.0000032")
    assert request_count == 1


@pytest.mark.anyio
async def test_cost_calculator_raises_on_external_service_error() -> None:
    calculator = CostCalculator(
        billing_service_url="http://billing.local",
        cost_path="/cost",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    with pytest.raises(CostCalculatorError):
        await calculator.calculate(
            model="deepseek-v3",
            input_tokens=1,
            output_tokens=1,
            cache_tokens=0,
        )
