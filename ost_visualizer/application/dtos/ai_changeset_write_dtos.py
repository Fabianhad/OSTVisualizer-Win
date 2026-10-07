from dataclasses import dataclass
from typing import Optional, Tuple
from .create_condition_spec_dto import CreateConditionSpec


@dataclass(frozen=True)
class AppliedChangeset:
    folder_uid: Optional[str] = None
    created_folder: bool = False
    condition_uids: Tuple[str, ...] = ()
    takeoff_uids: Tuple[str, ...] = ()
    page_uid: Optional[str] = None
    previous_scale: Optional[Tuple[float, float]] = None
    previous_positions: Tuple[Tuple[str, Tuple[float, ...]], ...] = ()
    resulting_tokens: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class AiTakeoffWrite:
    condition_key: str
    page_uid: str
    position: Tuple[float, ...]
    holes: Tuple[Tuple[float, ...], ...] = ()
    area_uid: Optional[str] = None


@dataclass(frozen=True)
class AiChangesetWritePlan:
    folder_name: str
    existing_folder_uid: Optional[str]
    conditions: Tuple[Tuple[str, CreateConditionSpec], ...]
    takeoffs: Tuple[AiTakeoffWrite, ...]
    existing_condition_uids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AiChangesetWriteResult:
    folder_uid: Optional[str]
    created_folder: bool
    condition_uids: Tuple[Tuple[str, str], ...]
    takeoff_uids: Tuple[str, ...]


@dataclass(frozen=True)
class AiChangesetUndoPlan:
    takeoff_uids: Tuple[str, ...]
    condition_uids: Tuple[str, ...]
    folder_uid: Optional[str] = None


@dataclass(frozen=True)
class AiScaleUndoPlan:
    page_uid: str
    scale_factor1: float
    scale_factor2: float
    positions: Tuple[Tuple[str, Tuple[float, ...]], ...]


@dataclass(frozen=True)
class AiChangesetCommit:
    committed: bool
    result: Optional[AiChangesetWriteResult] = None
    message: str = ""
    locked: bool = False
    conflict: bool = False
