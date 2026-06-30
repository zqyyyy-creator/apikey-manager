import asyncio
import json
import sys
from types import SimpleNamespace

from app.litellm_integration.custom_logger import MaasCustomLogger


def test_custom_logger_extracts_key_hash_id_from_user_api_key_dict() -> None:
    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    key_hash_id = callback._extract_key_hash_id(
        {"user_api_key_dict": {"token": "hash_001"}}
    )

    assert key_hash_id == "hash_001"


def test_custom_logger_prefers_explicit_metadata_key_hash_id() -> None:
    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    key_hash_id = callback._extract_key_hash_id(
        {
            "user_api_key_dict": {"token": "local_gateway_master_key"},
            "litellm_params": {"metadata": {"key_hash_id": "hash_001"}},
        }
    )

    assert key_hash_id == "hash_001"


def test_custom_logger_extracts_usage_from_openai_like_response() -> None:
    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=500),
        )
    )

    usage = callback._extract_usage(response)

    assert usage == {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_tokens": 500,
    }


def test_custom_logger_calculates_spend_delta_and_replaces_response_cost() -> None:
    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )
    kwargs = {
        "response_cost": 0.01,
        "standard_logging_object": {"response_cost": 0.01},
    }

    adjustment = callback._calculate_spend_adjustment(kwargs, {"cost": "0.052"})

    assert adjustment == {
        "maas_cost": 0.052,
        "default_cost": 0.01,
        "delta_cost": 0.041999999999999996,
    }
    assert kwargs["response_cost"] == 0.052
    assert kwargs["standard_logging_object"]["response_cost"] == 0.052
    assert kwargs["_maas_spend_adjusted"] is True


def test_custom_logger_spend_delta_is_idempotent() -> None:
    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    adjustment = callback._calculate_spend_adjustment(
        {"_maas_spend_adjusted": True, "response_cost": 0.01},
        {"cost": "0.052"},
    )

    assert adjustment is None


def test_custom_logger_success_event_calls_cost_api_for_managed_key() -> None:
    seen_request = None

    class FakeLogger(MaasCustomLogger):
        async def _fetch_cost(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal seen_request
            seen_request = kwargs
            return {
                "managed": True,
                "cost": "0.0015",
                "currency": "CNY",
                "charge_detail": {
                    "input_cost": "0.001",
                    "output_cost": "0.0004",
                    "cache_cost": "0.0001",
                },
            }

    callback = FakeLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
        realtime_cost_enabled=True,
    )
    response = SimpleNamespace(
        model="deepseek-v3",
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=500),
        ),
    )

    asyncio.run(
        callback.async_log_success_event(
            {"model": "deepseek-v3", "user_api_key_dict": {"token": "hash_001"}},
            response,
            None,
            None,
        )
    )

    assert seen_request == {
        "key_hash_id": "hash_001",
        "model": "deepseek-v3",
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_tokens": 500,
    }


def test_custom_logger_success_event_syncs_managed_spend_delta() -> None:
    seen_adjustment = None

    class FakeLogger(MaasCustomLogger):
        async def _fetch_cost(self, **kwargs):  # noqa: ANN003, ANN201
            return {
                "managed": True,
                "cost": "0.052",
                "currency": "CNY",
                "charge_detail": {
                    "input_cost": "0.040",
                    "output_cost": "0.010",
                    "cache_cost": "0.002",
                },
            }

        async def _apply_spend_adjustment(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal seen_adjustment
            seen_adjustment = kwargs

    callback = FakeLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
        realtime_cost_enabled=True,
    )
    response = SimpleNamespace(
        model="deepseek-v3",
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=500),
        ),
    )

    asyncio.run(
        callback.async_log_success_event(
            {
                "model": "deepseek-v3",
                "user_api_key_dict": {"token": "hash_001"},
                "response_cost": 0.01,
            },
            response,
            None,
            None,
        )
    )

    assert seen_adjustment is not None
    assert seen_adjustment["response_cost"] == 0.041999999999999996


def test_custom_logger_skips_when_key_hash_id_is_missing() -> None:
    class FakeLogger(MaasCustomLogger):
        async def _fetch_cost(self, **kwargs):  # noqa: ANN003, ANN201
            raise AssertionError("cost API should not be called")

    callback = FakeLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    asyncio.run(callback.async_log_success_event({}, SimpleNamespace(), None, None))


