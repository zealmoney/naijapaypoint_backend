from django.conf import settings
from django.core.mail import send_mail


class EmailNotificationService:
    @staticmethod
    def send_email(to_email, subject, message):
        if not to_email:
            return False

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=True,
        )

        return True

    @staticmethod
    def send_wallet_funded(user, amount):
        return EmailNotificationService.send_email(
            to_email=user.email,
            subject="Wallet Funded Successfully",
            message=f"Your NaijaPayPoint wallet has been credited with ₦{amount}.",
        )

    @staticmethod
    def send_transaction_success(user, title, message):
        return EmailNotificationService.send_email(
            to_email=user.email,
            subject=title,
            message=message,
        )

    @staticmethod
    def send_refund(user, amount, reference):
        return EmailNotificationService.send_email(
            to_email=user.email,
            subject="Transaction Refunded",
            message=f"₦{amount} has been refunded to your wallet for transaction {reference}.",
        )

    @staticmethod
    def send_support_reply(user, ticket_id):
        return EmailNotificationService.send_email(
            to_email=user.email,
            subject=f"Support Reply for Ticket #{ticket_id}",
            message=f"NaijaPayPoint support has replied to your ticket #{ticket_id}. Please log in to view the response.",
        )