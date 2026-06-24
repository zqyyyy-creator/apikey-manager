import asyncio
import json

import httpx
import pytest

from app.litellm_integration.client import LagProxyError, LiteLLMClient


def test_generate_key_calls_lag_proxy_with_user_header() -> None:
    captured_request = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "key": "sk-maas-secret",
                "key_hash_id": "hash_001",
                "key_alias": "sk...cret",
            },
            request=request,
        )

    async def run_test():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = LiteLLMClient(
                base_url="http://lag-proxy",
                http_client=http_client,
            )

            return await client.generate_key(
                team_id="AI_TEST_12345",
                user_id="12345",
                name="production-api-key",
                description="生产环境 API 调用专用 key",
            )

    generated = asyncio.run(run_test())

    assert generated.key == "sk-maas-secret"
    assert generated.key_hash_id == "hash_001"
    assert generated.key_alias == "sk...cret"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://lag-proxy/key/generate"
    assert captured_request.headers["x-user-id"] == "12345"

    payload = json.loads(captured_request.content)
    assert payload == {
        "team_id": "AI_TEST_12345",
        "key_alias": "production-api-key",
        "metadata": {"description": "生产环境 API 调用专用 key"},
    }


def test_generate_key_accepts_wrapped_data_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "key": "sk-maas-secret",
                    "token_id": "hash_001",
                    "key_alias": "sk...cret",
                },
                "message": "success",
            },
            request=request,
        )

    async def run_test():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = LiteLLMClient(
                base_url="http://lag-proxy",
                http_client=http_client,
            )

            return await client.generate_key(
                team_id="AI_TEST_12345",
                user_id="12345",
            )

    generated = asyncio.run(run_test())

    assert generated.key_hash_id == "hash_001"


def test_block_and_unblock_key_call_expected_paths() -> None:
    seen_paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = LiteLLMClient(
                base_url="http://lag-proxy",
                http_client=http_client,
            )

            await client.block_key(key="hash_001", user_id="12345", reason="test")
            await client.unblock_key(key="hash_001", user_id="12345")

    asyncio.run(run_test())

    assert seen_paths == ["/key/block", "/key/unblock"]


def test_lag_proxy_http_error_raises_domain_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"message": "bad gateway"}, request=request)

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = LiteLLMClient(
                base_url="http://lag-proxy",
                http_client=http_client,
            )

            with pytest.raises(LagProxyError):
                await client.get_key_info(key="hash_001", user_id="12345")

    asyncio.run(run_test())
