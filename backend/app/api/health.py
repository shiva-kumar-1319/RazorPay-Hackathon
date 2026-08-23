from datetime import UTC, datetime

from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Check API availability")
def health_check() -> HealthResponse:
    """Return process-level health. Dependency checks begin with Day 2 persistence."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
    )
