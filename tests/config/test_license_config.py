import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.config import license_config
from ost_visualizer.config.license_config import _load_trusted_public_key
from ost_visualizer.domain.services.hardware_identity import HWID_EXTERNAL_LENGTH

ATTACKER_KEY = "attacker-controlled-key"


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


class TrustedPublicKeyLoadingTests(unittest.TestCase):
    """The trusted key comes only from the bundled file or the local .secrets file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / "ost_visualizer" / "config"
        self.package.mkdir(parents=True)
        self.bundled = self.package / "license_public_key.pem"
        self.local = self.root / ".secrets" / "license_public_key.pem"
        module_file = patch.object(
            license_config, "__file__", str(self.package / "license_config.py")
        )
        module_file.start()
        self.addCleanup(module_file.stop)

    def write_local(self, text):
        self.local.parent.mkdir(exist_ok=True)
        self.local.write_text(text, encoding="utf-8")

    def test_no_key_files_means_an_empty_trusted_key(self):
        self.assertEqual(_load_trusted_public_key(), "")

    def test_bundled_key_is_read_and_stripped(self):
        self.bundled.write_text("\n  BUNDLED-KEY\n\n", encoding="utf-8")
        self.assertEqual(_load_trusted_public_key(), "BUNDLED-KEY")

    def test_local_secrets_key_is_the_development_fallback(self):
        self.write_local("  LOCAL-KEY  \n")
        self.assertEqual(_load_trusted_public_key(), "LOCAL-KEY")

    def test_bundled_key_wins_over_the_local_key(self):
        self.bundled.write_text("BUNDLED-KEY", encoding="utf-8")
        self.write_local("LOCAL-KEY")
        self.assertEqual(_load_trusted_public_key(), "BUNDLED-KEY")

    def test_environment_variables_never_override_either_key_source(self):
        environment = {
            "OST_LICENSE_PUBLIC_KEY_PEM": ATTACKER_KEY,
            "OST_LICENSE_PUBLIC_KEY": ATTACKER_KEY,
            "OSTV_LICENSE_PUBLIC_KEY_PEM": ATTACKER_KEY,
        }
        with patch.dict(os.environ, environment):
            self.assertEqual(_load_trusted_public_key(), "")
            self.bundled.write_text("BUNDLED-KEY", encoding="utf-8")
            self.assertEqual(_load_trusted_public_key(), "BUNDLED-KEY")
            self.bundled.unlink()
            self.write_local("LOCAL-KEY")
            self.assertEqual(_load_trusted_public_key(), "LOCAL-KEY")

    def test_an_empty_key_file_yields_an_empty_trusted_key(self):
        self.bundled.write_text("   \n", encoding="utf-8")
        self.write_local("LOCAL-KEY")
        self.assertEqual(_load_trusted_public_key(), "")


class LicenseConstantsTests(unittest.TestCase):
    def test_license_timing_and_size_limits_are_the_documented_values(self):
        self.assertEqual(license_config.LICENSE_OFFLINE_GRACE_HOURS, 72)
        self.assertEqual(license_config.LICENSE_VALIDATION_INTERVAL_SECONDS, 300)
        self.assertEqual(license_config.MAX_LICENSE_KEY_LENGTH, 80)
        self.assertEqual(license_config.MAX_HWID_LENGTH, HWID_EXTERNAL_LENGTH)

    def test_module_level_key_has_no_environment_override(self):
        self.assertIsInstance(license_config.TRUSTED_LICENSE_PUBLIC_KEY_PEM, str)
        self.assertNotEqual(license_config.TRUSTED_LICENSE_PUBLIC_KEY_PEM, ATTACKER_KEY)
        source = Path(license_config.__file__).read_text(encoding="utf-8")
        self.assertNotIn("environ", source)
        self.assertNotIn("getenv", source)


if __name__ == "__main__":
    unittest.main()
