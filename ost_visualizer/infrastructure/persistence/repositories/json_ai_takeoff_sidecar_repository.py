import json
import re
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
        if not isinstance(bid_key, str) or not _BID_KEY_PATTERN.fullmatch(bid_key):
            raise ValueError("Invalid sidecar key")
        path = self._directory / f"{bid_key}.json"
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
