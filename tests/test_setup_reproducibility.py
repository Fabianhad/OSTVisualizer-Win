import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SetupReproducibilityTests(unittest.TestCase):
    def _run_native_dependency_helper(
        self, command: str, **environment: str
    ) -> subprocess.CompletedProcess[str]:
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        process_environment = os.environ.copy()
        process_environment["OSTV_NATIVE_DEPENDENCY_MODULE"] = str(
            PROJECT_ROOT / "scripts" / "native-dependency-install.psm1"
        )
        process_environment.update(environment)
        return subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=process_environment,
        )

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
        self.assertEqual(script.count("Install-NativeDependencyDirectory"), 2)
        self.assertIn("Assert-PdfiumInstallation", script)
        self.assertIn("Assert-QpdfInstallation", script)

    def test_existing_native_dependency_must_match_the_pinned_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdfium = Path(tmp) / "pdfium"
            pdfium.mkdir()
            (pdfium / "VERSION").write_text(
                "MAJOR=145\nMINOR=0\nBUILD=1\nPATCH=0\n",
                encoding="ascii",
            )
            result = self._run_native_dependency_helper(
                "Import-Module $env:OSTV_NATIVE_DEPENDENCY_MODULE -Force; "
                "Assert-PdfiumInstallation "
                "-Directory $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY "
                "-ExpectedVersion '146.0.7651.0'",
                OSTV_NATIVE_DEPENDENCY_DIRECTORY=str(pdfium),
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PDFium 145.0.1.0 is installed", result.stderr)

    def test_failed_native_dependency_preparation_never_owns_final_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_directory = root / "dependency"
            result = self._run_native_dependency_helper(
                "Import-Module $env:OSTV_NATIVE_DEPENDENCY_MODULE -Force; "
                "try { "
                "Install-NativeDependencyDirectory "
                "-FinalDirectory $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY "
                "-PrepareDirectory { param($staging) "
                "Set-Content -LiteralPath (Join-Path $staging 'partial.txt') "
                "-Value 'partial'; throw 'controlled extraction failure' } "
                "-ValidateDirectory { param($directory) } | Out-Null; "
                "exit 10 "
                "} catch { "
                "if (Test-Path -LiteralPath $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY) "
                "{ exit 11 }; "
                "$remaining = @(Get-ChildItem -LiteralPath $env:OSTV_NATIVE_DEPENDENCY_ROOT "
                "-Filter '.dependency.staging-*'); "
                "if ($remaining.Count -ne 0) { exit 12 }; exit 0 }",
                OSTV_NATIVE_DEPENDENCY_DIRECTORY=str(final_directory),
                OSTV_NATIVE_DEPENDENCY_ROOT=str(root),
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_successful_native_dependency_preparation_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_directory = root / "dependency"
            result = self._run_native_dependency_helper(
                "Import-Module $env:OSTV_NATIVE_DEPENDENCY_MODULE -Force; "
                "$prepare = { param($staging) "
                "$package = Join-Path $staging 'package'; "
                "New-Item -ItemType Directory -Path $package | Out-Null; "
                "Set-Content -LiteralPath (Join-Path $package 'VERSION') "
                "-Value '1.2.3'; return $package }; "
                "$validate = { param($directory) "
                "if ((Get-Content -LiteralPath (Join-Path $directory 'VERSION')) "
                "-ne '1.2.3') { throw 'invalid staged version' } }; "
                "$first = Install-NativeDependencyDirectory "
                "-FinalDirectory $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY "
                "-PrepareDirectory $prepare -ValidateDirectory $validate; "
                "$second = Install-NativeDependencyDirectory "
                "-FinalDirectory $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY "
                "-PrepareDirectory { throw 'must not prepare twice' } "
                "-ValidateDirectory $validate; "
                "if (-not $first -or $second) { exit 20 }; "
                "if (-not (Test-Path -LiteralPath "
                "(Join-Path $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY 'VERSION'))) "
                "{ exit 21 }; exit 0",
                OSTV_NATIVE_DEPENDENCY_DIRECTORY=str(final_directory),
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_concurrent_native_dependency_commit_cannot_nest_staged_package(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_directory = root / "dependency"
            result = self._run_native_dependency_helper(
                "Import-Module $env:OSTV_NATIVE_DEPENDENCY_MODULE -Force; "
                "try { "
                "Install-NativeDependencyDirectory "
                "-FinalDirectory $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY "
                "-PrepareDirectory { param($staging) "
                "$package = Join-Path $staging 'package'; "
                "New-Item -ItemType Directory -Path $package | Out-Null; "
                "Set-Content -LiteralPath (Join-Path $package 'VERSION') "
                "-Value 'staged'; "
                "New-Item -ItemType Directory "
                "-Path $env:OSTV_NATIVE_DEPENDENCY_DIRECTORY | Out-Null; "
                "Set-Content -LiteralPath (Join-Path "
                "$env:OSTV_NATIVE_DEPENDENCY_DIRECTORY 'VERSION') "
                "-Value 'winner'; return $package } "
                "-ValidateDirectory { param($directory) } | Out-Null; exit 30 "
                "} catch { "
                "$winner = Get-Content -LiteralPath (Join-Path "
                "$env:OSTV_NATIVE_DEPENDENCY_DIRECTORY 'VERSION'); "
                "if ($winner -ne 'winner') { exit 31 }; "
                "if (Test-Path -LiteralPath (Join-Path "
                "$env:OSTV_NATIVE_DEPENDENCY_DIRECTORY 'package')) { exit 32 }; "
                "$remaining = @(Get-ChildItem -LiteralPath "
                "$env:OSTV_NATIVE_DEPENDENCY_ROOT "
                "-Filter '.dependency.staging-*'); "
                "if ($remaining.Count -ne 0) { exit 33 }; exit 0 }",
                OSTV_NATIVE_DEPENDENCY_DIRECTORY=str(final_directory),
                OSTV_NATIVE_DEPENDENCY_ROOT=str(root),
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

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
