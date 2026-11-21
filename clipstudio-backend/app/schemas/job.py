from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    job_type: str = Field(..., max_length=100)
    entity_type: str = Field(default="test", max_length=50)
    entity_id: str | None = Field(default=None, max_length=36)
    payload: dict | None = None


class JobRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str | None
    job_type: str
    status: str
    progress_percent: float
    current_step: str
    result_data: str | None
    error_message: str | None
    retry_count: int
    max_retries: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)



class JobProgressEvent(BaseModel):
    event_type: str = "job_progress"
    job_id: str
    status: str
    progress_percent: float
    current_step: str
    message: str
    timestamp: datetime
