import asyncio
import os
from typing import Any

from banking.db import postgres_repository
from banking.utils.logger import get_logger

logger = get_logger(__name__)


class PostgresSessionSyncService:
    """Service for syncing InMemoryStore data to PostgreSQL."""

    def __init__(self):
        self._enabled = os.getenv("ENABLE_SESSION_SYNC", "true").lower() == "true"

        if self._enabled:
            logger.info("PostgreSQL session sync enabled - mirroring to session_store table")
        else:
            logger.info("PostgreSQL session sync disabled - using InMemoryStore only")

    @property
    def is_sync_enabled(self) -> bool:
        return self._enabled

    async def sync_session_field(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        thread_id: str,
        max_retries: int = 2,
    ) -> bool:
        if not self._enabled:
            return False

        for attempt in range(max_retries + 1):
            try:
                await postgres_repository.upsert_session_data(thread_id=thread_id, key=key, value=value)
                if attempt == 0:
                    logger.debug("PostgreSQL sync: %s/%s", thread_id, key)
                else:
                    logger.info("PostgreSQL sync succeeded on attempt %s: %s/%s", attempt + 1, thread_id, key)
                return True
            except Exception as exc:
                if attempt < max_retries:
                    delay = 0.5 * (attempt + 1)
                    logger.warning(
                        "PostgreSQL sync attempt %s/%s failed: %s. Retrying in %ss...",
                        attempt + 1,
                        max_retries + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "PostgreSQL sync failed after %s attempts: %s/%s - %s",
                        max_retries + 1,
                        thread_id,
                        key,
                        exc,
                    )
                    return False

        return False


postgres_session_sync_service = PostgresSessionSyncService()
