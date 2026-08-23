"""FastAPI application entry point for RecoverX."""

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api.events import router as events_router
from backend.app.api.health import router as health_router
from backend.app.config import get_settings
from backend.app.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("Starting %s in %s", settings.app_name, settings.app_env)
    yield
    logging.getLogger(__name__).info("Stopping %s", settings.app_name)


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Day 1 foundation for an AI revenue recovery engine.",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(events_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started_at = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("recoverx.request").info(
        "%s %s -> %s in %.2fms request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started_at) * 1000,
        request_id,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception("Unhandled application error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
