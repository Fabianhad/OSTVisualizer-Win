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


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_WRITE = 2
    KEY_READ = 1
    REG_SZ = "REG_SZ"

    def __init__(self, tree):
        self.tree = {}
        for path, children in tree.items():
            self._add(path, children)
        self.values = set()
        self.deleted = []
        self.opened = []
        self.closed_keys = []

    def _add(self, path, children):
        self.tree[path] = list(children)
        for child, grandchildren in children.items():
            self._add(f"{path}\\{child}", grandchildren)

    def CreateKeyEx(self, root, key_path, _reserved, _access):
        self.tree.setdefault(key_path, [])
        return key_path

    def SetValueEx(self, key, name, _reserved, value_type, value):
        self.values.add((key, name, value, value_type))

    def OpenKey(self, root, key_path, _reserved, _access):
        if key_path not in self.tree:
            raise FileNotFoundError(key_path)
        self.opened.append(key_path)
        return key_path

    def EnumKey(self, key, index):
        children = [
            path
            for path in self.tree
            if path.startswith(key + "\\") and "\\" not in path[len(key) + 1 :]
        ]
        if index >= len(children):
            raise OSError("no more keys")
        return children[index].rsplit("\\", 1)[1]

    def CloseKey(self, key):
        self.closed_keys.append(key)

    def DeleteKey(self, root, key_path):
        if key_path not in self.tree:
            raise FileNotFoundError(key_path)
        del self.tree[key_path]
        self.deleted.append(key_path)


class FileAssociationRegistryTests(unittest.TestCase):
    EXE = Path("C:/Program Files/OST Visualizer/Visualizer.exe")
    COMMAND = '"C:\\Program Files\\OST Visualizer\\Visualizer.exe" "%1"'
    ICON = '"C:\\Program Files\\OST Visualizer\\Visualizer.exe",0'

    def test_registry_register_and_unregister_keys(self):
        registry = _startup_import_FakeRegistry()
        registrar = FileAssociationRegistrar(
            executable_path=self.EXE, registry=registry
        )
        self.assertEqual(build_open_command(self.EXE), self.COMMAND)
        registrar.register()
        self.assertEqual(registry.deleted, [])
        expected_values = {}
        for extension, prog_id, description in (
            (".ost", "OSTVisualizer.ost", "OST Visualizer OST Project"),
            (".osp", "OSTVisualizer.osp", "OST Visualizer OSP Package"),
        ):
            classes = "Software\\Classes\\"
            expected_values[(f"{classes}{extension}", "")] = prog_id
            expected_values[(f"{classes}{prog_id}", "")] = description
            expected_values[(f"{classes}{prog_id}\\Application", "ApplicationName")] = (
                "OST Visualizer"
            )
            expected_values[(f"{classes}{prog_id}\\DefaultIcon", "")] = self.ICON
            expected_values[(f"{classes}{prog_id}\\shell\\open\\command", "")] = (
                self.COMMAND
            )
        self.assertEqual(registry.values, expected_values)
        self.assertEqual(
            {extension: prog_id for extension, (prog_id, _) in ASSOCIATIONS.items()},
            {".ost": "OSTVisualizer.ost", ".osp": "OSTVisualizer.osp"},
        )
        registered_values = dict(registry.values)
        registrar.unregister()
        self.assertEqual(
            registry.deleted,
            [
                "Software\\Classes\\.ost",
                "Software\\Classes\\OSTVisualizer.ost",
                "Software\\Classes\\.osp",
                "Software\\Classes\\OSTVisualizer.osp",
            ],
        )
        self.assertEqual(registry.values, registered_values)

    def test_unregister_does_not_write_registry_values(self):
        registry = _startup_import_FakeRegistry()
        FileAssociationRegistrar(
            executable_path=self.EXE, registry=registry
        ).unregister()
        self.assertEqual(registry.values, {})
        self.assertEqual(len(registry.deleted), 4)

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

    def test_winreg_registry_writes_values_and_deletes_trees_depth_first(self):
        winreg = FakeWinreg(
            {
                "Software\\Classes\\Prog": {"command": {"nested": {}}, "icon": {}},
            }
        )
        registry = WinRegRegistry(import_module=lambda name: winreg)
        registry.set_value("Software\\Classes\\Prog", "", "Description")
        self.assertEqual(
            winreg.values,
            {("Software\\Classes\\Prog", "", "Description", "REG_SZ")},
        )
        self.assertEqual(winreg.closed_keys, ["Software\\Classes\\Prog"])
        winreg.closed_keys.clear()
        registry.delete_tree("Software\\Classes\\Prog")
        self.assertEqual(
            winreg.deleted,
            [
                "Software\\Classes\\Prog\\command\\nested",
                "Software\\Classes\\Prog\\command",
                "Software\\Classes\\Prog\\icon",
                "Software\\Classes\\Prog",
            ],
        )
        self.assertEqual(winreg.tree, {})
        self.assertEqual(sorted(winreg.opened), sorted(winreg.closed_keys))
        registry.delete_tree("Software\\Classes\\Prog")
        self.assertEqual(len(winreg.deleted), 4)
