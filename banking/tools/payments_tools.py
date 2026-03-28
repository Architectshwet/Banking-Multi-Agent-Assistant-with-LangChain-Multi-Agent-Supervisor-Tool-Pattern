from typing import Literal

from langchain_core.tools import tool
from langgraph.config import get_config

from banking.services.payments_service import payments_service
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
async def list_saved_payees(
    intent: Literal["view_saved_payees_only", "transfer_fund"] = "transfer_fund",
) -> dict:
    """List saved payees for visibility and fund-transfer preparation.

    Use this tool when the user wants to view saved payees, or as Step 1 before
    `get_fund_transfer_details` so the user can select a payee nickname.

    Args:
        intent: User intent for this call. Values: `view_saved_payees_only` or `transfer_fund`.
                Default is `transfer_fund`.

    This tool requires an authenticated session (customer ID is read from session context).
    """
    logger.info("[list_saved_payees] tool_input: %s", {"intent": intent})
    thread_id, session_data = await _get_context()
    logger.info("[list_saved_payees] thread_id: %s", thread_id)
    result = await payments_service.list_saved_payees(thread_id, session_data, intent=intent)
    logger.info("[list_saved_payees] next_action: %s", result.get("next_action", "N/A"))
    return result

@tool
async def get_fund_transfer_details() -> dict:
    """Step 2 for fund transfer: collect source account, amount, and optional reference note.

    Call this after `list_saved_payees` once the user selects a payee.
    """
    logger.info("[get_fund_transfer_details] tool_input: {}")
    thread_id, session_data = await _get_context()
    logger.info("[get_fund_transfer_details] thread_id: %s", thread_id)
    result = await payments_service.get_fund_transfer_details(
        thread_id,
        session_data,
    )
    logger.info("[get_fund_transfer_details] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def initiate_fund_transfer(
    from_account_id: str,
    payee_nickname: str,
    amount: float,
    reference_note: str = "",
) -> dict:
    """Step 3 for fund transfer: send an immediate transfer to a selected saved payee.

    Call this after `list_saved_payees` and `get_fund_transfer_details`.

    Args:
        from_account_id: Source account ID from which funds should be debited. Always ask the user.
        payee_nickname: Payee nickname selected by the user from `list_saved_payees`.
        amount: Transfer amount to send. Always ask the user.
        reference_note: Optional transfer note shown in transfer history.
    """
    logger.info(
        "[initiate_fund_transfer] tool_input: %s",
        {
            "from_account_id": from_account_id,
            "payee_nickname": payee_nickname,
            "amount": amount,
            "reference_note": reference_note,
        },
    )
    thread_id, session_data = await _get_context()
    logger.info("[initiate_fund_transfer] thread_id: %s", thread_id)
    result = await payments_service.initiate_transfer(
        thread_id,
        session_data,
        from_account_id=from_account_id,
        payee_nickname=payee_nickname,
        amount=amount,
        reference_note=reference_note,
    )
    logger.info("[initiate_fund_transfer] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def create_bill_payment(
    from_account_id: str,
    biller_name: str,
    amount: float,
    category: str = "Utilities",
) -> dict:
    """Create an immediate bill payment from a selected account.

    Args:
        from_account_id: Source account ID to pay the bill from. Always ask the user.
        biller_name: Name of the biller (for example, STC, Electricity Company). Always ask the user.
        amount: Bill payment amount. Always ask the user.
        category: Bill category label (for example, Utilities, Telecom, Insurance). Always ask the user.
    """
    logger.info(
        "[create_bill_payment] tool_input: %s",
        {
            "from_account_id": from_account_id,
            "biller_name": biller_name,
            "amount": amount,
            "category": category,
        },
    )
    thread_id, session_data = await _get_context()
    logger.info("[create_bill_payment] thread_id: %s", thread_id)
    result = await payments_service.create_bill_payment(
        thread_id,
        session_data,
        from_account_id=from_account_id,
        biller_name=biller_name,
        amount=amount,
        category=category,
    )
    logger.info("[create_bill_payment] next_action: %s", result.get("next_action", "N/A"))
    return result
