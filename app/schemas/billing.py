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


class BillingTotals(BaseModel):
    total_request_count: int = 0
    total_input_tokens: Decimal = Decimal("0")
    total_cache_tokens: Decimal = Decimal("0")
    total_output_tokens: Decimal = Decimal("0")
    total_input_cost: Decimal = Decimal("0")
    total_cache_cost: Decimal = Decimal("0")
    total_output_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")


class BillingPageData(BaseModel):
    items: list[BillingItem]
    total: int
    page: int
    page_size: int
    summary: BillingTotals = Field(default_factory=BillingTotals)


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


class BillingSummaryPageData(BaseModel):
    items: list[BillingSummaryItem]
    total: int
    page: int
    page_size: int
    summary: BillingTotals = Field(default_factory=BillingTotals)
