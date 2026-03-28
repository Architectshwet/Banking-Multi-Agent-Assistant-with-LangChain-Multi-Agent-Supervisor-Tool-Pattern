from typing import Optional

from langchain_core.tools import tool
from langgraph.config import get_config

from banking.services.account_service import account_service
from banking.state.store import get_session, get_store
from banking.utils.logger import get_logger

logger = get_logger(__name__)


async def _get_context():
    config = get_config()
    configurable = config.get("configurable", {}) or {}
    thread_id = configurable.get("thread_id")
    parent_thread_id = configurable.get("parent_thread_id") or thread_id
    store = get_store()
    session_data = await get_session(store, parent_thread_id)
    return parent_thread_id, session_data


@tool
async def get_customer_profile() -> dict:
    """Use this tool when user asks about their customer profile details.
    This includes name, email, phone, segment, relationship details, and branch/country information.
    """
    logger.info("[get_customer_profile] tool_input: {}")
    thread_id, session_data = await _get_context()
    logger.info("[get_customer_profile] thread_id: %s", thread_id)
    result = await account_service.get_customer_overview(thread_id, session_data)
    logger.info("[get_customer_profile] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def get_account_details(
    account_id: Optional[str] = "",
    account_type: Optional[str] = "",
) -> dict:
    """Use this tool when user is interested to know about account ID, account name, account type, currency,
    available balance, ledger balance, or they want the full details of one account or all their accounts.

    Args:
        account_id: Account ID (example: ACC1001).
        account_type: Account type. Values are savings or checking.
    """
    logger.info(
        "[get_account_details] tool_input: %s",
        {"account_id": account_id, "account_type": account_type},
    )
    thread_id, session_data = await _get_context()
    logger.info("[get_account_details] thread_id: %s", thread_id)
    result = await account_service.get_account_details(
        thread_id,
        session_data,
        account_id=account_id,
        account_type=account_type,
    )
    logger.info("[get_account_details] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def get_recent_transactions(
    account_id: Optional[str] = "",
    days: int = 30,
) -> dict:
    """Use this tool when the user is interested in recent transactions for one account or across all their accounts.

    Args:
        account_id: Account ID (example: ACC1001).
        days: Lookback period in days (for example, 7, 30, or 90).
    """
    logger.info(
        "[get_recent_transactions] tool_input: %s",
        {"account_id": account_id, "days": days},
    )
    thread_id, session_data = await _get_context()
    logger.info("[get_recent_transactions] thread_id: %s", thread_id)
    result = await account_service.get_recent_transactions(
        thread_id,
        session_data,
        account_id=account_id,
        days=days,
    )
    logger.info("[get_recent_transactions] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def get_card_portfolio() -> dict:
    """
    Use this tool when user is interested to know card details such as card ID, account ID, card type, network,
    status, available credit, credit limit, reward points, due dates, expiry, or full details of their cards.

    """
    logger.info("[get_card_portfolio] tool_input: {}")
    thread_id, session_data = await _get_context()
    logger.info("[get_card_portfolio] thread_id: %s", thread_id)
    result = await account_service.get_card_portfolio(thread_id, session_data)
    logger.info("[get_card_portfolio] next_action: %s", result.get("next_action", "N/A"))
    return result
