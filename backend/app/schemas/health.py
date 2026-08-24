from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    timestamp: datetime
    database: Optional[str] = None
