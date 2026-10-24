import requests
from decimal import Decimal, InvalidOperation
from django.conf import settings


class PaystackService:
    BASE_URL = "https://api.paystack.co"

    @staticmethod
    def _headers():
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

    @classmethod
    def initialize_transaction(
        cls,
        email,
        amount,
        reference,
        callback_url=None,
    ):
        url = f"{cls.BASE_URL}/transaction/initialize"

        payload = {
            "email": email,
            "amount": int(amount * 100),
            "reference": reference,
        }

        if callback_url:
            payload["callback_url"] = callback_url

        try:
            response = requests.post(
                url,
                json=payload,
                headers=cls._headers(),
                timeout=30,
            )

            try:
                response_data = response.json()
            except ValueError:
                return {
                    "status": False,
                    "message": (
                        "Paystack returned an invalid response."
                    ),
                    "http_status": response.status_code,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": (
                        "Paystack rejected the initialization request."
                    ),
                    "http_status": response.status_code,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "message": "Paystack initialization request timed out.",
            }

        except requests.RequestException:
            return {
                "status": False,
                "message": "Unable to connect to Paystack.",
            }

    @classmethod
    def verify_transaction(cls, reference):
        url = f"{cls.BASE_URL}/transaction/verify/{reference}"

        try:
            response = requests.get(
                url,
                headers=cls._headers(),
                timeout=30,
            )

            try:
                response_data = response.json()
            except ValueError:
                return {
                    "status": False,
                    "message": "Paystack returned an invalid response.",
                    "http_status": response.status_code,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": "Paystack verification failed.",
                    "http_status": response.status_code,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "message": "Paystack verification request timed out.",
            }

        except requests.RequestException:
            return {
                "status": False,
                "message": "Unable to connect to Paystack.",
            }

    @classmethod
    def create_refund(
        cls,
        *,
        transaction_reference,
        amount=None,
        customer_note="",
        merchant_note="",
    ):
        url = f"{cls.BASE_URL}/refund"

        payload = {
            "transaction": transaction_reference,
        }

        if amount is not None:
            try:
                refund_amount = Decimal(str(amount))
                refund_kobo = refund_amount * Decimal("100")

                if (
                    not refund_amount.is_finite()
                    or refund_amount <= 0
                    or refund_kobo != refund_kobo.to_integral_value()
                ):
                    raise ValueError("Invalid refund amount.")

            except (InvalidOperation, ValueError, TypeError):
                return {
                    "status": False,
                    "outcome": "invalid_amount",
                    "message": "Invalid refund amount.",
                }

            payload["amount"] = int(refund_kobo)

        if customer_note:
            payload["customer_note"] = customer_note

        if merchant_note:
            payload["merchant_note"] = merchant_note

        try:
            response = requests.post(
                url,
                json=payload,
                headers=cls._headers(),
                timeout=30,
            )

            try:
                response_data = response.json()
            except ValueError:
                return {
                    "status": False,
                    "outcome": "unknown",
                    "message": (
                        "Paystack refund confirmation is unavailable. "
                        "Check Paystack before retrying."
                    ),
                    "http_status": response.status_code,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": "Paystack rejected the refund request.",
                    "http_status": response.status_code,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "outcome": "unknown",
                "message": (
                    "Refund confirmation is unavailable. "
                    "Check Paystack before retrying."
                ),
            }

        except requests.RequestException:
            return {
                "status": False,
                "outcome": "unknown",
                "message": (
                    "Refund confirmation is unavailable. "
                    "Check Paystack before retrying."
                ),
            }