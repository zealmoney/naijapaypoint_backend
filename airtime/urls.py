from django.urls import path
from .views import AirtimePurchaseView

urlpatterns = [
    path("purchase/", AirtimePurchaseView.as_view(), name="airtime_purchase"),
]