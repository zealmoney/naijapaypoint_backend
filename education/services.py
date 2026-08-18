import requests

from django.conf import settings


class VTPassEducationService:
    @staticmethod
    def _headers():
        return {
            "api-key": settings.VTPASS_API_KEY,
            "secret-key": settings.VTPASS_SECRET_KEY,
            "Content-Type": "application/json",
        }

    @classmethod
    def _post(cls, path, payload):
        url = f"{settings.VTPASS_BASE_URL}{path}"

        print("========== VTPASS EDUCATION ==========")
        print("URL:", url)
        print("PAYLOAD:", payload)

        try:
            response = requests.post(
                url,
                json=payload,
                headers=cls._headers(),
                timeout=30,
            )

            print("VTPASS STATUS:", response.status_code)
            print("VTPASS RAW RESPONSE:", response.text)

            try:
                return response.json()

            except ValueError:
                return {
                    "code": "provider_error",
                    "response_description": (
                        "VTPass returned an invalid response."
                    ),
                    "http_status": response.status_code,
                    "raw_response": response.text,
                }

        except requests.Timeout:
            return {
                "code": "provider_timeout",
                "response_description": (
                    "VTPass request timed out."
                ),
            }

        except requests.RequestException as exc:
            return {
                "code": "provider_error",
                "response_description": (
                    "Provider request failed"
                ),
                "error": str(exc),
            }

    @classmethod
    def get_plans(
        cls,
        service_id,
    ):
        url = (
            f"{settings.VTPASS_BASE_URL}"
            "/service-variations"
        )

        try:
            response = requests.get(
                url,
                params={
                    "serviceID": service_id,
                },
                headers=cls._headers(),
                timeout=30,
            )

            print(
                "EDUCATION PLANS STATUS:",
                response.status_code,
            )

            print(
                "EDUCATION PLANS RESPONSE:",
                response.text,
            )

            try:
                return response.json()

            except ValueError:
                return {
                    "code": "provider_error",
                    "response_description": (
                        "VTPass returned an invalid "
                        "plans response."
                    ),
                    "raw_response": response.text,
                }

        except requests.Timeout:
            return {
                "code": "provider_timeout",
                "response_description": (
                    "VTPass plans request timed out."
                ),
            }

        except requests.RequestException as exc:
            return {
                "code": "provider_error",
                "response_description": (
                    "Unable to load education plans."
                ),
                "error": str(exc),
            }

    @classmethod
    def purchase_pin(
        cls,
        request_id,
        service_id,
        variation_code,
        quantity,
        phone,
        profile_id="",
    ):
        payload = {
            "request_id": request_id,
            "serviceID": service_id,
            "variation_code": variation_code,
            "phone": phone,
        }

        if service_id == "jamb":
            payload["billersCode"] = profile_id

        else:
            payload["quantity"] = quantity

        return cls._post(
            "/pay",
            payload,
        )