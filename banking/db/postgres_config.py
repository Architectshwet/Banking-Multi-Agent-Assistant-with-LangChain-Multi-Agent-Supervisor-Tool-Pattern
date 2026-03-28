import asyncio
import logging
import os
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


@dataclass
class PostgresConfig:
    """PostgreSQL configuration settings."""

    host: str = "localhost"
    port: int = 5432
    database: str = "banking_db"
    user: str = "postgres"
    password: str = "postgres"
    min_connections: int = 1
    max_connections: int = 10
    ssl_mode: str = "prefer"
    connect_timeout: int = 10
    command_timeout: int = 30
    postgres_url: str = ""

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        return cls(
            min_connections=int(os.getenv("POSTGRES_MIN_CONNECTIONS", "1")),
            max_connections=int(os.getenv("POSTGRES_MAX_CONNECTIONS", "10")),
            ssl_mode=os.getenv("POSTGRES_SSL_MODE", "prefer"),
            connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
            command_timeout=int(os.getenv("POSTGRES_COMMAND_TIMEOUT", "30")),
            postgres_url=os.getenv("POSTGRESQL_URL", ""),
        )

    def get_connection_string(self) -> str:
        if self.postgres_url:
            return self.postgres_url
        raise ValueError("POSTGRESQL_URL is required")

    def get_async_connection_string(self) -> str:
        return self.get_connection_string()

    def get_connection_params(self) -> dict[str, Any]:
        if self.postgres_url:
            return {"dsn": self.postgres_url}
        raise ValueError("POSTGRESQL_URL is required")


class PostgresConnectionManager:
    """Manages PostgreSQL connections for both sync and async operations."""

    def __init__(self, config: PostgresConfig):
        self.config = config
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    self._pool = await asyncpg.create_pool(
                        self.config.get_async_connection_string(),
                        min_size=self.config.min_connections,
                        max_size=self.config.max_connections,
                        command_timeout=self.config.command_timeout,
                        max_inactive_connection_lifetime=60.0,
                        timeout=self.config.connect_timeout,
                        statement_cache_size=0,
                    )
                    logger.info(
                        "Created PostgreSQL connection pool with %s connections",
                        self.config.max_connections,
                    )
        return self._pool

    async def close_pool(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Closed PostgreSQL connection pool")

    @asynccontextmanager
    async def get_connection(self):
        pool = await self.get_pool()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            await pool.release(conn)

    @asynccontextmanager
    async def new_connection(self):
        conn = await asyncpg.connect(
            self.config.get_async_connection_string(),
            timeout=self.config.connect_timeout,
        )
        try:
            yield conn
        finally:
            await conn.close()

    @contextmanager
    def get_sync_connection(self):
        conn = psycopg2.connect(**self.config.get_connection_params())
        try:
            yield conn
        finally:
            conn.close()

    async def execute(self, query: str, *args, **kwargs):
        async with self.get_connection() as conn:
            return await conn.execute(query, *args, timeout=self.config.command_timeout, **kwargs)

    async def fetch(self, query: str, *args, **kwargs):
        async with self.get_connection() as conn:
            return await conn.fetch(query, *args, timeout=self.config.command_timeout, **kwargs)

    async def fetchrow(self, query: str, *args, **kwargs):
        async with self.get_connection() as conn:
            return await conn.fetchrow(query, *args, timeout=self.config.command_timeout, **kwargs)

    async def fetchval(self, query: str, *args, **kwargs):
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args, timeout=self.config.command_timeout, **kwargs)

    def execute_sync(self, query: str, *args, **kwargs):
        with self.get_sync_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, *args, **kwargs)
                conn.commit()
                return cur.fetchall()

    def fetch_sync(self, query: str, *args, **kwargs):
        with self.get_sync_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, *args, **kwargs)
                return cur.fetchall()


default_config = PostgresConfig()
default_manager = PostgresConnectionManager(default_config)


async def test_connection(config: PostgresConfig | None = None) -> bool:
    if config is None:
        config = default_config

    try:
        manager = PostgresConnectionManager(config)
        async with manager.get_connection() as conn:
            result = await conn.fetchval("SELECT 1")
            logger.info("PostgreSQL connection test successful")
            return result == 1
    except Exception as exc:
        logger.error("PostgreSQL connection test failed: %s", exc)
        return False
