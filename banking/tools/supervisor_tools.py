from typing import Any

from langchain_core.tools import tool
from langgraph.config import get_config

from banking.services.account_service import account_service
from banking.state.store import get_session, get_store
from banking.utils.logger import get_logger

logger = get_logger(__name__)

_account_agent = None
_payments_agent = None


def configure_specialist_agents(account_agent, payments_agent) -> None:
    global _account_agent, _payments_agent
    _account_agent = account_agent
    _payments_agent = payments_agent


async def _get_context():
    config = get_config()
    thread_id = config.get("configurable", {}).get("thread_id")
    store = get_store()
    session_data = await get_session(store, thread_id)
    return thread_id, session_data


def _build_subagent_config(agent_scope: str) -> dict[str, Any]:
    config = get_config()
    parent_configurable = dict(config.get("configurable", {}) or {})
    parent_thread_id = str(parent_configurable.get("thread_id") or "").strip()

    if not parent_thread_id:
        return {}

    # Keep specialist memory isolated while preserving access to shared session state.
    specialist_thread_id = f"{parent_thread_id}:{agent_scope}"
    logger.info(
        "[subagent_config] scope=%s parent_thread_id=%s specialist_thread_id=%s",
        agent_scope,
        parent_thread_id,
        specialist_thread_id,
    )
    return {
        "configurable": {
            "thread_id": specialist_thread_id,
            "parent_thread_id": parent_thread_id,
        }
    }


def _extract_last_message_text(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not messages:
        return str(result)

    last_message = messages[-1]
    content = getattr(last_message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        merged = " ".join(part for part in text_parts if part)
        return merged.strip() or str(last_message)

    return str(content or last_message)


@tool
async def greeting() -> dict:
    """Use this tool to greet the user and request customer ID."""
    logger.info("[greeting] tool_input: {}")
    result = {
        "next_action": (
            "Hello, I am Amina from Aurora Digital Bank. "
            "Please share your customer ID to continue. "
            "Once the customer ID is provided, proceed by calling `authentication` tool."
        )
    }
    logger.info("[greeting] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def authentication(customer_id: str) -> dict:
    """Use this tool to authenticate the user with customer ID.

    Call this tool immediately after the user provides customer ID.

    Args:
        customer_id: Customer ID provided by the user.
    """
    logger.info("[authentication] tool_input: %s", {"customer_id": customer_id})
    thread_id, session_data = await _get_context()
    logger.info("[authentication] thread_id: %s", thread_id)
    result = await account_service.authenticate_customer(
        thread_id,
        session_data,
        customer_id=customer_id,
    )
    logger.info("[authentication] next_action: %s", result.get("next_action", "N/A"))
    return result


@tool
async def account_agent_tool(request: str) -> str:
    """Use this tool when user wants account-domain help.
    This includes profile details, account details and balances, recent transactions, and card portfolio details.

    Args:
        request: Natural-language account request using only user-provided context.
    """
    logger.info("[account_agent_tool] tool_input: %s", {"request": request})
    if _account_agent is None:
        return "Account specialist is not configured. Tell the user to retry shortly."

    result = await _account_agent.ainvoke(
        {"messages": [{"role": "user", "content": request}]},
        config=_build_subagent_config("account"),
    )
    response_text = _extract_last_message_text(result)
    response_text = f"Tell the user ONLY this from `account_agent_tool`:\n{response_text}"
    logger.info("[account_agent_tool] next_action: %s", response_text)
    return response_text


@tool
async def payments_agent_tool(request: str) -> str:
    """Use this tool when user wants payment-domain help.
    This includes saved payees, immediate fund transfers to saved payees, and bill payments.

    Args:
        request: Natural-language payment request using only user-provided context.
    """
    logger.info("[payments_agent_tool] tool_input: %s", {"request": request})
    if _payments_agent is None:
        return "Payments specialist is not configured. Tell the user to retry shortly."

    result = await _payments_agent.ainvoke(
        {"messages": [{"role": "user", "content": request}]},
        config=_build_subagent_config("payments"),
    )
    response_text = _extract_last_message_text(result)
    response_text = f"Tell the user ONLY this from `payments_agent_tool`:\n{response_text}"
    logger.info("[payments_agent_tool] next_action: %s", response_text)
    return response_text
