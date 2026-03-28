import asyncio
import logging
import os
from typing import Optional

import asyncpg

from banking.db.postgres_config import PostgresConfig

logger = logging.getLogger(__name__)


class DatabaseSingleton:
    """Singleton class to manage a single PostgreSQL connection pool."""

    _instance: Optional["DatabaseSingleton"] = None
    _pool: asyncpg.Pool | None = None
    _lock = asyncio.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        if cls._pool is None:
            async with cls._lock:
                if cls._pool is None:
                    config = PostgresConfig.from_env()
                    postgres_url = os.getenv("POSTGRESQL_URL", "").strip()
                    if not postgres_url:
                        raise ValueError("POSTGRESQL_URL is required for database persistence")

                    logger.info("Creating PostgreSQL connection pool using POSTGRESQL_URL")
                    cls._pool = await asyncpg.create_pool(
                        dsn=postgres_url,
                        min_size=config.min_connections,
                        max_size=config.max_connections,
                        command_timeout=config.command_timeout,
                    )
                    cls._initialized = True
                    logger.info("PostgreSQL connection pool created successfully")
        return cls._pool

    @classmethod
    async def close(cls):
        if cls._pool is not None:
            async with cls._lock:
                if cls._pool is not None:
                    await cls._pool.close()
                    cls._pool = None
                    cls._initialized = False
                    logger.info("PostgreSQL connection pool closed")

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._initialized
