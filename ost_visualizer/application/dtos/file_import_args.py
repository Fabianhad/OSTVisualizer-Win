from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
from ...shared.texts import (
    FILE_IMPORT_ARGS_MESSAGE_FILE_DOES_NOT_EXIST,
    FILE_IMPORT_ARGS_MESSAGE_UNSUPPORTED_FILE_TYPE_ONLY_OST_AND,
)

PROJECT_IMPORT_EXTENSION_OST = ".ost"
PROJECT_IMPORT_EXTENSION_OSP = ".osp"
SUPPORTED_PROJECT_IMPORT_EXTENSIONS = frozenset(
    {PROJECT_IMPORT_EXTENSION_OST, PROJECT_IMPORT_EXTENSION_OSP}
)


@dataclass(frozen=True)
class ParsedProjectFileArg:
    path: str
    extension: str


@dataclass(frozen=True)
class RejectedProjectFileArg:
    value: str
    reason: str


@dataclass(frozen=True)
class ProjectFileArgs:
    files: List[ParsedProjectFileArg] = field(default_factory=list)
    rejected: List[RejectedProjectFileArg] = field(default_factory=list)

    @property
    def has_file_args(self) -> bool:
        return bool(self.files or self.rejected)


def parse_project_file_args(argv: Iterable[str]) -> ProjectFileArgs:
    files: List[ParsedProjectFileArg] = []
    rejected: List[RejectedProjectFileArg] = []
    for raw_arg in list(argv):
        if raw_arg.startswith("-"):
            continue
        raw_value = str(raw_arg)
        path = Path(raw_value).expanduser().resolve(strict=False)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_PROJECT_IMPORT_EXTENSIONS:
            rejected.append(
                RejectedProjectFileArg(
                    value=raw_value,
                    reason=(
                        FILE_IMPORT_ARGS_MESSAGE_UNSUPPORTED_FILE_TYPE_ONLY_OST_AND
                    ),
                )
            )
            continue
        if not path.is_file():
            rejected.append(
                RejectedProjectFileArg(
                    value=str(path),
                    reason=FILE_IMPORT_ARGS_MESSAGE_FILE_DOES_NOT_EXIST,
                )
            )
            continue
        files.append(ParsedProjectFileArg(path=str(path), extension=suffix))
    return ProjectFileArgs(
        files=files,
        rejected=rejected,
    )
