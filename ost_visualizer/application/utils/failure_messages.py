from ...domain.services.file_error_reasons import describe_failure
from ...shared.texts import (
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_AN_UNEXPECTED_ERROR_STOPPED_DATABASE,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_FAILED_REASON,
)


def maintenance_failure_message(error: BaseException) -> str:
    if isinstance(error, RuntimeError) and str(error).strip():
        return str(error)
    return describe_failure(
        error,
        DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_FAILED_REASON,
        DATABASE_MAINTENANCE_SERVICE_MESSAGE_AN_UNEXPECTED_ERROR_STOPPED_DATABASE,
    )
