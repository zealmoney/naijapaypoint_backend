from django.db import migrations


def sanitize_historical_kyc_data(apps, schema_editor):
    KYCVerification = apps.get_model(
        "kyc",
        "KYCVerification",
    )

    queryset = KYCVerification.objects.filter(
        automated_verification_status="passed",
    )

    for verification in queryset.iterator():
        raw_identity = (
            verification.identity_verification_value
            or ""
        )

        if raw_identity:
            verification.identity_verification_last4 = (
                raw_identity[-4:]
            )
            verification.identity_verification_value = ""

        provider_response = (
            verification.provider_response
            or {}
        )

        if provider_response:
            entity = provider_response.get("entity") or {}

            if "verification" in provider_response:
                safe_verification = (
                    provider_response.get("verification")
                )
            else:
                safe_verification = entity.get(
                    "verification"
                )

            verification.provider_response = {
                "verification": safe_verification,
            }

        verification.automated_verification_error = ""

        verification.save(
            update_fields=[
                "identity_verification_last4",
                "identity_verification_value",
                "provider_response",
                "automated_verification_error",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "kyc",
            "0006_kycverification_identity_verification_last4",
        ),
    ]

    operations = [
        migrations.RunPython(
            sanitize_historical_kyc_data,
            migrations.RunPython.noop,
        ),
    ]