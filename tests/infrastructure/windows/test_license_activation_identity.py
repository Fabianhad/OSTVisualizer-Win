import os
import unittest
from unittest.mock import patch
import pywintypes
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
        self.failing_call = None

    def _fail_if_requested(self, call):
        if self.failing_call == call:
            raise pywintypes.error(5, call, "Access is denied.")

    def GetUserNameEx(self, name_format):
        self.user_name_formats.append(name_format)
        self._fail_if_requested("GetUserNameEx")
        return self.windows_account

    def GetComputerNameEx(self, name_format):
        self.computer_name_formats.append(name_format)
        self._fail_if_requested("GetComputerNameEx")
        return self.computer_name


class FakeWindowsNetworkApi:
    def __init__(self, join_name, join_status) -> None:
        self.join_name = join_name
        self.join_status = join_status
        self.computers = []
        self.fails = False

    def NetGetJoinInformation(self, computer):
        self.computers.append(computer)
        if self.fails:
            raise pywintypes.error(1722, "NetGetJoinInformation", "RPC unavailable.")
        return self.join_name, self.join_status


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
            (
                "STALE-NAME",
                win32netcon.NetSetupUnjoined,
                WindowsJoinType.UNJOINED,
                "",
            ),
        )
        for join_name, join_status, expected_type, expected_name in scenarios:
            with self.subTest(join_type=expected_type, join_name=join_name):
                identity = WindowsLicenseActivationIdentityProvider(
                    windows_api=FakeWindowsApi(),
                    windows_network_api=FakeWindowsNetworkApi(
                        join_name,
                        join_status,
                    ),
                ).get_identity()
                self.assertEqual(
                    identity,
                    LicenseActivationIdentityDto(
                        version=LICENSE_ACTIVATION_IDENTITY_VERSION,
                        windows_account=r"EXAMPLE\Estimator",
                        computer_name="ESTIMATOR-PC",
                        join_type=expected_type,
                        join_name=expected_name,
                    ),
                )

    def test_joined_computer_without_join_name_is_an_explicit_failure(self):
        for join_status in (
            win32netcon.NetSetupWorkgroupName,
            win32netcon.NetSetupDomainName,
        ):
            with self.subTest(join_status=join_status):
                provider = WindowsLicenseActivationIdentityProvider(
                    windows_api=FakeWindowsApi(),
                    windows_network_api=FakeWindowsNetworkApi(None, join_status),
                )
                with self.assertRaisesRegex(
                    LicenseActivationIdentityError,
                    "invalid account or computer identity",
                ) as raised:
                    provider.get_identity()
                self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_windows_api_failures_are_explicit_failures(self):
        scenarios = ("GetUserNameEx", "GetComputerNameEx", "NetGetJoinInformation")
        for failing_call in scenarios:
            with self.subTest(failing_call=failing_call):
                windows_api = FakeWindowsApi()
                network_api = FakeWindowsNetworkApi(
                    "EXAMPLE", win32netcon.NetSetupDomainName
                )
                windows_api.failing_call = failing_call
                network_api.fails = failing_call == "NetGetJoinInformation"
                provider = WindowsLicenseActivationIdentityProvider(
                    windows_api=windows_api,
                    windows_network_api=network_api,
                )
                with self.assertRaisesRegex(
                    LicenseActivationIdentityError,
                    "Unable to query the current Windows account",
                ) as raised:
                    provider.get_identity()
                self.assertIsInstance(raised.exception.__cause__, pywintypes.error)

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
        invalid_identities = (
            ("", "ESTIMATOR-PC"),
            (r" EXAMPLE\Estimator", "ESTIMATOR-PC"),
            (r"EXAMPLE\Estimator", ""),
            (r"EXAMPLE\Estimator", "ESTIMATOR-PC "),
            ("EXAMPLE\\Est\x00imator", "ESTIMATOR-PC"),
            (r"EXAMPLE\Estimator", "E" * 256),
            ("E" * 513, "ESTIMATOR-PC"),
        )
        for windows_account, computer_name in invalid_identities:
            with self.subTest(
                account_length=len(windows_account), computer_name=computer_name
            ):
                provider = WindowsLicenseActivationIdentityProvider(
                    windows_api=FakeWindowsApi(
                        windows_account=windows_account,
                        computer_name=computer_name,
                    ),
                    windows_network_api=FakeWindowsNetworkApi(
                        "EXAMPLE",
                        win32netcon.NetSetupDomainName,
                    ),
                )
                with self.assertRaisesRegex(
                    LicenseActivationIdentityError,
                    "invalid account or computer identity",
                ) as raised:
                    provider.get_identity()
                self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_live_windows_identity_is_available_without_environment_fallbacks(self):
        environment = {
            "USERNAME": "ENV-FALLBACK-USER",
            "USERDOMAIN": "ENV-FALLBACK-DOMAIN",
            "COMPUTERNAME": "ENV-FALLBACK-PC",
            "LOGONSERVER": r"\\ENV-FALLBACK-SERVER",
            "USERDNSDOMAIN": "ENV-FALLBACK.EXAMPLE",
        }
        with patch.dict(os.environ, environment):
            identity = WindowsLicenseActivationIdentityProvider().get_identity()
        self.assertEqual(identity.version, LICENSE_ACTIVATION_IDENTITY_VERSION)
        self.assertIn("\\", identity.windows_account)
        self.assertTrue(identity.computer_name)
        for value in environment.values():
            self.assertNotIn(value, identity.to_payload().values())
            self.assertNotIn(value.upper(), identity.windows_account.upper())
        self.assertIn(
            identity.join_type,
            (
                WindowsJoinType.UNJOINED,
                WindowsJoinType.WORKGROUP,
                WindowsJoinType.DOMAIN,
            ),
        )
        if identity.join_type == WindowsJoinType.UNJOINED:
            self.assertEqual(identity.join_name, "")
        else:
            self.assertTrue(identity.join_name)
