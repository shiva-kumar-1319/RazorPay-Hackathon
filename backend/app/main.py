"""FastAPI application entry point for RecoverX."""

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.customers import router as customers_router
from backend.app.api.events import router as events_router
from backend.app.api.health import router as health_router
from backend.app.api.recovery import router as recovery_router
from backend.app.api.simulator import router as simulator_router
from backend.app.api.transactions import router as transactions_router
from backend.app.config import get_settings
from backend.app.db import initialize_database
from backend.app.logging import configure_logging
from backend.app.services.recovery_service import recovery_orchestrator


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.auto_create_schema:
        initialize_database()
    # Ensure orchestrator event subscriptions are initialized
    _ = recovery_orchestrator
    logging.getLogger(__name__).info("Starting %s in %s (version 0.5.0)", settings.app_name, settings.app_env)
    yield
    logging.getLogger(__name__).info("Stopping %s", settings.app_name)


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="Day 6 Transaction & Customer Intelligence for RecoverX AI Revenue Recovery Engine.",
    lifespan=lifespan,
)

# CORS middleware for merchant dashboard and frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(events_router)
app.include_router(customers_router)
app.include_router(simulator_router)
app.include_router(transactions_router)
app.include_router(recovery_router)


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
