from django.urls import path

from .views import (
    MyReferralView,
    ReferralHistoryView,
)

urlpatterns = [
    path(
        "me/",
        MyReferralView.as_view(),
        name="my-referrals",
    ),
    path(
        "history/",
        ReferralHistoryView.as_view(),
        name="referral-history",
    ),
]