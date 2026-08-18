import requests
from django.conf import settings


class VTPassAirtimeService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def purchase_airtime(cls, request_id, service_id, phone, amount):
        url = f"{settings.VTPASS_BASE_URL}/pay"

        payload = {
            "request_id": request_id,
            "serviceID": service_id,
            "amount": str(amount),
            "phone": phone,
        }

        print("VTPASS AIRTIME PAYLOAD:", payload)

        response = requests.post(
            url,
            json=payload,
            headers=cls._headers(),
            timeout=30,
        )

        print("VTPASS STATUS:", response.status_code)
        print("VTPASS RAW RESPONSE:", response.text)

        return response.json()