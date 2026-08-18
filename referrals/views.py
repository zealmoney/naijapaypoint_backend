from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ReferralProfile, Referral
from .serializers import (
    ReferralProfileSerializer,
    ReferralSerializer,
)


class MyReferralView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = ReferralProfile.objects.get_or_create(
            user=request.user
        )

        serializer = ReferralProfileSerializer(profile)

        return Response(serializer.data)


class ReferralHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        referrals = Referral.objects.filter(
            referrer=request.user
        ).order_by("-created_at")

        serializer = ReferralSerializer(
            referrals,
            many=True,
        )

        return Response(serializer.data)