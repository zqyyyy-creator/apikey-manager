from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_current_auth_context
from app.schemas.auth import AuthContext
from app.schemas.common import ApiResponse, success_response

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/auth", response_model=ApiResponse[AuthContext])
async def debug_auth(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> dict[str, object]:
    return success_response(auth.model_dump())
