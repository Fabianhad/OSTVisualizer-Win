import sqlite3
import unittest
import uuid
from dataclasses import replace
from itertools import product
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from tests import test_mdb_sql_behavior_parity as parity
from tests.test_infrastructure_lifecycle import _SqliteDuplicateOps
from tests.test_plan_view_action_handler import (
    FakeAccess,
    FakeDeferredPersistence,
    FakeEventBus,
    FakePageSettingsBar,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
    FakeWriteService,
)


class PlanPropertyHistoryIdentityTests(unittest.TestCase):
    @staticmethod
    def committed(authoritative_result=None):
        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=authoritative_result,
        )

    def complete_property(self, data, write):
        _database, _bid, kind, updates, _options, callback = write.queued_properties[-1]
        for uid, target in updates:
            item = data.takeoffs[uid]
            data.takeoffs[uid] = replace(
                item,
                **{"area_uid" if kind == "takeoff_area" else "condition_uid": target},
            )
        callback(self.committed())

    def make_handler(self):
        data = FakeProjectData()
        data.takeoffs = {
            "parent": Takeoff(
                uid="parent",
                page_uid="p1",
                condition_uid="c1",
                area_uid="area-a",
                position=[0, 0, 10, 0, 10, 10],
            ),
            "child": Takeoff(
                uid="child",
                page_uid="p1",
                condition_uid="c1",
                area_uid="area-b",
                parent_uid="parent",
                is_negative=True,
                position=[1, 1, 2, 1, 2, 2],
            ),
        }
        write = FakeWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        return handler, data, write, undo

    def test_older_area_and_condition_history_follows_restored_parent_and_child(self):
        for kind, reuse_old_uid, selected in product(
            ("area", "condition"),
            (False, True),
            (("parent",), ("child",), ("parent", "child")),
        ):
            with self.subTest(
                kind=kind, reuse_old_uid=reuse_old_uid, selected=selected
            ):
                handler, data, write, undo = self.make_handler()
                if kind == "area":
                    handler.on_assign_to_area(list(selected))
                else:
                    handler.on_reassign_condition(list(selected), "42")
                handler.on_elements_deleted(["parent"])
                self.assertEqual(data.takeoffs, {})
                for cycle in range(2):
                    parent, child = f"parent-{cycle}", f"child-{cycle}"
                    write.uid_batches = [[parent], [child]]
                    undo.undo()
                    self.assertEqual(data.takeoffs[child].parent_uid, parent)
                    if reuse_old_uid:
                        data.takeoffs["parent"] = Takeoff(
                            uid="parent",
                            page_uid="p1",
                            condition_uid="42",
                            area_uid="unrelated",
                        )
                        data.takeoffs["child"] = Takeoff(
                            uid="child",
                            page_uid="p1",
                            condition_uid="42",
                            area_uid="unrelated",
                        )
                    undo.undo()
                    restored = [data.takeoffs[parent], data.takeoffs[child]]
                    if kind == "area":
                        self.assertEqual(
                            [item.area_uid for item in restored], ["area-a", "area-b"]
                        )
                    else:
                        self.assertEqual(
                            [item.condition_uid for item in restored], ["c1", "c1"]
                        )
                    if reuse_old_uid:
                        for uid in ("parent", "child"):
                            self.assertEqual(data.takeoffs[uid].area_uid, "unrelated")
                            self.assertEqual(data.takeoffs[uid].condition_uid, "42")
                    undo.redo()
                    self.assertEqual(data.takeoffs[child].parent_uid, parent)
                    undo.redo()
                    self.assertNotIn(parent, data.takeoffs)
                    self.assertNotIn(child, data.takeoffs)

    def test_sql_history_rebinds_after_restore_and_hydration_before_older_replay(self):
        for kind in ("area", "condition"):
            with self.subTest(kind=kind):
                handler, data, write, undo = self.make_handler()
                write.sql_collaboration_mutations = True
                if kind == "area":
                    handler.on_assign_to_area(["parent", "child"])
                else:
                    handler.on_reassign_condition(["parent", "child"], "42")
                self.complete_property(data, write)
                handler.on_elements_deleted(["parent"])
                deleted = write.queued_deletes[-1]
                for uid in deleted[2]:
                    data.takeoffs.pop(uid)
                deleted[-1](self.committed())
                for cycle in range(2):
                    undo.undo()
                    database, payload, _options, callback = write.queued_pastes[-1]
                    parent, child = f"sql-parent-{cycle}", f"sql-child-{cycle}"
                    write.uid_batches = [[parent], [child]]
                    result = write.execute_plan_items_paste_local(database, payload)
                    self.assertTrue(
                        handler._project_mdb_plan_items_paste(
                            FakeUiState().get_selected_bid_ref(), payload, result
                        )
                    )
                    data.takeoffs = {
                        uid: replace(item) for uid, item in data.takeoffs.items()
                    }
                    callback(self.committed(result.authoritative_result))
                    data.takeoffs["parent"] = Takeoff(
                        uid="parent",
                        page_uid="p1",
                        condition_uid="42",
                        area_uid="unrelated",
                    )
                    undo.undo()
                    self.assertEqual(
                        {uid for uid, _target in write.queued_properties[-1][3]},
                        {parent, child},
                    )
                    self.complete_property(data, write)
                    restored = [data.takeoffs[parent], data.takeoffs[child]]
                    self.assertEqual(
                        [
                            item.area_uid if kind == "area" else item.condition_uid
                            for item in restored
                        ],
                        ["area-a", "area-b"] if kind == "area" else ["c1", "c1"],
                    )
                    self.assertEqual(data.takeoffs["parent"].area_uid, "unrelated")
                    self.assertEqual(data.takeoffs[child].parent_uid, parent)
                    undo.redo()
                    self.complete_property(data, write)
                    undo.redo()
                    deleted = write.queued_deletes[-1]
                    self.assertEqual(set(deleted[2]), {parent, child})
                    for uid in deleted[2]:
                        data.takeoffs.pop(uid)
                    deleted[-1](self.committed())

    def test_deleted_area_uid_reuse_cannot_redirect_older_assignment_history(self):
        handler, data, _write, undo = self.make_handler()
        data.takeoffs["parent"].area_uid = "2"
        handler.on_assign_to_area(["parent"])
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript(
            """
            CREATE TABLE Bids (UID INTEGER PRIMARY KEY);
            INSERT INTO Bids VALUES (7);
            CREATE TABLE BidAreas (UID INTEGER PRIMARY KEY, BidUID INTEGER,
                ParentUID INTEGER, Name TEXT, Sequence INTEGER, GUID TEXT);
            INSERT INTO BidAreas VALUES (1,7,NULL,'Retained',1,'retained'), (2,7,NULL,'Original',2,'original');
        """
        )
        ops = _SqliteDuplicateOps(db)
        service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda *_args: False
        )
        service._save_bid_areas = SimpleNamespace(execute=ops.save_bid_areas)
        service._event_bus = EventBus()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = FakeUiState()
        coordinator._undo_service = undo
        service._event_bus.subscribe(
            AppEvents.BID_AREAS_DELETED, coordinator._on_bid_areas_deleted
        )
        result = service.save_bid_areas_result(
            "bid.mdb",
            "7",
            BidAreaChangeset([], [], ["2"]),
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result.success)
        recreated = service.save_bid_areas_result(
            "bid.mdb",
            "7",
            BidAreaChangeset([BidArea("draft", "7", "", "Unrelated", 2)], [], []),
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(recreated.value, {"draft": "2"})
        # The application must invalidate this older operation before the UID
        # can represent a different Area. A normal reload is not that signal.
        undo.undo()
        self.assertEqual(
            data.takeoffs["parent"].area_uid,
            "0",
            "Older history assigned the unrelated Area that reused UID 2",
        )

    def test_area_deletion_invalidates_only_owning_main_and_detached_history(self):
        for surface in ("main", "detached"):
            for bid_ref in (
                BidRef("bid.mdb", "7"),
                BidRef("bid.mdb", "8"),
                BidRef("other.mdb", "7"),
            ):
                with self.subTest(surface=surface, bid_ref=bid_ref):
                    undo = UndoRedoService()
                    undo.set_active_bid(bid_ref)
                    undo.push_local(lambda: True, lambda: True)
                    if surface == "main":
                        owner = UIEventCoordinator.__new__(UIEventCoordinator)
                        owner.ui_state_manager = SimpleNamespace(
                            get_selected_bid_ref=lambda: bid_ref
                        )
                        owner._undo_service = undo
                    else:
                        owner = DetachedPageViewManager.__new__(DetachedPageViewManager)
                        owner.repository = SimpleNamespace(
                            get_active_view=lambda: SimpleNamespace(bid_ref=bid_ref)
                        )
                        owner._window_undo_service = undo
                    owner._on_bid_areas_deleted("bid.mdb", "7", ("2",))
                    self.assertEqual(undo.can_undo(), bid_ref != BidRef("bid.mdb", "7"))

    def test_queued_area_deletion_invalidates_only_after_confirmed_commit(self):
        for status in (
            MutationOutcomeStatus.COMMITTED,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        ):
            with self.subTest(status=status):
                service = parity.MdbSqlBehaviorParityTests._local_composite_service()
                service._event_bus = FakeEventBus()
                queued = []
                service._queue_project_write = (
                    lambda *args, **_kwargs: queued.append(args) or 1
                )
                completed = []
                changes = BidAreaChangeset([], [], ["2"])
                service.queue_bid_areas_save("bid.mdb", "7", changes, completed.append)
                self.assertEqual(service._event_bus.events, [])
                # A dialog's next draft cannot change the already queued deletion.
                changes.deleted_uids.clear()
                result = replace(self.committed(), outcome_status=status)
                queued[0][4](result)
                self.assertEqual(completed, [result])
                if status in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                ):
                    self.assertEqual(
                        service._event_bus.events,
                        [
                            (
                                AppEvents.BID_AREAS_DELETED,
                                {
                                    "database_id": "bid.mdb",
                                    "bid_uid": "7",
                                    "area_uids": ("2",),
                                },
                            )
                        ],
                    )
                else:
                    self.assertEqual(service._event_bus.events, [])

    def test_queued_area_save_persists_the_same_snapshot_as_its_delete_event(self):
        service, provider = parity.MdbSqlBehaviorParityTests._queued_project_service()
        service._event_bus = FakeEventBus()
        submitted = BidAreaChangeset(
            [BidArea("draft", "7", "1", "New", 2, "guid")],
            [BidArea("1", "7", "", "Original", 1)],
            ["2"],
        )
        persisted = []
        service._save_bid_areas = SimpleNamespace(
            execute=lambda _db, _bid, changes: persisted.append(changes)
            or {"draft": "4"}
        )
        service.queue_bid_areas_save("database", "7", submitted, lambda _result: None)
        submitted.deleted_uids[:] = ["3"]
        submitted.updated[0].name = "Later draft"
        submitted.new[0].parent_uid = "3"
        submitted.new[0].guid = "later-guid"
        submitted.new.clear()
        result = provider.requests[-1][1]()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(persisted[0].deleted_uids, ["2"])
        self.assertEqual(persisted[0].updated[0].name, "Original")
        self.assertEqual(
            persisted[0].new, [BidArea("draft", "7", "1", "New", 2, "guid")]
        )

    def test_same_uid_in_two_history_lifetimes_is_not_a_shared_entity(self):
        self.check_two_lifetimes(False)

    def test_late_property_completion_cannot_recreate_invalidated_history(self):
        handler, data, write, undo = self.make_handler()
        write.sql_collaboration_mutations = True
        handler.on_assign_to_area(["parent"])
        undo.clear()  # Committed Area deletion invalidates the original history generation.
        self.complete_property(data, write)
        self.assertFalse(undo.can_undo())
        self.assertFalse(undo.can_redo())

    def test_late_placement_undo_cannot_suspend_new_history_after_invalidation(self):
        handler, data, write, undo = self.make_handler()
        write.sql_collaboration_mutations = True
        bid_ref = FakeUiState().get_selected_bid_ref()
        placed = data.takeoffs.pop("child")
        placed = replace(placed, parent_uid="0")
        data.takeoffs[placed.uid] = placed
        payload = handler._delete_restore_payload(bid_ref, [placed], [], {})
        handler._push_sql_takeoff_placement_history(
            bid_ref, list(payload.takeoff_specs), [placed.uid]
        )
        undo.undo()
        deleted_callback = write.queued_deletes[-1][-1]
        # The old delete has committed, but its UI completion is still pending.
        data.takeoffs.pop(placed.uid)
        undo.clear()
        data.takeoffs[placed.uid] = replace(placed, area_uid="new-area")
        handler._push_sql_property_history(
            bid_ref,
            "takeoff_area",
            [(placed.uid, "new-area")],
            [(placed.uid, "0")],
            ("p1",),
            (),
        )
        deleted_callback(self.committed())
        undo.undo()
        self.assertEqual(len(write.queued_properties), 1)
        self.assertEqual(write.queued_properties[0][3], [(placed.uid, "new-area")])

    def test_other_local_property_history_follows_delete_restore(self):
        for kind in ("negative", "curve", "text"):
            with self.subTest(kind=kind):
                handler, data, write, undo = self.make_handler()
                if kind == "negative":
                    handler.on_set_negative(["parent"], True)
                elif kind == "curve":
                    handler.on_set_curved(["parent"], True)
                else:
                    handler.on_condition_text_properties_flushed(
                        [("parent", "dimension", {"FontSize": 10}, {"FontSize": 20})]
                    )
                handler.on_elements_deleted(["parent"])
                write.uid_batches = [["restored-parent"], ["restored-child"]]
                undo.undo()
                undo.undo()
                self.assertEqual(write.local_properties[-1][3][0][0], "restored-parent")

    def test_late_related_completions_cannot_recreate_invalidated_history(self):
        for kind in ("delete", "paste", "geometry", "placement"):
            with self.subTest(kind=kind):
                handler, data, write, undo = self.make_handler()
                write.sql_collaboration_mutations = True
                bid_ref = FakeUiState().get_selected_bid_ref()
                if kind == "delete":
                    handler.on_elements_deleted(["parent"])
                    callback = write.queued_deletes[-1][-1]
                    data.takeoffs.clear()
                    result = self.committed()
                elif kind == "paste":
                    payload = handler._delete_restore_payload(
                        bid_ref, [data.takeoffs["parent"]], [], {}
                    )
                    handler._queue_sql_plan_items_paste_payload(
                        bid_ref, "p1", payload, ()
                    )
                    callback = write.queued_pastes[-1][-1]
                    persisted = write.execute_plan_items_paste_local("bid.mdb", payload)
                    result = self.committed(persisted.authoritative_result)
                elif kind == "geometry":
                    handler._queue_sql_plan_geometry(
                        bid_ref,
                        takeoff_changes=[("parent", [0, 0, 10, 10], [1, 1, 11, 11])],
                    )
                    callback = write.queued_geometry[-1][-1]
                    result = self.committed()
                else:
                    payload = handler._delete_restore_payload(
                        bid_ref, [data.takeoffs["parent"]], [], {}
                    )
                    handler._queue_takeoff_placement(
                        bid_ref, list(payload.takeoff_specs)
                    )
                    operation_id, callback = write.queued_takeoff_callbacks[-1]
                    data.takeoffs["created"] = Takeoff(
                        uid="created", page_uid="p1", condition_uid="c1"
                    )
                    result = replace(
                        self.committed(),
                        operation_id=operation_id,
                        created_resource_ids=("created",),
                    )
                undo.clear()
                callback(result)
                self.assertFalse(undo.can_undo())
                self.assertFalse(undo.can_redo())

    def test_placement_redo_rebinds_later_property_history(self):
        for sql, fast_refresh in ((False, True), (False, False), (True, True)):
            with self.subTest(sql=sql, fast_refresh=fast_refresh):
                handler, data, write, undo = self.make_handler()
                bid_ref = FakeUiState().get_selected_bid_ref()
                item = data.takeoffs.pop("child")
                item = replace(item, parent_uid="0", uid="placed")
                payload = handler._delete_restore_payload(bid_ref, [item], [], {})
                specs = list(payload.takeoff_specs)
                data.takeoffs[item.uid] = item
                write.sql_collaboration_mutations = sql
                if sql:
                    handler._push_sql_takeoff_placement_history(
                        bid_ref, specs, [item.uid]
                    )
                else:
                    handler._push_takeoff_insert_history(
                        bid_ref,
                        [item.uid],
                        specs,
                        lambda: True,
                        fast_refresh=fast_refresh,
                    )
                handler.on_assign_to_area([item.uid])
                if sql:
                    self.complete_property(data, write)
                undo.undo()
                if sql:
                    self.complete_property(data, write)
                undo.undo()
                if sql or not fast_refresh:
                    data.takeoffs.pop(item.uid)
                if sql:
                    write.queued_deletes[-1][-1](self.committed())
                write.uid_batches = [["restored-placement"]]
                undo.redo()
                if sql or not fast_refresh:
                    data.takeoffs["restored-placement"] = replace(
                        item, uid="restored-placement"
                    )
                if sql:
                    write.queued_takeoff_callbacks[-1][1](
                        replace(
                            self.committed(),
                            created_resource_ids=("restored-placement",),
                        )
                    )
                data.takeoffs[item.uid] = replace(item, area_uid="unrelated")
                undo.redo()
                if sql:
                    self.complete_property(data, write)
                self.assertEqual(data.takeoffs["restored-placement"].area_uid, "0")
                self.assertEqual(data.takeoffs[item.uid].area_uid, "unrelated")

    def test_composite_backout_restore_preserves_external_parent_in_projection(self):
        handler, data, _write, _undo = self.make_handler()
        bid_ref = FakeUiState().get_selected_bid_ref()
        child = data.takeoffs.pop("child")
        payload = handler._delete_restore_payload(bid_ref, [child], [], {})
        service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        result = service.execute_plan_items_paste_local(
            "bid.mdb", payload, publish_database_refreshed_after_write=False
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertTrue(handler._project_mdb_plan_items_paste(bid_ref, payload, result))
        self.assertEqual(data.takeoffs["parent-new"].parent_uid, "parent")
        self.assertEqual(data.takeoffs["parent-new"].position, child.position)

    def test_separately_deleted_backout_restores_to_reallocated_parent(self):
        handler, data, write, undo = self.make_handler()
        handler.on_assign_to_area(["child"])
        handler.on_elements_deleted(["child"])
        handler.on_elements_deleted(["parent"])
        write.uid_batches = [["parent-restored"]]
        undo.undo()
        data.takeoffs["parent"] = Takeoff(
            uid="parent", page_uid="p1", condition_uid="c1", area_uid="unrelated"
        )
        write.uid_batches = [["child-restored"]]
        undo.undo()
        self.assertEqual(data.takeoffs["child-restored"].parent_uid, "parent-restored")
        undo.undo()
        self.assertEqual(data.takeoffs["child-restored"].area_uid, "area-b")

    def test_sql_separately_deleted_backout_uses_restored_parent_dependency(self):
        handler, data, write, undo = self.make_handler()
        bid_ref = FakeUiState().get_selected_bid_ref()
        write.sql_collaboration_mutations = True
        handler.on_assign_to_area(["child"])
        self.complete_property(data, write)
        for uid in ("child", "parent"):
            handler.on_elements_deleted([uid])
            data.takeoffs.pop(uid)
            write.queued_deletes[-1][-1](self.committed())
        for uid in ("parent-restored", "child-restored"):
            undo.undo()
            database, payload, _options, callback = write.queued_pastes[-1]
            if uid == "child-restored":
                self.assertEqual(payload.takeoff_specs[0].parent_uid, "parent-restored")
            write.uid_batches = [[uid]]
            result = write.execute_plan_items_paste_local(database, payload)
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
            if uid == "child-restored":
                spec = payload.takeoff_specs[0]
                data.takeoffs[uid] = Takeoff(
                    uid=uid,
                    page_uid=spec.page_uid,
                    condition_uid=spec.condition_uid,
                    parent_uid=spec.parent_uid,
                    area_uid=spec.area_uid,
                    position=list(spec.position),
                    is_negative=spec.is_negative,
                )
            else:
                self.assertTrue(
                    handler._project_mdb_plan_items_paste(bid_ref, payload, result)
                )
            callback(self.committed(result.authoritative_result))
        self.assertEqual(data.takeoffs["child-restored"].parent_uid, "parent-restored")
        undo.undo()
        self.complete_property(data, write)
        self.assertEqual(data.takeoffs["child-restored"].area_uid, "area-b")

    def test_external_parent_reusing_backout_source_uid_is_not_a_batch_parent(self):
        handler, data, write, undo = self.make_handler()
        bid_ref = FakeUiState().get_selected_bid_ref()
        write.sql_collaboration_mutations = True
        for uid in ("child", "parent"):
            handler.on_elements_deleted([uid])
            data.takeoffs.pop(uid)
            write.queued_deletes[-1][-1](self.committed())
        undo.undo()
        database, payload, _options, callback = write.queued_pastes[-1]
        write.uid_batches = [["child"]]
        result = write.execute_plan_items_paste_local(database, payload)
        self.assertTrue(handler._project_mdb_plan_items_paste(bid_ref, payload, result))
        callback(self.committed(result.authoritative_result))
        undo.undo()
        _database, payload, _options, _callback = write.queued_pastes[-1]
        self.assertEqual(payload.takeoff_specs[0].parent_uid, "child")
        self.assertEqual(payload.takeoff_external_parent_sources, ("child",))
        for sql in (False, True):
            with self.subTest(sql=sql):
                if sql:
                    service, provider = (
                        parity.MdbSqlBehaviorParityTests._queued_project_service()
                    )
                    service._insert_takeoffs = parity._SequenceUseCase(["new-child"])
                    service.queue_plan_items_paste(
                        "database", payload, lambda _result: None
                    )
                    self.assertIn(
                        parity.ResourceRef("takeoff", "child", 7),
                        provider.requests[-1][0].dependency_resources,
                    )
                    result = provider.requests[-1][1]()
                else:
                    service = (
                        parity.MdbSqlBehaviorParityTests._local_composite_service()
                    )
                    result = service.execute_plan_items_paste_local("database", payload)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    service._insert_takeoffs.calls[0][2][0].parent_uid, "child"
                )
                self.assertTrue(
                    handler._project_mdb_plan_items_paste(bid_ref, payload, result)
                )
                restored_uid = result.created_resource_ids[0]
                self.assertEqual(data.takeoffs[restored_uid].parent_uid, "child")

    def test_external_parent_collision_cannot_attach_backout_to_another_restored_item(
        self,
    ):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, data, _write, _undo = self.make_handler()
                bid_ref = FakeUiState().get_selected_bid_ref()
                child = data.takeoffs["child"]
                other = replace(data.takeoffs["parent"], uid="other", parent_uid="0")
                payload = handler._delete_restore_payload(
                    bid_ref, [child, other], [], {}
                )
                parents = handler._history_parent_targets(
                    bid_ref, payload.takeoff_source_uids, payload.takeoff_specs
                )
                parents["parent"].uid = "other"
                data.takeoffs["other"] = replace(data.takeoffs["parent"], uid="other")
                payload = handler._paste_payload_with_history_parents(payload, parents)
                if sql:
                    service, provider = (
                        parity.MdbSqlBehaviorParityTests._queued_project_service()
                    )
                    service._insert_takeoffs = parity._SequenceUseCase(
                        ["child-new", "other-new"]
                    )
                    service.queue_plan_items_paste("database", payload, lambda _r: None)
                    result = provider.requests[-1][1]()
                else:
                    service = (
                        parity.MdbSqlBehaviorParityTests._local_composite_service()
                    )
                    service._insert_takeoffs = parity._SequenceUseCase(
                        ["child-new", "other-new"]
                    )
                    result = service.execute_plan_items_paste_local("database", payload)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    [spec.parent_uid for spec in service._insert_takeoffs.calls[0][2]],
                    ["other", "0"],
                )
                self.assertTrue(
                    handler._project_mdb_plan_items_paste(bid_ref, payload, result)
                )
                self.assertEqual(data.takeoffs["child-new"].parent_uid, "other")
                self.assertEqual(data.takeoffs["other-new"].parent_uid, "0")

    def test_restoring_later_uid_lifetime_cannot_rebind_earlier_deleted_entity(self):
        self.check_two_lifetimes(True)

    def test_sql_same_uid_in_two_history_lifetimes_is_not_a_shared_entity(self):
        self.check_two_lifetimes(True, sql=True)

    def check_two_lifetimes(self, delete_later_entity, *, sql=False):
        handler, data, write, undo = self.make_handler()
        bid_ref = FakeUiState().get_selected_bid_ref()
        write.sql_collaboration_mutations = sql
        delivered = {"properties": 0, "deletes": 0, "pastes": 0}

        def deliver():
            if not sql:
                return
            if len(write.queued_properties) > delivered["properties"]:
                delivered["properties"] = len(write.queued_properties)
                self.complete_property(data, write)
            elif len(write.queued_deletes) > delivered["deletes"]:
                delivered["deletes"] = len(write.queued_deletes)
                request = write.queued_deletes[-1]
                for uid in request[2]:
                    data.takeoffs.pop(uid)
                request[-1](self.committed())
            elif len(write.queued_pastes) > delivered["pastes"]:
                delivered["pastes"] = len(write.queued_pastes)
                database, payload, _options, callback = write.queued_pastes[-1]
                result = write.execute_plan_items_paste_local(database, payload)
                self.assertTrue(
                    handler._project_mdb_plan_items_paste(bid_ref, payload, result)
                )
                data.takeoffs = {
                    uid: replace(item) for uid, item in data.takeoffs.items()
                }
                callback(self.committed(result.authoritative_result))

        def undo_step():
            undo.undo()
            deliver()

        def redo_step():
            undo.redo()
            deliver()

        handler.on_assign_to_area(["parent"])
        deliver()
        handler.on_elements_deleted(["parent"])
        deliver()
        other = Takeoff(
            uid="copy-source",
            page_uid="p1",
            condition_uid="c1",
            area_uid="other-area",
            position=[100, 100, 110, 100, 110, 110],
        )
        payload = handler._delete_restore_payload(bid_ref, [other], [], {})
        data.takeoffs["parent"] = replace(other, uid="parent")
        if sql:
            handler._push_sql_paste_history(
                bid_ref, payload, {"copy-source": "parent"}, {}
            )
        else:
            handler._push_mdb_paste_history(
                bid_ref, payload, (), {"copy-source": "parent"}, {}
            )
        handler.on_assign_to_area(["parent"])
        deliver()
        if delete_later_entity:
            handler.on_elements_deleted(["parent"])
            deliver()
            write.uid_batches = [["later-restored"]]
            undo_step()
        undo_step()  # property on the later entity
        undo_step()  # remove the later entity
        write.uid_batches = [["original-restored"], ["original-hole"]]
        undo_step()  # restore the first entity
        undo_step()  # property on the first entity
        self.assertEqual(data.takeoffs["original-restored"].area_uid, "area-a")
        redo_step()
        redo_step()
        write.uid_batches = [["other-restored"]]
        redo_step()
        self.assertEqual(data.takeoffs["other-restored"].area_uid, "other-area")
        redo_step()
        self.assertEqual(data.takeoffs["other-restored"].area_uid, "0")
        self.assertEqual(data.takeoffs["other-restored"].position, other.position)


if __name__ == "__main__":
    unittest.main()
