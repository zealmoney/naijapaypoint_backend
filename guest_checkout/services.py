import uuid


class GuestReferenceService:

    @staticmethod
    def generate_reference():
        return f"GUEST-{uuid.uuid4().hex[:14].upper()}"