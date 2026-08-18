from airtime.services import VTPassAirtimeService
from data_services.services import VTPassDataService
from electricity.services import VTPassElectricityService
from cable.services import VTPassCableService


class GuestPurchaseService:

    @staticmethod
    def execute(transaction):

        if transaction.service_type == "airtime":
            return VTPassAirtimeService.purchase_airtime(
                request_id=transaction.reference,
                service_id=transaction.provider,
                amount=transaction.amount,
                phone=transaction.recipient,
            )

        if transaction.service_type == "data":
            return VTPassDataService.purchase_data(
                request_id=transaction.reference,
                service_id=transaction.provider,
                billers_code=transaction.recipient,
                variation_code=transaction.variation_code,
                amount=transaction.amount,
                phone=transaction.recipient,
            )

        if transaction.service_type == "electricity":
            return VTPassElectricityService.purchase_electricity(
                request_id=transaction.reference,
                service_id=transaction.provider,
                billers_code=transaction.recipient,
                variation_code=transaction.variation_code,
                amount=transaction.amount,
                phone=transaction.guest_phone,
            )

        if transaction.service_type == "cable":
            return VTPassCableService.purchase_subscription(
                request_id=transaction.reference,
                service_id=transaction.provider,
                smartcard_number=transaction.recipient,
                variation_code=transaction.variation_code,
                amount=transaction.amount,
                phone=transaction.guest_phone,
            )

        raise ValueError(
            f"Unsupported guest service: {transaction.service_type}"
        )