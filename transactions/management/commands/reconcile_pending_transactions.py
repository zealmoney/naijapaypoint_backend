from datetime import timedelta
from django.db.models import Q

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from common.transaction_status import (
    classify_vtpass_response,
)
from common.vtpass_recovery import (
    VTPassRecoveryService,
)
from notifications.services import (
    NotificationService,
)
from transactions.models import Transaction

from wallets.models import WalletTransaction
from wallets.services import WalletService


SERVICE_MODELS = {
    "airtime": (
        "airtime",
        "AirtimeTransaction",
    ),
    "data": (
        "data_services",
        "DataTransaction",
    ),
    "electricity": (
        "electricity",
        "ElectricityTransaction",
    ),
    "cable": (
        "cable",
        "CableTransaction",
    ),
    "education": (
        "education",
        "EducationTransaction",
    ),
}


class Command(BaseCommand):
    help = (
        "Requery pending VTPass transactions "
        "and resolve them as success, refunded, "
        "or still pending."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age",
            type=int,
            default=2,
            help=(
                "Only reconcile transactions "
                "at least this many minutes old. "
                "Default: 2."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help=(
                "Maximum number of pending "
                "transactions to process. "
                "Default: 100."
            ),
        )

        parser.add_argument(
            "--max-attempts",
            type=int,
            default=6,
            help=(
                "Maximum number of unsuccessful "
                "requery attempts before the "
                "transaction is flagged for "
                "manual review. Default: 6."
            ),
        )

        parser.add_argument(
            "--reference",
            type=str,
            default="",
            help=(
                "Reconcile one specific "
                "transaction reference."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Requery transactions without "
                "changing database or wallet "
                "balances."
            ),
        )

    def handle(self, *args, **options):
        min_age = max(
            options["min_age"],
            0,
        )

        limit = max(
            options["limit"],
            1,
        )

        max_attempts = max(
            options["max_attempts"],
            1,
        )

        reference = (
            options["reference"] or ""
        ).strip()

        dry_run = options["dry_run"]

        queryset = (
            Transaction.objects
            .select_related("user")
            .filter(
                status="pending",
                provider="vtpass",
                service_type__in=(
                    SERVICE_MODELS.keys()
                ),
            )
            .order_by("created_at")
        )

        if reference:
            queryset = queryset.filter(
                reference=reference
            )
        else:
            cutoff = (
                timezone.now()
                - timedelta(
                    minutes=min_age
                )
            )

            queryset = queryset.filter(
                created_at__lte=cutoff
            )

        eligible_transactions = []

        for tx in queryset:
            metadata = tx.metadata or {}

            if metadata.get(
                "requires_manual_review"
            ) is True:
                continue

            eligible_transactions.append(tx)

            if (
                len(eligible_transactions)
                >= limit
            ):
                break

        pending_transactions = (
            eligible_transactions
        )

        if not pending_transactions:
            self.stdout.write(
                self.style.SUCCESS(
                    "No pending VTPass "
                    "transactions found."
                )
            )
            return

        self.stdout.write(
            f"Found "
            f"{len(pending_transactions)} "
            "pending transaction(s)."
        )

        counters = {
            "success": 0,
            "refunded": 0,
            "pending": 0,
            "skipped": 0,
            "errors": 0,
        }

        for tx in pending_transactions:
            self.stdout.write("")
            self.stdout.write(
                f"Reconciling "
                f"{tx.reference} "
                f"({tx.service_type})..."
            )

            try:
                provider_response = (
                    VTPassRecoveryService
                    .requery(
                        tx.reference
                    )
                )
            except Exception as exc:
                counters["errors"] += 1

                self.stderr.write(
                    self.style.ERROR(
                        f"{tx.reference}: "
                        f"requery exception: "
                        f"{exc}"
                    )
                )

                continue

            result = (
                classify_vtpass_response(
                    provider_response
                )
            )

            provider_code = provider_response.get(
                "code",
                "N/A",
            )

            provider_description = (
                provider_response.get(
                    "response_description",
                    "N/A",
                )
            )

            self.stdout.write(
                f"Provider result: {result}"
            )

            self.stdout.write(
                f"Provider code: {provider_code}"
            )

            self.stdout.write(
                f"Provider description: "
                f"{provider_description}"
            )

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "DRY RUN: no changes "
                        "were written."
                    )
                )

                if result == "success":
                    counters["success"] += 1

                elif result == "failed":
                    counters["refunded"] += 1

                elif result == "manual_review":
                    counters["skipped"] += 1

                else:
                    counters["pending"] += 1

                continue

            if result == "manual_review":
                try:
                    changed = (
                        self._mark_manual_review(
                            tx_id=tx.id,
                            provider_response=(
                                provider_response
                            ),
                        )
                    )

                    counters["skipped"] += 1

                except Exception as exc:
                    counters["errors"] += 1

                    self.stderr.write(
                        self.style.ERROR(
                            f"{tx.reference}: "
                            "manual-review marking "
                            f"failed: {exc}"
                        )
                    )

                continue

            try:
                if result == "success":
                    changed = (
                        self._mark_success(
                            tx_id=tx.id,
                            provider_response=(
                                provider_response
                            ),
                        )
                    )

                    if changed:
                        counters["success"] += 1
                    else:
                        counters["skipped"] += 1

                elif result == "failed":
                    changed = (
                        self._refund_failure(
                            tx_id=tx.id,
                            provider_response=(
                                provider_response
                            ),
                        )
                    )

                    if changed:
                        counters["refunded"] += 1
                    else:
                        counters["skipped"] += 1

                else:
                    changed = self._keep_pending(
                        tx_id=tx.id,
                        provider_response=provider_response,
                        max_attempts=max_attempts,
                    )

                    if changed:
                        counters["pending"] += 1
                    else:
                        counters["skipped"] += 1

            except Exception as exc:
                counters["errors"] += 1

                self.stderr.write(
                    self.style.ERROR(
                        f"{tx.reference}: "
                        f"reconciliation failed: "
                        f"{exc}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Reconciliation complete."
            )
        )

        self.stdout.write(
            f"Success: "
            f"{counters['success']}"
        )
        self.stdout.write(
            f"Refunded: "
            f"{counters['refunded']}"
        )
        self.stdout.write(
            f"Still pending: "
            f"{counters['pending']}"
        )
        self.stdout.write(
            f"Skipped: "
            f"{counters['skipped']}"
        )
        self.stdout.write(
            f"Errors: "
            f"{counters['errors']}"
        )

    @transaction.atomic
    def _mark_success(
        self,
        *,
        tx_id,
        provider_response,
    ):
        main_tx = (
            Transaction.objects
            .select_for_update()
            .select_related("user")
            .get(id=tx_id)
        )

        if main_tx.status != "pending":
            return False

        service_tx = (
            self._get_service_transaction(
                main_tx
            )
        )

        provider_reference = (
            provider_response.get(
                "requestId"
            )
            or provider_response.get(
                "transactionId"
            )
            or main_tx.reference
        )

        main_tx.status = "success"
        main_tx.provider_reference = (
            provider_reference
        )

        main_tx.metadata = {
            **(main_tx.metadata or {}),
            "provider_response":
                provider_response,
            "requires_requery": False,
            "reconciled": True,
            "reconciled_at":
                timezone.now().isoformat(),
            "reconciliation_result":
                "success",
        }

        main_tx.save(
            update_fields=[
                "status",
                "provider_reference",
                "metadata",
            ]
        )

        if service_tx is not None:
            self._update_service_success(
                service_tx,
                provider_response,
            )

        NotificationService.create_notification(
            user=main_tx.user,
            notification_type="transaction",
            title="Transaction Successful",
            message=(
                f"Your "
                f"{main_tx.service_type} "
                f"transaction of "
                f"₦{main_tx.amount} "
                "has been confirmed "
                "successfully."
            ),
            metadata={
                "reference":
                    main_tx.reference,
                "service_type":
                    main_tx.service_type,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{main_tx.reference}: "
                "marked successful."
            )
        )

        return True

    @transaction.atomic
    def _mark_manual_review(
        self,
        *,
        tx_id,
        provider_response,
    ):
        main_tx = (
            Transaction.objects
            .select_for_update()
            .get(id=tx_id)
        )

        if main_tx.status != "pending":
            return False

        metadata = main_tx.metadata or {}

        main_tx.metadata = {
            **metadata,
            "provider_response":
                provider_response,
            "provider_result":
                "manual_review",
            "requires_requery":
                False,
            "requires_manual_review":
                True,
            "reconciled":
                True,
            "reconciled_at":
                timezone.now().isoformat(),
            "reconciliation_result":
                "manual_review",
            "reconciliation_warning": (
                "VTPass could not confirm "
                "the original request ID. "
                "Automatic refund blocked."
            ),
        }

        main_tx.save(
            update_fields=[
                "metadata",
            ]
        )

        service_tx = (
            self._get_service_transaction(
                main_tx
            )
        )

        if service_tx is not None:
            self._save_provider_response(
                service_tx,
                provider_response,
            )

        self.stderr.write(
            self.style.WARNING(
                f"{main_tx.reference}: "
                "requires manual review. "
                "No refund performed."
            )
        )

        return True

    @transaction.atomic
    def _refund_failure(
        self,
        *,
        tx_id,
        provider_response,
    ):
        main_tx = (
            Transaction.objects
            .select_for_update(of=("self",))
            .select_related(
                "user",
                "user__wallet",
            )
            .get(id=tx_id)
        )

        if main_tx.status != "pending":
            return False

        original_debit = (
            WalletTransaction.objects
            .filter(
                wallet=main_tx.user.wallet,
                reference=main_tx.reference,
                transaction_type="debit",
                amount=main_tx.amount,
            )
            .first()
        )

        if original_debit is None:
            metadata = (
                main_tx.metadata or {}
            )

            main_tx.metadata = {
                **(main_tx.metadata or {}),
                "provider_response":
                    provider_response,
                "requires_requery": False,
                "requires_manual_review": False,
                "reconciled": True,
                "reconciled_at":
                    timezone.now().isoformat(),
                "reconciliation_result":
                    "refunded",
                "requery_attempts": (
                    main_tx.metadata or {}
                ).get(
                    "requery_attempts",
                    0,
                ),
            }

            main_tx.save(
                update_fields=[
                    "metadata",
                ]
            )

            self.stderr.write(
                self.style.ERROR(
                    f"{main_tx.reference}: "
                    "refund blocked because "
                    "matching wallet debit "
                    "was not found."
                )
            )

            return False

        refund_reference = (
            f"REFUND-"
            f"{main_tx.reference}"
        )

        # WalletService is expected to be
        # idempotent for repeated references.
        WalletService.credit_wallet(
            wallet=main_tx.user.wallet,
            amount=main_tx.amount,
            reference=refund_reference,
            description=(
                "Refund for failed "
                f"{main_tx.service_type} "
                "transaction"
            ),
        )

        service_tx = (
            self._get_service_transaction(
                main_tx
            )
        )

        if service_tx is not None:
            self._update_service_refunded(
                service_tx,
                provider_response,
            )

        main_tx.status = "refunded"
        main_tx.metadata = {
            **(main_tx.metadata or {}),
            "provider_response":
                provider_response,
            "requires_requery": False,
            "reconciled": True,
            "reconciled_at":
                timezone.now().isoformat(),
            "reconciliation_result":
                "refunded",
            "refund_reference":
                refund_reference,
        }

        main_tx.save(
            update_fields=[
                "status",
                "metadata",
            ]
        )

        NotificationService.create_notification(
            user=main_tx.user,
            notification_type="refund",
            title="Wallet Refunded",
            message=(
                f"₦{main_tx.amount} "
                "has been refunded to "
                "your wallet after the "
                "provider confirmed the "
                "transaction failed."
            ),
            metadata={
                "reference":
                    main_tx.reference,
                "refund_reference":
                    refund_reference,
                "service_type":
                    main_tx.service_type,
            },
        )

        self.stdout.write(
            self.style.WARNING(
                f"{main_tx.reference}: "
                "confirmed failed and "
                "refunded."
            )
        )

        return True

    @transaction.atomic
    def _keep_pending(
        self,
        *,
        tx_id,
        provider_response,
        max_attempts,
    ):
        main_tx = (
            Transaction.objects
            .select_for_update()
            .get(id=tx_id)
        )

        if main_tx.status != "pending":
            return False

        metadata = (
            main_tx.metadata or {}
        )

        history = metadata.get(
            "requery_history",
            [],
        )

        if not isinstance(
            history,
            list,
        ):
            history = []

        attempts = int(
            metadata.get(
                "requery_attempts",
                0,
            )
            or 0
        )

        attempts += 1

        now = timezone.now()

        history.append(
            {
                "attempt": attempts,
                "checked_at":
                    now.isoformat(),
                "response":
                    provider_response,
            }
        )

        # -----------------------------
        # RETRY LIMIT REACHED
        # -----------------------------
        if attempts >= max_attempts:
            main_tx.metadata = {
                **metadata,
                "provider_response":
                    provider_response,
                "requires_requery": False,
                "requires_manual_review":
                    True,
                "requery_attempts":
                    attempts,
                "last_requery_at":
                    now.isoformat(),
                "requery_history":
                    history[-20:],
                "reconciliation_result":
                    "manual_review",
                "reconciliation_warning": (
                    "Maximum automatic "
                    "requery attempts reached. "
                    "No automatic refund was "
                    "performed."
                ),
            }

            main_tx.save(
                update_fields=[
                    "metadata",
                ]
            )

            service_tx = (
                self._get_service_transaction(
                    main_tx
                )
            )

            if service_tx is not None:
                self._save_provider_response(
                    service_tx,
                    provider_response,
                )

            self.stderr.write(
                self.style.WARNING(
                    f"{main_tx.reference}: "
                    f"still unresolved after "
                    f"{attempts} attempts; "
                    "manual review required."
                )
            )

            return True

        # -----------------------------
        # STILL PENDING
        # -----------------------------
        main_tx.metadata = {
            **metadata,
            "provider_response":
                provider_response,
            "requires_requery": True,
            "requires_manual_review":
                False,
            "requery_attempts":
                attempts,
            "last_requery_at":
                now.isoformat(),
            "requery_history":
                history[-20:],
        }

        main_tx.save(
            update_fields=[
                "metadata",
            ]
        )

        service_tx = (
            self._get_service_transaction(
                main_tx
            )
        )

        if service_tx is not None:
            self._save_provider_response(
                service_tx,
                provider_response,
            )

        self.stdout.write(
            self.style.WARNING(
                f"{main_tx.reference}: "
                f"still pending "
                f"(attempt "
                f"{attempts}/"
                f"{max_attempts})."
            )
        )

        return True
    
    def _get_service_transaction(
        self,
        main_tx,
    ):
        config = SERVICE_MODELS.get(
            main_tx.service_type
        )

        if not config:
            return None

        app_label, model_name = config

        try:
            model = apps.get_model(
                app_label,
                model_name,
            )
        except LookupError:
            self.stderr.write(
                self.style.WARNING(
                    f"{main_tx.reference}: "
                    f"could not load "
                    f"{app_label}."
                    f"{model_name}."
                )
            )
            return None

        try:
            return (
                model.objects
                .select_for_update()
                .get(
                    reference=(
                        main_tx.reference
                    )
                )
            )
        except model.DoesNotExist:
            self.stderr.write(
                self.style.WARNING(
                    f"{main_tx.reference}: "
                    "service-specific "
                    "transaction not found."
                )
            )
            return None

    def _update_service_success(
        self,
        service_tx,
        provider_response,
    ):
        update_fields = []

        if hasattr(
            service_tx,
            "status",
        ):
            service_tx.status = "success"
            update_fields.append(
                "status"
            )

        if hasattr(
            service_tx,
            "provider_response",
        ):
            service_tx.provider_response = (
                provider_response
            )
            update_fields.append(
                "provider_response"
            )

        if (
            hasattr(
                service_tx,
                "token",
            )
            and not getattr(
                service_tx,
                "token",
                "",
            )
        ):
            token = self._extract_token(
                provider_response
            )

            if token:
                service_tx.token = token
                update_fields.append(
                    "token"
                )

        if (
            hasattr(
                service_tx,
                "pin",
            )
            and not getattr(
                service_tx,
                "pin",
                "",
            )
        ):
            pin = self._extract_pin(
                provider_response
            )

            if pin:
                service_tx.pin = pin
                update_fields.append(
                    "pin"
                )

        if update_fields:
            service_tx.save(
                update_fields=list(
                    dict.fromkeys(
                        update_fields
                    )
                )
            )

    def _update_service_refunded(
        self,
        service_tx,
        provider_response,
    ):
        update_fields = []

        if hasattr(
            service_tx,
            "status",
        ):
            service_tx.status = "refunded"
            update_fields.append(
                "status"
            )

        if hasattr(
            service_tx,
            "provider_response",
        ):
            service_tx.provider_response = (
                provider_response
            )
            update_fields.append(
                "provider_response"
            )

        if update_fields:
            service_tx.save(
                update_fields=list(
                    dict.fromkeys(
                        update_fields
                    )
                )
            )

    def _save_provider_response(
        self,
        service_tx,
        provider_response,
    ):
        if not hasattr(
            service_tx,
            "provider_response",
        ):
            return

        service_tx.provider_response = (
            provider_response
        )

        service_tx.save(
            update_fields=[
                "provider_response"
            ]
        )

    @staticmethod
    def _extract_token(
        response,
    ):
        if not isinstance(
            response,
            dict,
        ):
            return ""

        content = response.get(
            "content",
            {},
        )

        token = (
            response.get("token")
            or response.get(
                "purchased_code"
            )
            or (
                content.get("token")
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or (
                content.get(
                    "purchased_code"
                )
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or ""
        )

        token = str(token).strip()

        if token.lower().startswith(
            "token :"
        ):
            token = token.split(
                ":",
                1,
            )[1].strip()

        return token

    @staticmethod
    def _extract_pin(
        response,
    ):
        if not isinstance(
            response,
            dict,
        ):
            return ""

        content = response.get(
            "content",
            {},
        )

        pin = (
            response.get("pin")
            or response.get("token")
            or response.get(
                "purchased_code"
            )
            or (
                content.get("pin")
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or (
                content.get("token")
                if isinstance(
                    content,
                    dict,
                )
                else ""
            )
            or ""
        )

        return str(pin).strip()