import json
import os
import re
import uuid
from pathlib import Path
from ....domain.entities.ai_takeoff import (
    BID_KEY_LENGTH,
    SIDECAR_LOAD_CORRUPT,
    SIDECAR_LOAD_FOUND,
    SIDECAR_LOAD_MISSING,
    AiTakeoffSidecar,
    SidecarLoad,
)

MAX_SIDECAR_BYTES = 5 * 1024 * 1024
_BID_KEY_PATTERN = re.compile(rf"[0-9a-f]{{{BID_KEY_LENGTH}}}")


class JsonAiTakeoffSidecarRepository:
    def __init__(self, directory: Path):
        self._directory = Path(directory)

    def load(self, bid_key: str) -> SidecarLoad:
        path = self._path(bid_key)
        try:
            if path.stat().st_size > MAX_SIDECAR_BYTES:
                return SidecarLoad(SIDECAR_LOAD_CORRUPT)
            raw = path.read_bytes()
        except FileNotFoundError:
            return SidecarLoad(SIDECAR_LOAD_MISSING)
        except OSError:
            return SidecarLoad(SIDECAR_LOAD_CORRUPT)
        try:
            sidecar = AiTakeoffSidecar.from_dict(json.loads(raw.decode("utf-8")))
        except (UnicodeError, ValueError):
            return SidecarLoad(SIDECAR_LOAD_CORRUPT)
        if sidecar.bid_key != bid_key:
            return SidecarLoad(SIDECAR_LOAD_CORRUPT)
        return SidecarLoad(SIDECAR_LOAD_FOUND, sidecar)

    def save(self, sidecar: AiTakeoffSidecar) -> None:
        path = self._path(sidecar.bid_key)
        payload = (
            json.dumps(sidecar.to_dict(), indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_SIDECAR_BYTES:
            raise ValueError("The sidecar is larger than the 5 MB limit")
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _path(self, bid_key: str) -> Path:
        if not isinstance(bid_key, str) or not _BID_KEY_PATTERN.fullmatch(bid_key):
            raise ValueError("Invalid sidecar key")
        return self._directory / f"{bid_key}.json"
