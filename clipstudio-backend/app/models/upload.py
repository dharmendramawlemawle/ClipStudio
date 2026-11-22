from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class UploadSession(Base, TimestampMixin):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        index=True,
        nullable=False,
    )  # active, completed, cancelled, expired, failed
    temporary_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_chunk_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
