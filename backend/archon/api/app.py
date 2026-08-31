"""FastAPI application factory with structured error handling (spec sections 47, 54)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from archon import __version__
from archon.api.routers import archaeology, architecture, repositories, runs, scoring, source
from archon.config import get_settings
from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import configure_logging, get_logger

log = get_logger("archon.api")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    settings.ensure_dirs()

    app = FastAPI(
        title="ARCHON API",
        version=__version__,
        description="AI Software Archaeologist & Self-Healing Legacy Code Platform",
    )

    @app.exception_handler(ArchonError)
    async def _archon_error(_request: Request, exc: ArchonError) -> JSONResponse:
        if exc.http_status >= 500:
            log.error("archon error", extra={"extra_fields": exc.to_dict()})
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.VALIDATION.value,
                    "message": "request validation failed",
                    "context": {"errors": exc.errors()},
                    "recoverability": Recoverability.NON_RECOVERABLE.value,
                    "suggested_action": "Fix the request payload and retry.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL.value,
                    "message": "internal server error",
                    "context": {},
                    "recoverability": Recoverability.NON_RECOVERABLE.value,
                    "suggested_action": "Check server logs; this is a bug.",
                }
            },
        )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(repositories.router)
    app.include_router(runs.router)
    app.include_router(source.router)
    app.include_router(architecture.router)
    app.include_router(archaeology.router)
    app.include_router(scoring.router)
    return app


app = create_app()
