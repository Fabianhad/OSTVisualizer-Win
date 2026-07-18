from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Dict, List
from .database_descriptor import DatabaseBackend, DatabaseDescriptor


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def deduplicate_entries(entries: List[FileEntry]) -> List[FileEntry]:
    seen: Dict[str, int] = {}
    result: List[FileEntry] = []
    for entry in entries:
        norm = entry.identity_key
        if norm in seen:
            idx = seen[norm]
            if entry.is_checked and not result[idx].is_checked:
                result[idx] = result[idx].with_checked(True)
        else:
            seen[norm] = len(result)
            result.append(entry)
    return result


@dataclass(init=False)
class FileEntry:
    descriptor: DatabaseDescriptor
    is_checked: bool

    def __init__(
        self,
        file_path: str = "",
        is_checked: bool = True,
        descriptor: DatabaseDescriptor | None = None,
    ) -> None:
        self.descriptor = descriptor or DatabaseDescriptor.for_access(file_path)
        self.is_checked = is_checked

    @property
    def file_path(self) -> str:
        return self.descriptor.access_path

    @classmethod
    def for_descriptor(
        cls, descriptor: DatabaseDescriptor, *, is_checked: bool = True
    ) -> FileEntry:
        return cls(
            is_checked=is_checked,
            descriptor=descriptor,
        )

    @property
    def database_id(self) -> str:
        return self.descriptor.database_id

    @property
    def backend(self) -> DatabaseBackend:
        return self.descriptor.backend

    @property
    def identity_key(self) -> str:
        if self.backend == DatabaseBackend.ACCESS:
            return f"access:{self.normalized_path}"
        return f"sql_server:{self.database_id.casefold()}"

    @property
    def normalized_path(self) -> str:
        if self.backend != DatabaseBackend.ACCESS:
            return self.database_id.casefold()
        return normalize_path(self.file_path)

    @property
    def runtime_locator(self) -> str:
        if self.backend == DatabaseBackend.ACCESS:
            return self.file_path
        return self.database_id

    def with_checked(self, checked: bool) -> FileEntry:
        return FileEntry.for_descriptor(self.descriptor, is_checked=checked)

    def to_dict(self) -> dict:
        return {
            "descriptor": self.descriptor.to_dict(),
            "is_checked": self.is_checked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileEntry:
        descriptor_data = data.get("descriptor")
        if isinstance(descriptor_data, dict):
            if set(data) != {"descriptor", "is_checked"}:
                raise ValueError("Saved database entry has an unsupported format")
            return cls.for_descriptor(
                DatabaseDescriptor.from_dict(descriptor_data),
                is_checked=_saved_checked(data),
            )
        if set(data) != {"file_path", "is_checked"}:
            raise ValueError("Saved Access database entry has an unsupported format")
        file_path = data.get("file_path")
        if not isinstance(file_path, str):
            raise ValueError("Saved Access database file_path value is invalid")
        return cls(
            file_path=file_path,
            is_checked=_saved_checked(data),
        )


@dataclass
class FileState:
    file_entries: List[FileEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": 2,
            "database_entries": [entry.to_dict() for entry in self.file_entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileState:
        state = cls()
        if not data:
            return state
        entries_data = data.get("database_entries")
        if isinstance(entries_data, list):
            if data.get("version") != 2:
                raise ValueError("Saved database entries use an unsupported version")
        else:
            entries_data = data.get("file_entries")
        if isinstance(entries_data, list):
            raw = [
                (
                    FileEntry.from_dict(entry)
                    if isinstance(entry, dict)
                    else FileEntry(file_path=str(entry))
                )
                for entry in entries_data
            ]
            state.file_entries = deduplicate_entries(raw)
        return state

    def get_checked_files(self) -> List[str]:
        return [
            entry.file_path
            for entry in self.file_entries
            if entry.is_checked and entry.backend == DatabaseBackend.ACCESS
        ]

    def contains_path(self, file_path: str) -> bool:
        norm = normalize_path(file_path)
        return any(e.normalized_path == norm for e in self.file_entries)

    def clear(self) -> None:
        self.file_entries.clear()


def _saved_checked(data: dict) -> bool:
    checked = data.get("is_checked")
    if not isinstance(checked, bool):
        raise ValueError("Saved database checked state is invalid")
    return checked
