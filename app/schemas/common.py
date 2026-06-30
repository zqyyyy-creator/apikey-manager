from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(description="Business response code. 0 means success.")
    data: T | None = Field(default=None, description="Response payload.")
    message: str = Field(description="Human-readable response message.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "code": 0,
                    "data": {},
                    "message": "success",
                },
                {
                    "code": 40000,
                    "data": None,
                    "message": "Request parameter error",
                },
            ]
        }
    }


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def success_response(data: T | None = None, message: str = "success") -> dict[str, object]:
    return {
        "code": 0,
        "data": data,
        "message": message,
    }
