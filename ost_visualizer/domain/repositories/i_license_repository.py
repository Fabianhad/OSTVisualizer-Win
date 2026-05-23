from pathlib import Path
from typing import Protocol, runtime_checkable
from ..entities.license import License


@runtime_checkable
class ILicenseRepository(Protocol):
    license_path: Path

    def load(self) -> License: ...
    def save(self, license_data: License) -> None: ...
    def clear(self) -> None: ...
