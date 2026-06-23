import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.config import get_settings
from app.middleware.logging import RequestLoggingMiddleware, configure_logging
from app.routers import debug, health


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    enable_docs = settings.enable_docs

    app = FastAPI(
        title="MaaS API",
        version="1.0.0",
        description=(
            "MaaS gateway key management API. "
            "All /api/v1/* endpoints require OAuth2 Bearer authentication "
            "and x-user-id header."
        ),
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(health.router)
    app.include_router(debug.router)

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = openapi_schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Paste the OAuth2 access_token here.",
        }
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()


def run() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
