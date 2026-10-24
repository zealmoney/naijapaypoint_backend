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

from .models import CableTransaction
from .views import CablePurchaseView
from .serializers import (
    CablePlansSerializer,
    CablePurchaseSerializer,
    CableVerifySerializer,
)


class CableSerializerSecurityTests(
    SimpleTestCase
):
    def test_supported_providers_are_allowed(self):
        providers = (
            "dstv",
            "gotv",
            "startimes",
            "showmax",
        )

        for provider in providers:
            serializer = CablePlansSerializer(
                data={
                    "provider": provider,
                }
            )

            self.assertTrue(
                serializer.is_valid(),
                serializer.errors,
            )

    def test_arbitrary_provider_is_rejected(self):
        serializer = CablePlansSerializer(
            data={
                "provider": "evil-service",
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

    def test_purchase_rejects_arbitrary_provider(
        self,
    ):
        serializer = CablePurchaseSerializer(
            data={
                "provider": "evil-service",
                "smartcard_number": "1234567890",
                "plan_id": "TEST-PLAN",
            }
        )

        self.assertFalse(
            serializer.is_valid()
        )

    def test_client_price_and_name_are_discarded(
        self,
    ):
        serializer = CablePurchaseSerializer(
            data={
                "provider": "dstv",
                "smartcard_number": "1234567890",
                "plan_id": "TEST-PLAN",
                "plan_name": "Fake Cheap Plan",
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

class CablePlansSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="cable_plans_security_test",
            email="cable-plans-security@example.com",
            password="TestPassword123!",
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_plans_response_is_allowlisted(
        self,
        mock_get_plans,
    ):
        mock_get_plans.return_value = {
            "response_description":
                "Provider catalogue",
            "requestId":
                "CATALOGUE-SECRET",
            "content": {
                "serviceID": "dstv",
                "internal_provider_value":
                    "must-not-leak",
                "varations": [
                    {
                        "variation_code":
                            "TEST-PLAN-1",
                        "name":
                            "Test Cable Plan",
                        "variation_amount":
                            "4500.00",
                        "fixedPrice": "Yes",
                        "internal_plan_value":
                            "plan-secret",
                    }
                ],
            },
        }

        response = self.client.get(
            "/api/cable/plans/",
            {
                "provider": "dstv",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        self.assertEqual(
            response.data,
            [
                {
                    "plan_id":
                        "TEST-PLAN-1",
                    "plan_name":
                        "Test Cable Plan",
                    "amount":
                        "4500.00",
                }
            ],
        )

        response_text = str(response.data)

        self.assertNotIn(
            "CATALOGUE-SECRET",
            response_text,
        )
        self.assertNotIn(
            "must-not-leak",
            response_text,
        )
        self.assertNotIn(
            "plan-secret",
            response_text,
        )

    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_invalid_catalogue_response_is_safe(
        self,
        mock_get_plans,
    ):
        mock_get_plans.return_value = {
            "requestId":
                "INVALID-CATALOGUE-SECRET",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self.client.get(
            "/api/cable/plans/",
            {
                "provider": "dstv",
            },
        )

        self.assertEqual(
            response.status_code,
            502,
            response.data,
        )

        self.assertNotIn(
            "INVALID-CATALOGUE-SECRET",
            str(response.data),
        )
        self.assertNotIn(
            "must-not-leak",
            str(response.data),
        )

    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_catalogue_provider_exception_is_safe(
        self,
        mock_get_plans,
    ):
        mock_get_plans.side_effect = Exception(
            "secret catalogue timeout"
        )

        response = self.client.get(
            "/api/cable/plans/",
            {
                "provider": "dstv",
            },
        )

        self.assertEqual(
            response.status_code,
            502,
            response.data,
        )

        self.assertNotIn(
            "secret catalogue timeout",
            str(response.data),
        )

    @patch(
        "cable.views.VTPassCableService.get_plans"
    )
    def test_malformed_plan_is_excluded_from_catalogue(
        self,
        mock_get_plans,
    ):
        mock_get_plans.return_value = {
            "response_description": "Successful",
            "content": {
                "varations": [
                    {
                        "variation_code":
                            "VALID-PLAN-1",
                        "name":
                            "Valid Cable Plan",
                        "variation_amount":
                            "3500.00",
                    },
                    {
                        "variation_code":
                            "BROKEN-PLAN",
                        "name":
                            "Broken Cable Plan",
                        "variation_amount":
                            "not-a-price",
                        "internal_provider_value":
                            "must-not-leak",
                    },
                    {
                        "variation_code":
                            "VALID-PLAN-2",
                        "name":
                            "Second Valid Plan",
                        "variation_amount":
                            "5000.00",
                    },
                ]
            },
            "requestId":
                "CATALOGUE-SECRET-REFERENCE",
        }

        response = self.client.get(
            "/api/cable/plans/",
            {
                "provider": "dstv",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        self.assertEqual(
            response.data,
            [
                {
                    "plan_id":
                        "VALID-PLAN-1",
                    "plan_name":
                        "Valid Cable Plan",
                    "amount":
                        "3500.00",
                },
                {
                    "plan_id":
                        "VALID-PLAN-2",
                    "plan_name":
                        "Second Valid Plan",
                    "amount":
                        "5000.00",
                },
            ],
        )

        response_text = str(response.data)

        self.assertNotIn(
            "BROKEN-PLAN",
            response_text,
        )
        self.assertNotIn(
            "not-a-price",
            response_text,
        )
        self.assertNotIn(
            "internal_provider_value",
            response_text,
        )
        self.assertNotIn(
            "must-not-leak",
            response_text,
        )
        self.assertNotIn(
            "CATALOGUE-SECRET-REFERENCE",
            response_text,
        )

class CableVerificationSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="cable_verify_security_test",
            email="cable-verify-security@example.com",
            password="TestPassword123!",
        )

        self.client = APIClient()
        self.client.force_authenticate(
            user=self.user
        )

    @patch(
        "cable.views."
        "VTPassCableService.verify_smartcard"
    )
    def test_verification_does_not_expose_provider_response(
        self,
        mock_verify,
    ):
        mock_verify.return_value = {
            "code": "000",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "requestId":
                "PROVIDER-SECRET-REFERENCE",
            "content": {
                "Customer_Name":
                    "Test Customer",
                "Customer_Number":
                    "1234567890",
                "Status": "ACTIVE",
                "internal_provider_value":
                    "must-not-leak",
            },
        }

        response = self.client.post(
            "/api/cable/verify/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
            response.data,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "PROVIDER-SECRET-REFERENCE",
            response_text,
        )
        self.assertNotIn(
            "must-not-leak",
            response_text,
        )
        self.assertNotIn(
            "requestId",
            response.data,
        )

    @patch(
        "cable.views."
        "VTPassCableService.verify_smartcard"
    )
    def test_failed_verification_does_not_expose_provider_response(
        self,
        mock_verify,
    ):
        mock_verify.return_value = {
            "code": "016",
            "response_description":
                "TRANSACTION FAILED",
            "requestId":
                "FAILED-VERIFY-SECRET",
            "internal_provider_value":
                "failed-secret-must-not-leak",
        }

        response = self.client.post(
            "/api/cable/verify/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            400,
            response.data,
        )

        response_text = str(response.data)

        self.assertNotIn(
            "FAILED-VERIFY-SECRET",
            response_text,
        )
        self.assertNotIn(
            "failed-secret-must-not-leak",
            response_text,
        )

    @patch(
        "cable.views."
        "VTPassCableService.verify_smartcard"
    )
    def test_verification_provider_exception_is_safe(
        self,
        mock_verify,
    ):
        mock_verify.side_effect = Exception(
            "secret cable verification timeout"
        )

        response = self.client.post(
            "/api/cable/verify/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            502,
            response.data,
        )

        self.assertNotIn(
            "secret cable verification timeout",
            str(response.data),
        )

class CablePurchaseSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="cable_security_test",
            email="cable-security@example.com",
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
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
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
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "000",
            "response_description":
                "TRANSACTION SUCCESSFUL",
            "requestId": "PROVIDER-CABLE-1",
        }

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
                "plan_id":
                    "TEST-CABLE-PLAN",
                "customer_name":
                    "Test Customer",

                # Deliberately tampered values.
                "plan_name":
                    "Fake Cheap Plan",
                "amount": "1.00",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )

        cable_tx = (
            CableTransaction.objects.get(
                user=self.user
            )
        )

        self.assertEqual(
            cable_tx.plan_name,
            "Authoritative Cable Plan",
        )
        self.assertEqual(
            cable_tx.amount,
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
            "TEST-CABLE-PLAN",
        )
        self.assertEqual(
            purchase_kwargs["amount"],
            Decimal("4500.00"),
        )

    @patch(
        "cable.views.NotificationService"
        ".create_notification"
    )
    @patch(
        "cable.views.VTPassCableService"
        ".purchase_subscription"
    )
    @patch(
        "cable.views.VTPassCableService.get_plans"
    )
    def test_provider_exception_does_not_refund(
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
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.side_effect = Exception(
            "Simulated provider timeout"
        )

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number": "1234567890",
                "plan_id": "TEST-CABLE-PLAN",
                "customer_name": "Test Customer",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        cable_tx = CableTransaction.objects.get(
            user=self.user,
        )
        main_tx = Transaction.objects.get(
            reference=cable_tx.reference,
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            cable_tx.status,
            "pending",
        )
        self.assertEqual(
            main_tx.status,
            "pending",
        )
        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                reference=(
                    f"REFUND-{cable_tx.reference}"
                ),
                transaction_type="credit",
            ).exists()
        )

    @patch(
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
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
                        "variation_code":
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "000",
            "requestId":
                "PROVIDER-SECRET-REFERENCE",
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
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number": "1234567890",
                "plan_id": "TEST-CABLE-PLAN",
                "customer_name": "Test Customer",
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
            "PROVIDER-SECRET-REFERENCE",
            str(response.data),
        )

        self.assertNotIn(
            "internal_provider_value",
            str(response.data),
        )

        cable_tx = (
            CableTransaction.objects.get(
                user=self.user
            )
        )

        self.assertEqual(
            cable_tx.provider_response,
            {
                "code": "000",
                "result": "success",
            },
        )

        main_tx = Transaction.objects.get(
            reference=cable_tx.reference
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
            "internal_provider_value",
            str(main_tx.metadata),
        )

    @patch(
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_pending_response_does_not_expose_provider_response(
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
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "099",
            "requestId": "PENDING-SECRET",
            "response_description":
                "TRANSACTION PENDING",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
                "plan_id":
                    "TEST-CABLE-PLAN",
                "customer_name":
                    "Test Customer",
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
            "provider_result",
            response.data,
        )
        self.assertNotIn(
            "PENDING-SECRET",
            str(response.data),
        )
        self.assertNotIn(
            "internal_provider_value",
            str(response.data),
        )


    @patch(
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_manual_review_does_not_expose_provider_response(
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
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "015",
            "requestId": "REVIEW-SECRET",
            "response_description":
                "UNKNOWN PROVIDER STATE",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
                "plan_id":
                    "TEST-CABLE-PLAN",
                "customer_name":
                    "Test Customer",
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
            "provider_result",
            response.data,
        )
        self.assertNotIn(
            "REVIEW-SECRET",
            str(response.data),
        )
        self.assertNotIn(
            "internal_provider_value",
            str(response.data),
        )


    @patch(
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
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
                        "variation_code":
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.return_value = {
            "code": "016",
            "requestId": "FAILED-SECRET",
            "response_description":
                "TRANSACTION FAILED",
            "internal_provider_value":
                "must-not-leak",
        }

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
                "plan_id":
                    "TEST-CABLE-PLAN",
                "customer_name":
                    "Test Customer",
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
            "provider_result",
            response.data,
        )
        self.assertNotIn(
            "FAILED-SECRET",
            str(response.data),
        )
        self.assertNotIn(
            "internal_provider_value",
            str(response.data),
        )

    @patch(
        "cable.views."
        "NotificationService.create_notification"
    )
    @patch(
        "cable.views."
        "VTPassCableService.purchase_subscription"
    )
    @patch(
        "cable.views."
        "VTPassCableService.get_plans"
    )
    def test_provider_exception_detail_is_not_exposed(
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
                            "TEST-CABLE-PLAN",
                        "name":
                            "Authoritative Cable Plan",
                        "variation_amount":
                            "4500.00",
                    }
                ]
            }
        }

        mock_purchase.side_effect = TimeoutError(
            "secret provider timeout detail"
        )

        starting_balance = (
            self.user.wallet.balance
        )

        response = self.client.post(
            "/api/cable/purchase/",
            {
                "provider": "dstv",
                "smartcard_number":
                    "1234567890",
                "plan_id":
                    "TEST-CABLE-PLAN",
                "customer_name":
                    "Test Customer",
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

        self.assertNotIn(
            "provider_response",
            response.data,
        )

        self.assertNotIn(
            "provider_result",
            response.data,
        )

        cable_tx = (
            CableTransaction.objects.get(
                user=self.user
            )
        )

        self.assertEqual(
            cable_tx.status,
            "pending",
        )

        main_tx = Transaction.objects.get(
            reference=cable_tx.reference,
            service_type="cable",
        )

        self.assertEqual(
            main_tx.status,
            "pending",
        )

        self.user.wallet.refresh_from_db()

        self.assertEqual(
            self.user.wallet.balance,
            starting_balance
            - Decimal("4500.00"),
        )

        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.user.wallet,
                transaction_type="credit",
                reference=(
                    f"REFUND-"
                    f"{cable_tx.reference}"
                ),
            ).exists()
        )

class CableRefundSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="cable_refund_test",
            email="cable-refund@example.com",
            password="TestPassword123!",
        )

        self.wallet = self.user.wallet
        self.wallet.balance = Decimal("5500.00")
        self.wallet.save(
            update_fields=["balance"]
        )

        self.reference = "CABLE-SECURITY-TEST"
        self.amount = Decimal("4500.00")

        self.cable_tx = CableTransaction.objects.create(
            user=self.user,
            provider="dstv",
            smartcard_number="1234567890",
            plan_id="TEST-CABLE-PLAN",
            plan_name="Test Cable Plan",
            customer_name="Test Customer",
            amount=self.amount,
            reference=self.reference,
            status="pending",
        )

        self.main_tx = Transaction.objects.create(
            user=self.user,
            service_type="cable",
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
            description="Test original cable debit",
        )

    def test_pending_transaction_refunds_once(
        self,
    ):
        provider_response = {
            "code": "016",
            "response_description": "Failed",
        }

        (
            cable_tx,
            main_tx,
            refunded,
        ) = CablePurchaseView._refund_pending_transaction(
            cable_tx=self.cable_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response=provider_response,
            refund_message=(
                "Refund for failed cable subscription"
            ),
        )

        self.assertTrue(refunded)

        self.wallet.refresh_from_db()
        cable_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
        )
        self.assertEqual(
            cable_tx.status,
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
            CablePurchaseView
            ._refund_pending_transaction(
                cable_tx=self.cable_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=provider_response,
                refund_message=(
                    "Refund for failed "
                    "cable subscription"
                ),
            )
        )

        second_result = (
            CablePurchaseView
            ._refund_pending_transaction(
                cable_tx=self.cable_tx,
                main_tx=self.main_tx,
                amount=self.amount,
                reference=self.reference,
                provider_response=provider_response,
                refund_message=(
                    "Refund for failed "
                    "cable subscription"
                ),
            )
        )

        self.assertTrue(first_result[2])
        self.assertFalse(second_result[2])

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("10000.00"),
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
            cable_tx,
            main_tx,
            refunded,
        ) = CablePurchaseView._refund_pending_transaction(
            cable_tx=self.cable_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response={
                "code": "016",
                "response_description": "Failed",
            },
            refund_message=(
                "Refund for failed "
                "cable subscription"
            ),
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()
        cable_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )
        self.assertEqual(
            cable_tx.status,
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
        self.cable_tx.status = "success"
        self.cable_tx.save(
            update_fields=["status"]
        )

        self.main_tx.status = "success"
        self.main_tx.save(
            update_fields=["status"]
        )

        (
            cable_tx,
            main_tx,
            refunded,
        ) = CablePurchaseView._refund_pending_transaction(
            cable_tx=self.cable_tx,
            main_tx=self.main_tx,
            amount=self.amount,
            reference=self.reference,
            provider_response={
                "code": "016",
                "response_description": "Failed",
            },
            refund_message=(
                "Refund for failed "
                "cable subscription"
            ),
        )

        self.assertFalse(refunded)

        self.wallet.refresh_from_db()
        cable_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )
        self.assertEqual(
            cable_tx.status,
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
        self.cable_tx.status = "refunded"
        self.cable_tx.save(
            update_fields=["status"]
        )

        self.main_tx.status = "refunded"
        self.main_tx.save(
            update_fields=["status"]
        )

        (
            cable_tx,
            main_tx,
            marked_success,
        ) = (
            CablePurchaseView
            ._mark_pending_transaction_success(
                cable_tx=self.cable_tx,
                main_tx=self.main_tx,
            )
        )

        self.assertFalse(marked_success)

        cable_tx.refresh_from_db()
        main_tx.refresh_from_db()

        self.assertEqual(
            cable_tx.status,
            "refunded",
        )
        self.assertEqual(
            main_tx.status,
            "refunded",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.balance,
            Decimal("5500.00"),
        )