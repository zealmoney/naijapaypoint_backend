from rest_framework.permissions import BasePermission


class IsKYCReviewer(BasePermission):
    message = "You do not have permission to review KYC applications."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )