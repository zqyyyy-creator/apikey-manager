from decimal import Decimal

from pydantic import BaseModel


class ChargeDetail(BaseModel):
    input_cost: Decimal
    output_cost: Decimal
    cache_cost: Decimal

    model_config = {
        "json_schema_extra": {
            "example": {
                "input_cost": "0.040",
                "output_cost": "0.010",
                "cache_cost": "0.002",
            }
        }
    }


class InternalKeyCostData(BaseModel):
    managed: bool
    cost: Decimal | None = None
    currency: str | None = None
    charge_detail: ChargeDetail | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "managed": True,
                    "cost": "0.052",
                    "currency": "CNY",
                    "charge_detail": {
                        "input_cost": "0.040",
                        "output_cost": "0.010",
                        "cache_cost": "0.002",
                    },
                },
                {
                    "managed": False,
                    "cost": None,
                    "currency": None,
                    "charge_detail": None,
                },
            ]
        }
    }
