import os
import unittest
from unittest.mock import patch
from ost_visualizer.config.license_config import _load_trusted_public_key


class LicenseActivationContractTests(unittest.TestCase):
    def test_environment_cannot_replace_the_trusted_license_public_key(self):
        with patch.dict(
            os.environ,
            {"OST_LICENSE_PUBLIC_KEY_PEM": "attacker-controlled-key"},
        ), patch(
            "ost_visualizer.config.license_config.Path.exists",
            return_value=False,
        ):
            self.assertEqual(_load_trusted_public_key(), "")
