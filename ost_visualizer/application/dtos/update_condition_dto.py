from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class UpdateConditionDto:
    _changes: Dict[str, Any] = field(default_factory=dict, repr=False)

    def set(self, name: str, value: Any) -> None:
        self._changes[name] = value

    def get_changes(self) -> Dict[str, Any]:
        return dict(self._changes)

    def is_empty(self) -> bool:
        return len(self._changes) == 0

    def get(self, name: str, default: Any = None) -> Any:
        return self._changes.get(name, default)


@dataclass
class UpdateConditionResultDto:
    success: bool = False
    error: Optional[str] = None
    error_presented: bool = False
