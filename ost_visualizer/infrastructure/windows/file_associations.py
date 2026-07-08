"""Development/manual repair helpers for Windows file associations.
Installed OST Visualizer builds get file associations from the MSI package.
"""

from __future__ import annotations
import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional, Protocol
from ...application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
)

APP_NAME = "OST Visualizer"
ASSOCIATIONS = {
    PROJECT_IMPORT_EXTENSION_OST: ("OSTVisualizer.ost", "OST Visualizer OST Project"),
    PROJECT_IMPORT_EXTENSION_OSP: ("OSTVisualizer.osp", "OST Visualizer OSP Package"),
}
CLASSES_ROOT = "Software\\Classes"
DEFAULT_VALUE = ""


class FileAssociationRegistryError(RuntimeError):
    pass


class IRegistry(Protocol):
    def set_value(self, key_path: str, name: str, value: str) -> None: ...
    def delete_tree(self, key_path: str) -> None: ...
class WinRegRegistry:
    def __init__(
        self, import_module: Callable[[str], ModuleType] = importlib.import_module
    ) -> None:
        try:
            winreg = import_module("winreg")
        except ImportError as exc:
            raise FileAssociationRegistryError(
                "Windows file associations can only be registered on Windows."
            ) from exc
        self._winreg = winreg
        self._root = winreg.HKEY_CURRENT_USER

    def set_value(self, key_path: str, name: str, value: str) -> None:
        key = self._winreg.CreateKeyEx(self._root, key_path, 0, self._winreg.KEY_WRITE)
        try:
            self._winreg.SetValueEx(key, name, 0, self._winreg.REG_SZ, value)
        finally:
            self._winreg.CloseKey(key)

    def delete_tree(self, key_path: str) -> None:
        self._delete_tree(key_path)

    def _delete_tree(self, key_path: str) -> None:
        try:
            key = self._winreg.OpenKey(
                self._root,
                key_path,
                0,
                self._winreg.KEY_READ | self._winreg.KEY_WRITE,
            )
        except FileNotFoundError:
            return
        try:
            while True:
                try:
                    child = self._winreg.EnumKey(key, 0)
                except OSError:
                    break
                self._delete_tree(f"{key_path}\\{child}")
        finally:
            self._winreg.CloseKey(key)
        try:
            self._winreg.DeleteKey(self._root, key_path)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class FileAssociationRegistrar:
    executable_path: Path
    app_script_path: Optional[Path] = None
    registry: Optional[IRegistry] = None

    def register(self) -> None:
        registry = self.registry or WinRegRegistry()
        command = build_open_command(self.executable_path, self.app_script_path)
        icon = build_icon_value(self.executable_path)
        for extension, (prog_id, description) in ASSOCIATIONS.items():
            registry.set_value(_class_key(extension), DEFAULT_VALUE, prog_id)
            registry.set_value(_class_key(prog_id), DEFAULT_VALUE, description)
            registry.set_value(
                _class_key(f"{prog_id}\\Application"), "ApplicationName", APP_NAME
            )
            registry.set_value(
                _class_key(f"{prog_id}\\DefaultIcon"), DEFAULT_VALUE, icon
            )
            registry.set_value(
                _class_key(f"{prog_id}\\shell\\open\\command"),
                DEFAULT_VALUE,
                command,
            )

    def unregister(self) -> None:
        registry = self.registry or WinRegRegistry()
        for extension, (prog_id, _) in ASSOCIATIONS.items():
            registry.delete_tree(_class_key(extension))
            registry.delete_tree(_class_key(prog_id))


def build_open_command(
    executable_path: Path, app_script_path: Optional[Path] = None
) -> str:
    executable = f'"{_command_path(executable_path)}"'
    if app_script_path is not None:
        return f'{executable} "{_command_path(app_script_path)}" "%1"'
    return f'{executable} "%1"'


def build_icon_value(executable_path: Path) -> str:
    return f'"{_command_path(executable_path)}",0'


def _command_path(executable_path: Path) -> str:
    return str(executable_path.expanduser().resolve(strict=False))


def _class_key(relative_path: str) -> str:
    return f"{CLASSES_ROOT}\\{relative_path}"
