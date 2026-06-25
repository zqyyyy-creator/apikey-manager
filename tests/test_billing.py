from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.exceptions import AppException, ErrorCode
from app.main import app
from app.routers.billing import get_billing_service
from app.schemas.auth import AuthContext
from app.schemas.billing import BillingItem, BillingPageData, BillingTotals
from app.services.billing_service import BillingService


def auth_context() -> AuthContext:
    return AuthContext(
        client_id="maas2ss",
        user_id="12345",
        team_id="AI_TEST_12345",
        access_token="token_123",
    )


async def fake_auth_context() -> AuthContext:
    return auth_context()


async def fake_db():
    yield None


def clear_overrides() -> None:
    app.dependency_overrides.clear()


class FakeBillingService:
    async def get_key_billing(self, db, auth, key_id, **kwargs):  # noqa: ANN001
        assert auth.team_id == "AI_TEST_12345"
        assert key_id == "hash_001"
        assert kwargs["group_by"] == "date_model"
        item = BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 25),
            model="deepseek-v3",
            request_count=3,
            input_tokens=Decimal("1000"),
            cache_tokens=Decimal("600"),
            output_tokens=Decimal("250"),
            input_cost=Decimal("1.00"),
            cache_cost=Decimal("0.06"),
            output_cost=Decimal("0.50"),
            cost=Decimal("1.56"),
        )
        return BillingPageData(
            items=[item],
            total=1,
            page=1,
            page_size=20,
            summary=BillingTotals(
                total_request_count=3,
                total_input_tokens=Decimal("1000"),
                total_cache_tokens=Decimal("600"),
                total_output_tokens=Decimal("250"),
                total_input_cost=Decimal("1.00"),
                total_cache_cost=Decimal("0.06"),
                total_output_cost=Decimal("0.50"),
                total_cost=Decimal("1.56"),
            ),
        )

    async def get_billing_summary(self, db, auth, **kwargs):  # noqa: ANN001
        raise NotImplementedError


def install_router_overrides() -> None:
    app.dependency_overrides[get_current_auth_context] = fake_auth_context
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_billing_service] = lambda: FakeBillingService()


def test_key_billing_route_returns_usage_breakdown() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        response = client.get("/api/v1/keys/hash_001/billing?group_by=date_model")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    item = body["data"]["items"][0]
    assert item["input_tokens"] == "1000"
    assert item["cache_tokens"] == "600"
    assert item["output_tokens"] == "250"
    assert item["input_cost"] == "1.00"
    assert item["cache_cost"] == "0.06"
    assert item["output_cost"] == "0.50"
    assert item["cost"] == "1.56"


def test_billing_date_range_cannot_exceed_seven_days() -> None:
    service = BillingService(clickhouse_client=None)

    try:
        service._resolve_date_range(date(2026, 6, 1), date(2026, 6, 8))
    except AppException as exc:
        assert exc.code == ErrorCode.BILLING_DATE_RANGE_EXCEEDED
    else:
        raise AssertionError("Expected date range error")


def test_billing_item_summary_uses_plan_field_mapping() -> None:
    service = BillingService(clickhouse_client=None)
    items = [
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 25),
            model="deepseek-v3",
            request_count=3,
            input_tokens=Decimal("1000"),
            cache_tokens=Decimal("600"),
            output_tokens=Decimal("250"),
            input_cost=Decimal("1.00"),
            cache_cost=Decimal("0.06"),
            output_cost=Decimal("0.50"),
            cost=Decimal("1.56"),
        )
    ]

    summary = service._summarize_billing_items(items)

    assert summary.total_request_count == 3
    assert summary.total_input_tokens == Decimal("1000")
    assert summary.total_cache_tokens == Decimal("600")
    assert summary.total_output_tokens == Decimal("250")
    assert summary.total_input_cost == Decimal("1.00")
    assert summary.total_cache_cost == Decimal("0.06")
    assert summary.total_output_cost == Decimal("0.50")
    assert summary.total_cost == Decimal("1.56")


def test_billing_date_range_is_converted_to_epoch_millis() -> None:
    service = BillingService(clickhouse_client=None)

    start_ms, end_ms = service._date_range_to_millis(
        date(2026, 6, 25),
        date(2026, 6, 25),
    )

    assert start_ms == 1782345600000
    assert end_ms == 1782432000000


def test_latest_billing_rows_sql_deduplicates_changelog_by_id() -> None:
    service = BillingService(clickhouse_client=None)
    service.clickhouse_client.database = "dev_dbt_data"
    service.clickhouse_client.billing_table = "dws_para_statements_changelog"

    sql = service._latest_billing_rows_sql(extra_filters="AND resource_uuid = {key_id:String}")

    assert "argMax(used_value, _seq_id) AS used_value" in sql
    assert "GROUP BY id" in sql
    assert "HAVING _action != 'DELETE'" in sql
    assert "FROM dev_dbt_data.dws_para_statements_changelog" in sql
