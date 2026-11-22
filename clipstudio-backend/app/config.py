from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ClipStudio application settings with environment variable support."""

    APP_NAME: str = "ClipStudio"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Project directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_DIR: Path = BASE_DIR / "data"
    MEDIA_DIR: Path = STORAGE_DIR / "media"
    MEDIA_ORIGINALS_DIR: Path = MEDIA_DIR / "originals"
    MEDIA_THUMBNAILS_DIR: Path = MEDIA_DIR / "thumbnails"
    TEMP_DIR: Path = STORAGE_DIR / "temp"
    UPLOADS_TEMP_DIR: Path = TEMP_DIR / "uploads"
    THUMBNAILS_TEMP_DIR: Path = TEMP_DIR / "thumbnails"

    # SQLite Database Configuration
    DB_FILE: Path = STORAGE_DIR / "clipstudio.db"

    @property
    def DATABASE_URL(self) -> str:
        """Async database URL for aiosqlite."""
        db_path = str(self.DB_FILE).replace("\\", "/")
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        db_path = str(self.DB_FILE).replace("\\", "/")
        return f"sqlite:///{db_path}"

    # CORS origins
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Ingestion & Upload Policies (Phase 2A)
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GB default
    MIN_FREE_DISK_RESERVE_BYTES: int = 1 * 1024 * 1024 * 1024  # 1 GB minimum free disk reserve
    UPLOAD_SESSION_TTL_HOURS: int = 24
    DEFAULT_CHUNK_SIZE_BYTES: int = 1024 * 1024  # 1 MB

    # Hardware & Job Execution Policies (Intel i5-1135G7 / 16GB)
    MAX_CONCURRENT_HEAVY_JOBS: int = 1
    JOB_POLL_INTERVAL_SECONDS: float = 0.5
    DEFAULT_CPU_THREADS: int = 4

    # FFmpeg Processing Engine Configuration (Phase 2B.1)
    FFMPEG_PATH: str | None = None
    FFPROBE_PATH: str | None = None
    MAX_CONCURRENT_FFMPEG_JOBS: int = 1
    FFMPEG_SUBPROCESS_TIMEOUT_SECONDS: float = 3600.0  # 1 hour maximum per job
    FFMPEG_STDERR_MAX_BYTES: int = 256 * 1024  # 256 KB bounded circular buffer

    # Thumbnail Generation Configuration (Phase 2B.2)
    THUMBNAIL_WIDTH: int = 640
    THUMBNAIL_QUALITY: int = 2  # JPEG quality scale in ffmpeg (q:v 2 is high quality)
    THUMBNAIL_DEFAULT_TIMESTAMP_PERCENT: float = 0.10  # 10% into video
    THUMBNAIL_MIN_TIMESTAMP_SECONDS: float = 0.5
    THUMBNAIL_SUBPROCESS_TIMEOUT_SECONDS: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# Ensure required local directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
settings.MEDIA_ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
settings.MEDIA_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOADS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
settings.THUMBNAILS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
