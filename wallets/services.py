from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Wallet, WalletTransaction


class WalletService:
    @staticmethod
    @transaction.atomic
    def credit_wallet(wallet, amount, reference, description="Wallet credit"):
        amount = Decimal(amount)

        if amount <= 0:
            raise ValidationError("Amount must be greater than zero.")

        wallet = Wallet.objects.select_for_update().get(id=wallet.id)
        wallet.balance += amount
        wallet.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type="credit",
            amount=amount,
            reference=reference,
            description=description,
        )

        return wallet

    @staticmethod
    @transaction.atomic
    def debit_wallet(wallet, amount, reference, description="Wallet debit"):
        amount = Decimal(amount)

        if amount <= 0:
            raise ValidationError("Amount must be greater than zero.")

        wallet = Wallet.objects.select_for_update().get(id=wallet.id)

        if wallet.balance < amount:
            raise ValidationError("Insufficient wallet balance.")

        wallet.balance -= amount
        wallet.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=description,
        )

        return wallet