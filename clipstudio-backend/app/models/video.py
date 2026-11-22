from typing import TYPE_CHECKING
from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class ImportedVideo(Base, TimestampMixin):
    __tablename__ = "imported_videos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    video_codec: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    audio_codec: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    container_format: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="videos")
