class EmailTemplates:

    @staticmethod
    def wallet_funded(amount):
        return {
            "subject": "Wallet Funded Successfully",
            "message": f"""
Hello,

Your NaijaPayPoint wallet has been credited successfully.

Amount: ₦{amount}

Thank you for using NaijaPayPoint.
            """
        }

    @staticmethod
    def referral_bonus(amount):
        return {
            "subject": "Referral Bonus Received",
            "message": f"""
Hello,

You have received a referral bonus of ₦{amount}.

Thank you for referring users to NaijaPayPoint.
            """
        }

    @staticmethod
    def support_reply(ticket_id):
        return {
            "subject": f"Support Ticket #{ticket_id}",
            "message": f"""
Hello,

NaijaPayPoint support has replied to your support ticket.

Please log in to view the latest response.
            """
        }

    @staticmethod
    def refund(amount, reference):
        return {
            "subject": "Transaction Refunded",
            "message": f"""
Hello,

Your transaction has been refunded.

Reference: {reference}
Amount: ₦{amount}

The refund has been credited to your wallet.
            """
        }