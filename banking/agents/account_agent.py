import datetime
import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from banking.prompts.account_prompt import ACCOUNT_AGENT_SYSTEM_PROMPT_TEMPLATE
from banking.tools.account_tools import (
    get_account_details,
    get_card_portfolio,
    get_customer_profile,
    get_recent_transactions,
)


def get_current_date_string() -> str:
    return datetime.datetime.now().strftime("%B %d, %Y (%A)")


account_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.1"),
    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
)


def create_account_agent(checkpointer=None, store=None):
    current_date = get_current_date_string()
    system_prompt = ACCOUNT_AGENT_SYSTEM_PROMPT_TEMPLATE.format(current_date=current_date)

    return create_agent(
        model=account_llm,
        tools=[
            get_customer_profile,
            get_account_details,
            get_recent_transactions,
            get_card_portfolio,
        ],
        system_prompt=system_prompt,
        name="AccountAgent",
        checkpointer=checkpointer,
        store=store,
    )
