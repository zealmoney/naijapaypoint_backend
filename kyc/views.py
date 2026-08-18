from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import (
    FormParser,
    JSONParser,
    MultiPartParser,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import KYCVerification
from .serializers import (
    AdminKYCDetailSerializer,
    AdminKYCListSerializer,
    KYCApproveSerializer,
    KYCRejectSerializer,
    KYCStartSerializer,
    KYCSubmitSerializer,
    KYCUpdateSerializer,
    KYCVerificationSerializer,
)
from .automated_verification import (
    KYCAutomatedVerificationService,
)
from .services import KYCService
from .permissions import IsKYCReviewer


class KYCStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        verification = KYCService.get_for_user(
            request.user
        )

        if verification is None:
            return Response(
                {
                    "exists": False,
                    "status": (
                        KYCVerification.Status.NOT_STARTED
                    ),
                    "status_display": "Not Started",
                    "verification_level": (
                        KYCVerification
                        .VerificationLevel
                        .REGISTERED
                    ),
                    "verification_level_display": "Registered",
                    "can_start": True,
                    "can_edit": False,
                    "can_submit": False,
                    "verification": None,
                },
                status=status.HTTP_200_OK,
            )

        serializer = KYCVerificationSerializer(
            verification,
            context={"request": request},
        )

        return Response(
            {
                "exists": True,
                "can_start": False,
                "verification": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class KYCStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = KYCStartSerializer(
            data=request.data
        )
        request_serializer.is_valid(
            raise_exception=True
        )

        verification, created = (
            KYCService.start_verification(
                request.user
            )
        )

        response_serializer = (
            KYCVerificationSerializer(
                verification,
                context={"request": request},
            )
        )

        return Response(
            {
                "message": (
                    "KYC verification started successfully."
                    if created
                    else "KYC verification retrieved successfully."
                ),
                "created": created,
                "verification": response_serializer.data,
            },
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )


class KYCUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    def get_object(self, user) -> KYCVerification:
        try:
            return (
                KYCVerification.objects
                .select_related("user", "reviewed_by")
                .get(user=user)
            )
        except KYCVerification.DoesNotExist as exc:
            raise NotFound(
                "Start your KYC verification before updating it."
            ) from exc

    @transaction.atomic
    def patch(self, request):
        print(">>> USING UPDATED KYCUpdateView <<<")
        verification = (
            KYCVerification.objects
            .select_for_update()
            .filter(user=request.user)
            .first()
        )

        if verification is None:
            raise NotFound(
                "Start your KYC verification before updating it."
            )

        serializer = KYCUpdateSerializer(
            verification,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(
            raise_exception=True
        )

        verification = serializer.save()

        response_serializer = (
            KYCVerificationSerializer(
                verification,
                context={"request": request},
            )
        )

        return Response(
            {
                "message": "KYC draft updated successfully.",
                "verification": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        """
        PUT is supported for frontend convenience, but it behaves as a
        partial draft update so users are not forced to upload every
        document again.
        """
        return self.patch(request)


class KYCSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = KYCSubmitSerializer(
            data=request.data
        )

        request_serializer.is_valid(
            raise_exception=True
        )

        verification = (
            KYCService.submit_verification(
                request.user
            )
        )

        response_serializer = (
            KYCVerificationSerializer(
                verification,
                context={"request": request},
            )
        )

        return Response(
            {
                "message": (
                    "Your KYC application has been submitted "
                    "successfully."
                ),
                "verification": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

class AdminKYCListView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def get(self, request):
        queryset = (
            KYCVerification.objects
            .select_related("user", "reviewed_by")
            .all()
        )

        requested_status = request.query_params.get("status")

        if requested_status:
            queryset = queryset.filter(status=requested_status)

        search = request.query_params.get("search", "").strip()

        if search:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(user__email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(document_number__icontains=search)
            )

        queryset = queryset.order_by(
            "-submitted_at",
            "-created_at",
        )

        serializer = AdminKYCListSerializer(
            queryset,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "count": queryset.count(),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminKYCPendingListView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def get(self, request):
        queryset = (
            KYCVerification.objects
            .select_related("user", "reviewed_by")
            .filter(
                status__in=[
                    KYCVerification.Status.SUBMITTED,
                    KYCVerification.Status.UNDER_REVIEW,
                ]
            )
            .order_by("submitted_at")
        )

        serializer = AdminKYCListSerializer(
            queryset,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "count": queryset.count(),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

class AdminKYCPendingCountView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def get(self, request):
        pending_count = KYCVerification.objects.filter(
            status__in=[
                KYCVerification.Status.SUBMITTED,
                KYCVerification.Status.UNDER_REVIEW,
            ]
        ).count()

        return Response(
            {
                "pending_count": pending_count,
            },
            status=status.HTTP_200_OK,
        )


class AdminKYCDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def get(self, request, verification_id):
        try:
            verification = (
                KYCVerification.objects
                .select_related("user", "reviewed_by")
                .get(pk=verification_id)
            )
        except KYCVerification.DoesNotExist:
            raise NotFound("KYC application was not found.")

        serializer = AdminKYCDetailSerializer(
            verification,
            context={"request": request},
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class AdminKYCApproveView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def post(self, request, verification_id):
        request_serializer = KYCApproveSerializer(
            data=request.data
        )
        request_serializer.is_valid(raise_exception=True)

        verification = KYCService.approve_verification(
            verification_id=verification_id,
            reviewer=request.user,
            review_note=request_serializer.validated_data.get(
                "review_note",
                "",
            ),
        )

        response_serializer = AdminKYCDetailSerializer(
            verification,
            context={"request": request},
        )

        return Response(
            {
                "message": "KYC application approved successfully.",
                "verification": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminKYCRejectView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def post(self, request, verification_id):
        request_serializer = KYCRejectSerializer(
            data=request.data
        )
        request_serializer.is_valid(raise_exception=True)

        verification = KYCService.reject_verification(
            verification_id=verification_id,
            reviewer=request.user,
            rejection_reason=(
                request_serializer.validated_data[
                    "rejection_reason"
                ]
            ),
            review_note=request_serializer.validated_data.get(
                "review_note",
                "",
            ),
        )

        response_serializer = AdminKYCDetailSerializer(
            verification,
            context={"request": request},
        )

        return Response(
            {
                "message": "KYC application rejected.",
                "verification": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

class AdminKYCRunAutomatedCheckView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsKYCReviewer,
    ]

    def post(self, request, verification_id):
        try:
            verification = (
                KYCAutomatedVerificationService
                .run_identity_check(
                    verification_id=verification_id
                )
            )
        except KYCVerification.DoesNotExist:
            return Response(
                {"detail": "KYC application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            AdminKYCDetailSerializer(
                verification,
                context={"request": request},
            ).data,
            status=status.HTTP_200_OK,
        )