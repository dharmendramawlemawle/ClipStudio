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
    TEMP_DIR: Path = STORAGE_DIR / "temp"

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

    # Hardware & Job Execution Policies (Intel i5-1135G7 / 16GB)
    MAX_CONCURRENT_HEAVY_JOBS: int = 1
    JOB_POLL_INTERVAL_SECONDS: float = 0.5
    DEFAULT_CPU_THREADS: int = 4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# Ensure required local directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
