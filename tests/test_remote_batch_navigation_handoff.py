from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseChangePollResult,
    DatabaseSession,
    HydratedDatabaseChangeBatch,
    ResourceRef,
)
from ost_visualizer.application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    _DatabaseRuntime,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from tests import test_page_folder_ownership
from tests.test_sql_collaboration_phase4 import (
    _batch,
    _change,
    _coordinator,
    _DelayedReconciliationDispatcher,
    _EventBus,
    _shutdown_coordinator,
    _token_service,
)


class RemoteBatchNavigationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_page_folder_ownership.PageFolderOwnershipTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.data = self.fixture.hierarchy_service()
        self.tokens, drafts = _token_service()
        self.events = _EventBus()
        self.dispatcher = _DelayedReconciliationDispatcher()
        self.store = Mock()
        reconciliation = RemoteChangeReconciliationService(
            self.data, self.events, self.tokens, drafts, ConflictResolutionService()
        )
        self.coordinator = _coordinator(
            Mock(),
            self.store,
            Mock(),
            self.dispatcher,
            reconciliation,
            Mock(),
            Mock(),
            self.tokens,
            drafts,
            self.events,
            1,
        )
        self.runtime = _DatabaseRuntime("database", 1)
        self.runtime.session = DatabaseSession("database", "session")
        self.coordinator._runtimes["database"] = self.runtime
        self.addCleanup(self.cleanup_coordinator)

    def cleanup_coordinator(self):
        self.coordinator._runtimes.clear()
        _shutdown_coordinator(self.coordinator)

    def queue_snapshot(self, version):
        batch = _batch(
            "database",
            "epoch",
            0,
            version,
            (_change("database", ResourceRef("page", "1", 8), version),),
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            bid_data_by_bid={8: self.fixture.read()},
            hierarchy_file=HierarchyFileEntry(
                file_path="database", orphan_bids=[deepcopy(self.fixture.info)]
            ),
            settings_defaults={},
            page_delete_content_uids_by_bid={8: frozenset()},
        )
        self.store.poll_changes.return_value = DatabaseChangePollResult(batch, hydrated)
        self.coordinator._poll_once(self.runtime)
        self.assertEqual(len(self.dispatcher.pending), 1)

    def load_newer_navigation(self):
        self.fixture.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID=10, Sequence=1 WHERE UID=1"
        )
        self.fixture.connection.execute("DELETE FROM BidPages WHERE UID=3")
        self.fixture.info.name = "Navigation New"
        self.fixture.info.folders["10"].name = "New folder"
        self.data.replace_database_hierarchy(
            HierarchyFileEntry(file_path="database", orphan_bids=[self.fixture.info]),
            {},
        )
        use_case = LoadBidUseCase(
            self.fixture.model, self.data, Mock(), self.tokens, Mock()
        )
        use_case.apply_prepared(
            self.fixture.bid_ref, PreparedBidLoad(self.fixture.read(), None)
        )

    def test_older_remote_snapshot_cannot_replace_newer_navigation(self):
        self.assert_late_snapshot_rejected(switch_bid=False)

    def test_older_remote_snapshot_cannot_replace_reactivated_bid(self):
        self.assert_late_snapshot_rejected(switch_bid=True)

    def assert_late_snapshot_rejected(self, *, switch_bid):
        self.queue_snapshot(1)
        if switch_bid:
            self.data.replace_database_hierarchy(
                HierarchyFileEntry(
                    file_path="database",
                    orphan_bids=[
                        self.fixture.info,
                        HierarchyBidInfo(uid="9", name="B"),
                    ],
                ),
                {},
            )
            LoadBidUseCase(
                self.fixture.model, self.data, Mock(), self.tokens, Mock()
            ).apply_prepared(
                BidRef("database", "9"), PreparedBidLoad(BidLoadResult(), None)
            )
            self.assertEqual(self.fixture.model.current_bid.uid, "9")
        self.load_newer_navigation()
        model = self.fixture.model
        bid = model.current_bid
        page = model.get_page("1")
        order = [p.uid for p in self.data.get_all_pages()]
        model.select_pages(["1"])
        self.dispatcher.deliver_pending()
        self.assertIs(model.get_page("1"), page)
        self.assertIs(model.current_bid, bid)
        self.assertEqual(bid.name, "Navigation New")
        self.assertEqual(bid.folders["10"].name, "New folder")
        self.assertEqual(page.folder_uid, "10")
        self.assertEqual([p.uid for p in self.data.get_all_pages()], order)
        self.assertIsNone(model.get_page("3"))
        self.assertEqual(model.get_selected_pages(), ["1"])
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertTrue(self.runtime.recovery_requested)

    def test_deleted_bid_is_not_resurrected_by_pending_snapshot(self):
        self.queue_snapshot(1)
        self.data.replace_database_hierarchy(
            HierarchyFileEntry(file_path="database"), {}
        )
        self.assertIsNone(self.data.get_bid(self.fixture.bid_ref))
        self.dispatcher.deliver_pending()
        self.assertIsNone(self.data.get_bid(self.fixture.bid_ref))
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertTrue(self.runtime.recovery_requested)

    def test_new_remote_snapshot_after_navigation_still_applies(self):
        self.load_newer_navigation()
        self.fixture.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID=NULL WHERE UID=1"
        )
        self.fixture.info.name = "Remote Newest"
        self.queue_snapshot(3)
        self.dispatcher.deliver_pending()
        self.assertIsNone(self.fixture.model.get_page("1").folder_uid)
        self.assertEqual(self.fixture.model.current_bid.name, "Remote Newest")
        self.assertIsNone(self.fixture.model.get_page("3"))
        self.assertEqual(self.runtime.acknowledged_version, 3)
        self.assertFalse(self.runtime.recovery_requested)

    def queue_startup_snapshot(self, version=1):
        class StartupQueued(Exception):
            pass

        pending = []

        def dispatch(callback, payload):
            pending.append((callback, payload))
            raise StartupQueued()

        batch = _batch(
            "database",
            "",
            0,
            version,
            tuple(
                _change(
                    "database",
                    ResourceRef(resource_type, "database"),
                    version,
                    operation=ChangeOperation.BULK_REFRESH,
                )
                for resource_type in (
                    "database",
                    "default_layers_collection",
                    "job_statuses_collection",
                    "employees_collection",
                    "pay_classes_collection",
                )
            ),
            delivered_through=0,
        )
        self.coordinator._remote_reader.initial_reconciliation.return_value = (
            HydratedDatabaseChangeBatch(
                batch,
                hierarchy_file=HierarchyFileEntry(
                    file_path="database", orphan_bids=[deepcopy(self.fixture.info)]
                ),
                settings_defaults={},
                default_layers=(),
                job_statuses=(),
                employees=(),
                pay_classes=(),
                used_job_status_uids=frozenset(),
                used_employee_uids=frozenset(),
            )
        )
        self.store.start_session.side_effect = lambda database_id, session_id, *_args, stop_requested=None: DatabaseSession(
            database_id, session_id
        )
        if not self.runtime.recovery_requested:
            self.runtime.session = None
        self.runtime.ready_event.clear()
        with unittest.mock.patch.object(
            self.coordinator._dispatcher, "dispatch", dispatch
        ):
            with self.assertRaises(StartupQueued):
                self.coordinator._run_worker(self.runtime)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][0].__name__, "_on_session_started")
        return pending[0]

    def test_startup_without_incumbent_cannot_overwrite_first_navigation(self):
        self.data.clear_bid()
        callback, payload = self.queue_startup_snapshot()
        self.load_newer_navigation()
        bid = self.fixture.model.current_bid
        page = self.fixture.model.get_page("1")
        self.fixture.model.select_pages(["1"])
        callback(payload)
        self.assertEqual(bid.name, "Navigation New")
        self.assertEqual(bid.folders["10"].name, "New folder")
        self.assertIs(self.fixture.model.current_bid, bid)
        self.assertIs(self.fixture.model.get_page("1"), page)
        self.assertEqual(page.folder_uid, "10")
        self.assertIsNone(self.fixture.model.get_page("3"))
        self.assertEqual(self.fixture.model.get_selected_pages(), ["1"])
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertTrue(self.runtime.recovery_requested)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertEqual(
            sum(
                event == AppEvents.FULL_RECONCILIATION_REQUIRED
                for event, _ in self.events.published
            ),
            1,
        )
        # Complete the existing recovery handshake, then accept fresh startup
        # hydration and a genuinely newer poll without advancing the startup checkpoint.
        old_session = self.runtime.session
        self.assertTrue(self.coordinator.resume_controlled_recovery("database"))
        self.fixture.info.name = "Startup Fresh"
        fresh_callback, fresh_payload = self.queue_startup_snapshot(version=2)
        fresh_callback(fresh_payload)
        self.assertIsNot(self.runtime.session, old_session)
        self.assertFalse(self.runtime.recovery_requested)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertEqual(bid.name, "Startup Fresh")
        self.assertIs(self.fixture.model.get_page("1"), page)
        self.fixture.info.name = "Remote Newest"
        self.queue_snapshot(3)
        self.dispatcher.deliver_pending()
        self.assertEqual(self.runtime.acknowledged_version, 3)
        self.assertFalse(self.runtime.pending_delivery)
        self.assertEqual(bid.name, "Remote Newest")

    def test_startup_without_incumbent_accepts_unchanged_empty_navigation(self):
        self.data.clear_bid()
        callback, payload = self.queue_startup_snapshot()
        callback(payload)
        self.assertIsNone(self.fixture.model.current_bid)
        self.assertIsNotNone(self.data.get_bid(self.fixture.bid_ref))
        self.assertFalse(self.runtime.recovery_requested)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertEqual(self.runtime.acknowledged_version, 0)

    def test_navigation_during_recovery_can_retry_until_authority_stabilizes(self):
        self.data.clear_bid()
        r0, payload0 = self.queue_startup_snapshot()
        self.load_newer_navigation()
        r0(payload0)
        self.assertTrue(self.coordinator.resume_controlled_recovery("database"))
        r1, payload1 = self.queue_startup_snapshot(version=2)
        # A -> B -> A changes the incarnation while preserving database and Bid UID.
        self.data.replace_database_hierarchy(
            HierarchyFileEntry(
                file_path="database",
                orphan_bids=[self.fixture.info, HierarchyBidInfo(uid="9", name="B")],
            ),
            {},
        )
        use_case = LoadBidUseCase(
            self.fixture.model, self.data, Mock(), self.tokens, Mock()
        )
        use_case.apply_prepared(
            BidRef("database", "9"), PreparedBidLoad(BidLoadResult(), None)
        )
        self.fixture.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID=NULL, Sequence=70 WHERE UID=1"
        )
        self.fixture.connection.execute("DELETE FROM BidPages WHERE UID=2")
        self.fixture.info.name = "Navigation Two"
        use_case.apply_prepared(
            self.fixture.bid_ref, PreparedBidLoad(self.fixture.read(), None)
        )
        bid = self.fixture.model.current_bid
        page = self.fixture.model.get_page("1")
        order = [p.uid for p in self.data.get_all_pages()]
        self.fixture.model.select_pages(["1"])
        r1(payload1)
        self.assertIs(self.fixture.model.current_bid, bid)
        self.assertIs(self.fixture.model.get_page("1"), page)
        self.assertEqual(bid.name, "Navigation Two")
        self.assertIsNone(page.folder_uid)
        self.assertEqual([p.uid for p in self.data.get_all_pages()], order)
        self.assertIsNone(self.fixture.model.get_page("2"))
        self.assertIsNone(self.fixture.model.get_page("3"))
        self.assertEqual(self.fixture.model.get_selected_pages(), ["1"])
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertTrue(self.runtime.recovery_requested)
        self.coordinator._poll_once(self.runtime)
        self.store.poll_changes.assert_not_called()
        self.assertTrue(self.coordinator.resume_controlled_recovery("database"))
        r1(payload1)
        self.assertFalse(self.coordinator.resume_controlled_recovery("database"))
        r2, payload2 = self.queue_startup_snapshot(version=3)
        r2(payload2)
        self.assertFalse(self.runtime.recovery_requested)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertIs(self.fixture.model.get_page("1"), page)
        self.fixture.info.name = "Remote Newest"
        self.queue_snapshot(4)
        self.dispatcher.deliver_pending()
        self.assertEqual(bid.name, "Remote Newest")
        self.assertEqual(self.runtime.acknowledged_version, 4)
        self.assertFalse(self.runtime.pending_delivery)
        self.assertTrue(self.runtime.healthy)
        self.assertEqual(
            sum(
                event == AppEvents.FULL_RECONCILIATION_REQUIRED
                for event, _ in self.events.published
            ),
            2,
        )

    def test_malformed_recovery_still_retains_existing_retry_limit(self):
        self.coordinator._on_session_reconciliation_required(
            (
                "database",
                self.runtime.generation,
                self.runtime.session_generation,
                "First reconciliation failure",
            )
        )
        self.assertTrue(self.coordinator.resume_controlled_recovery("database"))
        callback, payload = self.queue_startup_snapshot()
        database_id, generation, session_generation, hydrated, owner = payload
        callback(
            (
                database_id,
                generation,
                session_generation,
                replace(hydrated, settings_defaults=None),
                owner,
            )
        )
        self.assertTrue(self.runtime.recovery_requested)
        self.assertTrue(self.runtime.ready_event.is_set())
        self.assertEqual(self.runtime.acknowledged_version, 0)
        self.assertFalse(self.coordinator.resume_controlled_recovery("database"))
