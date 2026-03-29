from dataclasses import dataclass, field
from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


@dataclass
class PickerDialogResult(Generic[T]):
    selected_uid: Optional[str] = None
    items: List[T] = field(default_factory=list)
