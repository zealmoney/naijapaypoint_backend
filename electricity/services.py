import requests
from django.conf import settings


class VTPassElectricityService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def verify_meter(cls, service_id, billers_code, meter_type):
        url = f"{settings.VTPASS_BASE_URL}/merchant-verify"

        payload = {
            "serviceID": service_id,
            "billersCode": billers_code,
            "type": meter_type,
        }

        response = requests.post(
            url,
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )

        return response.json()

    @classmethod
    def purchase_electricity(
        cls,
        request_id,
        service_id,
        billers_code,
        variation_code,
        amount,
        phone,
    ):
        url = f"{settings.VTPASS_BASE_URL}/pay"

        payload = {
            "request_id": request_id,
            "serviceID": service_id,
            "billersCode": billers_code,
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