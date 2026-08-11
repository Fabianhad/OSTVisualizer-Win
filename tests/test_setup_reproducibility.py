import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SetupReproducibilityTests(unittest.TestCase):
    def test_only_required_qt_version_is_pinned(self) -> None:
        requirements = {
            line.strip()
            for line in (PROJECT_ROOT / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(
            requirements,
            {
                "pyodbc",
                "PySide6==6.10.2",
                "Nuitka",
                "pywin32",
            },
        )

    def test_python_setup_propagates_installer_failure(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
        self.assertIn("$VenvPython -m pip install", script)
        install_at = script.index("$VenvPython -m pip install")
        exit_check_at = script.index("$LASTEXITCODE -ne 0", install_at)
        success_at = script.index('Write-Host "Python setup complete."', exit_check_at)
        self.assertLess(install_at, exit_check_at)
        self.assertLess(exit_check_at, success_at)

    def test_native_archives_are_versioned_and_sha256_verified(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "setup-cpp.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("/releases/latest/", script)
        self.assertIn("releases/download/$PdfiumReleaseTag/pdfium-win-x64.tgz", script)
        self.assertIn("releases/download/v$QpdfVersion/$QpdfDirName.zip", script)
        expected_hashes = {
            "17c2f2fdb09607163304b19ee5724ac0ea71d244cd74c45d3a8e524396357f59",
            "8941870a604e7c87ed24566b038d46c24ce76616254d2383c578f60c0677f202",
        }
        self.assertEqual(
            set(re.findall(r"'[0-9a-f]{64}'", script)),
            {f"'{digest}'" for digest in expected_hashes},
        )
        self.assertIn(
            "Get-FileHash -LiteralPath $Destination -Algorithm SHA256", script
        )
        self.assertEqual(script.count("Invoke-VerifiedDownload -Url"), 2)

    def test_native_extractor_failure_is_not_reported_as_success(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "setup-cpp.ps1").read_text(
            encoding="utf-8"
        )
        extract_at = script.index("tar -xzf")
        exit_check_at = script.index("$LASTEXITCODE -ne 0", extract_at)
        success_at = script.index("PDFium downloaded to", exit_check_at)
        self.assertLess(extract_at, exit_check_at)
        self.assertLess(exit_check_at, success_at)


if __name__ == "__main__":
    unittest.main()
