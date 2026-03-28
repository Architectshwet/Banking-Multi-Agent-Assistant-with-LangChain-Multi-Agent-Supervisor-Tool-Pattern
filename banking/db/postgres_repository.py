import json
import logging
from typing import Any

from banking.db.db_singleton import DatabaseSingleton

logger = logging.getLogger(__name__)

_CONVERSATION_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT 'BankingAgent',
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_history_conversation_id
ON conversation_history(conversation_id);

CREATE INDEX IF NOT EXISTS idx_conversation_history_created_at
ON conversation_history(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_history_agent
ON conversation_history(agent_name);

CREATE INDEX IF NOT EXISTS idx_conversation_history_role
ON conversation_history(role);
"""

_SESSION_STORE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_store (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(thread_id, key)
);

CREATE INDEX IF NOT EXISTS idx_session_store_thread_id ON session_store(thread_id);
CREATE INDEX IF NOT EXISTS idx_session_store_created_at ON session_store(created_at DESC);
"""

_BANKING_SCHEMA_SQL = """
DROP TABLE IF EXISTS banking_transfers CASCADE;
DROP TABLE IF EXISTS banking_payees CASCADE;
DROP TABLE IF EXISTS banking_transactions CASCADE;
DROP TABLE IF EXISTS banking_cards CASCADE;
DROP TABLE IF EXISTS banking_accounts CASCADE;
DROP TABLE IF EXISTS banking_customers CASCADE;
DROP TABLE IF EXISTS banking_service_requests CASCADE;
DROP TABLE IF EXISTS banking_faq_articles CASCADE;
DROP TABLE IF EXISTS banking_loans CASCADE;

CREATE TABLE IF NOT EXISTS banking_customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    segment TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    relationship_since DATE NOT NULL,
    preferred_branch TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'Saudi Arabia'
);

CREATE TABLE IF NOT EXISTS banking_accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES banking_customers(customer_id) ON DELETE CASCADE,
    account_type TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_number_masked TEXT NOT NULL,
    currency TEXT NOT NULL,
    available_balance NUMERIC(14, 2) NOT NULL,
    ledger_balance NUMERIC(14, 2) NOT NULL,
    status TEXT NOT NULL,
    iban_masked TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    opened_at DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS banking_cards (
    card_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES banking_customers(customer_id) ON DELETE CASCADE,
    account_id TEXT REFERENCES banking_accounts(account_id) ON DELETE SET NULL,
    card_type TEXT NOT NULL,
    network TEXT NOT NULL,
    masked_number TEXT NOT NULL,
    status TEXT NOT NULL,
    available_credit NUMERIC(14, 2),
    credit_limit NUMERIC(14, 2),
    reward_points INTEGER DEFAULT 0,
    payment_due_date DATE,
    expires_on DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS banking_transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES banking_accounts(account_id) ON DELETE CASCADE,
    transaction_type TEXT NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    currency TEXT NOT NULL,
    transfer_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    transaction_date TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS banking_payees (
    payee_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES banking_customers(customer_id) ON DELETE CASCADE,
    nickname TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    account_number_masked TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    last_used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS banking_transfers (
    transfer_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES banking_customers(customer_id) ON DELETE CASCADE,
    from_account_id TEXT NOT NULL REFERENCES banking_accounts(account_id) ON DELETE CASCADE,
    payee_id TEXT REFERENCES banking_payees(payee_id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NOT NULL,
    currency TEXT NOT NULL,
    transfer_type TEXT NOT NULL,
    category TEXT NOT NULL,
    reference_note TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_banking_accounts_customer_id ON banking_accounts(customer_id);
CREATE INDEX IF NOT EXISTS idx_banking_cards_customer_id ON banking_cards(customer_id);
CREATE INDEX IF NOT EXISTS idx_banking_transactions_account_id ON banking_transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_banking_payees_customer_id ON banking_payees(customer_id);
CREATE INDEX IF NOT EXISTS idx_banking_transfers_customer_id ON banking_transfers(customer_id);
"""


async def initialize_conversation_table():
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_CONVERSATION_HISTORY_TABLE_SQL)
        logger.info("Conversation history table initialized successfully")


async def initialize_session_store_table():
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_SESSION_STORE_TABLE_SQL)
        logger.info("Session store table initialized successfully")


async def initialize_banking_schema():
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_BANKING_SCHEMA_SQL)
        logger.info("Banking schema initialized successfully")


async def append_message_to_conversation(
    conversation_id: str,
    role: str,
    content: str,
    agent_name: str = "BankingAgent",
) -> dict[str, Any]:
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            """
            INSERT INTO conversation_history (
                conversation_id,
                agent_name,
                role,
                content,
                created_at
            )
            VALUES ($1, $2, $3, $4, NOW())
            RETURNING id, conversation_id, role, created_at
            """,
            conversation_id,
            agent_name,
            role,
            content,
        )
        return {
            "id": result["id"],
            "conversation_id": result["conversation_id"],
            "role": result["role"],
            "created_at": result["created_at"].isoformat(),
            "success": True,
        }


async def upsert_session_data(thread_id: str, key: str, value: dict[str, Any]) -> dict[str, Any]:
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        value_json = json.dumps(value)
        result = await conn.fetchrow(
            """
            INSERT INTO session_store (thread_id, key, value, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW(), NOW())
            ON CONFLICT (thread_id, key)
            DO UPDATE SET
                value = $3::jsonb,
                updated_at = NOW()
            RETURNING id, thread_id, key, created_at, updated_at
            """,
            thread_id,
            key,
            value_json,
        )
        return {
            "id": result["id"],
            "thread_id": result["thread_id"],
            "key": result["key"],
            "created_at": result["created_at"].isoformat(),
            "updated_at": result["updated_at"].isoformat(),
            "success": True,
        }


async def fetchrow(query: str, *args):
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args):
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args):
    pool = await DatabaseSingleton.get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
