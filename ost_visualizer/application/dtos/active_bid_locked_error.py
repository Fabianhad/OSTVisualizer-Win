import uuid
from .collaboration_dtos import (
    BID_LOCKED_MESSAGE,
    MutationOutcomeStatus,
    MutationRejectionReason,
    QueuedMutationResult,
)


class ActiveBidLockedError(RuntimeError):
    def __init__(self, message: str = BID_LOCKED_MESSAGE) -> None:
        super().__init__(message)


def locked_bid_refusal_result(database_id: str) -> QueuedMutationResult:
    return QueuedMutationResult(
        database_id=database_id,
        runtime_generation=0,
        operation_id=str(uuid.uuid4()),
        outcome_status=MutationOutcomeStatus.REJECTED,
        message=str(ActiveBidLockedError()),
        rejection_reason=MutationRejectionReason.BID_LOCKED,
    )
