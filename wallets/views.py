from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Wallet

from .serializers import WalletSerializer, WalletTransactionSerializer


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet, created = Wallet.objects.get_or_create(user=request.user)
        serializer = WalletSerializer(wallet)
        return Response(serializer.data)


class WalletTransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        transactions = request.user.wallet.transactions.all().order_by("-created_at")
        serializer = WalletTransactionSerializer(transactions, many=True)
        return Response(serializer.data)