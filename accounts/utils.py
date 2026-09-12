class PhoneNormalizationError(ValueError):
    pass


def normalize_nigerian_phone(value):
    if value is None:
        return None

    phone = str(value).strip()

    if not phone:
        return None

    phone = (
        phone
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if phone.startswith("+234"):
        phone = "0" + phone[4:]
    elif phone.startswith("234"):
        phone = "0" + phone[3:]

    if not phone.isdigit():
        raise PhoneNormalizationError(
            "Enter a valid Nigerian phone number."
        )

    if len(phone) != 11 or not phone.startswith("0"):
        raise PhoneNormalizationError(
            "Enter a valid Nigerian phone number, for example "
            "08012345678 or +2348012345678."
        )

    return phone