def test_custom_logger_default_mode_neutralizes_managed_key_default_cost() -> None:
    seen_adjustment = None
    cost_api_called = False

    class FakeLogger(MaasCustomLogger):
        async def _fetch_managed_status(self, **kwargs):  # noqa: ANN003, ANN201
            return {"managed": True}

        async def _fetch_cost(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal cost_api_called
            cost_api_called = True
            raise AssertionError("cost API should not be called")

        async def _apply_spend_adjustment(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal seen_adjustment
            seen_adjustment = kwargs

    callback = FakeLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    asyncio.run(
        callback.async_log_success_event(
            {
                "model": "deepseek-v3",
                "user_api_key_dict": {"token": "hash_001"},
                "response_cost": 0.01,
                "standard_logging_object": {"response_cost": 0.01},
            },
            SimpleNamespace(model="deepseek-v3"),
            None,
            None,
        )
    )

    assert cost_api_called is False
    assert seen_adjustment is not None
    assert seen_adjustment["response_cost"] == -0.01


def test_custom_logger_default_mode_leaves_non_managed_key_on_litellm_default() -> None:
    adjustment_called = False

    class FakeLogger(MaasCustomLogger):
        async def _fetch_managed_status(self, **kwargs):  # noqa: ANN003, ANN201
            return {"managed": False}

        async def _apply_spend_adjustment(self, **kwargs):  # noqa: ANN003, ANN201
            nonlocal adjustment_called
            adjustment_called = True

    callback = FakeLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    asyncio.run(
        callback.async_log_success_event(
            {
                "model": "deepseek-v3",
                "user_api_key_dict": {"token": "hash_001"},
                "response_cost": 0.01,
            },
            SimpleNamespace(model="deepseek-v3"),
            None,
            None,
        )
    )

    assert adjustment_called is False


def test_custom_logger_starts_budget_sync_when_initialized_inside_event_loop() -> None:
    started = False

    class FakeLogger(MaasCustomLogger):
        async def _budget_sync_loop(self):  # noqa: ANN201
            nonlocal started
            started = True

    async def run() -> MaasCustomLogger:
        callback = FakeLogger(
            maas_api_url="http://maas-api",
            internal_api_key="internal-key",
            budget_sync_enabled=True,
        )
        await asyncio.sleep(0)
        return callback

    callback = asyncio.run(run())

    assert started is True
    assert callback._budget_sync_task is not None
    assert callback._budget_sync_task.done()


def test_custom_logger_applies_budget_sync_to_litellm_state(monkeypatch) -> None:
    class FakePrismaVerificationToken:
        def __init__(self) -> None:
            self.update_call = None

        async def update(self, **kwargs):  # noqa: ANN003, ANN201
            self.update_call = kwargs
            return {
                "token": "hash_001",
                "spend": kwargs["data"]["spend"],
            }

    class FakePrismaDb:
        def __init__(self) -> None:
            self.litellm_verificationtoken = FakePrismaVerificationToken()

    class FakePrismaClient:
        def __init__(self) -> None:
            self.db = FakePrismaDb()

    class FakeUserApiKeyCache:
        def __init__(self) -> None:
            self.value = None

        async def async_get_cache(self, key):  # noqa: ANN001, ANN201
            return {"token": key}

        async def async_set_cache(self, key, value):  # noqa: ANN001, ANN201
            self.value = (key, value)

    class FakeMemoryCache:
        def __init__(self) -> None:
            self.values = {}

        def set_cache(self, key, value, **kwargs):  # noqa: ANN001, ANN003
            self.values[key] = value

    class FakeRedisCache:
        def __init__(self) -> None:
            self.values = {}

        async def async_set_cache(self, key, value, **kwargs):  # noqa: ANN001, ANN003
            self.values[key] = value

    class FakeSpendCounterCache:
        def __init__(self) -> None:
            self.in_memory_cache = FakeMemoryCache()
            self.redis_cache = FakeRedisCache()

    prisma_client = FakePrismaClient()
    user_api_key_cache = FakeUserApiKeyCache()
    spend_counter_cache = FakeSpendCounterCache()
    monkeypatch.setitem(
        sys.modules,
        "litellm.proxy.proxy_server",
        SimpleNamespace(
            prisma_client=prisma_client,
            user_api_key_cache=user_api_key_cache,
            spend_counter_cache=spend_counter_cache,
        ),
    )

    callback = MaasCustomLogger(
        maas_api_url="http://maas-api",
        internal_api_key="internal-key",
    )

    asyncio.run(
        callback._apply_key_budget_sync(
            {
                "key_hash_id": "hash_001",
                "spend": "123.45",
                "max_budget": "1000.00",
                "budget_duration": None,
                "budget_limits": [
                    {
                        "budget_duration": "1d",
                        "max_budget": "100.00",
                        "spend": "12.50",
                    }
                ],
                "blocked": False,
            }
        )
    )

    update_data = prisma_client.db.litellm_verificationtoken.update_call["data"]
    assert update_data["spend"] == 123.45
    assert update_data["max_budget"] == 1000.0
    assert json.loads(update_data["budget_limits"]) == [
        {"budget_duration": "1d", "max_budget": 100.0}
    ]
    assert spend_counter_cache.in_memory_cache.values["spend:key:hash_001"] == 123.45
    assert (
        spend_counter_cache.in_memory_cache.values["spend:key:hash_001:window:1d"]
        == 12.5
    )
    assert user_api_key_cache.value[0] == "hash_001"
