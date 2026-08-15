from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router
from backend.app.config import Settings, get_settings
from backend.app.observability import configure_logging, install_request_logging
from backend.app.readiness import readiness_report


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Keys by Friday API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    install_request_logging(
        app, google_cloud_project=settings.google_cloud_project
    )
    app.include_router(router, prefix="/api")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    async def ready(response: Response) -> dict[str, object]:
        is_ready, checks = readiness_report(settings)
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        }

    return app


app = create_app()
