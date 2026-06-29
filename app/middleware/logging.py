import time
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        logger = structlog.get_logger()
        headers = MutableHeaders(scope=scope)
        trace_id = headers.get("x-trace-id") or str(uuid4())
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        started_at = time.perf_counter()
        status_code = 500

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        async def send_with_trace_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers["x-trace-id"] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_id)
        except Exception:
            logger.exception(
                "request_failed",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "request_completed",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
