from typing import Any

from langgraph.store.memory import InMemoryStore

from banking.utils.logger import get_logger

logger = get_logger(__name__)

_store: InMemoryStore | None = None


def get_store() -> InMemoryStore:
    """Get or create the global store instance."""
    global _store
    if _store is None:
        _store = InMemoryStore()
        logger.info("InMemoryStore initialized for session data")
    return _store


async def get_session(store: InMemoryStore, thread_id: str) -> dict[str, Any]:
    """Get the entire session data for a thread."""
    namespace = ("session", thread_id)
    items = await store.asearch(namespace, limit=100)

    session: dict[str, Any] = {}
    for item in items:
        if item.key and item.value is not None:
            session[item.key] = item.value

    return session


async def set_session(store: InMemoryStore, thread_id: str, session: dict[str, Any]) -> None:
    """Set the entire session data for a thread."""
    namespace = ("session", thread_id)

    for key, value in session.items():
        await store.aput(namespace=namespace, key=key, value=value)

        try:
            from banking.db.postgres_session_sync import postgres_session_sync_service

            if postgres_session_sync_service.is_sync_enabled:
                await postgres_session_sync_service.sync_session_field(
                    namespace=namespace,
                    key=key,
                    value=value if isinstance(value, dict) else {"value": value},
                    thread_id=thread_id,
                )
        except Exception as exc:
            logger.warning("Failed to sync session data to PostgreSQL: %s", exc)


def reset_store():
    global _store
    _store = None
    logger.info("Store reset")


def cleanup_store():
    global _store
    _store = None
    logger.info("Store cleanup")
