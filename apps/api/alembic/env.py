"""Alembic environment.

Reads the DB URL from ``WINNOW_DATABASE_URL``. Refuses to run if unset —
we do not want accidental migrations against whatever ``sqlalchemy.url``
in alembic.ini happens to default to.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from winnow_api.db import Base  # noqa: F401  ensures models are registered

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("WINNOW_DATABASE_URL")
if not db_url:
    raise RuntimeError(
        "WINNOW_DATABASE_URL is not set. Refusing to run migrations against "
        "an implicit default. Set it in your shell or .env."
    )
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
