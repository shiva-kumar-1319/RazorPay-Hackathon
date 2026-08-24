from datetime import UTC, datetime

from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.db import check_database_health
from backend.app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Check API availability")
def health_check() -> HealthResponse:
    """Return service health and database connectivity status."""
    settings = get_settings()
    db_healthy = check_database_health()
    overall_status = "ok" if db_healthy else "degraded"

    return HealthResponse(
        status=overall_status,
        service=settings.app_name,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
        database="connected" if db_healthy else "unavailable",
    )
