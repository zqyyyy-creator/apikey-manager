from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


LimitType = Literal["daily", "weekly", "monthly", "total"]


class CreateSpendingLimitRequest(BaseModel):
    limit_type: LimitType
    amount: Decimal = Field(decimal_places=2)
    currency: str = Field(default="CNY", max_length=8)
    enabled: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "limit_type": "daily",
                "amount": 100.00,
                "currency": "CNY",
                "enabled": True,
            }
        }
    }


class UpdateSpendingLimitRequest(BaseModel):
    amount: Decimal | None = Field(default=None, decimal_places=2)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "UpdateSpendingLimitRequest":
        if self.amount is None and self.enabled is None:
            raise ValueError("At least one field is required")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "amount": 200.00,
                "enabled": True,
            }
        }
    }


class SpendingLimitData(BaseModel):
    id: int
    key_id: str
    limit_type: LimitType
    amount: Decimal
    currency: str = "CNY"
    enabled: bool
    created_at: datetime
    updated_at: datetime | None = None


class SpendingLimitListData(BaseModel):
    items: list[SpendingLimitData]
