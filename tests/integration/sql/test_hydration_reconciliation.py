import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG,
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
    SUPPORTED_REMOTE_RESOURCE_TYPES,
    CollaborationResourceFamily,
    coalesced_resource_type,
)
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
from ost_visualizer.application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ost_visualizer.application.services.local_draft_registry import LocalDraftRegistry
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.sql.remote_change_reader import (
    _MAX_HYDRATION_BATCH_PARAMETERS,
    _MAX_HYDRATION_BATCH_QUERIES,
    SqlRemoteChangeReader,
    _execute_recorded_queries,
    _recorded_query_batches,
)
from tests.helpers.sql.collaboration import (
    _EventBus,
    _ProjectData,
    _TokenReader,
    _batch,
    _change,
    _token_service,
)


class HydrationReconciliationCollaborationTests(unittest.TestCase):
    def test_remote_cover_sheet_hydration_carries_delete_confirmation_snapshot(self):
        cover_sheet = object()

        class _Reader:
            @staticmethod
            def _parse_cover_sheet_data(_connection, bid_uid):
                self.assertEqual(bid_uid, "8")
                return cover_sheet

            @staticmethod
            def _parse_pages_with_delete_content(_connection, bid_uid):
                self.assertEqual(bid_uid, "8")
                return {"page-1"}

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("cover_sheet", "8", 8),
                    2,
                ),
            ),
        )
        hydrated = remote_reader.hydrate_connection(batch, object())
        self.assertIs(hydrated.cover_sheet_by_bid[8], cover_sheet)
        self.assertEqual(
            hydrated.page_delete_content_uids_by_bid[8], frozenset({"page-1"})
        )
        project_data = _ProjectData("database")
        tokens, drafts = _token_service()
        service = RemoteChangeReconciliationService(
            project_data,
            _EventBus(),
            tokens,
            drafts,
            ConflictResolutionService(),
        )
        self.assertTrue(service.apply(hydrated).applied)
        self.assertIs(project_data.cover_sheets[("database", "8")], cover_sheet)
        self.assertEqual(
            project_data.page_delete_content[("database", "8")],
            frozenset({"page-1"}),
        )
