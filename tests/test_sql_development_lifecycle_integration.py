from __future__ import annotations
import ctypes
import json
import os
import subprocess
import unittest
from pathlib import Path


class SqlDevelopmentLifecycleIntegrationTests(unittest.TestCase):
    """Destructive whole-instance coverage for a dedicated disposable machine."""

    @classmethod
    def setUpClass(cls):
        if os.name != "nt":
            raise unittest.SkipTest("SQL lifecycle integration tests require Windows.")
        from ost_visualizer.infrastructure.sql.credential_store import (
            WindowsCredentialStore,
        )
        from tools.manage_sql_development import (
            CLIENT_CREDENTIAL_TARGET,
            INTEGRATION_CREDENTIAL_TARGET,
        )

        required = (
            "OSTV_SQL_LIFECYCLE_TESTS",
            "OSTV_SQL_DESTRUCTIVE_TESTS",
            "OSTV_SQL_DISPOSABLE_MACHINE",
        )
        if any(os.environ.get(name) != "1" for name in required):
            raise unittest.SkipTest(
                "Whole-instance SQL lifecycle tests require all three explicit opt-ins."
            )
        if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
            raise unittest.SkipTest(
                "Whole-instance SQL lifecycle tests require elevation."
            )
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.setup_script = cls.repo_root / "scripts" / "setup-sql-development.ps1"
        cls.credential_store = WindowsCredentialStore()
        cls.client_credential_target = CLIENT_CREDENTIAL_TARGET
        cls.integration_credential_target = INTEGRATION_CREDENTIAL_TARGET

    def test_idempotency_rotation_teardown_and_fresh_rebuild(self):
        environment_removed = False
        try:
            self._run_setup()
            initial_password = self._required_client_password()
            initial_snapshot = self._machine_snapshot()
            self._run_setup()
            self.assertEqual(self._required_client_password(), initial_password)
            self.assertEqual(self._machine_snapshot(), initial_snapshot)
            self._run_setup("-RotateClientPassword")
            rotated_password = self._required_client_password()
            self.assertNotEqual(rotated_password, initial_password)
            self.assertEqual(
                self._machine_snapshot(),
                initial_snapshot,
                "Password rotation must not rebuild or restart the SQL environment.",
            )
            self._run_setup("-RemoveOwnedEnvironment", "-ConfirmDestructive")
            environment_removed = True
            self._assert_owned_environment_absent()
            self._run_setup()
            environment_removed = False
            self.assertTrue(self._required_client_password())
            rebuilt = self._machine_snapshot()
            self.assertEqual(rebuilt["database_count"], 1)
            self.assertEqual(rebuilt["leaf_certificate_count"], 1)
            self.assertEqual(rebuilt["firewall_rule_count"], 1)
        finally:
            if environment_removed:
                self._run_setup()

    def _run_setup(self, *arguments: str) -> None:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.setup_script),
            *arguments,
        ]
        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=7_200,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "The guarded SQL lifecycle command failed; inspect the setup log locally.",
        )

    def _required_client_password(self) -> str:
        value = self.credential_store.read_password(self.client_credential_target)
        self.assertIsNotNone(value)
        return str(value)

    def _machine_snapshot(self) -> dict[str, object]:
        script = r"""
$service=Get-CimInstance Win32_Service -Filter "Name='MSSQL`$OSTVDEV'"
$databaseCount=Invoke-Sqlcmd -ServerInstance 'tcp:localhost' `
    -Database master -Encrypt Mandatory -TrustServerCertificate:$false `
    -Query "SET NOCOUNT ON; SELECT COUNT(*) AS Value FROM sys.databases WHERE name=N'OSTV_CLIENT_TEST'" |
    Select-Object -ExpandProperty Value
$leafCount=@(Get-ChildItem Cert:\LocalMachine\My | Where-Object FriendlyName -eq `
    'OST Visualizer SQL Development').Count
$firewallCount=@(Get-NetFirewallRule -DisplayName `
    'OST Visualizer SQL Development - Local Only' -ErrorAction SilentlyContinue).Count
[pscustomobject]@{
    service_process_id=[int]$service.ProcessId
    service_start_mode=[string]$service.StartMode
    database_count=[int]$databaseCount
    leaf_certificate_count=[int]$leafCount
    firewall_rule_count=[int]$firewallCount
}|ConvertTo-Json -Compress
"""
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def _assert_owned_environment_absent(self) -> None:
        script = r"""
$serviceCount=@(Get-Service -Name 'MSSQL$OSTVDEV' -ErrorAction SilentlyContinue).Count
$registryExists=Test-Path -LiteralPath 'HKLM:\SOFTWARE\OSTVisualizer\SqlDevelopment'
$instanceRegistry='HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL'
$instanceExists=(Test-Path -LiteralPath $instanceRegistry) -and `
    $null -ne (Get-ItemProperty -LiteralPath $instanceRegistry).PSObject.Properties['OSTVDEV']
$firewallCount=@(Get-NetFirewallRule -DisplayName `
    'OST Visualizer SQL Development - Local Only' -ErrorAction SilentlyContinue).Count
$leafCount=@(Get-ChildItem Cert:\LocalMachine\My | Where-Object FriendlyName -eq `
    'OST Visualizer SQL Development').Count
$rootPersonalCount=@(Get-ChildItem Cert:\LocalMachine\My | Where-Object Subject -eq `
    'CN=OSTV Local SQL Development Root').Count
$rootTrustedCount=@(Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -eq `
    'CN=OSTV Local SQL Development Root').Count
$backupRootExists=Test-Path -LiteralPath `
    (Join-Path $env:ProgramData 'OSTVisualizer\SqlIntegrationBackups')
[pscustomobject]@{
    service_count=$serviceCount
    registry_exists=$registryExists
    instance_exists=$instanceExists
    firewall_rule_count=$firewallCount
    leaf_certificate_count=$leafCount
    root_personal_count=$rootPersonalCount
    root_trusted_count=$rootTrustedCount
    backup_root_exists=$backupRootExists
}|ConvertTo-Json -Compress
"""
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["service_count"], 0)
        self.assertFalse(result["registry_exists"])
        self.assertFalse(result["instance_exists"])
        self.assertEqual(result["firewall_rule_count"], 0)
        self.assertEqual(result["leaf_certificate_count"], 0)
        self.assertEqual(result["root_personal_count"], 0)
        self.assertEqual(result["root_trusted_count"], 0)
        self.assertFalse(result["backup_root_exists"])
        self.assertIsNone(
            self.credential_store.read_password(self.client_credential_target)
        )
        self.assertIsNone(
            self.credential_store.read_password(self.integration_credential_target)
        )
        self.assertFalse(
            (self.repo_root / ".secrets" / "sql-development.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
