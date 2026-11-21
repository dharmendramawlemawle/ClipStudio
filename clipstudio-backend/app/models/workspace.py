from typing import TYPE_CHECKING
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.video import ImportedVideo


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    videos: Mapped[list["ImportedVideo"]] = relationship(
        "ImportedVideo",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
