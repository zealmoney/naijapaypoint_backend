from django.urls import path
from .views import (
    TransactionListView,
    TransactionDetailView,
    TransactionReceiptView,
)

urlpatterns = [
    path("", TransactionListView.as_view(), name="transactions"),
    path("<str:reference>/", TransactionDetailView.as_view(), name="transaction_detail"),
    path("<str:reference>/receipt/", TransactionReceiptView.as_view(), name="transaction_receipt"),
]