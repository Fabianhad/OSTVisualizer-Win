import logging
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationExecutionResult,
    MutationOutcomeStatus,
    MutationRejectionReason,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    UIAccessManager,
)
from ost_visualizer.presentation.services.undo_redo_service import (
    MutationHistoryState,
    UndoRedoService,
)
from tests.application.services.test_sql_collaboration_coordinator import (
    _SqlCollaborationCoordinatorCollaborationFixture,
)
from tests.application.services.write_permission_support import (
    _DatabaseCapability,
    _EventBus,
    _ProjectData,
    _TransactionMonitor,
)
from tests.helpers.sql.collaboration import _LockingStore, _queue_test_mutation
from tests.presentation.managers.permission_support import _License, _UiState

_UI_LOGGER = "ost_visualizer.presentation.coordinators.ui_event_coordinator"


class BidLockedRejectionChainTests(_SqlCollaborationCoordinatorCollaborationFixture):
    """Decision B4 end to end: the REAL SqlCollaborationCoordinator work loop delivers
    writes the SQL writer refused with REJECTED / bid_locked to a REAL undo history
    entry and to plain callbacks, publishes the coordinator's notice on a REAL event
    bus, and the REAL UIEventCoordinator handler logs one warning per refusal,
    re-resolves the lock flag ONCE for the whole burst and makes the REAL
    UIAccessManager disable the Bid's content edits; the history entry returns to
    READY and replays, no synchronization conflict is published. Fakes: the work
    callables return the writer's REJECTED result (the writer is covered in
    test_writer), the store, the project data and the main window."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _wire(self):
        bus = EventBus()
        published = []
        original_publish = bus.publish

        def recording_publish(event, **payload):
            published.append(event)
            original_publish(event, **payload)

        bus.publish = recording_publish
        coordinator, runtime = self.ready_coordinator(
            store=_LockingStore(), event_bus=bus
        )
        bid_ref = BidRef(runtime.database_id, "7")
        status = {"uid": "1"}
        resolves = []

        class ProjectData(_ProjectData):
            def __init__(self):
                super().__init__()
                self.bid_ref = bid_ref

            def get_bid(self, requested):
                if requested != bid_ref:
                    return None
                return SimpleNamespace(uid="7", status_uid=status["uid"])

            def get_job_status_snapshot(self, _database_id):
                resolves.append(status["uid"])
                return [
                    JobStatus(uid="1", name="Open", locked=False),
                    JobStatus(uid="2", name="Awarded", locked=True),
                ]

            def set_current_bid_locked(self, locked):
                self.locked = locked

            def get_current_file_path(self):
                return bid_ref.file_path

        project_data = ProjectData()
        access = UIAccessManager(
            _EventBus(),
            _License(),
            _TransactionMonitor(),
            project_data,
            _UiState(bid_ref),
            _DatabaseCapability(),
        )
        menu_updates = []
        ui = UIEventCoordinator.__new__(UIEventCoordinator)
        ui._is_cleaning_up = False
        ui._bid_lock_reverify_scheduled = set()
        ui._bid_lock_watch = set()
        ui.project_data = project_data
        ui.ui_access_manager = access
        ui._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True
        )
        ui._update_menu_state = lambda: menu_updates.append(True)
        bus.subscribe(AppEvents.BID_LOCKED_REJECTION, ui._on_bid_locked_rejection)
        return SimpleNamespace(
            bus=bus,
            published=published,
            coordinator=coordinator,
            runtime=runtime,
            bid_ref=bid_ref,
            status=status,
            resolves=resolves,
            project_data=project_data,
            access=access,
            menu_updates=menu_updates,
        )

    @staticmethod
    def _bid_locked_work():
        return MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="The database rejected the project update.",
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )

    def _spin(self):
        for _ in range(3):
            self.app.processEvents()

    def test_a_burst_of_stale_lock_rejections_reverts_logs_and_locks_the_ui_once(self):
        wired = self._wire()
        coordinator, runtime = wired.coordinator, wired.runtime
        history = UndoRedoService()
        history.set_active_bid(wired.bid_ref)
        results = []

        def undo_submit(complete):
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "7", 7),),
                self._bid_locked_work,
                complete,
                operation_id="history-undo",
            )

        history.push(undo_submit, lambda complete: None)
        entry = history._undo_stack[-1]
        self.assertTrue(wired.access.is_allowed(Feature.EDIT_CONDITION))
        # the stale-flag situation: another client locked the Bid, the memory knows it
        wired.status["uid"] = "2"
        self.assertFalse(wired.project_data.locked)
        history.undo()
        for index in range(3):
            _queue_test_mutation(
                coordinator,
                runtime.database_id,
                (ResourceRef("takeoffs_collection", "7", 7),),
                self._bid_locked_work,
                results.append,
                operation_id=f"plain-{index}",
            )
        with self.assertLogs(_UI_LOGGER, "WARNING") as logs:
            for _ in range(4):
                coordinator._process_mutation_requests(runtime)
        # one warning per refused write, no error; nothing re-resolved before the
        # callbacks reverted (the re-resolve is deferred to the next event-loop turn)
        self.assertEqual(len(logs.records), 4)
        self.assertEqual({record.levelname for record in logs.records}, {"WARNING"})
        self.assertEqual(wired.resolves, [])
        self._spin()
        self.assertEqual(wired.resolves, ["2"])
        self.assertTrue(wired.project_data.locked)
        self.assertFalse(wired.access.is_allowed(Feature.EDIT_CONDITION))
        self.assertEqual(wired.menu_updates, [True])
        # every callback got the refusal with its reason
        self.assertEqual(len(results), 3)
        self.assertTrue(
            all(
                result.rejection_reason is MutationRejectionReason.BID_LOCKED
                for result in results
            )
        )
        # the history entry is READY again, on its stack, and replayable
        self.assertEqual(entry.state, MutationHistoryState.READY)
        self.assertTrue(history.can_undo())
        self.assertFalse(history.can_redo())
        # no conflict, no recovery, no reconnect: only the notices were published
        self.assertNotIn(AppEvents.SYNCHRONIZATION_CONFLICT, set(wired.published))
        self.assertNotIn(AppEvents.FULL_RECONCILIATION_REQUIRED, set(wired.published))
        self.assertFalse(runtime.recovery_requested)
        self.assertEqual(wired.published.count(AppEvents.BID_LOCKED_REJECTION), 4)

    def test_a_rejection_without_the_reason_publishes_no_notice_and_logs_nothing(self):
        wired = self._wire()
        results = []
        _queue_test_mutation(
            wired.coordinator,
            wired.runtime.database_id,
            (ResourceRef("takeoffs_collection", "7", 7),),
            lambda: MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.REJECTED, message="busy"
            ),
            results.append,
            operation_id="plain",
        )
        with self.assertNoLogs(_UI_LOGGER, "WARNING"):
            wired.coordinator._process_mutation_requests(wired.runtime)
            self._spin()
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].rejection_reason)
        self.assertNotIn(AppEvents.BID_LOCKED_REJECTION, set(wired.published))
        self.assertEqual(wired.resolves, [])
        self.assertFalse(wired.project_data.locked)


if __name__ == "__main__":
    unittest.main()
