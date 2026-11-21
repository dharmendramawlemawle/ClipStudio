from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ImportedVideoBase(BaseModel):
    file_name: str = Field(..., max_length=255)
    file_path: str = Field(..., max_length=500)
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    status: str = "pending"


class ImportedVideoCreate(ImportedVideoBase):
    workspace_id: str


class ImportedVideoRead(ImportedVideoBase):
    id: str
    workspace_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

