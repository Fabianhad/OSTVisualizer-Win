from pathlib import Path
from typing import Protocol
from ..entities.license import License


class ILicenseRepository(Protocol):
    license_path: Path

    def load(self) -> License: ...
    def save(self, license_data: License) -> None: ...
    def clear(self) -> None: ...
