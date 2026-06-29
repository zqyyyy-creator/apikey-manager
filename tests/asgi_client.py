import asyncio
from typing import Any

import httpx


def asgi_request(app: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
    async def run_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await asyncio.wait_for(
                client.request(method, url, **kwargs),
                timeout=5,
            )

    return asyncio.run(run_request())


def asgi_get(app: Any, url: str, **kwargs: Any) -> httpx.Response:
    return asgi_request(app, "GET", url, **kwargs)


def asgi_post(app: Any, url: str, **kwargs: Any) -> httpx.Response:
    return asgi_request(app, "POST", url, **kwargs)


def asgi_patch(app: Any, url: str, **kwargs: Any) -> httpx.Response:
    return asgi_request(app, "PATCH", url, **kwargs)


def asgi_delete(app: Any, url: str, **kwargs: Any) -> httpx.Response:
    return asgi_request(app, "DELETE", url, **kwargs)
