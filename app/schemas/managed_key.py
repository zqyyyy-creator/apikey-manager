from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


KeyStatus = Literal["active", "blocked", "revoked"]
LimitType = Literal["daily", "total"]


class CreateKeyRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "production-api-key",
                "description": "生产环境 API 调用专用 key",
            }
        }
    }


class CreateKeyData(BaseModel):
    id: str
    name: str | None
    description: str | None
    key: str
    key_alias: str
    status: KeyStatus
    created_at: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                "name": "production-api-key",
                "description": "生产环境 API 调用专用 key",
                "key": "sk-maas-000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
                "key_alias": "sk...87f9",
                "status": "active",
                "created_at": "2025-06-17T10:00:00Z",
            }
        }
    }


class ManagedKeyListItem(BaseModel):
    id: str
    name: str | None
    description: str | None
    team_id: str
    key_alias: str
    status: KeyStatus
    created_at: datetime
    blocked_reason: str | None
    blocked_at: datetime | None
    revoked_at: datetime | None


class SpendingLimitItem(BaseModel):
    id: int
    limit_type: LimitType
    amount: Decimal
    currency: str = "CNY"
    enabled: bool


class UsageSummary(BaseModel):
    today_cost: Decimal
    total_cost_7d: Decimal


class ManagedKeyDetail(ManagedKeyListItem):
    spending_limits: list[SpendingLimitItem] = Field(default_factory=list)
    usage_summary: UsageSummary | None = None


class RevokeKeyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=256)

    model_config = {
        "json_schema_extra": {
            "example": {
                "reason": "Key compromised, rotating to new key",
            }
        }
    }


class RevokeKeyData(BaseModel):
    id: str
    status: Literal["revoked"]
    revoked_at: datetime


class UnblockKeyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=256)

    model_config = {
        "json_schema_extra": {
            "example": {
                "reason": "Approved by admin after review",
            }
        }
    }


class UnblockKeyData(BaseModel):
    id: str
    status: Literal["active"]
    blocked_reason: None = None
    blocked_at: None = None
