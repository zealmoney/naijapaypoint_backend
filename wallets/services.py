from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Wallet, WalletTransaction


class WalletService:
    @staticmethod
    def _check_existing_transaction(
        reference,
        wallet,
        amount,
        transaction_type,
    ):
        existing = (
            WalletTransaction.objects
            .filter(reference=reference)
            .first()
        )

        if not existing:
            return None

        if (
            existing.wallet_id != wallet.id
            or existing.amount != amount
            or existing.transaction_type
            != transaction_type
        ):
            raise ValidationError(
                "Transaction reference already exists "
                "with different transaction details."
            )

        return existing

    @staticmethod
    @transaction.atomic
    def credit_wallet(
        wallet,
        amount,
        reference,
        description="Wallet credit",
    ):
        amount = Decimal(amount)

        if amount <= 0:
            raise ValidationError(
                "Amount must be greater than zero."
            )

        wallet = (
            Wallet.objects
            .select_for_update()
            .get(id=wallet.id)
        )

        # Idempotency protection.
        #
        # If this exact credit has already been
        # processed, return the wallet without
        # crediting it again.
        existing_transaction = (
            WalletService
            ._check_existing_transaction(
                reference=reference,
                wallet=wallet,
                amount=amount,
                transaction_type="credit",
            )
        )

        if existing_transaction:
            return wallet

        wallet.balance += amount
        wallet.save(
            update_fields=["balance"]
        )

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
    def debit_wallet(
        wallet,
        amount,
        reference,
        description="Wallet debit",
    ):
        amount = Decimal(amount)

        if amount <= 0:
            raise ValidationError(
                "Amount must be greater than zero."
            )

        wallet = (
            Wallet.objects
            .select_for_update()
            .get(id=wallet.id)
        )

        # Idempotency protection.
        #
        # A retry using the same transaction
        # reference must not debit the wallet
        # for a second time.
        existing_transaction = (
            WalletService
            ._check_existing_transaction(
                reference=reference,
                wallet=wallet,
                amount=amount,
                transaction_type="debit",
            )
        )

        if existing_transaction:
            return wallet

        if wallet.balance < amount:
            raise ValidationError(
                "Insufficient wallet balance."
            )

        wallet.balance -= amount
        wallet.save(
            update_fields=["balance"]
        )

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=description,
        )

        return wallet