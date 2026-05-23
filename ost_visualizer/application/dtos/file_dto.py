from dataclasses import dataclass, field
from typing import Dict


@dataclass
class FileLoadResultDto:
    success: bool
    file_path: str = ""
    file_name: str = ""
    stats: Dict[str, int] = field(default_factory=dict)
    error_message: str = ""
