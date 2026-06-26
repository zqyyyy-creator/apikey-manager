from decimal import Decimal

from app.schemas.internal import ChargeDetail


class CalculatedCost:
    def __init__(self, *, total: Decimal, charge_detail: ChargeDetail) -> None:
        self.total = total
        self.charge_detail = charge_detail


class CostCalculator:
    """Temporary local calculator until the external billing API contract is fixed."""

    INPUT_RATE = Decimal("0.000001")
    OUTPUT_RATE = Decimal("0.000002")
    CACHE_RATE = Decimal("0.0000002")

    async def calculate(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> CalculatedCost:
        input_cost = self.INPUT_RATE * Decimal(input_tokens)
        output_cost = self.OUTPUT_RATE * Decimal(output_tokens)
        cache_cost = self.CACHE_RATE * Decimal(cache_tokens)
        total = input_cost + output_cost + cache_cost
        return CalculatedCost(
            total=total,
            charge_detail=ChargeDetail(
                input_cost=input_cost,
                output_cost=output_cost,
                cache_cost=cache_cost,
            ),
        )

