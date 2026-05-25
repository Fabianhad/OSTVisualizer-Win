from pathlib import Path
from typing import Callable, Optional, Protocol


class IDatabaseCreator(Protocol):
    def create_database(
        self,
        db_path: Path,
        name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool: ...
