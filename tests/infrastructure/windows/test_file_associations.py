from __future__ import annotations
import unittest
from pathlib import Path
from ost_visualizer.infrastructure.windows.file_associations import (
    ASSOCIATIONS,
    FileAssociationRegistrar,
    FileAssociationRegistryError,
    WinRegRegistry,
    build_open_command,
)
from tests.helpers.startup_import import (
    FakeRegistry as _startup_import_FakeRegistry,
)


class FileAssociationRegistryTests(unittest.TestCase):
    def test_registry_register_and_unregister_keys(self):
        registry = _startup_import_FakeRegistry()
        exe = Path("C:/Program Files/OST Visualizer/Visualizer.exe")
        registrar = FileAssociationRegistrar(executable_path=exe, registry=registry)
        registrar.register()
        registrar.unregister()
        command = build_open_command(exe)
        self.assertEqual(
            command, '"C:\\Program Files\\OST Visualizer\\Visualizer.exe" "%1"'
        )
        for extension, (prog_id, description) in ASSOCIATIONS.items():
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{extension}", "")],
                prog_id,
            )
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{prog_id}", "")],
                description,
            )
            self.assertEqual(
                registry.values[
                    (f"Software\\Classes\\{prog_id}\\shell\\open\\command", "")
                ],
                command,
            )
            self.assertIn(f"Software\\Classes\\{extension}", registry.deleted)
            self.assertIn(f"Software\\Classes\\{prog_id}", registry.deleted)

    def test_registry_command_can_include_development_script(self):
        command = build_open_command(
            Path("C:/Python311/python.exe"),
            Path("C:/Projects/OST Visualizer/Visualizer.py"),
        )
        self.assertEqual(
            command,
            '"C:\\Python311\\python.exe" '
            '"C:\\Projects\\OST Visualizer\\Visualizer.py" "%1"',
        )

    def test_winreg_registry_reports_non_windows_import_failure(self):
        def missing_winreg(_name):
            raise ImportError("no winreg")

        with self.assertRaisesRegex(FileAssociationRegistryError, "only be registered"):
            WinRegRegistry(import_module=missing_winreg)
