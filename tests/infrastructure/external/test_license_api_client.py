import io
import json
import unittest
import urllib.error
import uuid
from unittest.mock import call, patch
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    WindowsJoinType,
)
from ost_visualizer.domain.services.hardware_identity import (
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)
from ost_visualizer.infrastructure.external.license_api_client import LicenseApiClient

_CLIENT_MODULE = "ost_visualizer.infrastructure.external.license_api_client"
SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")


class FixedActivationIdentityProvider:
    def get_identity(self):
        return LicenseActivationIdentityDto(
            version=LICENSE_ACTIVATION_IDENTITY_VERSION,
            windows_account=r"EXAMPLE\Estimator",
            computer_name="ESTIMATOR-PC",
            join_type=WindowsJoinType.DOMAIN,
            join_name="EXAMPLE",
        )


class UnexpectedActivationIdentityProvider:
    def get_identity(self):
        raise AssertionError("activation identity must not be queried")


class HwidV1LicenseContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        self.hwid = build_hwid(self.identity)

    def test_api_payload_keeps_one_self_versioned_hwid_field(self):
        self.assertTrue(is_canonical_hwid(self.hwid))
        self.assertTrue(self.hwid.startswith("v1:"))
        client = LicenseApiClient(
            activation_identity_provider=FixedActivationIdentityProvider()
        )
        with patch.object(client, "_post", return_value=(False, None)) as post:
            client.activate("LIC-TEST", self.hwid)
        post.assert_called_once_with(
            "activate",
            {
                "license_key": "LIC-TEST",
                "hwid": self.hwid,
                "activation_identity": {
                    "version": "v1",
                    "windows_account": r"EXAMPLE\Estimator",
                    "computer_name": "ESTIMATOR-PC",
                    "join_type": "domain",
                    "join_name": "EXAMPLE",
                },
            },
        )


class LicenseActivationIdentityTests(unittest.TestCase):
    def test_validation_and_deactivation_do_not_query_activation_identity(self):
        client = LicenseApiClient(
            activation_identity_provider=UnexpectedActivationIdentityProvider()
        )
        with patch.object(client, "_post", return_value=(False, None)) as post:
            client.validate("LIC-TEST", "v1:" + "A" * 64)
            client.deactivate("LIC-TEST", "v1:" + "A" * 64)
        self.assertEqual(
            post.call_args_list,
            [
                call(
                    "validate",
                    {"license_key": "LIC-TEST", "hwid": "v1:" + "A" * 64},
                ),
                call(
                    "deactivate",
                    {"license_key": "LIC-TEST", "hwid": "v1:" + "A" * 64},
                ),
            ],
        )


class _Response:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self):
        return self._body


class LicenseApiTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = LicenseApiClient(
            activation_identity_provider=UnexpectedActivationIdentityProvider(),
            base_url="https://example.invalid/api/",
            timeout=7,
        )
        patcher = patch(f"{_CLIENT_MODULE}.urllib.request.urlopen")
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch(f"{_CLIENT_MODULE}.time.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_post_sends_json_body_to_the_endpoint_and_returns_the_object(self):
        self.urlopen.return_value = _Response(b'{"valid": true}')
        result = self.client.validate("LIC-TEST", "v1:" + "A" * 64)
        self.assertEqual(result, (True, {"valid": True}))
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/api/validate")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data),
            {"license_key": "LIC-TEST", "hwid": "v1:" + "A" * 64},
        )
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 7)
        self.assertIsNotNone(self.urlopen.call_args.kwargs["context"])

    def test_non_object_or_malformed_responses_are_failures(self):
        for body in (b"[1]", b"not json", b"\xff"):
            with self.subTest(body=body):
                self.urlopen.return_value = _Response(body)
                with self.assertLogs(self.client.logger, level="WARNING"):
                    self.assertEqual(self.client.validate("LIC", None), (False, None))

    def test_http_client_error_returns_the_error_body_and_server_error_does_not(self):
        self.urlopen.side_effect = urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, io.BytesIO(b'{"error": "revoked"}')
        )
        self.assertEqual(
            self.client.validate("LIC", None), (False, {"error": "revoked"})
        )
        self.urlopen.side_effect = urllib.error.HTTPError(
            "url", 503, "Unavailable", {}, io.BytesIO(b'{"error": "ignored"}')
        )
        with self.assertLogs(self.client.logger, level="WARNING"):
            self.assertEqual(self.client.validate("LIC", None), (False, None))
        self.sleep.assert_not_called()

    def test_transient_network_failure_is_retried_once(self):
        self.urlopen.side_effect = [
            urllib.error.URLError("offline"),
            _Response(b'{"valid": true}'),
        ]
        self.assertEqual(self.client.validate("LIC", None), (True, {"valid": True}))
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(1)
        self.urlopen.reset_mock()
        self.sleep.reset_mock()
        self.urlopen.side_effect = TimeoutError()
        self.assertEqual(self.client.validate("LIC", None), (False, None))
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(1)
