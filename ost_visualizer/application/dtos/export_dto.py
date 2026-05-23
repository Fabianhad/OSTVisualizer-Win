from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional


class ExportErrorCode(Enum):
    UNKNOWN_FORMAT = auto()
    NO_DATA = auto()
    WORKER_FAILED = auto()
    WRITE_FAILED = auto()
    UNEXPECTED = auto()


@dataclass
class ExportRequestDto:
    page_uids: List[str]
    format_key: str
    filename: str


@dataclass
class ExportResultDto:
    success: bool
    page_count: int = 0
    format_name: str = ""
    error_message: Optional[str] = None
    error_code: Optional[ExportErrorCode] = None

    def __bool__(self) -> bool:
        return self.success
