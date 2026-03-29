from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class RenderResult:
    request_id: str
    success: bool
    image: Optional[Any]
    error: Optional[str]
