from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PasteRefRemap:
    takeoff_uids: Dict[str, str] = field(default_factory=dict)
    namedview_uids: Dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.takeoff_uids and not self.namedview_uids
