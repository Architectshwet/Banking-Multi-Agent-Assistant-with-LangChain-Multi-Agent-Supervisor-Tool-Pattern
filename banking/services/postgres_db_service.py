import logging
from typing import Any

from banking.db import postgres_repository
from banking.db.db_singleton import DatabaseSingleton

logger = logging.getLogger(__name__)


class PostgresDBService:
    """Service layer for PostgreSQL conversation history operations."""

    def __init__(self):
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            logger.info("PostgresDBService already initialized")
            return

        await DatabaseSingleton.get_pool()
        await postgres_repository.initialize_conversation_table()
        await postgres_repository.initialize_session_store_table()
        self._initialized = True
        logger.info("PostgresDBService initialized successfully")

    async def append_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        agent_name: str = "BankingAgent",
    ) -> dict[str, Any]:
        if not self._initialized:
            logger.warning("PostgresDBService not initialized, skipping message save")
            return {"success": False, "error": "Service not initialized"}

        try:
            return await postgres_repository.append_message_to_conversation(
                conversation_id=conversation_id,
                role=role,
                content=content,
                agent_name=agent_name,
            )
        except Exception as exc:
            logger.error("Failed to append message to conversation %s: %s", conversation_id, exc)
            return {"success": False, "error": str(exc)}

    async def close(self):
        if self._initialized:
            await DatabaseSingleton.close()
            self._initialized = False
            logger.info("PostgresDBService closed")
