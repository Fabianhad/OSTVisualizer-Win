import hashlib
import json
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class AuditEntry:
    event: str
    tool: str = ""
    input_hash: str = ""
    changeset_id: str = ""
    summary: str = ""
    approver: str = ""
    outcome: str = ""
    assumption_ids: Tuple[str, ...] = ()


def hash_arguments(arguments) -> str:
    text = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
