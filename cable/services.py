import requests
from django.conf import settings


class VTPassCableService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def get_plans(cls, service_id):
        url = f"{settings.VTPASS_BASE_URL}/service-variations"
        response = requests.get(
            url,
            params={"serviceID": service_id},
            headers=cls._headers(),
            timeout=30,
        )
        return response.json()

    @classmethod
    def verify_smartcard(cls, service_id, smartcard_number):
        url = f"{settings.VTPASS_BASE_URL}/merchant-verify"
        payload = {
            "serviceID": service_id,
            "billersCode": smartcard_number,
        }
        response = requests.post(
            url,
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )
        return response.json()

    @classmethod
    def purchase_subscription(cls, request_id, service_id, smartcard_number, variation_code, amount, phone):
        url = f"{settings.VTPASS_BASE_URL}/pay"
        payload = {
            "request_id": request_id,
            "serviceID": service_id,
            "billersCode": smartcard_number,
            "variation_code": variation_code,
            "amount": str(amount),
            "phone": phone,
        }
        response = requests.post(
            url,
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )
        return response.json()