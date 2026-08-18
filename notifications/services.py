from notifications.models import Notification


class NotificationService:

    @staticmethod
    def create_notification(
        *,
        user,
        notification_type,
        title,
        message,
        metadata=None,
    ):
        return Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata or {},
        )