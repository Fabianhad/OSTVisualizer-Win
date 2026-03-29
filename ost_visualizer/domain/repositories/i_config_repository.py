from pathlib import Path
from typing import Protocol, runtime_checkable
from ..entities.config import Config


@runtime_checkable
class IConfigRepository(Protocol):
    config_path: Path

    def load(self) -> Config: ...
    def save(self, config: Config) -> None: ...
