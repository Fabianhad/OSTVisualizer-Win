from pathlib import Path
from typing import Protocol


class IDatabaseCreator(Protocol):
    def create_database(self, db_path: Path, name: str) -> bool: ...
