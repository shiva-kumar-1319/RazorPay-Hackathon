"""FastAPI application entry point for RecoverX."""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.agent import router as agent_router
from backend.app.api.customers import router as customers_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.decision import router as decision_router
from backend.app.api.evaluation import router as evaluation_router
from backend.app.api.events import router as events_router
from backend.app.api.execution import router as execution_router
from backend.app.api.failures import router as failures_router
from backend.app.api.health import router as health_router
from backend.app.api.prediction import router as prediction_router
from backend.app.api.recovery import router as recovery_router
from backend.app.api.simulator import router as simulator_router
from backend.app.api.transactions import router as transactions_router
from backend.app.config import get_settings
from backend.app.db import initialize_database
from backend.app.logging import configure_logging
from backend.app.services.recovery_service import recovery_orchestrator

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.auto_create_schema:
        initialize_database()
    # Ensure orchestrator event subscriptions are initialized
    _ = recovery_orchestrator
    logging.getLogger(__name__).info("Starting %s in %s (version 1.0.0)", settings.app_name, settings.app_env)
    yield
    logging.getLogger(__name__).info("Stopping %s", settings.app_name)


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="RecoverX — Autonomous AI Revenue Recovery Platform for Modern Payment Gateways. Featuring Bounded ReAct Tool-Calling Agents, Calibrated Gradient Boosted Recovery ML, Net Expected Value Optimization, Distributed Idempotent Execution, and Cryptographic SHA-256 Audit Ledgers.",
    lifespan=lifespan,
)

# CORS middleware for merchant dashboard and frontend integrations
# Enforce secure origin handling (allow_credentials=True requires explicit origins, not wildcard)
_cors_origins = settings.cors_origins
_has_wildcard = "*" in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if not _has_wildcard else ["*"],
    allow_credentials=False if _has_wildcard else True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Mount static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount API Routers
app.include_router(health_router)
app.include_router(events_router)
app.include_router(failures_router)
app.include_router(customers_router)
app.include_router(simulator_router)
app.include_router(transactions_router)
app.include_router(recovery_router)
app.include_router(execution_router)
app.include_router(prediction_router)
app.include_router(decision_router)
app.include_router(agent_router)
app.include_router(dashboard_router)
app.include_router(evaluation_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def get_dashboard_page() -> HTMLResponse:
    """Serve the interactive single-page dashboard application."""
    html_file = TEMPLATES_DIR / "dashboard.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>RecoverX Dashboard</h1><p>Dashboard template not found.</p>")


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
