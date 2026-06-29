from decimal import Decimal

import pytest

from app.litellm_integration.cost_calculator import CostCalculator
from app.schemas.internal import ChargeDetail
from app.services.internal_cost_service import InternalCostService


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):  # noqa: ANN201
        return self.value


class FakeDb:
    def __init__(self, *, managed: bool) -> None:
        self.managed = managed
        self.execute_count = 0

    async def execute(self, statement):  # noqa: ANN001, ANN201
        self.execute_count += 1
        return FakeScalarResult("hash_001" if self.managed else None)


class FakeCostCalculator:
    async def calculate(self, **kwargs):  # noqa: ANN003, ANN201
        return type(
            "CalculatedCost",
            (),
            {
                "total": Decimal("0.0015000"),
                "charge_detail": ChargeDetail(
                    input_cost=Decimal("0.001000"),
                    output_cost=Decimal("0.000400"),
                    cache_cost=Decimal("0.0001000"),
                ),
            },
        )()


@pytest.mark.anyio
async def test_internal_cost_returns_not_managed_for_unknown_key() -> None:
    service = InternalCostService(cost_calculator=CostCalculator())

    data = await service.get_key_cost(
        FakeDb(managed=False),
        key_hash_id="missing_hash",
        model="deepseek-v3",
        input_tokens=1000,
        output_tokens=200,
        cache_tokens=500,
    )

    assert data.managed is False
    assert data.cost is None
    assert data.charge_detail is None


@pytest.mark.anyio
async def test_internal_cost_calculates_cny_cost_for_managed_key() -> None:
    service = InternalCostService(cost_calculator=FakeCostCalculator())

    data = await service.get_key_cost(
        FakeDb(managed=True),
        key_hash_id="hash_001",
        model="deepseek-v3",
        input_tokens=1000,
        output_tokens=200,
        cache_tokens=500,
    )

    assert data.managed is True
    assert data.currency == "CNY"
    assert data.charge_detail is not None
    assert data.charge_detail.input_cost == Decimal("0.001000")
    assert data.charge_detail.output_cost == Decimal("0.000400")
    assert data.charge_detail.cache_cost == Decimal("0.0001000")
    assert data.cost == Decimal("0.0015000")


@pytest.mark.anyio
async def test_internal_cost_caches_managed_key_lookup() -> None:
    db = FakeDb(managed=True)
    service = InternalCostService(cost_calculator=FakeCostCalculator())

    await service.get_key_cost(
        db,
        key_hash_id="hash_001",
        model="deepseek-v3",
        input_tokens=1,
        output_tokens=1,
        cache_tokens=0,
    )
    await service.get_key_cost(
        db,
        key_hash_id="hash_001",
        model="deepseek-v3",
        input_tokens=1,
        output_tokens=1,
        cache_tokens=0,
    )

    assert db.execute_count == 1
