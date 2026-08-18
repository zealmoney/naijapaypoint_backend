import requests
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

        print("========== PAYSTACK INIT ==========")
        print("REFERENCE:", reference)
        print("CALLBACK URL:", callback_url)
        print("PAYSTACK PAYLOAD:", payload)
        print("===================================")

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
                    "raw_response": response.text,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": response_data.get(
                        "message",
                        "Paystack rejected the initialization request.",
                    ),
                    "http_status": response.status_code,
                    "provider_response": response_data,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "message": "Paystack initialization request timed out.",
            }

        except requests.RequestException as exc:
            return {
                "status": False,
                "message": f"Unable to connect to Paystack: {exc}",
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
                    "raw_response": response.text,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": response_data.get(
                        "message",
                        "Paystack verification failed.",
                    ),
                    "http_status": response.status_code,
                    "provider_response": response_data,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "message": "Paystack verification request timed out.",
            }

        except requests.RequestException as exc:
            return {
                "status": False,
                "message": f"Unable to connect to Paystack: {exc}",
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
            payload["amount"] = int(amount * 100)

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
                    "message": "Paystack returned an invalid refund response.",
                    "http_status": response.status_code,
                    "raw_response": response.text,
                }

            if not response.ok:
                return {
                    "status": False,
                    "message": response_data.get(
                        "message",
                        "Paystack rejected the refund request.",
                    ),
                    "http_status": response.status_code,
                    "provider_response": response_data,
                }

            return response_data

        except requests.Timeout:
            return {
                "status": False,
                "message": "Paystack refund request timed out.",
            }

        except requests.RequestException as exc:
            return {
                "status": False,
                "message": f"Unable to connect to Paystack: {exc}",
            }