from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from .models import Wallet, WalletTransaction
from .services import WalletService


User = get_user_model()


class WalletServiceSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="wallet_security_user",
            email="wallet-security@example.com",
            password="StrongTestPass123!",
        )

        self.wallet, _ = Wallet.objects.get_or_create(
            user=self.user
        )

        self.wallet.balance = Decimal("5000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

    def test_credit_is_idempotent(self):
        WalletService.credit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-CREDIT-001",
            description="Security test credit",
        )

        WalletService.credit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-CREDIT-001",
            description="Security test credit",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("6000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                reference="WALLET-CREDIT-001"
            ).count(),
            1,
        )

    def test_debit_is_idempotent(self):
        WalletService.debit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-DEBIT-001",
            description="Security test debit",
        )

        WalletService.debit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-DEBIT-001",
            description="Security test debit",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                reference="WALLET-DEBIT-001"
            ).count(),
            1,
        )

    def test_credit_reference_conflict_fails_closed(self):
        WalletService.credit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-CONFLICT-001",
        )

        with self.assertRaises(ValidationError):
            WalletService.credit_wallet(
                wallet=self.wallet,
                amount=Decimal("2000.00"),
                reference="WALLET-CONFLICT-001",
            )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("6000.00"),
        )

    def test_reference_cannot_change_transaction_type(self):
        WalletService.credit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-TYPE-CONFLICT-001",
        )

        with self.assertRaises(ValidationError):
            WalletService.debit_wallet(
                wallet=self.wallet,
                amount=Decimal("1000.00"),
                reference="WALLET-TYPE-CONFLICT-001",
            )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("6000.00"),
        )

    def test_reference_cannot_be_reused_for_another_wallet(self):
        other_user = User.objects.create_user(
            username="wallet_security_other",
            email="wallet-security-other@example.com",
            password="StrongTestPass123!",
        )

        other_wallet, _ = Wallet.objects.get_or_create(
            user=other_user
        )

        WalletService.credit_wallet(
            wallet=self.wallet,
            amount=Decimal("1000.00"),
            reference="WALLET-OWNER-CONFLICT-001",
        )

        with self.assertRaises(ValidationError):
            WalletService.credit_wallet(
                wallet=other_wallet,
                amount=Decimal("1000.00"),
                reference="WALLET-OWNER-CONFLICT-001",
            )

        other_wallet.refresh_from_db()

        self.assertEqual(
            other_wallet.balance,
            Decimal("0.00"),
        )

    def test_debit_cannot_overdraw_wallet(self):
        with self.assertRaises(ValidationError):
            WalletService.debit_wallet(
                wallet=self.wallet,
                amount=Decimal("5000.01"),
                reference="WALLET-OVERDRAW-001",
            )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference="WALLET-OVERDRAW-001"
            ).exists()
        )

    def test_zero_credit_is_rejected(self):
        with self.assertRaises(ValidationError):
            WalletService.credit_wallet(
                wallet=self.wallet,
                amount=Decimal("0.00"),
                reference="WALLET-ZERO-CREDIT",
            )

    def test_negative_credit_is_rejected(self):
        with self.assertRaises(ValidationError):
            WalletService.credit_wallet(
                wallet=self.wallet,
                amount=Decimal("-1.00"),
                reference="WALLET-NEGATIVE-CREDIT",
            )

    def test_zero_debit_is_rejected(self):
        with self.assertRaises(ValidationError):
            WalletService.debit_wallet(
                wallet=self.wallet,
                amount=Decimal("0.00"),
                reference="WALLET-ZERO-DEBIT",
            )

    def test_negative_debit_is_rejected(self):
        with self.assertRaises(ValidationError):
            WalletService.debit_wallet(
                wallet=self.wallet,
                amount=Decimal("-1.00"),
                reference="WALLET-NEGATIVE-DEBIT",
            )


class WalletEndpointSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="wallet_endpoint_user",
            email="wallet-endpoint@example.com",
            password="StrongTestPass123!",
        )

        self.other_user = User.objects.create_user(
            username="wallet_endpoint_other",
            email="wallet-endpoint-other@example.com",
            password="StrongTestPass123!",
        )

        self.wallet, _ = Wallet.objects.get_or_create(
            user=self.user
        )

        self.other_wallet, _ = Wallet.objects.get_or_create(
            user=self.other_user
        )

        self.wallet.balance = Decimal("5000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.other_wallet.balance = Decimal("9000.00")
        self.other_wallet.save(
            update_fields=["balance"]
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=Decimal("500.00"),
            reference="USER-WALLET-TX-001",
            description="User transaction",
        )

        WalletTransaction.objects.create(
            wallet=self.other_wallet,
            transaction_type="debit",
            amount=Decimal("700.00"),
            reference="OTHER-WALLET-TX-001",
            description="Other user transaction",
        )

        self.client = APIClient()

    def test_wallet_endpoint_requires_authentication(self):
        response = self.client.get("/api/wallet/")

        self.assertIn(
            response.status_code,
            (401, 403),
        )

    def test_transaction_endpoint_requires_authentication(self):
        response = self.client.get(
            "/api/wallet/transactions/"
        )

        self.assertIn(
            response.status_code,
            (401, 403),
        )

    def test_user_only_sees_own_wallet(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/wallet/"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        self.assertEqual(
            Decimal(str(response.data["balance"])),
            Decimal("5000.00"),
        )

        self.assertNotEqual(
            Decimal(str(response.data["balance"])),
            Decimal("9000.00"),
        )

    def test_user_only_sees_own_transactions(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/wallet/transactions/"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        references = {
            item["reference"]
            for item in response.data
        }

        self.assertIn(
            "USER-WALLET-TX-001",
            references,
        )

        self.assertNotIn(
            "OTHER-WALLET-TX-001",
            references,
        )

    def test_wallet_response_does_not_expose_user_object(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/wallet/"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        self.assertNotIn(
            "user",
            response.data,
        )

    def test_transaction_response_does_not_expose_wallet_object(self):
        self.client.force_authenticate(
            user=self.user
        )

        response = self.client.get(
            "/api/wallet/transactions/"
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        self.assertTrue(response.data)

        for item in response.data:
            self.assertNotIn(
                "wallet",
                item,
            )