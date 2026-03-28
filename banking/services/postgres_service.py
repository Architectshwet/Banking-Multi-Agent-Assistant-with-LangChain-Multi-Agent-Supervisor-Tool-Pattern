import uuid
from datetime import date, datetime, timezone

from banking.db import postgres_repository
from banking.db.db_singleton import DatabaseSingleton
from banking.sample_data.seed_banking_data import get_seed_payload
from banking.utils.logger import get_logger

logger = get_logger(__name__)


def _record_to_dict(record) -> dict:
    return dict(record) if record else {}


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Unsupported date value type: {type(value)}")


def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported datetime value type: {type(value)}")


class PostgresService:
    """Banking domain schema and query service."""

    def __init__(self):
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        await DatabaseSingleton.get_pool()
        await postgres_repository.initialize_banking_schema()
        self._initialized = True
        logger.info("Banking domain schema initialized")

    async def seed_demo_data(self, reset: bool = False) -> dict:
        await self.initialize()

        if not reset:
            existing = await postgres_repository.fetchrow(
                "SELECT EXISTS (SELECT 1 FROM banking_customers LIMIT 1) AS has_data"
            )
            has_data = bool(existing["has_data"]) if existing else False
            if has_data:
                logger.info("Demo banking seed skipped: data already exists")
                return {
                    "success": True,
                    "seeded": False,
                    "skipped": True,
                    "reset": False
                    # "counts": await self.get_data_summary(),
                }

        payload = get_seed_payload()
        pool = await DatabaseSingleton.get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                if reset:
                    await conn.execute(
                        "TRUNCATE banking_transfers, banking_transactions, banking_cards, banking_payees, "
                        "banking_accounts, banking_customers RESTART IDENTITY CASCADE"
                    )

                await conn.executemany(
                    """
                    INSERT INTO banking_customers (
                        customer_id, full_name, email, phone, segment, risk_tier,
                        relationship_since, preferred_branch, country
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        email = EXCLUDED.email,
                        phone = EXCLUDED.phone,
                        segment = EXCLUDED.segment,
                        risk_tier = EXCLUDED.risk_tier,
                        relationship_since = EXCLUDED.relationship_since,
                        preferred_branch = EXCLUDED.preferred_branch,
                        country = EXCLUDED.country
                    """,
                    [
                        (
                            item["customer_id"],
                            item["full_name"],
                            item["email"],
                            item["phone"],
                            item["segment"],
                            item["risk_tier"],
                            _as_date(item["relationship_since"]),
                            item["preferred_branch"],
                            item["country"],
                        )
                        for item in payload["customers"]
                    ],
                )

                await conn.executemany(
                    """
                    INSERT INTO banking_accounts (
                        account_id, customer_id, account_type, account_name,
                        account_number_masked, currency, available_balance,
                        ledger_balance, status, iban_masked, branch_name, opened_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (account_id) DO UPDATE SET
                        customer_id = EXCLUDED.customer_id,
                        account_type = EXCLUDED.account_type,
                        account_name = EXCLUDED.account_name,
                        account_number_masked = EXCLUDED.account_number_masked,
                        currency = EXCLUDED.currency,
                        available_balance = EXCLUDED.available_balance,
                        ledger_balance = EXCLUDED.ledger_balance,
                        status = EXCLUDED.status,
                        iban_masked = EXCLUDED.iban_masked,
                        branch_name = EXCLUDED.branch_name,
                        opened_at = EXCLUDED.opened_at
                    """,
                    [
                        (
                            item["account_id"],
                            item["customer_id"],
                            item["account_type"],
                            item["account_name"],
                            item["account_number_masked"],
                            item["currency"],
                            item["available_balance"],
                            item["ledger_balance"],
                            item["status"],
                            item["iban_masked"],
                            item["branch_name"],
                            _as_date(item["opened_at"]),
                        )
                        for item in payload["accounts"]
                    ],
                )

                await conn.executemany(
                    """
                    INSERT INTO banking_cards (
                        card_id, customer_id, account_id, card_type, network, masked_number,
                        status, available_credit, credit_limit, reward_points, payment_due_date, expires_on
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (card_id) DO UPDATE SET
                        customer_id = EXCLUDED.customer_id,
                        account_id = EXCLUDED.account_id,
                        card_type = EXCLUDED.card_type,
                        network = EXCLUDED.network,
                        masked_number = EXCLUDED.masked_number,
                        status = EXCLUDED.status,
                        available_credit = EXCLUDED.available_credit,
                        credit_limit = EXCLUDED.credit_limit,
                        reward_points = EXCLUDED.reward_points,
                        payment_due_date = EXCLUDED.payment_due_date,
                        expires_on = EXCLUDED.expires_on
                    """,
                    [
                        (
                            item["card_id"],
                            item["customer_id"],
                            item["account_id"],
                            item["card_type"],
                            item["network"],
                            item["masked_number"],
                            item["status"],
                            item["available_credit"],
                            item["credit_limit"],
                            item["reward_points"],
                            _as_date(item["payment_due_date"]),
                            _as_date(item["expires_on"]),
                        )
                        for item in payload["cards"]
                    ],
                )

                await conn.executemany(
                    """
                    INSERT INTO banking_transactions (
                        transaction_id, account_id, transaction_type, amount, currency,
                        transfer_type, category, description, transaction_date
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (transaction_id) DO UPDATE SET
                        account_id = EXCLUDED.account_id,
                        transaction_type = EXCLUDED.transaction_type,
                        amount = EXCLUDED.amount,
                        currency = EXCLUDED.currency,
                        transfer_type = EXCLUDED.transfer_type,
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        transaction_date = EXCLUDED.transaction_date
                    """,
                    [
                        (
                            item["transaction_id"],
                            item["account_id"],
                            item["transaction_type"],
                            item["amount"],
                            item["currency"],
                            item["transfer_type"],
                            item["category"],
                            item["description"],
                            _as_datetime(item["transaction_date"]),
                        )
                        for item in payload["transactions"]
                    ],
                )

                await conn.executemany(
                    """
                    INSERT INTO banking_payees (
                        payee_id, customer_id, nickname, bank_name, account_number_masked,
                        category, status, last_used_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (payee_id) DO UPDATE SET
                        customer_id = EXCLUDED.customer_id,
                        nickname = EXCLUDED.nickname,
                        bank_name = EXCLUDED.bank_name,
                        account_number_masked = EXCLUDED.account_number_masked,
                        category = EXCLUDED.category,
                        status = EXCLUDED.status,
                        last_used_at = EXCLUDED.last_used_at
                    """,
                    [
                        (
                            item["payee_id"],
                            item["customer_id"],
                            item["nickname"],
                            item["bank_name"],
                            item["account_number_masked"],
                            item["category"],
                            item["status"],
                            _as_datetime(item["last_used_at"]),
                        )
                        for item in payload["payees"]
                    ],
                )

                await conn.executemany(
                    """
                    INSERT INTO banking_transfers (
                        transfer_id, customer_id, from_account_id, payee_id, amount,
                        currency, transfer_type, category, reference_note, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (transfer_id) DO UPDATE SET
                        customer_id = EXCLUDED.customer_id,
                        from_account_id = EXCLUDED.from_account_id,
                        payee_id = EXCLUDED.payee_id,
                        amount = EXCLUDED.amount,
                        currency = EXCLUDED.currency,
                        transfer_type = EXCLUDED.transfer_type,
                        category = EXCLUDED.category,
                        reference_note = EXCLUDED.reference_note,
                        created_at = EXCLUDED.created_at
                    """,
                    [
                        (
                            item["transfer_id"],
                            item["customer_id"],
                            item["from_account_id"],
                            item["payee_id"],
                            item["amount"],
                            item["currency"],
                            item["transfer_type"],
                            item["category"],
                            item["reference_note"],
                            _as_datetime(item["created_at"]),
                        )
                        for item in payload["transfers"]
                    ],
                )

        return {
            "success": True,
            "seeded": True,
            "skipped": False,
            "seeded_at": payload["seeded_at"],
            "reset": reset,
            "counts": await self.get_data_summary(),
        }

    async def get_data_summary(self) -> dict:
        summary = {}
        tables = [
            "banking_customers",
            "banking_accounts",
            "banking_cards",
            "banking_transactions",
            "banking_payees",
            "banking_transfers",
        ]
        for table in tables:
            row = await postgres_repository.fetchrow(f"SELECT COUNT(*) AS total FROM {table}")
            summary[table] = row["total"]
        return summary

    async def get_customer(self, customer_id: str) -> dict:
        row = await postgres_repository.fetchrow(
            "SELECT * FROM banking_customers WHERE customer_id = $1",
            customer_id,
        )
        return _record_to_dict(row)

    async def get_accounts(self, customer_id: str) -> list[dict]:
        rows = await postgres_repository.fetch(
            """
            SELECT * FROM banking_accounts
            WHERE customer_id = $1
            ORDER BY account_type, opened_at
            """,
            customer_id,
        )
        return [dict(row) for row in rows]

    async def get_account(self, account_id: str) -> dict:
        row = await postgres_repository.fetchrow(
            "SELECT * FROM banking_accounts WHERE account_id = $1",
            account_id,
        )
        return _record_to_dict(row)

    async def get_cards(self, customer_id: str) -> list[dict]:
        rows = await postgres_repository.fetch(
            """
            SELECT * FROM banking_cards
            WHERE customer_id = $1
            ORDER BY card_type, masked_number
            """,
            customer_id,
        )
        return [dict(row) for row in rows]

    async def get_recent_transactions(self, account_id: str, days: int = 30) -> list[dict]:
        rows = await postgres_repository.fetch(
            """
            SELECT * FROM banking_transactions
            WHERE account_id = $1
              AND transaction_date >= NOW() - ($2 || ' days')::interval
            ORDER BY transaction_date DESC
            LIMIT 20
            """,
            account_id,
            str(days),
        )
        return [dict(row) for row in rows]

    async def get_payees(self, customer_id: str) -> list[dict]:
        rows = await postgres_repository.fetch(
            """
            SELECT * FROM banking_payees
            WHERE customer_id = $1
            ORDER BY nickname
            """,
            customer_id,
        )
        return [dict(row) for row in rows]

    async def get_payee_by_nickname(self, customer_id: str, nickname: str) -> dict:
        row = await postgres_repository.fetchrow(
            """
            SELECT * FROM banking_payees
            WHERE customer_id = $1 AND LOWER(nickname) = LOWER($2)
            """,
            customer_id,
            nickname,
        )
        return _record_to_dict(row)

    async def create_transfer(
        self,
        customer_id: str,
        from_account_id: str,
        payee_id: str | None,
        amount: float,
        currency: str,
        transfer_type: str,
        category: str,
        reference_note: str,
        created_at: str | datetime | None = None,
    ) -> dict:
        transfer_id = f"TRF-{uuid.uuid4().hex[:10].upper()}"
        created_ts = _as_datetime(created_at) if created_at else datetime.now(timezone.utc)
        row = await postgres_repository.fetchrow(
            """
            INSERT INTO banking_transfers (
                transfer_id, customer_id, from_account_id, payee_id, amount,
                currency, transfer_type, category, reference_note, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            transfer_id,
            customer_id,
            from_account_id,
            payee_id,
            amount,
            currency,
            transfer_type,
            category,
            reference_note,
            created_ts,
        )
        return dict(row)

    async def create_bill_payment(
        self,
        customer_id: str,
        from_account_id: str,
        amount: float,
        category: str,
        reference_note: str,
        created_at: str | datetime | None = None,
    ) -> dict:
        return await self.create_transfer(
            customer_id=customer_id,
            from_account_id=from_account_id,
            payee_id=None,
            amount=amount,
            currency="SAR",
            transfer_type="Bill Payment",
            category=category,
            reference_note=reference_note,
            created_at=created_at,
        )

    async def get_transfers(self, customer_id: str, transfer_id: str = "", limit: int = 5) -> list[dict]:
        if transfer_id:
            rows = await postgres_repository.fetch(
                """
                SELECT t.*, p.nickname, a.account_name
                FROM banking_transfers t
                LEFT JOIN banking_payees p ON p.payee_id = t.payee_id
                JOIN banking_accounts a ON a.account_id = t.from_account_id
                WHERE t.customer_id = $1 AND t.transfer_id = $2
                ORDER BY t.created_at DESC
                """,
                customer_id,
                transfer_id,
            )
        else:
            rows = await postgres_repository.fetch(
                """
                SELECT t.*, p.nickname, a.account_name
                FROM banking_transfers t
                LEFT JOIN banking_payees p ON p.payee_id = t.payee_id
                JOIN banking_accounts a ON a.account_id = t.from_account_id
                WHERE t.customer_id = $1
                ORDER BY t.created_at DESC
                LIMIT $2
                """,
                customer_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def adjust_account_balance(self, account_id: str, amount_delta: float):
        await postgres_repository.execute(
            """
            UPDATE banking_accounts
            SET available_balance = available_balance + $2,
                ledger_balance = ledger_balance + $2
            WHERE account_id = $1
            """,
            account_id,
            amount_delta,
        )

    async def create_transfer_transaction(
        self,
        account_id: str,
        amount: float,
        category: str,
        transfer_type: str,
        description: str,
        transaction_date: str | datetime | None = None,
    ):
        transaction_ts = _as_datetime(transaction_date) if transaction_date else datetime.now(timezone.utc)
        await postgres_repository.execute(
            """
            INSERT INTO banking_transactions (
                transaction_id, account_id, transaction_type, amount, currency,
                transfer_type, category, description, transaction_date
            )
            VALUES ($1, $2, 'Debit', $3, 'SAR', $4, $5, $6, $7)
            """,
            f"TXN-{uuid.uuid4().hex[:10].upper()}",
            account_id,
            amount,
            transfer_type,
            category,
            description,
            transaction_ts,
        )


postgres_service = PostgresService()
