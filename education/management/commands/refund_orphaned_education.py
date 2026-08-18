from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from education.models import EducationTransaction
from transactions.models import Transaction
from wallets.services import WalletService


REFERENCE = "EDU-54C1BA606270493C"


class Command(BaseCommand):
    help = "Refund the one orphaned Education transaction."

    def handle(self, *args, **options):
        with transaction.atomic():
            try:
                edu_tx = (
                    EducationTransaction.objects
                    .select_for_update()
                    .select_related("user")
                    .get(reference=REFERENCE)
                )
            except EducationTransaction.DoesNotExist:
                raise CommandError(
                    f"Education transaction {REFERENCE} was not found."
                )

            if edu_tx.status != "pending":
                raise CommandError(
                    f"{REFERENCE} has status '{edu_tx.status}'. "
                    "Refund cancelled to prevent a duplicate refund."
                )

            try:
                main_tx = (
                    Transaction.objects
                    .select_for_update()
                    .get(reference=REFERENCE)
                )
            except Transaction.DoesNotExist:
                raise CommandError(
                    f"Main transaction {REFERENCE} was not found."
                )

            self.stdout.write(
                f"Refunding {REFERENCE}..."
            )

            self.stdout.write(
                f"Amount: ₦{edu_tx.amount}"
            )

            WalletService.credit_wallet(
                wallet=edu_tx.user.wallet,
                amount=edu_tx.amount,
                reference=f"REFUND-{REFERENCE}",
                description=(
                    "Refund for failed education purchase"
                ),
            )

            edu_tx.status = "refunded"
            edu_tx.save(
                update_fields=["status"]
            )

            main_tx.status = "refunded"

            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "manual_refund": True,
                "refund_reason": (
                    "Education provider call crashed before "
                    "automatic refund."
                ),
            }

            main_tx.save(
                update_fields=[
                    "status",
                    "metadata",
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully refunded ₦{edu_tx.amount} "
                f"for {REFERENCE}."
            )
        )