from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.video import ImportedVideoRead


class UploadInitiateRequest(BaseModel):
    workspace_id: str = Field(..., description="Target workspace UUID")
    filename: str = Field(..., min_length=1, max_length=255, description="Original filename")
    file_size_bytes: int = Field(..., gt=0, description="Total expected size in bytes")


class UploadSessionRead(BaseModel):
    id: str
    workspace_id: str
    original_filename: str
    expected_size_bytes: int
    received_size_bytes: int
    status: str
    chunk_count: int
    last_chunk_index: int
    sha256: str | None = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UploadChunkResponse(BaseModel):
    upload_id: str
    received_size_bytes: int
    expected_size_bytes: int
    chunk_index: int
    is_complete: bool


class UploadCompleteRequest(BaseModel):
    confirm_duplicate: bool = Field(
        default=False,
        description="Proceed with import even if duplicate content exists in workspace",
    )


class UploadCompleteResponse(BaseModel):
    status: str  # "completed" | "duplicate_detected" | "error"
    video: ImportedVideoRead | None = None
    duplicate_video_id: str | None = None
    message: str | None = None
