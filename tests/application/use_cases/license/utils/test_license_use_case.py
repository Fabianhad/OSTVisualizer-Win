import unittest
from ost_visualizer.application.dtos.license_dto import (
    LicenseOperationResultDto,
    LicenseOperationStatus,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_DEVICE_ACTIVATION_INACTIVE,
    ERROR_INVALID_ACTIVATION_IDENTITY,
    ERROR_LICENSE_NOT_FOUND,
    ERROR_MAX_ACTIVATIONS_REACHED,
    parse_failure_response,
    parse_signed_success_response,
)
from ost_visualizer.domain.entities.license import License, LicenseStatus


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
        self.assertEqual(
            failure.result.operation_status,
            LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
        )
        self.assertEqual(
            failure.error_code, ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE]
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
        self.assertEqual(
            failure.result.operation_status,
            LicenseOperationStatus.FAILED,
        )
        self.assertIn("Windows activation identity", failure.result.message)
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
        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.NETWORK_ERROR)
        self.assertIn("invalid response", failure.result.message)

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
        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertIn("invalid response", failure.result.message)

    def test_signed_success_parser_rejects_unsigned_success_payload(self):
        _response, contract_error = parse_signed_success_response(
            {"valid": True, "expiry_date": "2030-01-01T00:00:00"},
            success_field="valid",
            operation="validate",
        )
        self.assertIsNotNone(contract_error)
        self.assertEqual(
            contract_error.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
