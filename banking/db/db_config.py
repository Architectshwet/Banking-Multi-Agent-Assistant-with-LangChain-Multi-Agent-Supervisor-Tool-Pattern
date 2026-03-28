"""Database configuration helpers."""

from banking.config.settings import POSTGRESQL_URL


def get_postgres_url() -> str:
    """Get PostgreSQL connection URL."""
    if not POSTGRESQL_URL:
        raise ValueError("POSTGRESQL_URL is required")
    return POSTGRESQL_URL


def get_async_postgres_url() -> str:
    """Get async PostgreSQL connection URL."""
    return get_postgres_url()
