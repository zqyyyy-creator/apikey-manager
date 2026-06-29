from __future__ import annotations

from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


BillingGroupBy = Literal["date", "model", "date_model"]
BillingSummaryGroupBy = Literal["key", "key_date", "key_model"]


class BillingItem(BaseModel):
    key_id: str
    date: Date | None = None
    model: str | None = None
    request_count: int
    input_tokens: Decimal
    cache_tokens: Decimal
    output_tokens: Decimal
    input_cost: Decimal
    cache_cost: Decimal
    output_cost: Decimal
    cost: Decimal

    model_config = {
        "json_schema_extra": {
            "example": {
                "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                "date": "2026-06-29",
                "model": "deepseek-v3",
                "request_count": 1250,
                "input_tokens": "1000000",
                "cache_tokens": "600000",
                "output_tokens": "250000",
                "input_cost": "10.00",
                "cache_cost": "0.60",
                "output_cost": "1.90",
                "cost": "12.50",
            }
        }
    }


class BillingTotals(BaseModel):
    total_request_count: int = 0
    total_input_tokens: Decimal = Decimal("0")
    total_cache_tokens: Decimal = Decimal("0")
    total_output_tokens: Decimal = Decimal("0")
    total_input_cost: Decimal = Decimal("0")
    total_cache_cost: Decimal = Decimal("0")
    total_output_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_request_count": 1550,
                "total_input_tokens": "1150000",
                "total_cache_tokens": "600000",
                "total_output_tokens": "350000",
                "total_input_cost": "16.00",
                "total_cache_cost": "0.60",
                "total_output_cost": "4.65",
                "total_cost": "21.25",
            }
        }
    }


class BillingPageData(BaseModel):
    items: list[BillingItem]
    total: int
    page: int
    page_size: int
    summary: BillingTotals = Field(default_factory=BillingTotals)

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [
                    {
                        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                        "date": "2026-06-29",
                        "model": "deepseek-v3",
                        "request_count": 1250,
                        "input_tokens": "1000000",
                        "cache_tokens": "600000",
                        "output_tokens": "250000",
                        "input_cost": "10.00",
                        "cache_cost": "0.60",
                        "output_cost": "1.90",
                        "cost": "12.50",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "summary": {
                    "total_request_count": 1250,
                    "total_input_tokens": "1000000",
                    "total_cache_tokens": "600000",
                    "total_output_tokens": "250000",
                    "total_input_cost": "10.00",
                    "total_cache_cost": "0.60",
                    "total_output_cost": "1.90",
                    "total_cost": "12.50",
                },
            }
        }
    }


class BillingSummaryItem(BaseModel):
    key_id: str
    key_name: str | None
    key_alias: str
    date: Date | None = None
    model: str | None = None
    total_request_count: int
    total_input_tokens: Decimal
    total_cache_tokens: Decimal
    total_output_tokens: Decimal
    total_input_cost: Decimal
    total_cache_cost: Decimal
    total_output_cost: Decimal
    total_cost: Decimal

    model_config = {
        "json_schema_extra": {
            "example": {
                "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                "key_name": "production-api-key",
                "key_alias": "sk...87f9",
                "date": None,
                "model": None,
                "total_request_count": 15000,
                "total_input_tokens": "5000000",
                "total_cache_tokens": "1200000",
                "total_output_tokens": "2500000",
                "total_input_cost": "125.00",
                "total_cache_cost": "1.20",
                "total_output_cost": "30.58",
                "total_cost": "156.78",
            }
        }
    }


class BillingSummaryPageData(BaseModel):
    items: list[BillingSummaryItem]
    total: int
    page: int
    page_size: int
    summary: BillingTotals = Field(default_factory=BillingTotals)

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [
                    {
                        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                        "key_name": "production-api-key",
                        "key_alias": "sk...87f9",
                        "date": None,
                        "model": None,
                        "total_request_count": 15000,
                        "total_input_tokens": "5000000",
                        "total_cache_tokens": "1200000",
                        "total_output_tokens": "2500000",
                        "total_input_cost": "125.00",
                        "total_cache_cost": "1.20",
                        "total_output_cost": "30.58",
                        "total_cost": "156.78",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "summary": {
                    "total_request_count": 15000,
                    "total_input_tokens": "5000000",
                    "total_cache_tokens": "1200000",
                    "total_output_tokens": "2500000",
                    "total_input_cost": "125.00",
                    "total_cache_cost": "1.20",
                    "total_output_cost": "30.58",
                    "total_cost": "156.78",
                },
            }
        }
    }
