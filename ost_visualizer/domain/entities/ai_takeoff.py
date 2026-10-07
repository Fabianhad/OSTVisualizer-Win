import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from .database_descriptor import DatabaseBackend

SIDECAR_SCHEMA_VERSION = 1
ASSUMPTION_STATUSES = ("open", "accepted", "overridden")
ASSUMPTION_IMPACTS = ("high", "normal")
FINGERPRINT_OK = "ok"
FINGERPRINT_REBIND_REQUIRED = "rebind_required"
FINGERPRINT_MISMATCH = "fingerprint_mismatch"
SIDECAR_LOAD_FOUND = "found"
SIDECAR_LOAD_MISSING = "missing"
SIDECAR_LOAD_CORRUPT = "corrupt"
BID_KEY_LENGTH = 32
_UID_PATTERN = re.compile(r"[A-Za-z0-9_.:{}-]{1,128}")
_SIDECAR_KEYS = {
    "schema_version",
    "bid_key",
    "fingerprint",
    "levels",
    "registrations",
    "assumptions",
}


def ai_takeoff_bid_key(
    backend: DatabaseBackend, bid_uid: str, database_guid: Optional[str] = ""
) -> Optional[str]:
    bid = str(bid_uid or "").strip()
    if not bid:
        return None
    if backend == DatabaseBackend.SQL_SERVER:
        guid = str(database_guid or "").strip().lower()
        if not guid:
            return None
        identity = f"{backend.value}|{guid}|{bid}"
    else:
        identity = f"{backend.value}|{bid}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:BID_KEY_LENGTH]


SIDECAR_BID_CHANGED = "bid_changed"


class SidecarWriteRefused(Exception):
    def __init__(self, status: str):
        super().__init__(f"The AI sidecar is {status}; nothing was written.")
        self.status = status


@dataclass(frozen=True)
class SidecarFingerprint:
    database_id: str
    bid_name: str
    page_count: int
    first_page_pdf_source: str

    @classmethod
    def from_dict(cls, data: Any) -> "SidecarFingerprint":
        values = _exact(
            data,
            {"database_id", "bid_name", "page_count", "first_page_pdf_source"},
            "fingerprint",
        )
        return cls(
            database_id=_text(values, "database_id"),
            bid_name=_text(values, "bid_name"),
            page_count=_integer(values, "page_count"),
            first_page_pdf_source=_text(values, "first_page_pdf_source"),
        )

    def to_dict(self) -> dict:
        return {
            "database_id": self.database_id,
            "bid_name": self.bid_name,
            "page_count": self.page_count,
            "first_page_pdf_source": self.first_page_pdf_source,
        }


def compare_fingerprints(
    stored: SidecarFingerprint, current: SidecarFingerprint
) -> str:
    if stored.database_id == current.database_id:
        return FINGERPRINT_OK
    if stored.bid_name == current.bid_name and stored.page_count == current.page_count:
        return FINGERPRINT_REBIND_REQUIRED
    return FINGERPRINT_MISMATCH


@dataclass(frozen=True)
class Level:
    uid: str
    name: str
    top_elev_in: float

    @classmethod
    def from_dict(cls, data: Any) -> "Level":
        values = _exact(data, {"uid", "name", "top_elev_in"}, "level")
        return cls(
            uid=_uid(values, "uid"),
            name=_text(values, "name"),
            top_elev_in=_number(values, "top_elev_in"),
        )

    def to_dict(self) -> dict:
        return {"uid": self.uid, "name": self.name, "top_elev_in": self.top_elev_in}


@dataclass(frozen=True)
class SheetRegistration:
    page_uid: str
    level_uid: str
    transform: tuple
    residual_in: float

    @classmethod
    def from_dict(cls, data: Any) -> "SheetRegistration":
        values = _exact(
            data, {"page_uid", "level_uid", "transform", "residual_in"}, "registration"
        )
        transform = values["transform"]
        if not isinstance(transform, list) or len(transform) != 6:
            raise ValueError("registration transform must have six numbers")
        return cls(
            page_uid=_uid(values, "page_uid"),
            level_uid=_uid(values, "level_uid"),
            transform=tuple(_finite(value, "transform") for value in transform),
            residual_in=_number(values, "residual_in"),
        )

    def to_dict(self) -> dict:
        return {
            "page_uid": self.page_uid,
            "level_uid": self.level_uid,
            "transform": list(self.transform),
            "residual_in": self.residual_in,
        }


@dataclass(frozen=True)
class Assumption:
    uid: str
    value: str
    reason: str
    sheet_ref: str
    impact: str
    status: str

    @classmethod
    def from_dict(cls, data: Any) -> "Assumption":
        values = _exact(
            data,
            {"uid", "value", "reason", "sheet_ref", "impact", "status"},
            "assumption",
        )
        impact = _text(values, "impact")
        status = _text(values, "status")
        if impact not in ASSUMPTION_IMPACTS:
            raise ValueError("unknown assumption impact")
        if status not in ASSUMPTION_STATUSES:
            raise ValueError("unknown assumption status")
        return cls(
            uid=_uid(values, "uid"),
            value=_text(values, "value"),
            reason=_text(values, "reason"),
            sheet_ref=_text(values, "sheet_ref"),
            impact=impact,
            status=status,
        )

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "value": self.value,
            "reason": self.reason,
            "sheet_ref": self.sheet_ref,
            "impact": self.impact,
            "status": self.status,
        }


@dataclass(frozen=True)
class AiTakeoffSidecar:
    bid_key: str
    fingerprint: SidecarFingerprint
    levels: tuple = ()
    registrations: tuple = ()
    assumptions: tuple = ()
    schema_version: int = SIDECAR_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: Any) -> "AiTakeoffSidecar":
        values = _exact(data, _SIDECAR_KEYS, "sidecar")
        if _integer(values, "schema_version") != SIDECAR_SCHEMA_VERSION:
            raise ValueError("unsupported sidecar schema version")
        return cls(
            bid_key=_text(values, "bid_key"),
            fingerprint=SidecarFingerprint.from_dict(values["fingerprint"]),
            levels=tuple(Level.from_dict(item) for item in _items(values, "levels")),
            registrations=tuple(
                SheetRegistration.from_dict(item)
                for item in _items(values, "registrations")
            ),
            assumptions=tuple(
                Assumption.from_dict(item) for item in _items(values, "assumptions")
            ),
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "bid_key": self.bid_key,
            "fingerprint": self.fingerprint.to_dict(),
            "levels": [level.to_dict() for level in self.levels],
            "registrations": [item.to_dict() for item in self.registrations],
            "assumptions": [item.to_dict() for item in self.assumptions],
        }


@dataclass(frozen=True)
class SidecarLoad:
    state: str
    sidecar: Optional[AiTakeoffSidecar] = None


def _exact(data: Any, keys: set, label: str) -> Mapping:
    if not isinstance(data, Mapping) or set(data) != keys:
        raise ValueError(f"{label} has unexpected fields")
    return data


def _items(values: Mapping, key: str) -> list:
    items = values[key]
    if not isinstance(items, list):
        raise ValueError(f"{key} must be a list")
    return items


def _text(values: Mapping, key: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def _uid(values: Mapping, key: str) -> str:
    value = _text(values, key)
    if not _UID_PATTERN.fullmatch(value):
        raise ValueError(f"{key} must be a short identifier")
    return value


def _integer(values: Mapping, key: str) -> int:
    value = values[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _number(values: Mapping, key: str) -> float:
    return _finite(values[key], key)


def _finite(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} must be finite")
    return number
