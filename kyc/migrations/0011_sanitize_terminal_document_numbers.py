from django.db import migrations


def sanitize_terminal_document_numbers(apps, schema_editor):
    KYCVerification = apps.get_model(
        "kyc",
        "KYCVerification",
    )

    terminal_verifications = (
        KYCVerification.objects
        .filter(
            status__in=[
                "approved",
                "rejected",
            ]
        )
        .exclude(document_number="")
    )

    for verification in terminal_verifications.iterator():
        raw_document_number = (
            verification.document_number or ""
        ).strip()

        if raw_document_number:
            verification.document_number_last4 = (
                raw_document_number[-4:]
            )

        verification.document_number = ""

        verification.save(
            update_fields=[
                "document_number",
                "document_number_last4",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "kyc",
            "0010_kycverification_document_number_last4",
        ),
    ]

    operations = [
        migrations.RunPython(
            sanitize_terminal_document_numbers,
            migrations.RunPython.noop,
        ),
    ]