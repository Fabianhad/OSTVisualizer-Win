from dataclasses import dataclass, field
from typing import List, Optional
from ...domain.entities.takeoff import Takeoff
from .export_dto import ExportErrorCode


@dataclass
class ExportDialogDto:
    success: bool
    format_name: str = ""
    error: str = ""
    error_code: Optional[ExportErrorCode] = None
    dialog_title: str = ""
    default_filename: str = ""
    extension: str = ""
    valid_pages: List[str] = field(default_factory=list)
    takeoffs: List[Takeoff] = field(default_factory=list)
    page_names: List[str] = field(default_factory=list)
    bid_name: str = ""
