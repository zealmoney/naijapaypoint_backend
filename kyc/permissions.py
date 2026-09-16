from rest_framework.permissions import BasePermission


class IsKYCReviewer(BasePermission):
    message = "You do not have permission to review KYC applications."

    def has_permission(self, request, view):
        user = request.user

        return bool(
            user
            and user.is_authenticated
            and user.is_staff
            and user.has_perm(
                "kyc.review_kycverification"
            )
        )