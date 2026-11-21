import sys
from logging.config import fileConfig
from pathlib import Path
from alembic import context
from sqlalchemy import engine_from_config, pool

# Add parent directory to path so app modules are resolvable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.models.base import Base
# Import all models to ensure they register on Base.metadata
import app.models.workspace  # noqa: F401
import app.models.video      # noqa: F401
import app.models.job        # noqa: F401

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return config.get_main_option("sqlalchemy.url") or settings.SYNC_DATABASE_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Essential for SQLite column/table alterations
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Enable WAL mode and foreign keys
        connection.execute(context.autocommit_block(None)) if hasattr(context, "autocommit_block") else None
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Essential for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
