from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Dict, List


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def deduplicate_entries(entries: List[FileEntry]) -> List[FileEntry]:
    seen: Dict[str, int] = {}
    result: List[FileEntry] = []
    for entry in entries:
        norm = entry.normalized_path
        if norm in seen:
            idx = seen[norm]
            if entry.is_checked and not result[idx].is_checked:
                result[idx] = FileEntry(result[idx].file_path, is_checked=True)
        else:
            seen[norm] = len(result)
            result.append(entry)
    return result


@dataclass
class FileEntry:
    file_path: str
    is_checked: bool = True

    @property
    def normalized_path(self) -> str:
        return normalize_path(self.file_path)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "is_checked": self.is_checked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileEntry:
        return cls(
            file_path=str(data.get("file_path", "")),
            is_checked=bool(data.get("is_checked", True)),
        )


@dataclass
class FileState:
    file_entries: List[FileEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_entries": [entry.to_dict() for entry in self.file_entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileState:
        state = cls()
        if not data:
            return state
        if "file_entries" in data and isinstance(data["file_entries"], list):
            raw = [
                (
                    FileEntry.from_dict(entry)
                    if isinstance(entry, dict)
                    else FileEntry(file_path=str(entry))
                )
                for entry in data["file_entries"]
            ]
            state.file_entries = deduplicate_entries(raw)
        return state

    def get_checked_files(self) -> List[str]:
        return [entry.file_path for entry in self.file_entries if entry.is_checked]

    def contains_path(self, file_path: str) -> bool:
        norm = normalize_path(file_path)
        return any(e.normalized_path == norm for e in self.file_entries)

    def clear(self) -> None:
        self.file_entries.clear()
