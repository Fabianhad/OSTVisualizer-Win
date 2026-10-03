import unittest
import uuid
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
    locked_bid_refusal_result,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    BID_LOCKED_MESSAGE,
    MutationOutcomeStatus,
    MutationRejectionReason,
    rejection_reason_message,
)


class ActiveBidLockedErrorTests(unittest.TestCase):
    def test_default_message_matches_the_access_update_failure_text(self):
        # update_condition reports the same block as "The active bid is locked".
        self.assertEqual(str(ActiveBidLockedError()), "The active bid is locked")
        self.assertEqual(str(ActiveBidLockedError("custom")), "custom")

    def test_is_a_runtime_error_but_not_a_value_error(self):
        # Callers that only know the generic queue rejections (RuntimeError) still
        # present it; ValueError is the invalid-request channel and must not match.
        self.assertIsInstance(ActiveBidLockedError(), RuntimeError)
        self.assertNotIsInstance(ActiveBidLockedError(), ValueError)

    def test_refusal_result_is_a_fresh_rejected_result_that_attempted_no_commit(self):
        # Callers feed this to their own completion callback, so it must look like any
        # rejected write: REJECTED, nothing committed, no authoritative data, and a
        # distinct valid operation id per refusal (completions are keyed by it).
        first = locked_bid_refusal_result("database")
        second = locked_bid_refusal_result("database")
        self.assertEqual(first.database_id, "database")
        self.assertEqual(first.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(first.message, "The active bid is locked")
        self.assertIs(first.commit_attempted, False)
        self.assertIsNone(first.authoritative_result)
        self.assertIsNone(first.conflict)
        self.assertEqual(first.created_resource_ids, ())
        self.assertEqual(str(uuid.UUID(first.operation_id)), first.operation_id)
        self.assertNotEqual(first.operation_id, second.operation_id)

    def test_the_queue_time_refusal_carries_the_same_reason_as_the_writer_refusal(self):
        # Decision B2: the client-side refusal and the SQL writer's refusal must be
        # indistinguishable to a completion callback (REJECTED + bid_locked, one
        # shared message constant), so a handler needs one branch for both.
        refusal = locked_bid_refusal_result("database")
        self.assertIs(refusal.rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertEqual(refusal.rejection_reason, "bid_locked")
        self.assertEqual(refusal.message, BID_LOCKED_MESSAGE)
        self.assertEqual(
            refusal.message,
            rejection_reason_message(MutationRejectionReason.BID_LOCKED),
        )
        self.assertEqual(str(ActiveBidLockedError()), BID_LOCKED_MESSAGE)
