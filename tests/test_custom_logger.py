import asyncio
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
