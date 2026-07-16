from pathlib import Path
from typing import Protocol
from ..entities.config import Config


class IConfigRepository(Protocol):
    config_path: Path

    def load(self) -> Config: ...
    def save(self, config: Config) -> None: ...
