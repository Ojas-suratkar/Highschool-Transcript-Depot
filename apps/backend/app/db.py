import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Load environment variables from .env file
load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    # helpful default for local dev
    DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/transcripts'

# Pool hardening to avoid "UnixTransport closed / the handler is closed" errors.
# Cloud SQL (and the unix-socket proxy) drop idle connections; a pooled-but-dead
# connection then raises that asyncpg error on next use.
# - pool_pre_ping: validate (SELECT 1) before handing out a connection.
# - pool_recycle: proactively discard connections older than 15 min, well under
#   Cloud SQL's idle timeout, so we never reuse a server-closed socket.
# - Larger pool: batch extraction holds a session per concurrent file for the
#   full Doc AI + Gemini + reconciliation run, while the UI simultaneously polls
#   several heavy endpoints. A 30-connection pool was exhausted under that load
#   (QueuePool timeout), stalling the batch. 50+30 = 80 max per instance.
#   Cloud SQL max_connections = 100, so the service is pinned to max-instances=1
#   (the batch runs on a single instance anyway) to keep total under the limit.
# - pool_timeout raised to 60 s so a brief connection spike waits instead of
#   failing the in-flight extraction.
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_recycle=900,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "50")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "30")),
    pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "60")),
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
Base = declarative_base()

# Synchronous engine/session for the classifier-training pipeline (Document AI
# LRO polling + onboarding sync run in sync workers/threads). Small dedicated
# pool so it never competes with the async pool above.
from sqlalchemy import create_engine as _create_sync_engine  # noqa: E402

_SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg")
sync_engine = _create_sync_engine(
    _SYNC_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=900,
    pool_size=int(os.environ.get("DB_SYNC_POOL_SIZE", "5")),
    max_overflow=int(os.environ.get("DB_SYNC_MAX_OVERFLOW", "5")),
)
SessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
