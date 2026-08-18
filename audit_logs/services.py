from .models import AuditLog


class AuditLogService:
    @staticmethod
    def log_action(
        admin_user,
        action_type,
        target_user_email="",
        target_reference="",
        note="",
        metadata=None,
    ):
        return AuditLog.objects.create(
            admin_user=admin_user,
            action_type=action_type,
            target_user_email=target_user_email or "",
            target_reference=target_reference or "",
            note=note or "",
            metadata=metadata or {},
        )