import hashlib
import subprocess
import uuid
from pathlib import Path
from typing import Optional
from ..app_paths import get_app_data_dir

_INSTALL_ID_FILENAME = "install_id.txt"
_GENERIC_VALUES = {
    "",
    "none",
    "unknown",
    "null",
    "to be filled by o.e.m.",
    "default string",
    "system serial number",
    "base board serial number",
    "00000000-0000-0000-0000-000000000000",
    "00000000000000000000000000000000",
}


class HWIDGenerator:
    def __init__(self, app_data_dir: Optional[Path] = None):
        self._cached_hwid = None
        self._app_data_dir = app_data_dir or get_app_data_dir()

    def get_hwid(self) -> str:
        if self._cached_hwid:
            return self._cached_hwid
        stable_id = self._get_system_uuid()
        if not stable_id:
            stable_id = self._get_motherboard_serial()
        if stable_id:
            source = f"MACHINE:{stable_id}"
        else:
            source = f"INSTALL:{self._get_or_create_install_id()}"
        self._cached_hwid = self._hash_hwid(source)
        return self._cached_hwid

    def _get_motherboard_serial(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["wmic", "baseboard", "get", "serialnumber", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "SerialNumber=" in line:
                    serial = line.split("=")[1].strip()
                    if self._is_useful_identifier(serial):
                        return serial
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def _get_system_uuid(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["wmic", "csproduct", "get", "uuid", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "UUID=" in line:
                    uuid_val = line.split("=")[1].strip()
                    normalized = uuid_val.replace("-", "").upper()
                    if self._is_useful_identifier(
                        uuid_val
                    ) and self._is_useful_identifier(normalized):
                        return normalized
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def _get_or_create_install_id(self) -> str:
        install_id_path = self._app_data_dir / _INSTALL_ID_FILENAME
        install_id_path.parent.mkdir(parents=True, exist_ok=True)
        if install_id_path.exists():
            try:
                install_id = install_id_path.read_text(encoding="utf-8").strip()
                if self._is_useful_identifier(install_id):
                    return install_id
            except OSError:
                pass
        install_id = uuid.uuid4().hex.upper()
        install_id_path.write_text(install_id, encoding="utf-8")
        return install_id

    @staticmethod
    def _hash_hwid(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16].upper()

    @staticmethod
    def _is_useful_identifier(value: Optional[str]) -> bool:
        if value is None:
            return False
        normalized = value.strip().lower()
        if normalized in _GENERIC_VALUES:
            return False
        compact = normalized.replace("-", "").replace(" ", "")
        if compact and set(compact) == {"0"}:
            return False
        return bool(normalized)
