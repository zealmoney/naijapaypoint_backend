from decimal import Decimal, InvalidOperation


class VTPassCatalogueError(ValueError):
    pass


def extract_variations(response):
    if not isinstance(response, dict):
        raise VTPassCatalogueError(
            "Invalid provider catalogue response."
        )

    content = response.get("content")

    if isinstance(content, dict):
        variations = (
            content.get("varations")
            or content.get("variations")
        )

        if isinstance(variations, list):
            return variations

    if isinstance(content, list):
        return content

    data = response.get("data")

    if isinstance(data, list):
        return data

    raise VTPassCatalogueError(
        "Provider catalogue does not contain "
        "a valid variations list."
    )


def get_authoritative_plan(
    response,
    plan_id,
):
    requested_plan_id = str(
        plan_id
    ).strip()

    if not requested_plan_id:
        raise VTPassCatalogueError(
            "Plan ID is required."
        )

    variations = extract_variations(
        response
    )

    for plan in variations:
        if not isinstance(plan, dict):
            continue

        provider_plan_id = (
            plan.get("variation_code")
            or plan.get("code")
        )

        if str(
            provider_plan_id or ""
        ).strip() != requested_plan_id:
            continue

        raw_amount = (
            plan.get("variation_amount")
            if plan.get("variation_amount")
            is not None
            else plan.get("amount")
        )

        try:
            amount = Decimal(
                str(raw_amount)
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):
            raise VTPassCatalogueError(
                "Provider returned an invalid "
                "price for this plan."
            )

        if (
            not amount.is_finite()
            or amount <= Decimal("0")
        ):
            raise VTPassCatalogueError(
                "Provider returned an invalid "
                "price for this plan."
            )

        name = str(
            plan.get("name") or ""
        ).strip()

        if not name:
            raise VTPassCatalogueError(
                "Provider returned an invalid "
                "name for this plan."
            )

        return {
            "plan_id": requested_plan_id,
            "plan_name": name,
            "amount": amount,
        }

    raise VTPassCatalogueError(
        "Selected plan is not available."
    )