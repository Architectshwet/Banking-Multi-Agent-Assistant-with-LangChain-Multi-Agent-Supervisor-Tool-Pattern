import os

from dotenv import load_dotenv
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from banking.utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None


def get_checkpointer() -> AsyncPostgresSaver | None:
    """Initialize and return the PostgreSQL checkpointer."""
    global _checkpointer, _pool

    if _checkpointer is not None:
        return _checkpointer

    db_uri = os.getenv("POSTGRESQL_URL", "").strip()
    if not db_uri:
        logger.error("POSTGRESQL_URL is required for PostgreSQL checkpointer")
        logger.warning("Continuing without persistence. Conversation history will not be saved.")
        return None

    try:
        _pool = AsyncConnectionPool(
            conninfo=db_uri,
            min_size=1,
            max_size=10,
            max_idle=60,
            max_lifetime=1800,
            reconnect_timeout=30,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            },
        )
        _checkpointer = AsyncPostgresSaver(_pool)
        logger.info("PostgreSQL checkpointer configured successfully using POSTGRESQL_URL")
        return _checkpointer
    except Exception as exc:
        logger.error("Failed to configure checkpointer: %s", exc)
        logger.warning("Continuing without persistence. Conversation history will not be saved.")
        return None


def get_pool() -> AsyncConnectionPool | None:
    return _pool


async def cleanup():
    global _pool, _checkpointer
    if _pool:
        await _pool.close()
        _pool = None
        _checkpointer = None
        logger.info("Checkpointer resources cleaned up")
