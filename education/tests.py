from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from transactions.models import Transaction
from wallets.models import WalletTransaction

from .views import EducationPurchaseView

from .models import EducationTransaction
from .serializers import (
    EducationPlansSerializer,
    EducationPurchaseSerializer,
)


class EducationSerializerSecurityTests(
    SimpleTestCase
):
    def test_supported_providers_are_allowed(self):
        for provider in (
            "waec",
            "waec-registration",
            "neco",
            "jamb",
        ):
            serializer = EducationPlansSerializer(
                data={"provider": provider}
            )

            self.assertTrue(
                serializer.is_valid(),
                serializer.errors,
            )

    def test_arbitrary_provider_is_rejected(self):
        serializer = EducationPlansSerializer(
            data={"provider": "fake-provider"}
        )

        self.assertFalse(serializer.is_valid())

    def test_purchase_rejects_arbitrary_provider(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "fake-provider",
                "plan_id": "TEST-PLAN",
                "quantity": 1,
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_client_price_and_name_are_discarded(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "waec",
                "plan_id": "TEST-PLAN",
                "plan_name": "Fake Cheap Plan",
                "amount": "1.00",
                "quantity": 1,
            }
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        self.assertNotIn(
            "plan_name",
            serializer.validated_data,
        )
        self.assertNotIn(
            "amount",
            serializer.validated_data,
        )

    def test_quantity_must_be_at_least_one(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "waec",
                "plan_id": "TEST-PLAN",
                "quantity": 0,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "quantity",
            serializer.errors,
        )

    def test_quantity_cannot_exceed_ten(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "waec",
                "plan_id": "TEST-PLAN",
                "quantity": 11,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "quantity",
            serializer.errors,
        )

    def test_jamb_requires_profile_id(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "jamb",
                "plan_id": "TEST-JAMB",
                "quantity": 1,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "profile_id",
            serializer.errors,
        )

    def test_jamb_quantity_must_be_one(self):
        serializer = EducationPurchaseSerializer(
            data={
                "provider": "jamb",
                "plan_id": "TEST-JAMB",
                "quantity": 2,
                "profile_id": "1234567890",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "quantity",
            serializer.errors,
        )

class EducationPurchaseSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="education_security_test",
            email="education-security@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("10000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

    @patch(
        "education.views."
        "NotificationService.create_notification"
    )
    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_client_cannot_override_price_or_quantity_total(
        self,
        mock_get_plans,
        mock_purchase,
        mock_notification,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code":
                            "TEST-EDU-PLAN",
                        "name":
                            "Authoritative Education Plan",
                        "variation_amount":
                            "1500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "000",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "requestId": "PROVIDER-EDU-1",
        }

        response = self.client.post(
            "/api/education/purchase/",
            {
                "provider": "waec",
                "plan_id": "TEST-EDU-PLAN",

                # Deliberately tampered values.
                "plan_name": "Fake Cheap Plan",
                "amount": "1.00",

                "quantity": 3,
                "phone_number": "08000000000",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        education_tx = (
            EducationTransaction.objects.get(
                user=self.user
            )
        )

        self.assertEqual(
            education_tx.plan_name,
            "Authoritative Education Plan",
        )
        self.assertEqual(
            education_tx.quantity,
            3,
        )
        self.assertEqual(
            education_tx.amount,
            Decimal("4500.00"),
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )

        mock_purchase.assert_called_once()

        purchase_kwargs = (
            mock_purchase.call_args.kwargs
        )

        self.assertEqual(
            purchase_kwargs["variation_code"],
            "TEST-EDU-PLAN",
        )
        self.assertEqual(
            purchase_kwargs["quantity"],
            3,
        )

    def test_pending_transaction_refunds_once(self):
        reference = "EDUCATION-REFUND-TEST"
        amount = Decimal("4500.00")

        education_tx = (
            EducationTransaction.objects.create(
                user=self.user,
                provider="waec",
                plan_id="TEST-EDU-PLAN",
                plan_name="Test Education Plan",
                quantity=3,
                amount=amount,
                reference=reference,
                status="pending",
            )
        )

        main_tx = Transaction.objects.create(
            user=self.user,
            service_type="education",
            amount=amount,
            reference=reference,
            status="pending",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=(
                "Test original education debit"
            ),
        )

        (
            education_tx,
            main_tx,
            refunded,
        ) = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        self.assertTrue(refunded)
        self.assertEqual(
            education_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("14500.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{reference}",
                transaction_type="credit",
                amount=amount,
            ).count(),
            1,
        )

    def test_refund_requires_matching_original_debit(self):
        reference = "EDUCATION-NO-DEBIT-TEST"
        amount = Decimal("4500.00")

        education_tx = (
            EducationTransaction.objects.create(
                user=self.user,
                provider="waec",
                plan_id="TEST-EDU-PLAN",
                plan_name="Test Education Plan",
                quantity=3,
                amount=amount,
                reference=reference,
                status="pending",
            )
        )

        main_tx = Transaction.objects.create(
            user=self.user,
            service_type="education",
            amount=amount,
            reference=reference,
            status="pending",
            provider="vtpass",
        )

        (
            education_tx,
            main_tx,
            refunded,
        ) = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        self.assertFalse(refunded)

        education_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            education_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{reference}",
                transaction_type="credit",
            ).exists()
        )

    def test_refund_requires_both_records_pending(self):
        reference = "EDUCATION-STATE-TEST"
        amount = Decimal("4500.00")

        education_tx = (
            EducationTransaction.objects.create(
                user=self.user,
                provider="waec",
                plan_id="TEST-EDU-PLAN",
                plan_name="Test Education Plan",
                quantity=3,
                amount=amount,
                reference=reference,
                status="pending",
            )
        )

        main_tx = Transaction.objects.create(
            user=self.user,
            service_type="education",
            amount=amount,
            reference=reference,
            status="success",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=(
                "Test original education debit"
            ),
        )

        (
            education_tx,
            main_tx,
            refunded,
        ) = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        self.assertFalse(refunded)

        education_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            education_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "success",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                reference=f"REFUND-{reference}",
                transaction_type="credit",
            ).exists()
        )

    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_provider_exception_does_not_refund(
        self,
        mock_get_plans,
        mock_purchase_pin,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code":
                            "TEST-EDU-PLAN",
                        "name":
                            "Test Education Plan",
                        "variation_amount":
                            "1500.00",
                    }
                ]
            }
        }

        mock_purchase_pin.side_effect = (
            Exception(
                "Simulated provider timeout"
            )
        )

        response = self.client.post(
            "/api/education/purchase/",
            {
                "provider": "waec",
                "plan_id": "TEST-EDU-PLAN",
                "quantity": 1,
                "phone_number": "08000000001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        education_tx = (
            EducationTransaction.objects.get(
                user=self.user,
                plan_id="TEST-EDU-PLAN",
            )
        )

        main_tx = Transaction.objects.get(
            reference=education_tx.reference
        )

        education_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            education_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("8500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=(
                    f"REFUND-"
                    f"{education_tx.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )

    def test_refund_cannot_be_applied_twice(self):
        reference = "EDUCATION-DOUBLE-REFUND"
        amount = Decimal("4500.00")

        education_tx = (
            EducationTransaction.objects.create(
                user=self.user,
                provider="waec",
                plan_id="TEST-EDU-PLAN",
                plan_name="Test Education Plan",
                quantity=3,
                amount=amount,
                reference=reference,
                status="pending",
            )
        )

        main_tx = Transaction.objects.create(
            user=self.user,
            service_type="education",
            amount=amount,
            reference=reference,
            status="pending",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=(
                "Test original education debit"
            ),
        )

        first_result = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        second_result = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        self.assertTrue(first_result[2])
        self.assertFalse(second_result[2])

        education_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            education_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("14500.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{reference}",
                transaction_type="credit",
                amount=amount,
            ).count(),
            1,
        )

    def test_successful_transaction_cannot_be_refunded(self):
        reference = "EDUCATION-SUCCESS-NO-REFUND"
        amount = Decimal("4500.00")

        education_tx = (
            EducationTransaction.objects.create(
                user=self.user,
                provider="waec",
                plan_id="TEST-EDU-PLAN",
                plan_name="Test Education Plan",
                quantity=3,
                amount=amount,
                reference=reference,
                status="success",
            )
        )

        main_tx = Transaction.objects.create(
            user=self.user,
            service_type="education",
            amount=amount,
            reference=reference,
            status="success",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=amount,
            reference=reference,
            description=(
                "Test original education debit"
            ),
        )

        (
            education_tx,
            main_tx,
            refunded,
        ) = (
            EducationPurchaseView
            ._refund_pending_transaction(
                education_tx=education_tx,
                main_tx=main_tx,
                amount=amount,
                reference=reference,
                provider_response={
                    "code": "016",
                },
            )
        )

        self.assertFalse(refunded)

        education_tx.refresh_from_db()
        main_tx.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            education_tx.status,
            "success",
        )
        self.assertEqual(
            main_tx.status,
            "success",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{reference}",
                transaction_type="credit",
            ).exists()
        )

class EducationResponseConfidentialityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="education_confidentiality_test",
            email="education-confidentiality@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("20000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

        self.catalogue_response = {
            "content": {
                "varations": [
                    {
                        "variation_code":
                            "TEST-EDU-PLAN",
                        "name":
                            "Authoritative Education Plan",
                        "variation_amount":
                            "1500.00",
                    }
                ]
            }
        }

    def _purchase(self):
        return self.client.post(
            "/api/education/purchase/",
            {
                "provider": "waec",
                "plan_id": "TEST-EDU-PLAN",
                "quantity": 1,
                "phone_number": "08000000001",
            },
            format="json",
        )

    @patch(
        "education.views."
        "NotificationService.create_notification"
    )
    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_success_exposes_pin_but_not_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
        mock_notification,
    ):
        mock_get_plans.return_value = (
            self.catalogue_response
        )

        mock_purchase.return_value = {
            "code": "000",
            "requestId": "SECRET-PROVIDER-REFERENCE",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "content": {
                "transactions": {
                    "status": "delivered",
                }
            },
            "pin": "CUSTOMER-PIN-1234",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self._purchase()

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        # The purchased PIN is intentionally
        # customer-facing.
        self.assertEqual(
            response.data.get("pin"),
            "CUSTOMER-PIN-1234",
        )

        # Raw provider data must never be exposed.
        self.assertNotIn(
            "provider_response",
            response.data,
        )

        body = str(response.data)

        self.assertNotIn(
            "must-not-leak",
            body,
        )
        self.assertNotIn(
            "SECRET-PROVIDER-REFERENCE",
            body,
        )

        # Verify sensitive provider data is not
        # persisted in either transaction record.
        education_tx = EducationTransaction.objects.latest(
            "id"
        )
        main_tx = Transaction.objects.get(
            reference=education_tx.reference
        )

        self.assertEqual(
            education_tx.pin,
            "CUSTOMER-PIN-1234",
        )

        expected_sanitized_response = {
            "code": "000",
            "result": "success",
        }

        self.assertEqual(
            education_tx.provider_response,
            expected_sanitized_response,
        )

        self.assertEqual(
            main_tx.metadata["provider_response"],
            expected_sanitized_response,
        )

        self.assertEqual(
            main_tx.provider_reference,
            "SECRET-PROVIDER-REFERENCE",
        )

        self.assertNotIn(
            "must-not-leak",
            str(education_tx.provider_response),
        )

        self.assertNotIn(
            "must-not-leak",
            str(main_tx.metadata),
        )

    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_pending_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = (
            self.catalogue_response
        )

        mock_purchase.return_value = {
            "code": "099",
            "requestId": "PENDING-SECRET",
            "response_description":
                "TRANSACTION PENDING",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self._purchase()

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        transaction_data = (
            response.data.get("transaction")
            or {}
        )

        self.assertNotIn(
            "provider_response",
            transaction_data,
        )

        body = str(response.data)

        self.assertNotIn(
            "must-not-leak",
            body,
        )
        self.assertNotIn(
            "PENDING-SECRET",
            body,
        )

    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_manual_review_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = (
            self.catalogue_response
        )

        mock_purchase.return_value = {
            "code": "015",
            "requestId": "REVIEW-SECRET",
            "response_description":
                "UNKNOWN PROVIDER STATE",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self._purchase()

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        transaction_data = (
            response.data.get("transaction")
            or {}
        )

        self.assertNotIn(
            "provider_response",
            transaction_data,
        )

        body = str(response.data)

        self.assertNotIn(
            "must-not-leak",
            body,
        )
        self.assertNotIn(
            "REVIEW-SECRET",
            body,
        )

    @patch(
        "education.views."
        "NotificationService.create_notification"
    )
    @patch(
        "education.views."
        "VTPassEducationService.purchase_pin"
    )
    @patch(
        "education.views."
        "VTPassEducationService.get_plans"
    )
    def test_failed_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
        mock_notification,
    ):
        mock_get_plans.return_value = (
            self.catalogue_response
        )

        mock_purchase.return_value = {
            "code": "016",
            "requestId": "FAILED-SECRET",
            "response_description":
                "TRANSACTION FAILED",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self._purchase()

        self.assertEqual(
            response.status_code,
            400,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        transaction_data = (
            response.data.get("transaction")
            or {}
        )

        self.assertNotIn(
            "provider_response",
            transaction_data,
        )

        body = str(response.data)

        self.assertNotIn(
            "must-not-leak",
            body,
        )
        self.assertNotIn(
            "FAILED-SECRET",
            body,
        )
