"""Alembic env for fabrik-claim-validator.

Migrations are hand-written DDL (``op.execute``) to keep the asyncpg-only
runtime stack. We do not load SQLAlchemy ORM metadata here.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Load .env.local if present (WSL dev convenience). Never overrides real env.
for candidate in (".env.local", ".env"):
    if os.path.exists(candidate):
        load_dotenv(candidate, override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL is required for alembic migrations")
    # Alembic uses sync psycopg (v3); rewrite async/default drivers accordingly.
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


config.set_main_option("sqlalchemy.url", _resolve_db_url())

target_metadata = None  # No ORM — migrations are hand-written DDL.


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
