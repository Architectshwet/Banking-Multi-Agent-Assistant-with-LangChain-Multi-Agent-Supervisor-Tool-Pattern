from banking.services.postgres_service import postgres_service
from banking.state.store import get_store, set_session


class AccountService:
    """Account and card service workflows."""

    @staticmethod
    def _get_authenticated_customer_id(session_data: dict) -> str | None:
        customer_id = str(session_data.get("customer_id") or "").strip()
        return customer_id or None

    async def authenticate_customer(self, thread_id: str, session_data: dict, customer_id: str) -> dict:
        resolved_customer_id = (customer_id or "").strip()
        if not resolved_customer_id:
            return {"next_action": "Tell the user to share their customer ID to continue."}

        customer = await postgres_service.get_customer(resolved_customer_id)
        if not customer:
            return {
                "next_action": (
                    f"Tell the user a customer profile was not found for {resolved_customer_id}. "
                    "Ask them to confirm and share a valid customer ID."
                )
            }

        await set_session(get_store(), thread_id, {"customer_id": resolved_customer_id})

        return {
            "next_action": (
                f"Tell the user customer ID {resolved_customer_id} is verified. "
                "You can now help with profile details (name, email, phone, segment, relationship, branch/country), "
                "account details (IDs, type, currency, balances), recent transactions, card portfolio details, "
                "saved payees, fund transfers, and bill payments. Ask what they want to do next."
            )
        }

    async def get_customer_overview(self, thread_id: str, session_data: dict) -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        customer = await postgres_service.get_customer(resolved_customer_id)
        if not customer:
            return {
                "next_action": (
                    f"Tell the user a customer profile was not found for {resolved_customer_id}. "
                    "Ask them to confirm the customer ID before continuing."
                )
            }

        return {
            "next_action": (
                "Tell the user the requested profile details from the `customer` object. "
                "Answer only what they asked (for example: name, email, phone, segment, or relationship details)."
            ),
            "customer": customer,
        }

    async def get_account_details(
        self,
        thread_id: str,
        session_data: dict,
        account_id: str = "",
        account_type: str = "",
    ) -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        accounts = await postgres_service.get_accounts(resolved_customer_id)
        if not accounts:
            return {
                "next_action": "Tell the user no accounts are available for this customer profile."
            }

        selected_accounts = accounts
        if account_id:
            selected_account = next((account for account in accounts if account["account_id"] == account_id), None)
            if not selected_account:
                available_ids = ", ".join(account["account_id"] for account in accounts)
                return {
                    "next_action": (
                        f"Tell the user account ID {account_id} was not found, but these account IDs are available: {available_ids}. "
                        "If the user selects any of these available account IDs, proceed by calling "
                        "`get_account_details` tool with the selected account_id."
                    )
                }
            selected_accounts = [selected_account]
        elif account_type:
            normalized_type = account_type.rstrip("s").lower()
            selected_accounts = [
                account
                for account in accounts
                if account["account_type"].lower() == account_type.lower()
                or account["account_type"].lower() == normalized_type
            ]
            if not selected_accounts:
                available_types = ", ".join(sorted({account["account_type"] for account in accounts}))
                return {
                    "next_action": (
                        f"Tell the user no account was found for account type '{account_type}', but these account types are available: {available_types}. "
                        "If the user selects any of these available account types, proceed by calling "
                        "`get_account_details` tool with the selected account_type."
                    )
                }

        return {
            "next_action": (
                "Tell the user the requested account details from the `accounts` list. "
                "Answer only what they asked (for example: account_id, account_type, account_name, "
                "account_number_masked, currency, available_balance, ledger_balance, status, or iban_masked)."
            ),
            "accounts": selected_accounts,
        }

    async def get_recent_transactions(
        self,
        thread_id: str,
        session_data: dict,
        account_id: str = "",
        days: int = 30,
    ) -> dict:
        if days <= 0 or days > 365:
            return {"next_action": "Tell the user to provide a valid range between 1 and 365 days for transaction lookup."}

        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        accounts = await postgres_service.get_accounts(resolved_customer_id)
        if not accounts:
            return {
                "next_action": "Tell the user no accounts were found for this customer, so transactions cannot be retrieved.",
                "transactions": [],
            }

        if account_id:
            selected = next((account for account in accounts if account["account_id"] == account_id), None)
            if not selected:
                available_ids = ", ".join(account["account_id"] for account in accounts)
                return {
                    "next_action": (
                        f"Tell the user no transactions were found for account ID {account_id}, but these account IDs are available: {available_ids}. "
                        "If the user selects any of these available account IDs, proceed by calling "
                        "`get_recent_transactions` tool with the selected account_id."
                    )
                }
            selected_accounts = [selected]
        else:
            selected_accounts = accounts

        transactions: list[dict] = []
        for selected_account in selected_accounts:
            account_transactions = await postgres_service.get_recent_transactions(selected_account["account_id"], days=days)
            transactions.extend(account_transactions)

        transactions.sort(key=lambda item: str(item.get("transaction_date", "")), reverse=True)
        if not transactions:
            if account_id:
                next_action = (
                    f"Tell the user no recent transactions were found for account {account_id} in the last {days} days."
                )
            else:
                next_action = (
                    f"Tell the user no recent transactions were found across all accounts in the last {days} days."
                )
            return {
                "next_action": next_action,
                "transactions": [],
            }

        return {
            "next_action": (
                "Tell the user the requested transaction details from the `transactions` list. "
                "Answer only what they asked like any open-ended transaction/spending questions."
            ),
            "transactions": transactions,
        }

    async def get_card_portfolio(self, thread_id: str, session_data: dict) -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        cards = await postgres_service.get_cards(resolved_customer_id)

        if not cards:
            return {
                "next_action": "Tell the user no cards are available for this customer profile."
            }

        return {
            "next_action": (
                "Tell the user the requested card details from the `cards` list. "
                "Answer only what they asked."
            ),
            "cards": cards,
        }


account_service = AccountService()
