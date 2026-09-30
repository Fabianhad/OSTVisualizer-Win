import unittest
import uuid
from unittest.mock import patch
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    LicenseActivationIdentityError,
    WindowsJoinType,
)
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)
from ost_visualizer.infrastructure.external.license_api_client import LicenseApiClient
from unittest.mock import call, patch

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
