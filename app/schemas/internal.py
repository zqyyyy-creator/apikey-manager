from decimal import Decimal

from pydantic import BaseModel


class ChargeDetail(BaseModel):
    input_cost: Decimal
    output_cost: Decimal
    cache_cost: Decimal


class InternalKeyCostData(BaseModel):
    managed: bool
    cost: Decimal | None = None
    currency: str | None = None
    charge_detail: ChargeDetail | None = None

