from django.db import migrations


def sanitize_review_history(apps, schema_editor):
    KYCVerification = apps.get_model(
        "kyc",
        "KYCVerification",
    )

    for verification in KYCVerification.objects.all().iterator():
        metadata = verification.metadata or {}
        review_history = metadata.get(
            "review_history",
            [],
        )

        if not isinstance(review_history, list):
            continue

        sanitized_history = []

        for entry in review_history:
            if not isinstance(entry, dict):
                continue

            sanitized_history.append(
                {
                    "action": entry.get("action"),
                    "reviewer_id": entry.get("reviewer_id"),
                    "reviewed_at": entry.get("reviewed_at"),
                }
            )

        if review_history != sanitized_history:
            verification.metadata = {
                **metadata,
                "review_history": sanitized_history,
            }

            verification.save(
                update_fields=["metadata"]
            )


class Migration(migrations.Migration):

    dependencies = [
        (
            "kyc",
            "0007_sanitize_historical_kyc_data",
        ),
    ]

    operations = [
        migrations.RunPython(
            sanitize_review_history,
            migrations.RunPython.noop,
        ),
    ]