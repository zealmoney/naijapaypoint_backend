from django.test import TestCase
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.urls import reverse

from rest_framework.test import APIClient

from .models import KYCVerification

from .serializers import KYCUpdateSerializer
from .services import KYCService

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.exceptions import ValidationError

from .serializers import validate_kyc_image

from .serializers import (
    AdminKYCDetailSerializer,
    KYCVerificationSerializer,
)
from .views import _serve_kyc_document

User = get_user_model()


class KYCDocumentNumberSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="kyc_test_user",
            email="kyc-test@example.com",
            password="StrongTestPassword123!",
        )

        self.verification = KYCVerification.objects.create(
            user=self.user,
            status=KYCVerification.Status.DRAFT,
            document_type=KYCVerification.DocumentType.NATIONAL_ID,
            document_number="OLD-DOCUMENT-1234",
            document_number_last4="1234",
        )

    def test_changing_document_number_clears_stale_last4(self):
        serializer = KYCUpdateSerializer(
            self.verification,
            data={
                "document_number": "NEW-DOCUMENT-9999",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        verification = serializer.save()

        self.assertEqual(
            verification.document_number,
            "NEW-DOCUMENT-9999",
        )

        self.assertEqual(
            verification.document_number_last4,
            "",
        )

    def test_unrelated_edit_preserves_document_number_last4(self):
        serializer = KYCUpdateSerializer(
            self.verification,
            data={
                "first_name": "SecurityTest",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        verification = serializer.save()

        self.assertEqual(
            verification.document_number_last4,
            "1234",
        )

class KYCTerminalStateRetentionTests(TestCase):
    def setUp(self):
        self.reviewer = User.objects.create_user(
            username="kyc_reviewer",
            email="kyc-reviewer@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

    def _create_submitted_verification(
        self,
        username,
        email,
        document_number,
        identity_value,
    ):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="StrongTestPassword123!",
        )

        verification = KYCVerification.objects.create(
            user=user,
            status=KYCVerification.Status.SUBMITTED,
            document_type=(
                KYCVerification.DocumentType.NATIONAL_ID
            ),
            document_number=document_number,
            identity_verification_method=(
                KYCVerification
                .IdentityVerificationMethod
                .BVN
            ),
            identity_verification_value=identity_value,
        )

        return user, verification

    def test_approval_clears_raw_sensitive_values_and_preserves_last4(self):
        user, verification = self._create_submitted_verification(
            username="approval_test_user",
            email="approval-test@example.com",
            document_number="NATIONAL-ID-5678",
            identity_value="12345678901",
        )

        result = KYCService.approve_verification(
            verification.id,
            self.reviewer,
            "Approved during security test.",
        )

        result.refresh_from_db()
        user.refresh_from_db()

        self.assertEqual(
            result.status,
            KYCVerification.Status.APPROVED,
        )

        self.assertEqual(
            result.document_number,
            "",
        )
        self.assertEqual(
            result.document_number_last4,
            "5678",
        )

        self.assertEqual(
            result.identity_verification_value,
            "",
        )
        self.assertEqual(
            result.identity_verification_last4,
            "8901",
        )

        self.assertTrue(user.is_verified)

    def test_rejection_clears_raw_sensitive_values_and_preserves_last4(self):
        user, verification = self._create_submitted_verification(
            username="rejection_test_user",
            email="rejection-test@example.com",
            document_number="PASSPORT-2468",
            identity_value="10987654321",
        )

        result = KYCService.reject_verification(
            verification.id,
            self.reviewer,
            "Document could not be verified.",
            "Rejected during security test.",
        )

        result.refresh_from_db()
        user.refresh_from_db()

        self.assertEqual(
            result.status,
            KYCVerification.Status.REJECTED,
        )

        self.assertEqual(
            result.document_number,
            "",
        )
        self.assertEqual(
            result.document_number_last4,
            "2468",
        )

        self.assertEqual(
            result.identity_verification_value,
            "",
        )
        self.assertEqual(
            result.identity_verification_last4,
            "4321",
        )

        self.assertFalse(user.is_verified)

class KYCDocumentAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()

        self.customer_one = User.objects.create_user(
            username="document_customer_one",
            email="document-customer-one@example.com",
            password="StrongTestPassword123!",
        )

        self.customer_two = User.objects.create_user(
            username="document_customer_two",
            email="document-customer-two@example.com",
            password="StrongTestPassword123!",
        )

        self.non_reviewer_staff = User.objects.create_user(
            username="document_staff_no_permission",
            email="document-staff-no-permission@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.reviewer = User.objects.create_user(
            username="document_reviewer",
            email="document-reviewer@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        reviewer_permission = Permission.objects.get(
            codename="review_kycverification",
        )
        self.reviewer.user_permissions.add(
            reviewer_permission
        )

        self.verification_one = (
            KYCVerification.objects.create(
                user=self.customer_one,
                status=KYCVerification.Status.SUBMITTED,
                document_type=(
                    KYCVerification.DocumentType.NATIONAL_ID
                ),
            )
        )

        self.verification_two = (
            KYCVerification.objects.create(
                user=self.customer_two,
                status=KYCVerification.Status.SUBMITTED,
                document_type=(
                    KYCVerification.DocumentType.NATIONAL_ID
                ),
            )
        )

    @patch("kyc.views._serve_kyc_document")
    def test_customer_document_endpoint_uses_only_authenticated_users_kyc(
        self,
        mock_serve_document,
    ):
        mock_serve_document.return_value = HttpResponse(
            b"protected-document",
            content_type="image/jpeg",
        )

        self.client.force_authenticate(
            user=self.customer_one
        )

        response = self.client.get(
            reverse(
                "kyc:document",
                kwargs={
                    "document_type": "front",
                },
            )
        )

        self.assertEqual(response.status_code, 200)

        mock_serve_document.assert_called_once()

        served_verification = (
            mock_serve_document.call_args.args[0]
        )

        self.assertEqual(
            served_verification.pk,
            self.verification_one.pk,
        )

        self.assertNotEqual(
            served_verification.pk,
            self.verification_two.pk,
        )

    @patch("kyc.views._serve_kyc_document")
    def test_unauthenticated_user_cannot_access_customer_document(
        self,
        mock_serve_document,
    ):
        response = self.client.get(
            reverse(
                "kyc:document",
                kwargs={
                    "document_type": "front",
                },
            )
        )

        self.assertEqual(response.status_code, 401)
        mock_serve_document.assert_not_called()

    @patch("kyc.views._serve_kyc_document")
    def test_staff_without_reviewer_permission_cannot_access_admin_document(
        self,
        mock_serve_document,
    ):
        self.client.force_authenticate(
            user=self.non_reviewer_staff
        )

        response = self.client.get(
            reverse(
                "kyc:admin-document",
                kwargs={
                    "verification_id": (
                        self.verification_one.pk
                    ),
                    "document_type": "front",
                },
            )
        )

        self.assertEqual(response.status_code, 403)
        mock_serve_document.assert_not_called()

    @patch("kyc.views.AuditLogService.log_action")
    @patch("kyc.views._serve_kyc_document")
    def test_authorized_reviewer_can_access_admin_document(
        self,
        mock_serve_document,
        mock_log_action,
    ):
        mock_serve_document.return_value = HttpResponse(
            b"protected-document",
            content_type="image/jpeg",
        )

        self.client.force_authenticate(
            user=self.reviewer
        )

        response = self.client.get(
            reverse(
                "kyc:admin-document",
                kwargs={
                    "verification_id": (
                        self.verification_one.pk
                    ),
                    "document_type": "front",
                },
            )
        )

        self.assertEqual(response.status_code, 200)

        mock_serve_document.assert_called_once()

        served_verification = (
            mock_serve_document.call_args.args[0]
        )

        self.assertEqual(
            served_verification.pk,
            self.verification_one.pk,
        )

        mock_log_action.assert_called_once()

class KYCPrivacyRegressionTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.customer = User.objects.create_user(
            username="kyc_privacy_customer",
            email="kyc-privacy-customer@example.com",
            password="StrongTestPassword123!",
        )

        self.reviewer = User.objects.create_user(
            username="kyc_privacy_reviewer",
            email="kyc-privacy-reviewer@example.com",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        self.verification = KYCVerification.objects.create(
            user=self.customer,
            status=KYCVerification.Status.SUBMITTED,
            document_type=(
                KYCVerification.DocumentType.NATIONAL_ID
            ),
            document_number="NATIONAL-ID-5678",
            identity_verification_method=(
                KYCVerification
                .IdentityVerificationMethod
                .BVN
            ),
            identity_verification_value="12345678901",
            review_note="Internal reviewer note",
            reviewed_by=self.reviewer,
        )

    def test_customer_serializer_does_not_expose_raw_sensitive_fields(self):
        data = KYCVerificationSerializer(
            self.verification
        ).data

        self.assertNotIn(
            "document_number",
            data,
        )
        self.assertNotIn(
            "identity_verification_value",
            data,
        )
        self.assertNotIn(
            "review_note",
            data,
        )
        self.assertNotIn(
            "reviewed_by",
            data,
        )

        self.assertIn(
            "masked_document_number",
            data,
        )
        self.assertIn(
            "masked_identity_verification_value",
            data,
        )

        serialized_text = str(data)

        self.assertNotIn(
            "NATIONAL-ID-5678",
            serialized_text,
        )
        self.assertNotIn(
            "12345678901",
            serialized_text,
        )
        self.assertNotIn(
            "Internal reviewer note",
            serialized_text,
        )

    def test_admin_serializer_may_expose_review_fields_but_not_raw_identity_value(
        self,
    ):
        data = AdminKYCDetailSerializer(
            self.verification
        ).data

        self.assertNotIn(
            "identity_verification_value",
            data,
        )

        self.assertIn(
            "masked_identity_verification_value",
            data,
        )

        self.assertNotIn(
            "12345678901",
            str(data),
        )

    @patch("kyc.views._serve_kyc_document")
    def test_customer_document_response_has_no_store_cache_policy(
        self,
        mock_serve_document,
    ):
        response_from_helper = HttpResponse(
            b"protected-document",
            content_type="image/jpeg",
        )
        response_from_helper[
            "Cache-Control"
        ] = "private, no-store"

        mock_serve_document.return_value = (
            response_from_helper
        )

        client = APIClient()
        client.force_authenticate(
            user=self.customer
        )

        response = client.get(
            reverse(
                "kyc:document",
                kwargs={
                    "document_type": "front",
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response["Cache-Control"],
            "private, no-store",
        )

class KYCImageFormatValidationTests(TestCase):
    def _make_image_upload(
        self,
        *,
        actual_format,
        filename,
        content_type,
    ):
        image_bytes = BytesIO()

        Image.new(
            "RGB",
            (20, 20),
        ).save(
            image_bytes,
            format=actual_format,
        )

        return SimpleUploadedFile(
            filename,
            image_bytes.getvalue(),
            content_type=content_type,
        )

    def test_valid_jpeg_is_accepted(self):
        uploaded_file = self._make_image_upload(
            actual_format="JPEG",
            filename="identity.jpg",
            content_type="image/jpeg",
        )

        result = validate_kyc_image(
            uploaded_file
        )

        self.assertIs(
            result,
            uploaded_file,
        )
        self.assertEqual(
            uploaded_file.tell(),
            0,
        )

    def test_png_renamed_as_jpg_is_rejected(self):
        uploaded_file = self._make_image_upload(
            actual_format="PNG",
            filename="identity.jpg",
            content_type="image/jpeg",
        )

        with self.assertRaises(ValidationError):
            validate_kyc_image(
                uploaded_file
            )

        self.assertEqual(
            uploaded_file.tell(),
            0,
        )

    def test_jpeg_with_png_mime_type_is_rejected(self):
        uploaded_file = self._make_image_upload(
            actual_format="JPEG",
            filename="identity.jpg",
            content_type="image/png",
        )

        with self.assertRaises(ValidationError):
            validate_kyc_image(
                uploaded_file
            )

        self.assertEqual(
            uploaded_file.tell(),
            0,
        )

    def test_valid_png_is_accepted(self):
        uploaded_file = self._make_image_upload(
            actual_format="PNG",
            filename="identity.png",
            content_type="image/png",
        )

        result = validate_kyc_image(
            uploaded_file
        )

        self.assertIs(
            result,
            uploaded_file,
        )
        self.assertEqual(
            uploaded_file.tell(),
            0,
        )

class KYCStateMachineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="kyc_state_user",
            email="kyc-state@example.com",
            password="StrongTestPassword123!",
        )

    def _create_verification(self, status):
        return KYCVerification.objects.create(
            user=self.user,
            status=status,
        )

    def test_submitted_under_review_and_approved_cannot_be_edited(self):
        locked_statuses = [
            KYCVerification.Status.SUBMITTED,
            KYCVerification.Status.UNDER_REVIEW,
            KYCVerification.Status.APPROVED,
        ]

        for status in locked_statuses:
            with self.subTest(status=status):
                verification = self._create_verification(
                    status
                )

                serializer = KYCUpdateSerializer(
                    verification,
                    data={
                        "first_name": "BlockedEdit",
                    },
                    partial=True,
                )

                self.assertFalse(serializer.is_valid())

                self.assertIn(
                    "detail",
                    serializer.errors,
                )

                verification.delete()

    def test_submitted_under_review_and_approved_cannot_be_submitted(self):
        locked_statuses = [
            KYCVerification.Status.SUBMITTED,
            KYCVerification.Status.UNDER_REVIEW,
            KYCVerification.Status.APPROVED,
        ]

        for status in locked_statuses:
            with self.subTest(status=status):
                verification = self._create_verification(
                    status
                )

                with self.assertRaises(ValidationError):
                    KYCService.submit_verification(
                        self.user
                    )

                verification.delete()

    def test_incomplete_draft_cannot_be_submitted(self):
        verification = self._create_verification(
            KYCVerification.Status.DRAFT
        )

        with self.assertRaises(ValidationError) as context:
            KYCService.submit_verification(
                self.user
            )

        error_detail = context.exception.detail

        self.assertIn("fields", error_detail)
        self.assertIn(
            "first_name",
            error_detail["fields"],
        )
        self.assertIn(
            "document_number",
            error_detail["fields"],
        )
        self.assertIn(
            "document_front",
            error_detail["fields"],
        )
        self.assertIn(
            "selfie",
            error_detail["fields"],
        )

        verification.refresh_from_db()

        self.assertEqual(
            verification.status,
            KYCVerification.Status.DRAFT,
        )

    def test_not_started_can_be_edited_and_moves_to_draft(self):
        verification = self._create_verification(
            KYCVerification.Status.NOT_STARTED
        )

        serializer = KYCUpdateSerializer(
            verification,
            data={
                "first_name": "StateTest",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        verification = serializer.save()

        self.assertEqual(
            verification.status,
            KYCVerification.Status.DRAFT,
        )

        self.assertEqual(
            verification.first_name,
            "StateTest",
        )

    def test_rejected_can_be_edited_and_moves_to_draft(self):
        verification = self._create_verification(
            KYCVerification.Status.REJECTED
        )

        serializer = KYCUpdateSerializer(
            verification,
            data={
                "first_name": "ResubmissionTest",
            },
            partial=True,
        )

        self.assertTrue(
            serializer.is_valid(),
            serializer.errors,
        )

        verification = serializer.save()

        self.assertEqual(
            verification.status,
            KYCVerification.Status.DRAFT,
        )

        self.assertEqual(
            verification.first_name,
            "ResubmissionTest",
        )

class KYCDocumentResponseSecurityTests(TestCase):
    def test_serve_document_sets_private_no_store_cache_policy(self):
        user = User.objects.create_user(
            username="kyc_cache_test_user",
            email="kyc-cache-test@example.com",
            password="StrongTestPassword123!",
        )

        verification = KYCVerification(
            user=user,
        )

        document = SimpleUploadedFile(
            "identity.jpg",
            b"protected-document-content",
            content_type="image/jpeg",
        )

        verification.document_front = document

        response = _serve_kyc_document(
            verification,
            "front",
        )

        self.assertEqual(
            response["Cache-Control"],
            "private, no-store",
        )

        self.assertEqual(
            response["Content-Type"],
            "image/jpeg",
        )

        self.assertIn(
            'filename="kyc-front.jpg"',
            response["Content-Disposition"],
        )

        response.close()