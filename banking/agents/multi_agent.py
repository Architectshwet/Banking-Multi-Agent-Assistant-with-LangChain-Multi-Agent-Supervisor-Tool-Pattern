import datetime
import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from banking.agents.account_agent import create_account_agent
from banking.agents.payments_agent import create_payments_agent
from banking.prompts.main_prompt import MAIN_AGENT_SYSTEM_PROMPT_TEMPLATE
from banking.state.checkpointer import get_checkpointer
from banking.state.store import get_store
from banking.tools.supervisor_tools import (
    account_agent_tool,
    authentication,
    configure_specialist_agents,
    greeting,
    payments_agent_tool,
)
from banking.utils.logger import get_logger

logger = get_logger(__name__)


def get_current_date_string() -> str:
    return datetime.datetime.now().strftime("%B %d, %Y (%A)")


supervisor_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.1"),
    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
)


def create_banking_supervisor_agent(use_memory_checkpointer: bool = False):
    if use_memory_checkpointer:
        supervisor_checkpointer = MemorySaver()
        account_checkpointer = MemorySaver()
        payments_checkpointer = MemorySaver()
        logger.info("Using in-memory checkpointers for supervisor and specialists")
    else:
        supervisor_checkpointer = get_checkpointer()
        account_checkpointer = get_checkpointer()
        payments_checkpointer = get_checkpointer()
        logger.info("Using PostgreSQL checkpointers for supervisor and specialists")

    store = get_store()

    account_agent = create_account_agent(checkpointer=account_checkpointer, store=store)
    payments_agent = create_payments_agent(checkpointer=payments_checkpointer, store=store)
    configure_specialist_agents(account_agent, payments_agent)

    current_date = get_current_date_string()
    system_prompt = MAIN_AGENT_SYSTEM_PROMPT_TEMPLATE.format(current_date=current_date)

    banking_supervisor = create_agent(
        model=supervisor_llm,
        tools=[
            greeting,
            authentication,
            account_agent_tool,
            payments_agent_tool,
        ],
        system_prompt=system_prompt,
        name="BankingSupervisor",
        checkpointer=supervisor_checkpointer,
        store=store,
    )

    logger.info("Banking Supervisor Agent compiled successfully")
    return banking_supervisor


def create_banking_supervisor_agent_dev():
    return create_banking_supervisor_agent(use_memory_checkpointer=True)
