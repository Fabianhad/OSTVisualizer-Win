import unittest
from ost_visualizer.application.dtos.license_dto import (
    LicenseOperationResultDto,
    LicenseOperationStatus,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_DEVICE_ACTIVATION_INACTIVE,
    ERROR_INVALID_ACTIVATION_IDENTITY,
    ERROR_INVALID_HWID,
    ERROR_LICENSE_EXPIRED,
    ERROR_LICENSE_NOT_FOUND,
    ERROR_LICENSE_REVOKED,
    ERROR_MAX_ACTIVATIONS_REACHED,
    parse_failure_response,
    parse_signed_success_response,
)
from ost_visualizer.domain.entities.license import License, LicenseStatus

CONTRACT_ERROR_MESSAGE = (
    "The license server returned an invalid response. Please contact support."
)


class LicenseActivationContractTests(unittest.TestCase):
    def test_failure_parser_maps_explicit_inactive_device_contract(self):
        failure = parse_failure_response(
            {
                "valid": False,
                "error": "This device is not currently activated for this license.",
                "error_name": ERROR_DEVICE_ACTIVATION_INACTIVE,
                "error_code": ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE],
            },
            operation="validate",
            network_message="network",
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )
        self.assertFalse(failure.result.success)
        self.assertEqual(
            failure.result.operation_status,
            LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.INVALID)
        self.assertEqual(
            failure.result.message,
            "This device is not currently activated for this license.",
        )
        self.assertEqual(
            failure.result.error_code, ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE]
        )
        self.assertEqual(
            failure.error_code, ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE]
        )
        self.assertEqual(
            failure.server_message,
            "This device is not currently activated for this license.",
        )

    def test_failure_parser_maps_invalid_activation_identity_contract(self):
        failure = parse_failure_response(
            {
                "success": False,
                "error": "Invalid activation identity",
                "error_name": ERROR_INVALID_ACTIVATION_IDENTITY,
                "error_code": ERROR_CONTRACT[ERROR_INVALID_ACTIVATION_IDENTITY],
            },
            operation="activate",
            network_message="network",
        )
        self.assertFalse(failure.result.success)
        self.assertEqual(
            failure.result.operation_status,
            LicenseOperationStatus.FAILED,
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.INVALID)
        self.assertEqual(
            failure.result.message,
            "The license server rejected the Windows activation identity. "
            "Please contact support.",
        )
        self.assertEqual(failure.server_message, "Invalid activation identity")
        self.assertEqual(
            failure.error_code,
            ERROR_CONTRACT[ERROR_INVALID_ACTIVATION_IDENTITY],
        )

    def test_failure_parser_rejects_numeric_only_legacy_payload(self):
        failure = parse_failure_response(
            {
                "valid": False,
                "error": "Maximum activations reached",
                "error_code": ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            },
            operation="validate",
            network_message="network",
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )
        self.assertFalse(failure.result.success)
        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.NETWORK_ERROR)
        self.assertEqual(failure.result.message, CONTRACT_ERROR_MESSAGE)
        self.assertIsNone(failure.result.error_code)
        self.assertEqual(failure.server_message, CONTRACT_ERROR_MESSAGE)

    def test_failure_parser_rejects_mismatched_error_name_and_code(self):
        failure = parse_failure_response(
            {
                "success": False,
                "error": "Mismatch",
                "error_name": ERROR_LICENSE_NOT_FOUND,
                "error_code": ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            },
            operation="activate",
            network_message="network",
        )
        self.assertFalse(failure.result.success)
        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.INVALID)
        self.assertEqual(failure.result.message, CONTRACT_ERROR_MESSAGE)
        self.assertIsNone(failure.result.error_code)

    def test_signed_success_parser_rejects_unsigned_success_payload(self):
        response, contract_error = parse_signed_success_response(
            {"valid": True, "expiry_date": "2030-01-01T00:00:00"},
            success_field="valid",
            operation="validate",
        )
        self.assertIsNone(response)
        self.assertIsNotNone(contract_error)
        self.assertFalse(contract_error.success)
        self.assertEqual(
            contract_error.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(contract_error.license_status, LicenseStatus.NETWORK_ERROR)
        self.assertEqual(contract_error.message, CONTRACT_ERROR_MESSAGE)

    def test_failure_parser_rejects_malformed_markers_and_error_codes(self):
        valid_error = {
            "error": "License revoked",
            "error_name": ERROR_LICENSE_REVOKED,
            "error_code": ERROR_CONTRACT[ERROR_LICENSE_REVOKED],
        }
        malformed_payloads = {
            "success_marker_true": {**valid_error, "success": True},
            "marker_missing": dict(valid_error),
            "marker_wrong_field_for_activate": {**valid_error, "valid": False},
            "unknown_error_name": {
                **valid_error,
                "success": False,
                "error_name": "SOMETHING_ELSE",
            },
            "missing_error_name": {
                "success": False,
                "error_code": ERROR_CONTRACT[ERROR_LICENSE_REVOKED],
            },
            "string_error_code": {
                **valid_error,
                "success": False,
                "error_code": str(ERROR_CONTRACT[ERROR_LICENSE_REVOKED]),
            },
            "bool_error_code": {**valid_error, "success": False, "error_code": True},
        }
        for label, payload in malformed_payloads.items():
            with self.subTest(label=label):
                failure = parse_failure_response(
                    payload, operation="activate", network_message="network"
                )
                self.assertFalse(failure.result.success)
                self.assertEqual(
                    failure.result.operation_status,
                    LicenseOperationStatus.NETWORK_ERROR,
                )
                self.assertEqual(failure.result.message, CONTRACT_ERROR_MESSAGE)
                self.assertIsNone(failure.result.error_code)

    def test_failure_parser_maps_every_contract_error_for_each_operation(self):
        expected = {
            ERROR_LICENSE_NOT_FOUND: LicenseOperationStatus.INVALID_KEY,
            ERROR_LICENSE_EXPIRED: LicenseOperationStatus.EXPIRED,
            ERROR_LICENSE_REVOKED: LicenseOperationStatus.REVOKED,
            ERROR_MAX_ACTIVATIONS_REACHED: (
                LicenseOperationStatus.ACTIVATION_LIMIT_REACHED
            ),
            ERROR_INVALID_HWID: LicenseOperationStatus.FAILED,
            ERROR_DEVICE_ACTIVATION_INACTIVE: (
                LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE
            ),
            ERROR_INVALID_ACTIVATION_IDENTITY: LicenseOperationStatus.FAILED,
        }
        self.assertEqual(set(expected), set(ERROR_CONTRACT))
        for operation in ("activate", "deactivate", "validate"):
            marker = "valid" if operation == "validate" else "success"
            for error_name, status in expected.items():
                with self.subTest(operation=operation, error_name=error_name):
                    failure = parse_failure_response(
                        {
                            marker: False,
                            "error": "server text",
                            "error_name": error_name,
                            "error_code": ERROR_CONTRACT[error_name],
                        },
                        operation=operation,
                        network_message="network",
                    )
                    self.assertFalse(failure.result.success)
                    self.assertEqual(failure.result.operation_status, status)
                    self.assertEqual(
                        failure.result.error_code, ERROR_CONTRACT[error_name]
                    )
                    self.assertEqual(failure.server_message, "server text")
        expired = parse_failure_response(
            {
                "valid": False,
                "error_name": ERROR_LICENSE_EXPIRED,
                "error_code": ERROR_CONTRACT[ERROR_LICENSE_EXPIRED],
            },
            operation="validate",
            network_message="network",
        )
        self.assertEqual(expired.result.license_status, LicenseStatus.EXPIRED)
        self.assertEqual(expired.server_message, "Validate failed")

    def test_failure_parser_reports_network_failure_for_missing_response(self):
        failure = parse_failure_response(
            None,
            operation="validate",
            network_message="offline",
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )
        self.assertFalse(failure.result.success)
        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.NETWORK_ERROR)
        self.assertEqual(failure.result.message, "offline")
        self.assertIsNone(failure.error_code)

    def test_signed_success_parser_accepts_complete_payload_and_rejects_bad_fields(
        self,
    ):
        response, contract_error = parse_signed_success_response(
            {
                "success": True,
                "expiry_date": "2030-01-01T00:00:00",
                "signature": " sig ",
            },
            success_field="success",
            operation="activate",
        )
        self.assertIsNone(contract_error)
        self.assertEqual(response.signature, "sig")
        self.assertEqual(response.expiry_date_text, "2030-01-01T00:00:00")
        self.assertEqual(response.expiry_date.year, 2030)
        self.assertIsNotNone(response.expiry_date.tzinfo)
        self.assertEqual(
            parse_signed_success_response(
                {"success": False}, success_field="success", operation="activate"
            ),
            (None, None),
        )
        bad_payloads = {
            "missing_signature": {"success": True, "expiry_date": "2030-01-01"},
            "missing_expiry": {"success": True, "signature": "sig"},
            "truthy_non_bool_marker": {
                "success": 1,
                "expiry_date": "2030-01-01",
                "signature": "sig",
            },
        }
        for label, payload in bad_payloads.items():
            with self.subTest(label=label):
                response, contract_error = parse_signed_success_response(
                    payload, success_field="success", operation="activate"
                )
                self.assertIsNone(response)
                self.assertEqual(contract_error.message, CONTRACT_ERROR_MESSAGE)
                self.assertEqual(contract_error.license_status, LicenseStatus.INVALID)
        response, contract_error = parse_signed_success_response(
            {"valid": True, "expiry_date": "not-a-date", "signature": "sig"},
            success_field="valid",
            operation="validate",
        )
        self.assertIsNone(response)
        self.assertEqual(
            contract_error.message,
            "The license server returned an invalid expiry date.",
        )
        self.assertEqual(contract_error.license_status, LicenseStatus.NETWORK_ERROR)
