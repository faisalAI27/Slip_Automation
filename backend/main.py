"""FastAPI entry point for mobile and other non-Streamlit clients."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.reports import router as reports_router
from backend.schemas import HealthResponse
from config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    api = FastAPI(
        title="Slip Automation API",
        version="1.0.0",
        docs_url="/docs" if settings.app_env == "development" else None,
        redoc_url=None,
    )
    if settings.api_allowed_origins:
        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @api.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse()

    api.include_router(reports_router)
    return api


app = create_app()
