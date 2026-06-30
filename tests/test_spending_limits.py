import asyncio
from datetime import datetime
from decimal import Decimal

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.litellm_integration.budget_sync import BudgetSyncService
from app.main import app
from app.models.managed_key import ManagedKey, ManagedKeyStatus
from app.models.spending_limit import SpendingLimit, SpendingLimitType
from app.routers.spending_limits import get_spending_limit_service
from app.schemas.auth import AuthContext
from app.schemas.spending_limit import SpendingLimitData, SpendingLimitListData
from app.services.budget_spend_sync_service import BudgetSpendSyncService
from tests.asgi_client import asgi_delete, asgi_get, asgi_patch, asgi_post


def auth_context() -> AuthContext:
    return AuthContext(client_id="maas2ss", user_id="12345", team_id="AI_TEST_12345", access_token="token_123")


async def fake_auth_context() -> AuthContext:
    return auth_context()


async def fake_db():
    yield None


def clear_overrides() -> None:
    app.dependency_overrides.clear()


async def fake_spending_limit_service() -> "FakeSpendingLimitService":
    return FakeSpendingLimitService()


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
    app.dependency_overrides[get_spending_limit_service] = fake_spending_limit_service


def test_spending_limit_routes_return_spec_shapes() -> None:
    install_router_overrides()

    try:
        create_response = asgi_post(
            app,
            "/api/v1/keys/hash_001/limits",
            json={
                "limit_type": "daily",
                "amount": "100.00",
                "currency": "CNY",
                "enabled": True,
            },
        )
        list_response = asgi_get(app, "/api/v1/keys/hash_001/limits")
        update_response = asgi_patch(
            app,
            "/api/v1/keys/hash_001/limits/101",
            json={"amount": "200.00", "enabled": False},
        )
        delete_response = asgi_delete(app, "/api/v1/keys/hash_001/limits/101")
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
            "max_budget": Decimal("1000.00"),
            "clear_max_budget": False,
            "clear_budget_duration": True,
            "budget_limits": [
                {"budget_duration": "1d", "max_budget": "100.00"},
                {"budget_duration": "1w", "max_budget": "500.00"},
                {"budget_duration": "1mo", "max_budget": "1500.00"},
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


def test_budget_spend_sync_uses_key_creation_date_for_total_spend() -> None:
    seen_ranges = []

    class FakeBudgetSpendSyncService(BudgetSpendSyncService):
        async def _sum_cost_for_range(self, **kwargs):  # noqa: ANN003, ANN201
            seen_ranges.append((kwargs["start_date"], kwargs["end_date"]))
            return Decimal("0")

    managed_key = ManagedKey(
        key_hash_id="hash_001",
        team_id="AI_TEST_12345",
        key_alias="sk-...abcd",
        status=ManagedKeyStatus.ACTIVE,
        created_at=datetime(2026, 6, 25, 10, 0, 0),
    )
    total_limit = SpendingLimit(
        key_hash_id="hash_001",
        limit_type=SpendingLimitType.TOTAL,
        amount=Decimal("1000.00"),
        currency="CNY",
        enabled=True,
    )

    service = FakeBudgetSpendSyncService()
    data = asyncio.run(service._build_key_sync_data(managed_key, [total_limit]))

    assert data.key_hash_id == "hash_001"
    assert seen_ranges[0][0].isoformat() == "2026-06-25"
