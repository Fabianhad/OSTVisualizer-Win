import uuid
from .collaboration_dtos import MutationOutcomeStatus, QueuedMutationResult


def queue_submission_failure_result(
    database_id: str, error: BaseException
) -> QueuedMutationResult:
    return QueuedMutationResult(
        database_id=database_id,
        runtime_generation=0,
        operation_id=str(uuid.uuid4()),
        outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        message=str(error) or type(error).__name__,
    )
