import errno
import logging
import os
import stat
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from pathlib import PureWindowsPath
from ...shared.texts import (
    PATH_PROBE_MESSAGE_ACCESS_IS_DENIED,
    PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS,
    PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS_NO_LOCATION,
    PATH_PROBE_MESSAGE_CANNOT_ACCESS_THE_FILE,
    PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE,
    PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE_NO_LOCATION,
    PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST,
    PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST_NO_LOCATION,
    PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED,
    PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED_NO_LOCATION,
    PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND,
    PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND_NO_LOCATION,
    PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND,
    PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND_NO_LOCATION,
)

logger = logging.getLogger(__name__)
_stat_file = os.stat
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP})
_MISSING_WINERRORS = frozenset({2, 3, 21, 123, 1921})
_INACCESSIBLE_REASONS = {
    5: (PATH_PROBE_MESSAGE_ACCESS_IS_DENIED, PATH_PROBE_MESSAGE_ACCESS_IS_DENIED),
    53: (
        PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND,
        PATH_PROBE_MESSAGE_THE_NETWORK_PATH_WAS_NOT_FOUND_NO_LOCATION,
    ),
    64: (
        PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST,
        PATH_PROBE_MESSAGE_THE_NETWORK_CONNECTION_WAS_LOST_NO_LOCATION,
    ),
    67: (
        PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND,
        PATH_PROBE_MESSAGE_THE_NETWORK_SHARE_WAS_NOT_FOUND_NO_LOCATION,
    ),
    1219: (
        PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS,
        PATH_PROBE_MESSAGE_ALREADY_CONNECTED_WITH_DIFFERENT_CREDENTIALS_NO_LOCATION,
    ),
    1311: (
        PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE,
        PATH_PROBE_MESSAGE_NO_LOGON_SERVER_IS_AVAILABLE_NO_LOCATION,
    ),
    1326: (
        PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED,
        PATH_PROBE_MESSAGE_THE_NETWORK_CREDENTIALS_WERE_REJECTED_NO_LOCATION,
    ),
}
_MAX_KNOWN_INACCESSIBLE_PATHS = 1024
_inaccessible_reasons: "OrderedDict[str, str]" = OrderedDict()
_inaccessible_lock = threading.Lock()


class PathProbeState(str, Enum):
    EXISTS = "exists"
    MISSING = "missing"
    INACCESSIBLE = "inaccessible"


@dataclass(frozen=True)
class PathProbeResult:
    state: PathProbeState
    is_file: bool = False
    size: int = 0
    reason: str = ""

    @property
    def exists(self) -> bool:
        return self.state is PathProbeState.EXISTS


def probe_path(path) -> PathProbeResult:
    if not path:
        return PathProbeResult(PathProbeState.MISSING)
    try:
        text = os.fspath(path)
        result = _stat_file(text)
    except ValueError:
        return PathProbeResult(PathProbeState.MISSING)
    except OSError as exc:
        winerror = exc.winerror if sys.platform == "win32" else None
        if winerror not in _INACCESSIBLE_REASONS and (
            exc.errno in _MISSING_ERRNOS or winerror in _MISSING_WINERRORS
        ):
            _forget_inaccessible(text)
            return PathProbeResult(PathProbeState.MISSING)
        return _inaccessible(
            text,
            winerror,
            exc.strerror or type(exc).__name__,
            f"WinError {winerror}" if winerror is not None else type(exc).__name__,
        )
    except Exception as exc:
        name = type(exc).__name__
        return _inaccessible(str(path), None, name, name)
    _forget_inaccessible(text)
    return PathProbeResult(
        PathProbeState.EXISTS,
        is_file=stat.S_ISREG(result.st_mode),
        size=int(result.st_size),
    )


def known_inaccessible_reason(path) -> str:
    if not path:
        return ""
    with _inaccessible_lock:
        return _inaccessible_reasons.get(_path_key(os.fspath(path)), "")


def _inaccessible(text: str, winerror, system_text: str, cause: str) -> PathProbeResult:
    templates = _INACCESSIBLE_REASONS.get(winerror)
    if templates is None:
        reason = PATH_PROBE_MESSAGE_CANNOT_ACCESS_THE_FILE.format(
            system_reason=system_text
        )
    else:
        location = _location(text)
        with_location, without_location = templates
        reason = (
            with_location.format(location=location) if location else without_location
        )
    key = _path_key(text)
    with _inaccessible_lock:
        already_reported = _inaccessible_reasons.get(key) == reason
        _inaccessible_reasons[key] = reason
        _inaccessible_reasons.move_to_end(key)
        while len(_inaccessible_reasons) > _MAX_KNOWN_INACCESSIBLE_PATHS:
            _inaccessible_reasons.popitem(last=False)
    if not already_reported:
        logger.warning("Cannot access %s (%s): %s", text, cause, reason)
    return PathProbeResult(PathProbeState.INACCESSIBLE, reason=reason)


def _forget_inaccessible(text: str) -> None:
    with _inaccessible_lock:
        _inaccessible_reasons.pop(_path_key(text), None)


def _path_key(text: str) -> str:
    return os.path.normcase(text)


def _location(text: str) -> str:
    drive = PureWindowsPath(text).drive
    if drive.startswith("\\\\"):
        parts = [part for part in drive.split("\\") if part]
        if parts[:2] == ["?", "UNC"]:
            parts = parts[2:]
        if parts:
            return "\\\\" + parts[0]
    return drive
