from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.litellm_integration.budget_sync import BudgetSyncService
from app.main import app
from app.models.spending_limit import SpendingLimit, SpendingLimitType
from app.routers.spending_limits import get_spending_limit_service
from app.schemas.auth import AuthContext
from app.schemas.spending_limit import SpendingLimitData, SpendingLimitListData


def auth_context() -> AuthContext:
    return AuthContext(client_id="maas2ss", user_id="12345", team_id="AI_TEST_12345", access_token="token_123")


async def fake_auth_context() -> AuthContext:
    return auth_context()


async def fake_db():
    yield None


def clear_overrides() -> None:
    app.dependency_overrides.clear()


class FakeSpendingLimitService:
    async def create_limit(self, db, auth, key_id, request):  # noqa: ANN001
        assert key_id == "hash_001"
        assert auth.user_id == "12345"
        assert request.limit_type == "daily"
        return SpendingLimitData(
            id=101,
            key_id=key_id,
            limit_type=request.limit_type,
            amount=request.amount,
            currency=request.currency,
            enabled=request.enabled,
            created_at=datetime(2026, 6, 25, 10, 0, 0),
            updated_at=datetime(2026, 6, 25, 10, 0, 0),
        )

    async def list_limits(self, db, auth, key_id):  # noqa: ANN001
        return SpendingLimitListData(
            items=[
                SpendingLimitData(
                    id=101,
                    key_id=key_id,
                    limit_type="daily",
                    amount=Decimal("100.00"),
                    currency="CNY",
                    enabled=True,
                    created_at=datetime(2026, 6, 25, 10, 0, 0),
                    updated_at=datetime(2026, 6, 25, 10, 0, 0),
                )
            ]
        )

    async def update_limit(self, db, auth, key_id, limit_id, request):  # noqa: ANN001
        assert limit_id == 101
        return SpendingLimitData(
            id=limit_id,
            key_id=key_id,
            limit_type="daily",
            amount=request.amount,
            currency="CNY",
            enabled=request.enabled,
            created_at=datetime(2026, 6, 25, 10, 0, 0),
            updated_at=datetime(2026, 6, 25, 12, 0, 0),
        )

    async def delete_limit(self, db, auth, key_id, limit_id):  # noqa: ANN001
        assert key_id == "hash_001"
        assert limit_id == 101


def install_router_overrides() -> None:
    app.dependency_overrides[get_current_auth_context] = fake_auth_context
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_spending_limit_service] = lambda: FakeSpendingLimitService()


def test_spending_limit_routes_return_spec_shapes() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        create_response = client.post(
            "/api/v1/keys/hash_001/limits",
            json={
                "limit_type": "daily",
                "amount": "100.00",
                "currency": "CNY",
                "enabled": True,
            },
        )
        list_response = client.get("/api/v1/keys/hash_001/limits")
        update_response = client.patch(
            "/api/v1/keys/hash_001/limits/101",
            json={"amount": "200.00", "enabled": False},
        )
        delete_response = client.delete("/api/v1/keys/hash_001/limits/101")
    finally:
        clear_overrides()

    assert create_response.status_code == 201
    assert create_response.json()["data"]["limit_type"] == "daily"
    assert create_response.json()["data"]["amount"] == "100.00"

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["id"] == 101

    assert update_response.status_code == 200
    assert update_response.json()["data"]["amount"] == "200.00"
    assert update_response.json()["data"]["enabled"] is False

    assert delete_response.status_code == 200
    assert delete_response.json() == {"code": 0, "data": None, "message": "success"}


class FakeLiteLLMClient:
    def __init__(self) -> None:
        self.calls = []

    async def update_key(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return {"ok": True}


def make_limit(
    limit_type: SpendingLimitType,
    amount: Decimal,
    *,
    enabled: bool = True,
) -> SpendingLimit:
    return SpendingLimit(
        id=1,
        key_hash_id="hash_001",
        limit_type=limit_type,
        amount=amount,
        currency="CNY",
        enabled=enabled,
    )


def test_budget_sync_maps_multiple_periods_to_budget_limits() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[
                make_limit(SpendingLimitType.DAILY, Decimal("100.00")),
                make_limit(SpendingLimitType.WEEKLY, Decimal("500.00")),
                make_limit(SpendingLimitType.MONTHLY, Decimal("1500.00")),
                make_limit(SpendingLimitType.TOTAL, Decimal("1000.00")),
            ],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "clear_max_budget": True,
            "clear_budget_duration": True,
            "budget_limits": [
                {"budget_duration": "1d", "max_budget": "100.00"},
                {"budget_duration": "1w", "max_budget": "500.00"},
                {"budget_duration": "1mo", "max_budget": "1500.00"},
                {"budget_duration": None, "max_budget": "1000.00"},
            ],
        }
    ]


def test_budget_sync_maps_single_daily_limit_without_empty_budget_limits() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[make_limit(SpendingLimitType.DAILY, Decimal("100.00"))],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "max_budget": Decimal("100.00"),
            "budget_duration": "1d",
        }
    ]


def test_budget_sync_maps_single_weekly_limit_without_empty_budget_limits() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[make_limit(SpendingLimitType.WEEKLY, Decimal("500.00"))],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "max_budget": Decimal("500.00"),
            "budget_duration": "1w",
        }
    ]


def test_budget_sync_maps_single_monthly_limit_without_empty_budget_limits() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[make_limit(SpendingLimitType.MONTHLY, Decimal("1500.00"))],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "max_budget": Decimal("1500.00"),
            "budget_duration": "1mo",
        }
    ]


def test_budget_sync_maps_single_total_limit_without_empty_budget_limits() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[make_limit(SpendingLimitType.TOTAL, Decimal("1000.00"))],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "max_budget": Decimal("1000.00"),
            "clear_budget_duration": True,
        }
    ]


def test_budget_sync_clears_budget_when_no_limits_enabled() -> None:
    import asyncio

    client = FakeLiteLLMClient()
    service = BudgetSyncService(litellm_client=client)

    asyncio.run(
        service.sync_limits(
            key_hash_id="hash_001",
            user_id="12345",
            access_token="token_123",
            limits=[make_limit(SpendingLimitType.DAILY, Decimal("100.00"), enabled=False)],
        )
    )

    assert client.calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
            "clear_max_budget": True,
            "clear_budget_duration": True,
        }
    ]
