from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Transaction
from .serializers import TransactionSerializer, TransactionReceiptSerializer


class TransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        transactions = (
            Transaction.objects
            .filter(user=request.user)
            .order_by("-created_at")
        )

        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class TransactionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        try:
            transaction = Transaction.objects.get(
                user=request.user,
                reference=reference
            )
        except Transaction.DoesNotExist:
            return Response(
                {"detail": "Transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TransactionSerializer(transaction)
        return Response(serializer.data)


class TransactionReceiptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        try:
            transaction = Transaction.objects.get(
                user=request.user,
                reference=reference
            )
        except Transaction.DoesNotExist:
            return Response(
                {"detail": "Receipt not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TransactionReceiptSerializer(transaction)
        return Response(serializer.data)