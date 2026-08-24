VTPASS_FAILURE_CODES = {
    "010",
    "011",
    "012",
    "013",
    "016",
    "017",
    "018",
    "027",
    "028",
    "030",
    "032",
    "034",
    "035",
    "040",
    "083",
    "087",
    "091",
}

VTPASS_PENDING_CODES = {
    "001",
    "014",
    "044",
    "089",
    "099",
}

VTPASS_MANUAL_REVIEW_CODES = {
    "015",
    "085",
}


def classify_vtpass_response(response):
    """
    Classify a VTPass response into one of:

    success
    failed
    pending
    manual_review
    """

    if not isinstance(response, dict):
        return "pending"

    code = str(
        response.get("code") or ""
    ).strip()

    content = response.get(
        "content"
    )

    transaction_status = ""

    if isinstance(content, dict):
        transactions = content.get(
            "transactions"
        )

        if isinstance(
            transactions,
            dict,
        ):
            transaction_status = str(
                transactions.get(
                    "status"
                )
                or ""
            ).lower().strip()

    # --------------------------------
    # SUCCESS CODE
    # --------------------------------
    if code == "000":
        if transaction_status == "delivered":
            return "success"

        if transaction_status in {
            "pending",
            "initiated",
            "processing",
        }:
            return "pending"

        description = str(
            response.get(
                "response_description"
            )
            or ""
        ).lower().strip()

        if (
            "transaction successful"
            in description
        ):
            return "success"

        return "pending"

    # --------------------------------
    # MANUAL REVIEW
    # --------------------------------
    if code in VTPASS_MANUAL_REVIEW_CODES:
        return "manual_review"

    # --------------------------------
    # CONFIRMED FAILURE
    # --------------------------------
    if code in VTPASS_FAILURE_CODES:
        return "failed"

    # --------------------------------
    # KNOWN PENDING
    # --------------------------------
    if code in VTPASS_PENDING_CODES:
        return "pending"

    # Provider/network exceptions and
    # unknown responses must not trigger
    # automatic refunds.
    return "pending"