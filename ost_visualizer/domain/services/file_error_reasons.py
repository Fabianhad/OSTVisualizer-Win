import errno
import sys
from typing import Optional
from ...shared.texts import (
    FILE_ERROR_REASONS_MESSAGE_ACCESS_TO_THE_FILE_WAS_DENIED,
    FILE_ERROR_REASONS_MESSAGE_THE_DESTINATION_FOLDER_WAS_NOT_FOUND,
    FILE_ERROR_REASONS_MESSAGE_THE_FILE_IS_OPEN_IN_ANOTHER,
    FILE_ERROR_REASONS_MESSAGE_THE_FILE_WAS_NOT_FOUND,
    FILE_ERROR_REASONS_MESSAGE_THE_NETWORK_LOCATION_IS_NOT_AVAILABLE,
    FILE_ERROR_REASONS_MESSAGE_THERE_IS_NOT_ENOUGH_SPACE,
)

_IN_USE_WINERRORS = frozenset({32, 33})
_MISSING_WINERRORS = frozenset({2, 3})
_DENIED_WINERRORS = frozenset({5})
_DISK_FULL_WINERRORS = frozenset({39, 112})
_NETWORK_WINERRORS = frozenset({53, 64, 67})


def file_error_reason(error: BaseException) -> Optional[str]:
    if not isinstance(error, OSError):
        return None
    winerror = error.winerror if sys.platform == "win32" else None
    if winerror in _IN_USE_WINERRORS:
        return FILE_ERROR_REASONS_MESSAGE_THE_FILE_IS_OPEN_IN_ANOTHER
    if winerror in _NETWORK_WINERRORS:
        return FILE_ERROR_REASONS_MESSAGE_THE_NETWORK_LOCATION_IS_NOT_AVAILABLE
    if (
        isinstance(error, FileNotFoundError)
        or winerror in _MISSING_WINERRORS
        or (winerror is None and error.errno == errno.ENOENT)
    ):
        return FILE_ERROR_REASONS_MESSAGE_THE_FILE_WAS_NOT_FOUND
    if (
        isinstance(error, PermissionError)
        or winerror in _DENIED_WINERRORS
        or (winerror is None and error.errno == errno.EACCES)
    ):
        return FILE_ERROR_REASONS_MESSAGE_ACCESS_TO_THE_FILE_WAS_DENIED
    if winerror in _DISK_FULL_WINERRORS or (
        winerror is None and error.errno == errno.ENOSPC
    ):
        return FILE_ERROR_REASONS_MESSAGE_THERE_IS_NOT_ENOUGH_SPACE
    return None


def file_write_error_reason(error: BaseException) -> Optional[str]:
    reason = file_error_reason(error)
    if reason == FILE_ERROR_REASONS_MESSAGE_THE_FILE_WAS_NOT_FOUND:
        return FILE_ERROR_REASONS_MESSAGE_THE_DESTINATION_FOLDER_WAS_NOT_FOUND
    return reason


def describe_write_failure(
    error: BaseException, reason_template: str, generic: str
) -> str:
    reason = file_write_error_reason(error)
    return reason_template.format(reason=reason) if reason else generic


def describe_failure(error: BaseException, reason_template: str, generic: str) -> str:
    reason = file_error_reason(error)
    return reason_template.format(reason=reason) if reason else generic


def user_failure_message(error: BaseException, fallback: str) -> str:
    return file_error_reason(error) or fallback
