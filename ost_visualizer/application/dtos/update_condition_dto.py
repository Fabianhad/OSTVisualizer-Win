from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

MAX_CONDITION_NUMBER = 2147483647
MIN_ACCESS_LONG = -2147483648


class ConditionNumberOverflowError(ValueError):
    """A new, duplicated, renumbered or temporary condition number would pass the
    Access Long range."""


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
