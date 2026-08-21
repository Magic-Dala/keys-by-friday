from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import router
from backend.app.adk_runtime import AdkSessionReadinessProbe
from backend.app.config import Settings, get_settings
from backend.app.observability import configure_logging, install_request_logging
from backend.app.readiness import readiness_report
from backend.app.repositories.base import RepositoryUnavailableError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    session_probe: AdkSessionReadinessProbe | None = None
    database_url = settings.adk_session_database_url
    production_sqlite = bool(
        settings.app_environment == "production"
        and database_url
        and database_url.casefold().startswith("sqlite")
    )
    if (
        settings.adk_session_mode == "database"
        and database_url
        and not production_sqlite
    ):
        session_probe = AdkSessionReadinessProbe(database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            if session_probe is not None:
                await session_probe.close()

    app = FastAPI(
        title="Keys by Friday API", version="0.1.0", lifespan=lifespan
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["DELETE", "GET", "PATCH", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    install_request_logging(
        app, google_cloud_project=settings.google_cloud_project
    )
    app.include_router(router, prefix="/api")

    @app.exception_handler(RepositoryUnavailableError)
    async def repository_unavailable(
        request: Request, exc: RepositoryUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Persistence is temporarily unavailable."},
        )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    async def ready(response: Response) -> dict[str, object]:
        session_connected = (
            await session_probe.check() if session_probe is not None else None
        )
        is_ready, checks = readiness_report(
            settings, adk_session_connected=session_connected
        )
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        }

    return app


app = create_app()
