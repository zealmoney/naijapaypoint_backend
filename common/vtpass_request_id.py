import uuid
from zoneinfo import ZoneInfo

from django.utils import timezone


LAGOS_TZ = ZoneInfo("Africa/Lagos")


def generate_vtpass_request_id(prefix="NPP"):
    now = timezone.now().astimezone(
        LAGOS_TZ
    )

    timestamp = now.strftime(
        "%Y%m%d%H%M"
    )

    clean_prefix = "".join(
        char
        for char in prefix.upper()
        if char.isalnum()
    )

    suffix = (
        uuid.uuid4()
        .hex[:12]
        .upper()
    )

    return (
        f"{timestamp}"
        f"{clean_prefix}"
        f"{suffix}"
    )