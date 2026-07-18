from typing import Protocol


class IDatabasePermissionProbe(Protocol):
    def can_edit(self, database_id: str) -> bool: ...
