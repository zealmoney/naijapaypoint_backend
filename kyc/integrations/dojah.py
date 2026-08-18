from __future__ import annotations

from typing import Any

import requests
from django.conf import settings


class DojahAPIError(Exception):
    """Raised when Dojah cannot complete a verification request."""


class DojahService:
    @staticmethod
    def _headers() -> dict[str, str]:
        if not settings.DOJAH_APP_ID:
            raise DojahAPIError("DOJAH_APP_ID is not configured.")

        if not settings.DOJAH_SECRET_KEY:
            raise DojahAPIError(
                "DOJAH_SECRET_KEY is not configured."
            )

        return {
            "AppId": settings.DOJAH_APP_ID,
            "Authorization": settings.DOJAH_SECRET_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _url(path: str) -> str:
        return (
            f"{settings.DOJAH_BASE_URL.rstrip('/')}/"
            f"{path.lstrip('/')}"
        )

    @classmethod
    def verify_identity(
        cls,
        *,
        first_name: str,
        last_name: str,
        date_of_birth: str | None,
        mode: str,
        identity_value: str,
        customer_reference: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "mode": mode,
            "strict": "true",
            "first_name": first_name,
            "last_name": last_name,
            "customer_reference": customer_reference,
        }

        if date_of_birth:
            params["dob"] = date_of_birth

        if mode == "bvn":
            params["bvn"] = identity_value
        elif mode == "phone_number":
            params["phone_number"] = identity_value
        else:
            raise DojahAPIError(
                f"Unsupported identity mode: {mode}"
            )

        try:
            response = requests.get(
                cls._url("/api/v1/kyc/age_verification"),
                params=params,
                headers=cls._headers(),
                timeout=settings.DOJAH_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise DojahAPIError(
                "Unable to connect to Dojah."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DojahAPIError(
                "Dojah returned an invalid JSON response."
            ) from exc

        if not response.ok:
            message = (
                payload.get("error")
                or payload.get("message")
                or "Dojah identity verification failed."
            )

            raise DojahAPIError(str(message))

        return payload