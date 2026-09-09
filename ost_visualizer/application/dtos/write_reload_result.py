from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WriteReloadResult:
    value: object = None
    write_success: bool = False
    reload_success: bool = False
    failure_reason: Optional[str] = None
    blocked_uids: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return (
            self.write_success
            and self.reload_success
            and not self.failure_reason
            and not self.blocked_uids
        )

    @property
    def refresh_failed(self) -> bool:
        return self.write_success and not self.reload_success

    def __bool__(self) -> bool:
        return self.success
