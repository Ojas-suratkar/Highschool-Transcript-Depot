from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import create_engine
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add your model's MetaData object here
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app.db import Base
from app import models

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # If the URL uses an async driver (asyncpg) we create a sync engine
    # for Alembic migrations by removing the '+asyncpg' suffix. This
    # prevents async IO from being attempted during migration runs.
    url = config.get_main_option("sqlalchemy.url")
    # support alembic.ini values like 'env:ALEMBIC_URL' by resolving
    # the environment variable before attempting to parse the URL
    if isinstance(url, str) and url.startswith("env:"):
        env_var = url.split(":", 1)[1]
        resolved = os.environ.get(env_var)
        if not resolved:
            raise RuntimeError(f"Environment variable {env_var} is not set but required by alembic.ini")
        url = resolved

    # Remove +asyncpg if present (Alembic needs sync driver)
    if url and "+asyncpg" in url:
        url = url.replace("+asyncpg", "")

    # Create engine from the resolved URL
    if url:
        connectable = create_engine(url, poolclass=pool.NullPool)
    else:
        # Fallback to config-based engine creation
        connectable = engine_from_config(
            config.get_section(config.config_ini_section),
            prefix='sqlalchemy.',
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
