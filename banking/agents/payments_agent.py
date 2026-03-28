import datetime
import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from banking.prompts.payments_prompt import PAYMENTS_AGENT_SYSTEM_PROMPT_TEMPLATE
from banking.tools.payments_tools import (
    create_bill_payment,
    get_fund_transfer_details,
    initiate_fund_transfer,
    list_saved_payees,
)


def get_current_date_string() -> str:
    return datetime.datetime.now().strftime("%B %d, %Y (%A)")


payments_llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.1"),
    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
)


def create_payments_agent(checkpointer=None, store=None):
    current_date = get_current_date_string()
    system_prompt = PAYMENTS_AGENT_SYSTEM_PROMPT_TEMPLATE.format(current_date=current_date)

    return create_agent(
        model=payments_llm,
        tools=[
            list_saved_payees,
            get_fund_transfer_details,
            initiate_fund_transfer,
            create_bill_payment,
        ],
        system_prompt=system_prompt,
        name="PaymentsAgent",
        checkpointer=checkpointer,
        store=store,
    )
