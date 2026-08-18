import requests
from django.conf import settings


class VTPassDataService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def get_data_plans(cls, service_id):
        url = f"{settings.VTPASS_BASE_URL}/service-variations"

        response = requests.get(
            url,
            params={"serviceID": service_id},
            headers=cls._headers(),
            timeout=30,
        )

        return response.json()

    @classmethod
    def purchase_data(
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