from decimal import Decimal

from unittest.mock import Mock, patch
import requests

from django.test import SimpleTestCase

from .vtpass_catalogue import (
    VTPassCatalogueError,
    extract_variations,
    get_authoritative_plan,
)

from .vtpass_recovery import VTPassRecoveryService


class VTPassCatalogueTests(SimpleTestCase):
    def setUp(self):
        self.plan = {
            "variation_code": "TEST-PLAN",
            "name": "Test Plan",
            "variation_amount": "1500.00",
        }

    def test_extracts_misspelled_varations(self):
        response = {
            "content": {
                "varations": [self.plan],
            }
        }

        self.assertEqual(
            extract_variations(response),
            [self.plan],
        )

    def test_extracts_content_variations(self):
        response = {
            "content": {
                "variations": [self.plan],
            }
        }

        self.assertEqual(
            extract_variations(response),
            [self.plan],
        )

    def test_extracts_content_list(self):
        response = {
            "content": [self.plan],
        }

        self.assertEqual(
            extract_variations(response),
            [self.plan],
        )

    def test_extracts_data_list(self):
        response = {
            "data": [self.plan],
        }

        self.assertEqual(
            extract_variations(response),
            [self.plan],
        )

    def test_returns_authoritative_plan(self):
        response = {
            "content": {
                "variations": [self.plan],
            }
        }

        result = get_authoritative_plan(
            response,
            "TEST-PLAN",
        )

        self.assertEqual(
            result["plan_id"],
            "TEST-PLAN",
        )
        self.assertEqual(
            result["plan_name"],
            "Test Plan",
        )
        self.assertEqual(
            result["amount"],
            Decimal("1500.00"),
        )

    def test_supports_code_and_amount_fallbacks(self):
        response = {
            "data": [
                {
                    "code": "ALT-PLAN",
                    "name": "Alternative Plan",
                    "amount": "2500",
                }
            ]
        }

        result = get_authoritative_plan(
            response,
            "ALT-PLAN",
        )

        self.assertEqual(
            result["amount"],
            Decimal("2500"),
        )

    def test_rejects_unknown_plan(self):
        response = {
            "content": {
                "variations": [self.plan],
            }
        }

        with self.assertRaises(
            VTPassCatalogueError
        ):
            get_authoritative_plan(
                response,
                "NOT-AVAILABLE",
            )

    def test_rejects_malformed_price(self):
        response = {
            "content": {
                "variations": [
                    {
                        "variation_code": "BAD",
                        "name": "Bad Plan",
                        "variation_amount": "not-a-price",
                    }
                ],
            }
        }

        with self.assertRaises(
            VTPassCatalogueError
        ):
            get_authoritative_plan(
                response,
                "BAD",
            )

    def test_rejects_zero_price(self):
        response = {
            "content": {
                "variations": [
                    {
                        "variation_code": "FREE",
                        "name": "Free Plan",
                        "variation_amount": "0",
                    }
                ],
            }
        }

        with self.assertRaises(
            VTPassCatalogueError
        ):
            get_authoritative_plan(
                response,
                "FREE",
            )

    def test_rejects_nan_price(self):
        response = {
            "content": {
                "variations": [
                    {
                        "variation_code": "NAN",
                        "name": "Invalid Plan",
                        "variation_amount": "NaN",
                    }
                ],
            }
        }

        with self.assertRaises(
            VTPassCatalogueError
        ):
            get_authoritative_plan(
                response,
                "NAN",
            )

    def test_rejects_infinite_price(self):
        response = {
            "content": {
                "variations": [
                    {
                        "variation_code": "INFINITE",
                        "name": "Invalid Plan",
                        "variation_amount": "Infinity",
                    }
                ],
            }
        }

        with self.assertRaises(
            VTPassCatalogueError
        ):
            get_authoritative_plan(
                response,
                "INFINITE",
            )

    def test_rejects_invalid_catalogue(self):
        with self.assertRaises(
            VTPassCatalogueError
        ):
            extract_variations(
                {"content": {"unexpected": []}}
            )

class VTPassRecoveryPrivacyTests(SimpleTestCase):

    @patch("common.vtpass_recovery.requests.post")
    def test_invalid_json_does_not_expose_raw_response(
        self,
        mock_post,
    ):
        response = Mock()
        response.status_code = 502
        response.text = (
            "PRIVATE-CUSTOMER-DATA-12345"
        )
        response.json.side_effect = ValueError(
            "Invalid JSON"
        )

        mock_post.return_value = response

        result = VTPassRecoveryService.requery(
            "TEST-REQUERY-001"
        )

        self.assertEqual(
            result["code"],
            "REQUERY_INVALID_JSON",
        )

        self.assertEqual(
            result["http_status"],
            502,
        )

        self.assertNotIn(
            "raw_response",
            result,
        )

        self.assertNotIn(
            "PRIVATE-CUSTOMER-DATA-12345",
            str(result),
        )

    @patch("common.vtpass_recovery.requests.post")
    def test_connection_error_does_not_expose_exception(
        self,
        mock_post,
    ):
        mock_post.side_effect = (
            requests.ConnectionError(
                "PRIVATE-API-KEY-12345"
            )
        )

        result = VTPassRecoveryService.requery(
            "TEST-REQUERY-002"
        )

        self.assertEqual(
            result,
            {
                "code": "REQUERY_CONNECTION_ERROR",
                "response_description":
                    "Unable to connect to VTPass.",
            },
        )

        self.assertNotIn(
            "PRIVATE-API-KEY-12345",
            str(result),
        )