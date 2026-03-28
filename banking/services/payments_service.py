from datetime import datetime, timezone

from banking.services.postgres_service import postgres_service
from banking.state.store import get_store, set_session


class PaymentsService:
    """Payments and transfer workflows."""

    @staticmethod
    def _get_authenticated_customer_id(session_data: dict) -> str | None:
        customer_id = str(session_data.get("customer_id") or "").strip()
        return customer_id or None

    async def list_saved_payees(self, thread_id: str, session_data: dict, intent: str = "transfer_fund") -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        payees = await postgres_service.get_payees(resolved_customer_id)
        if not payees:
            return {
                "next_action": "Tell the user no saved payees were found for this customer.",
                "payees": [],
            }

        normalized_intent = (intent or "transfer_fund").strip().lower()
        payee_lines = [
            f"- {payee.get('nickname', '')} ({payee.get('bank_name', '')}, {payee.get('account_number_masked', '')})"
            for payee in payees
        ]
        payee_list_text = "\n".join(payee_lines)

        if normalized_intent == "view_saved_payees_only":
            return {
                "next_action": (
                    "If the user asked to view payees, share the requested details from `payees` "
                    "(nickname, bank_name, account_number_masked, category, status, last_used_at)."
                ),
                "payees": payees,
            }

        return {
            "next_action": (
                "Tell the user ONLY this:\n"
                f"These are your saved payees:\n{payee_list_text}\n"
                "Which payee do you want to select for fund transfer?\n"
                "Do NOT add extra text. "
                "Once the user selects a payee, call `get_fund_transfer_details`."
            ),
            "payees": payees,
        }

    async def get_fund_transfer_details(
        self,
        thread_id: str,
        session_data: dict,
    ) -> dict:
        customer_id = str(session_data.get("customer_id") or "").strip()
        if not customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }

        accounts = await postgres_service.get_accounts(customer_id)
        active_accounts = [account for account in accounts if str(account.get("status", "")).lower() == "active"]
        if not active_accounts:
            return {
                "next_action": (
                    "Tell the user no active source accounts are available for transfer."
                )
            }

        return {
            "next_action": (
                "Ask the user for missing transfer fund details:\n"
                "- from_account_id (show options from `accounts`)\n"
                "- amount\n"
                "- reference_note (reference code, optional)\n"
                "If the user has not provided any of these, do not assume. Ask for them.\n"
                "Once the user provides them, call `initiate_fund_transfer` with "
                "from_account_id, payee_nickname, amount, and reference_note."
            ),
            "accounts": active_accounts,
        }

    async def initiate_transfer(
        self,
        thread_id: str,
        session_data: dict,
        from_account_id: str,
        payee_nickname: str,
        amount: float,
        reference_note: str = "",
    ) -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        if amount <= 0:
            return {"next_action": "Tell the user the transfer amount must be greater than zero."}

        from_account = await postgres_service.get_account(from_account_id)
        if not from_account:
            return {"next_action": f"Tell the user source account {from_account_id} could not be found."}
        if from_account.get("customer_id") != resolved_customer_id:
            return {"next_action": "Tell the user the selected source account does not belong to the active customer."}
        if str(from_account.get("status", "")).lower() != "active":
            return {
                "next_action": (
                    f"Tell the user source account {from_account_id} is {from_account.get('status')}. "
                    "Ask them to choose an active account."
                )
            }

        payee = await postgres_service.get_payee_by_nickname(resolved_customer_id, payee_nickname)
        if not payee:
            return {"next_action": f"Tell the user a saved payee named {payee_nickname} was not found."}

        available_balance = float(from_account.get("available_balance") or 0)
        if amount > available_balance:
            return {
                "next_action": (
                    f"Tell the user funds are insufficient in {from_account.get('account_name', from_account_id)}. "
                    f"Available balance is {available_balance:.2f} SAR."
                )
            }

        transfer_timestamp = datetime.now(timezone.utc).isoformat()
        transfer = await postgres_service.create_transfer(
            customer_id=resolved_customer_id,
            from_account_id=from_account_id,
            payee_id=payee["payee_id"],
            amount=amount,
            currency="SAR",
            transfer_type="Internal Transfer",
            category="Transfer",
            created_at=transfer_timestamp,
            reference_note=reference_note or f"Transfer to {payee_nickname}",
        )

        await postgres_service.adjust_account_balance(from_account_id, -amount)
        await postgres_service.create_transfer_transaction(
            from_account_id,
            amount,
            category="Transfer",
            transfer_type="Internal Transfer",
            description=transfer["reference_note"],
            transaction_date=transfer_timestamp,
        )

        await set_session(
            get_store(),
            thread_id,
            {"last_transfer_id": transfer["transfer_id"]},
        )

        remaining_balance = available_balance - amount
        if remaining_balance < 500:
            next_action = (
                f"Tell the user transfer {transfer['transfer_id']} was processed to {payee_nickname}. "
                f"Remaining balance is low at {remaining_balance:.2f} SAR."
            )
        else:
            next_action = (
                f"Tell the user transfer {transfer['transfer_id']} was processed to {payee_nickname} for {amount:.2f} SAR."
            )

        return {
            "next_action": next_action,
            "transfer": transfer,
        }

    async def create_bill_payment(
        self,
        thread_id: str,
        session_data: dict,
        from_account_id: str,
        biller_name: str,
        amount: float,
        category: str = "Utilities",
    ) -> dict:
        resolved_customer_id = self._get_authenticated_customer_id(session_data)
        if not resolved_customer_id:
            return {
                "next_action": (
                    "Tell the user to share their customer ID first. "
                    "Once provided, proceed by calling `authentication`."
                )
            }
        if amount <= 0:
            return {"next_action": "Tell the user the bill payment amount must be greater than zero."}

        from_account = await postgres_service.get_account(from_account_id)
        if not from_account:
            return {"next_action": f"Tell the user source account {from_account_id} could not be found."}
        if from_account.get("customer_id") != resolved_customer_id:
            return {"next_action": "Tell the user the selected source account does not belong to the active customer."}
        if str(from_account.get("status", "")).lower() != "active":
            return {
                "next_action": (
                    f"Tell the user source account {from_account_id} is {from_account.get('status')}. "
                    "Ask them to choose an active account."
                )
            }

        available_balance = float(from_account.get("available_balance") or 0)
        if amount > available_balance:
            return {
                "next_action": (
                    f"Tell the user funds are insufficient in {from_account.get('account_name', from_account_id)}. "
                    f"Available balance is {available_balance:.2f} SAR."
                )
            }

        reference_note = f"{biller_name} bill payment"
        transfer_timestamp = datetime.now(timezone.utc).isoformat()
        transfer = await postgres_service.create_bill_payment(
            customer_id=resolved_customer_id,
            from_account_id=from_account_id,
            amount=amount,
            category=category,
            reference_note=reference_note,
            created_at=transfer_timestamp,
        )

        await postgres_service.adjust_account_balance(from_account_id, -amount)
        await postgres_service.create_transfer_transaction(
            from_account_id,
            amount,
            category=category,
            transfer_type="Bill Payment",
            description=reference_note,
            transaction_date=transfer_timestamp,
        )

        return {
            "next_action": f"Tell the user bill payment {transfer['transfer_id']} for {biller_name} has been created.",
            "transfer": transfer,
        }


payments_service = PaymentsService()
