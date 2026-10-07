import json
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from ...application.dtos.ai_takeoff_audit_dtos import AuditEntry

AUDIT_MAX_BYTES = 10 * 1024 * 1024
AUDIT_KEEP_FILES = 5
AUDIT_RETENTION_DAYS = 365
AUDIT_TEXT_MAX_CHARS = 200
UNKEYED_AUDIT_NAME = "unkeyed"
_KEY_PATTERN = re.compile(r"[0-9a-f]{32}")
_BIDI_FORMATTING = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def _clean(value) -> str:
    kept = []
    for character in str(value or ""):
        if character in "\t\n\r\x0b\x0c":
            kept.append(" ")
        elif (
            character not in _BIDI_FORMATTING
            and unicodedata.category(character) != "Cc"
        ):
            kept.append(character)
    return "".join(kept)[:AUDIT_TEXT_MAX_CHARS]


def restrict_to_current_user(path: Path) -> None:
    import ntsecuritycon
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION,
        win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE,
        ntsecuritycon.FILE_ALL_ACCESS,
        user,
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )


class AiTakeoffAuditLog:
    def __init__(
        self,
        directory: Path,
        clock: Callable[[], float] = time.time,
        max_bytes: int = AUDIT_MAX_BYTES,
        keep_files: int = AUDIT_KEEP_FILES,
        retention_days: int = AUDIT_RETENTION_DAYS,
        secure_directory: Callable[[Path], None] = restrict_to_current_user,
    ):
        self._directory = Path(directory)
        self._clock = clock
        self._max_bytes = int(max_bytes)
        self._keep_files = int(keep_files)
        self._retention_seconds = float(retention_days) * 86400.0
        self._secure_directory = secure_directory
        self._lock = threading.Lock()

    def record(self, bid_key: Optional[str], entry: AuditEntry) -> None:
        name = UNKEYED_AUDIT_NAME if bid_key is None else str(bid_key)
        if name != UNKEYED_AUDIT_NAME and not _KEY_PATTERN.fullmatch(name):
            raise ValueError("Invalid audit key")
        now = float(self._clock())
        line = (
            json.dumps(
                {
                    "time": datetime.fromtimestamp(now, timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "event": _clean(entry.event),
                    "tool": _clean(entry.tool),
                    "input_hash": _clean(entry.input_hash),
                    "changeset_id": _clean(entry.changeset_id),
                    "summary": _clean(entry.summary),
                    "approver": _clean(entry.approver),
                    "outcome": _clean(entry.outcome),
                    "assumption_ids": [_clean(item) for item in entry.assumption_ids],
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        with self._lock:
            if not self._directory.exists():
                self._directory.mkdir(parents=True)
                self._secure_directory(self._directory)
            current = self._directory / f"{name}.jsonl"
            if (
                current.exists()
                and current.stat().st_size + len(line) > self._max_bytes
            ):
                self._rotate(name)
            with current.open("ab") as handle:
                handle.write(line)
            self._prune(name, now)

    def _rotated(self, name: str, index: int) -> Path:
        return self._directory / f"{name}.{index}.jsonl"

    def _rotate(self, name: str) -> None:
        oldest = self._rotated(name, self._keep_files - 1)
        if oldest.exists():
            oldest.unlink()
        for index in range(self._keep_files - 2, 0, -1):
            source = self._rotated(name, index)
            if source.exists():
                source.replace(self._rotated(name, index + 1))
        (self._directory / f"{name}.jsonl").replace(self._rotated(name, 1))

    def _prune(self, name: str, now: float) -> None:
        for index in range(1, self._keep_files):
            path = self._rotated(name, index)
            if path.exists() and now - path.stat().st_mtime > self._retention_seconds:
                path.unlink()
