from datetime import datetime
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="Application health status (ok / degraded / error)")
    app_name: str
    version: str
    timestamp: datetime
    database: str
    active_jobs: int = Field(default=0, description="Count of currently running jobs")
    hardware: dict[str, str | int | float] = Field(
        default_factory=dict,
        description="Core hardware & host runtime metrics",
    )
