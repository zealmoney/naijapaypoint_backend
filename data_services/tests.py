from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from wallets.models import (
    Wallet,
    WalletTransaction,
)
from transactions.models import Transaction
from .views import DataPurchaseView

from .models import DataTransaction

from .serializers import (
    DataPlansSerializer,
    DataPurchaseSerializer,
)


class DataSerializerSecurityTests(
    SimpleTestCase
):
    def test_supported_networks_are_allowed(self):
        networks = (
            "mtn-data",
            "airtel-data",
            "glo-data",
            "etisalat-data",
        )

        for network in networks:
            serializer = DataPlansSerializer(
                data={
                    "network": network,
                }
            )

            self.assertTrue(
                serializer.is_valid(),
                serializer.errors,
            )

    def test_arbitrary_network_is_rejected(self):
        serializer = DataPlansSerializer(
            data={
                "network": "evil-service",
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

    def test_purchase_rejects_arbitrary_network(
        self,
    ):
        serializer = DataPurchaseSerializer(
            data={
                "network": "evil-service",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

    def test_client_price_and_name_are_discarded(
        self,
    ):
        serializer = DataPurchaseSerializer(
            data={
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
                "plan_name": "Fake Plan",
                "amount": "1.00",
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

class DataPurchaseSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="data_security_test",
            email="data-security@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("5000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

    @patch(
        "data_services.views."
        "NotificationService.create_notification"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_client_cannot_override_plan_price(
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
                            "TEST-PLAN",
                        "name":
                            "Authoritative Plan",
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
            "requestId": "PROVIDER-TEST-1",
        }

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number":
                    "08000000001",
                "plan_id": "TEST-PLAN",

                # Deliberately tampered values.
                "plan_name": "Fake Cheap Plan",
                "amount": "1.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        data_tx = DataTransaction.objects.get(
            user=self.user
        )

        self.assertEqual(
            data_tx.plan_name,
            "Authoritative Plan",
        )
        self.assertEqual(
            data_tx.amount,
            Decimal("1500.00"),
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )

        mock_purchase.assert_called_once()

        purchase_kwargs = (
            mock_purchase.call_args.kwargs
        )

        self.assertEqual(
            purchase_kwargs["variation_code"],
            "TEST-PLAN",
        )
        self.assertEqual(
            purchase_kwargs["amount"],
            Decimal("1500.00"),
        )

    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_provider_exception_does_not_refund(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code":
                            "TEST-PLAN",
                        "name":
                            "Authoritative Plan",
                        "variation_amount":
                            "1500.00",
                    }
                ]
            }
        }

        mock_purchase.side_effect = Exception(
            "Simulated provider timeout"
        )

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number":
                    "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        data_tx = DataTransaction.objects.get(
            user=self.user
        )

        main_tx = Transaction.objects.get(
            reference=data_tx.reference
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("3500.00"),
        )
        self.assertEqual(
            data_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=(
                    f"REFUND-{data_tx.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )

    @patch(
        "data_services.views."
        "NotificationService.create_notification"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_success_response_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
        mock_notification,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "TEST-PLAN",
                        "name": "Authoritative Plan",
                        "variation_amount": "1500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "000",
            "requestId": "PROVIDER-SECRET-REFERENCE",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "content": {
                "transactions": {
                    "status": "delivered",
                    "internal_provider_value":
                        "must-not-leak",
                }
            },
        }

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "must-not-leak",
            str(response.data),
        )

        data_tx = DataTransaction.objects.get(
            user=self.user
        )

        # Store only sanitized provider information.
        self.assertEqual(
            data_tx.provider_response,
            {
                "code": "000",
                "result": "success",
            },
        )

        # Preserve the provider reference separately
        # for transaction reconciliation.
        main_tx = Transaction.objects.get(
            reference=data_tx.reference
        )

        self.assertEqual(
            main_tx.provider_reference,
            "PROVIDER-SECRET-REFERENCE",
        )

        self.assertEqual(
            main_tx.metadata["provider_response"],
            {
                "code": "000",
                "result": "success",
            },
        )

        self.assertNotIn(
            "must-not-leak",
            str(main_tx.metadata),
        )

    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_pending_response_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "TEST-PLAN",
                        "name": "Authoritative Plan",
                        "variation_amount": "1500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "099",
            "response_description":
                "Transaction is being processed",
            "internal_provider_value":
                "pending-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "pending-secret-must-not-leak",
            str(response.data),
        )

        transaction_data = response.data.get(
            "transaction",
            {},
        )

        self.assertNotIn(
            "provider_response",
            transaction_data,
        )

    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_provider_exception_detail_is_not_exposed(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "TEST-PLAN",
                        "name": "Authoritative Plan",
                        "variation_amount": "1500.00",
                    }
                ]
            }
        }

        mock_purchase.side_effect = TimeoutError(
            "secret provider timeout detail"
        )

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        self.assertNotIn(
            "secret provider timeout detail",
            str(response.data),
        )

        data_tx = DataTransaction.objects.get(
            user=self.user
        )

        self.assertNotIn(
            "secret provider timeout detail",
            str(data_tx.provider_response),
        )

        self.assertEqual(
            data_tx.status,
            "pending",
        )

    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_manual_review_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "TEST-PLAN",
                        "name": "Authoritative Plan",
                        "variation_amount": "1500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "099",
            "response_description":
                "Transaction requires manual review",
            "internal_provider_value":
                "manual-review-secret",
        }

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "manual-review-secret",
            str(response.data),
        )

    @patch(
        "data_services.views."
        "NotificationService.create_notification"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.purchase_data"
    )
    @patch(
        "data_services.views."
        "VTPassDataService.get_data_plans"
    )
    def test_failed_response_does_not_expose_provider_response(
        self,
        mock_get_plans,
        mock_purchase,
        mock_notification,
    ):
        mock_get_plans.return_value = {
            "content": {
                "varations": [
                    {
                        "variation_code": "TEST-PLAN",
                        "name": "Authoritative Plan",
                        "variation_amount": "1500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "016",
            "response_description":
                "TRANSACTION FAILED",
            "internal_provider_value":
                "failed-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/data/purchase/",
            {
                "network": "mtn-data",
                "phone_number": "08000000001",
                "plan_id": "TEST-PLAN",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
            response.data,
        )

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "failed-secret-must-not-leak",
            str(response.data),
        )

class DataRefundSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="data_refund_test",
            email="data-refund@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("4000.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.reference = "DATA-SECURITY-TEST"
        self.amount = Decimal("1000.00")

        self.data_tx = DataTransaction.objects.create(
            user=self.user,
            network="mtn-data",
            phone_number="08000000000",
            plan_id="TEST-PLAN",
            plan_name="Test Plan",
            amount=self.amount,
            reference=self.reference,
            status="pending",
        )

        self.main_tx = Transaction.objects.create(
            user=self.user,
            service_type="data",
            amount=self.amount,
            reference=self.reference,
            status="pending",
            provider="vtpass",
        )

        WalletTransaction.objects.create(
            wallet=self.wallet,
            transaction_type="debit",
            amount=self.amount,
            reference=self.reference,
            description="Test original data debit",
        )

    def test_pending_transaction_refunds_once(
        self,
    ):
        provider_response = {
            "code": "016",
            "response_description": "Failed",
        }

        (
            data_tx,
            main_tx,
            refunded,
        ) = DataPurchaseView._refund_pending_transaction(
            data_tx=self.data_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response=provider_response,
            refund_message=(
                "Refund for failed data purchase"
            ),
        )

        self.assertTrue(refunded)

        self.wallet.refresh_from_db()
        data_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )
        self.assertEqual(
            data_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
                amount=self.amount,
            ).count(),
            1,
        )

    def test_refund_cannot_apply_twice(self):
        provider_response = {
            "code": "016",
            "response_description": "Failed",
        }

        first_result = (
            DataPurchaseView
            ._refund_pending_transaction(
                data_tx=self.data_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=provider_response,
                refund_message=(
                    "Refund for failed data purchase"
                ),
            )
        )

        second_result = (
            DataPurchaseView
            ._refund_pending_transaction(
                data_tx=self.data_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=provider_response,
                refund_message=(
                    "Refund for failed data purchase"
                ),
            )
        )

        self.assertTrue(first_result[2])
        self.assertFalse(second_result[2])

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
            ).count(),
            1,
        )

    def test_refund_requires_matching_original_debit(
        self,
    ):
        WalletTransaction.objects.filter(
            wallet=self.wallet,
            reference=self.reference,
            transaction_type="debit",
        ).delete()

        (
            data_tx,
            main_tx,
            refunded,
        ) = DataPurchaseView._refund_pending_transaction(
            data_tx=self.data_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response={
                "code": "016",
                "response_description": "Failed",
            },
            refund_message=(
                "Refund for failed data purchase"
            ),
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()
        data_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4000.00"),
        )
        self.assertEqual(
            data_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
            ).exists()
        )

    def test_successful_transaction_cannot_be_refunded(
        self,
    ):
        self.data_tx.status = "success"
        self.data_tx.save(
            update_fields=["status"]
        )

        self.main_tx.status = "success"
        self.main_tx.save(
            update_fields=["status"]
        )

        (
            data_tx,
            main_tx,
            refunded,
        ) = DataPurchaseView._refund_pending_transaction(
            data_tx=self.data_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response={
                "code": "016",
                "response_description": "Failed",
            },
            refund_message=(
                "Refund for failed data purchase"
            ),
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()
        data_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("4000.00"),
        )
        self.assertEqual(
            data_tx.status,
            "success",
        )
        self.assertEqual(
            main_tx.status,
            "success",
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
            ).exists()
        )

    def test_refunded_transaction_cannot_be_marked_success(
        self,
    ):
        (
            data_tx,
            main_tx,
            refunded,
        ) = DataPurchaseView._refund_pending_transaction(
            data_tx=self.data_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response={
                "code": "016",
                "response_description": "Failed",
            },
            refund_message=(
                "Refund for failed data purchase"
            ),
        )

        self.assertTrue(refunded)

        (
            data_tx,
            main_tx,
            marked_success,
        ) = DataPurchaseView._mark_pending_transaction_success(
            data_tx=data_tx,
            main_tx=main_tx,
        )

        self.assertFalse(marked_success)

        self.wallet.refresh_from_db()
        data_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5000.00"),
        )
        self.assertEqual(
            data_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=f"REFUND-{self.reference}",
                transaction_type="credit",
            ).count(),
            1,
        )