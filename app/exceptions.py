from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import success_response


class ErrorCode:
    INVALID_REQUEST = 40000
    UNAUTHENTICATED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    KEY_NOT_FOUND = 40401
    KEY_ALREADY_REVOKED = 40901
    KEY_NOT_BLOCKED = 40902
    KEY_REVOKED_CANNOT_UNBLOCK = 40903
    BILLING_DATE_RANGE_EXCEEDED = 40002
    BILLING_DATE_FORMAT_ERROR = 40003
    LIMIT_AMOUNT_INVALID = 40001
    LIMIT_NOT_FOUND = 40402
    LIMIT_TYPE_ALREADY_EXISTS = 40904
    INTERNAL_ERROR = 50000
    DATABASE_ERROR = 50001
    AUTH_CENTER_UNAVAILABLE = 50002
    BILLING_SOURCE_UNAVAILABLE = 50003


class AppException(Exception):
    def __init__(
        self,
        *,
        code: int,
        message: str,
        status_code: int,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data
        self.headers = headers


def error_response(
    *,
    code: int,
    message: str,
    status_code: int,
    data: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=success_response(data=data, message=message) | {"code": code},
        headers=headers,
    )


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        data=exc.data,
        headers=exc.headers,
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    code_by_status = {
        status.HTTP_400_BAD_REQUEST: ErrorCode.INVALID_REQUEST,
        status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
        status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
        status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    }
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(
        code=code_by_status.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
        message=message,
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        code=ErrorCode.INVALID_REQUEST,
        message="Request parameter error",
        status_code=status.HTTP_400_BAD_REQUEST,
        data={"errors": exc.errors()},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="Internal server error",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
