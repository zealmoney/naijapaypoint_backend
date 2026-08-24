import requests

from django.conf import settings


class VTPassRecoveryService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def requery(cls, request_id):
        url = f"{settings.VTPASS_BASE_URL}/requery"

        try:
            response = requests.post(
                url,
                json={
                    "request_id": request_id,
                },
                headers=cls._headers(),
                timeout=30,
            )

            try:
                data = response.json()
            except ValueError:
                return {
                    "code": "REQUERY_INVALID_JSON",
                    "response_description":
                        "VTPass returned an invalid requery response.",
                    "http_status": response.status_code,
                    "raw_response": response.text,
                }

            return data

        except requests.Timeout:
            return {
                "code": "REQUERY_TIMEOUT",
                "response_description":
                    "VTPass requery timed out.",
            }

        except requests.RequestException as exc:
            return {
                "code": "REQUERY_CONNECTION_ERROR",
                "response_description":
                    f"Unable to connect to VTPass: {exc}",
            }