import unittest
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    LicenseActivationIdentityError,
    WindowsJoinType,
)


class LicenseActivationIdentityTests(unittest.TestCase):
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
