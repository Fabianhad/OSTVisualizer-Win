import unittest
from unittest.mock import call, patch
import win32con
import win32netcon
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    LicenseActivationIdentityError,
    WindowsJoinType,
)
from ost_visualizer.infrastructure.windows.license_activation_identity import (
    WindowsLicenseActivationIdentityProvider,
)
from ost_visualizer.infrastructure.external.license_api_client import LicenseApiClient


class FakeWindowsApi:
    def __init__(
        self,
        windows_account=r"EXAMPLE\Estimator",
        computer_name="ESTIMATOR-PC",
    ) -> None:
        self.windows_account = windows_account
        self.computer_name = computer_name
        self.user_name_formats = []
        self.computer_name_formats = []

    def GetUserNameEx(self, name_format):
        self.user_name_formats.append(name_format)
        return self.windows_account

    def GetComputerNameEx(self, name_format):
        self.computer_name_formats.append(name_format)
        return self.computer_name


class FakeWindowsNetworkApi:
    def __init__(self, join_name, join_status) -> None:
        self.join_name = join_name
        self.join_status = join_status
        self.computers = []

    def NetGetJoinInformation(self, computer):
        self.computers.append(computer)
        return self.join_name, self.join_status


class UnexpectedActivationIdentityProvider:
    def get_identity(self):
        raise AssertionError("activation identity must not be queried")


class LicenseActivationIdentityTests(unittest.TestCase):
    def test_domain_identity_uses_supported_windows_apis(self):
        windows_api = FakeWindowsApi()
        network_api = FakeWindowsNetworkApi(
            "EXAMPLE",
            win32netcon.NetSetupDomainName,
        )
        identity = WindowsLicenseActivationIdentityProvider(
            windows_api=windows_api,
            windows_network_api=network_api,
        ).get_identity()
        self.assertEqual(
            identity,
            LicenseActivationIdentityDto(
                version=LICENSE_ACTIVATION_IDENTITY_VERSION,
                windows_account=r"EXAMPLE\Estimator",
                computer_name="ESTIMATOR-PC",
                join_type=WindowsJoinType.DOMAIN,
                join_name="EXAMPLE",
            ),
        )
        self.assertEqual(windows_api.user_name_formats, [win32con.NameSamCompatible])
        self.assertEqual(
            windows_api.computer_name_formats,
            [win32con.ComputerNameNetBIOS],
        )
        self.assertEqual(network_api.computers, [None])

    def test_workgroup_and_unjoined_identities_have_distinct_contracts(self):
        scenarios = (
            (
                "OFFICE",
                win32netcon.NetSetupWorkgroupName,
                WindowsJoinType.WORKGROUP,
                "OFFICE",
            ),
            (
                None,
                win32netcon.NetSetupUnjoined,
                WindowsJoinType.UNJOINED,
                "",
            ),
        )
        for join_name, join_status, expected_type, expected_name in scenarios:
            with self.subTest(join_type=expected_type):
                identity = WindowsLicenseActivationIdentityProvider(
                    windows_api=FakeWindowsApi(),
                    windows_network_api=FakeWindowsNetworkApi(
                        join_name,
                        join_status,
                    ),
                ).get_identity()
                self.assertEqual(identity.join_type, expected_type)
                self.assertEqual(identity.join_name, expected_name)

    def test_unknown_join_status_is_an_explicit_failure(self):
        provider = WindowsLicenseActivationIdentityProvider(
            windows_api=FakeWindowsApi(),
            windows_network_api=FakeWindowsNetworkApi("UNKNOWN", 99),
        )
        with self.assertRaisesRegex(
            LicenseActivationIdentityError,
            "unsupported computer join status 99",
        ):
            provider.get_identity()

    def test_invalid_windows_identity_is_an_explicit_failure(self):
        provider = WindowsLicenseActivationIdentityProvider(
            windows_api=FakeWindowsApi(windows_account=""),
            windows_network_api=FakeWindowsNetworkApi(
                "EXAMPLE",
                win32netcon.NetSetupDomainName,
            ),
        )
        with self.assertRaisesRegex(
            LicenseActivationIdentityError,
            "invalid account or computer identity",
        ):
            provider.get_identity()

    def test_payload_is_one_versioned_activation_identity(self):
        identity = LicenseActivationIdentityDto(
            version=LICENSE_ACTIVATION_IDENTITY_VERSION,
            windows_account=r"EXAMPLE\Estimator",
            computer_name="ESTIMATOR-PC",
            join_type=WindowsJoinType.DOMAIN,
            join_name="EXAMPLE",
        )
        self.assertEqual(
            identity.to_payload(),
            {
                "version": "v1",
                "windows_account": r"EXAMPLE\Estimator",
                "computer_name": "ESTIMATOR-PC",
                "join_type": "domain",
                "join_name": "EXAMPLE",
            },
        )

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

    def test_live_windows_identity_is_available_without_environment_fallbacks(self):
        identity = WindowsLicenseActivationIdentityProvider().get_identity()
        self.assertEqual(identity.version, LICENSE_ACTIVATION_IDENTITY_VERSION)
        self.assertIn("\\", identity.windows_account)
        self.assertTrue(identity.computer_name)
        self.assertIn(
            identity.join_type,
            (
                WindowsJoinType.UNJOINED,
                WindowsJoinType.WORKGROUP,
                WindowsJoinType.DOMAIN,
            ),
        )


if __name__ == "__main__":
    unittest.main()
