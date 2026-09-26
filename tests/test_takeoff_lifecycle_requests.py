import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)
from tests import test_plan_property_history_identity as history_fixtures
from tests import test_mdb_sql_behavior_parity as parity
from tests import test_takeoff_lifecycle_placement as placement_fixtures


class TakeoffLifecycleRequestTests(unittest.TestCase):
    def test_cross_bid_child_paste_uses_one_atomic_mutation(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            MutationExecutionResult,
        )

        handler, _data, write, undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        handler._clipboard_svc = SelectionClipboardService()
        handler._clipboard_svc.copy([], source_bid_uid="6", source_file_path="bid.mdb")
        submitted = []
        write.execute_plan_items_paste_local = lambda _database, payload, **_options: (
            submitted.append(payload)
            or MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "c1",
                    "page_uid": "p1",
                    "position": [1, 1, 2, 1, 2, 2],
                    "parent_uid": "parent",
                    "rotation": 0,
                    "is_negative": False,
                    "extras": {},
                }
            ],
            "6",
        )
        self.assertEqual(len(submitted), 1)
        self.assertEqual(write.condition_duplicate_calls, [])
        self.assertFalse(undo.can_undo())

    def test_nested_child_placement_persists_remapped_hierarchy(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, data, write, _undo = (
                    history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
                )
                handler._clipboard_svc = SelectionClipboardService()
                handler._clipboard_svc.copy(
                    [], source_bid_uid="7", source_file_path="bid.mdb"
                )
                write.sql_collaboration_mutations = sql
                placements = [
                    {
                        "source_uid": "source-root",
                        "condition_uid": "c1",
                        "page_uid": "p1",
                        "position": [1, 1, 9, 1, 9, 9],
                        "parent_uid": "parent",
                        "parent_is_internal": False,
                        "rotation": 0,
                        "is_negative": False,
                        "extras": {},
                    },
                    {
                        "source_uid": "source-child",
                        "condition_uid": "c1",
                        "page_uid": "p1",
                        "position": [2, 2, 3, 2, 3, 3],
                        "parent_uid": "source-root",
                        "parent_is_internal": True,
                        "rotation": 0,
                        "is_negative": False,
                        "extras": {},
                    },
                ]
                write.uid_batches = [["new-root"], ["new-child"]]
                handler.on_paste_backouts_placed(placements, "7")
                if sql:
                    _database, payload, _options, _callback = write.queued_pastes[-1]
                    self.assertEqual(
                        payload.takeoff_source_uids, ("source-root", "source-child")
                    )
                    self.assertEqual(
                        payload.takeoff_external_parent_sources, ("source-root",)
                    )
                else:
                    self.assertEqual(data.takeoffs["new-root"].parent_uid, "parent")
                    self.assertEqual(data.takeoffs["new-child"].parent_uid, "new-root")

    @classmethod
    def setUpClass(cls):
        placement_fixtures.TakeoffLifecyclePlacementTests.setUpClass()

    def test_mixed_paste_validates_external_attachment_footprint_before_submission(
        self,
    ):
        handler, data, write, _undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        view = placement_fixtures.TakeoffLifecyclePlacementTests().harness(
            Condition.TYPE_AREA, (0, 0), (1, 1), backout=True
        )
        condition = Condition(
            uid="attachment", condition_type=Condition.TYPE_ATTACHMENT, width=4, depth=4
        )
        view._current_conditions[condition.uid] = condition
        data.conditions[condition.uid] = condition
        handler._clipboard_svc = SelectionClipboardService()
        handler._clipboard_svc.copy([], source_bid_uid="7", source_file_path="bid.mdb")
        handler._plan_view.resolve_pasted_child_parents = (
            lambda *args: view.resolve_pasted_child_parents(*args)
        )
        handler._paste_translation = lambda *_: (0, 0, None)
        count = Takeoff(
            uid="count", condition_uid="c1", page_uid="p1", position=[20, 20]
        )
        attachment = Takeoff(
            uid="point",
            condition_uid="attachment",
            page_uid="p1",
            parent_uid="parent",
            position=[9, 9],
        )
        prepared = handler._prepare_plan_items_paste(
            handler._ui_state.get_selected_bid_ref(),
            "p1",
            "0",
            [count],
            [attachment],
            [],
        )
        self.assertIsNone(prepared)
        self.assertEqual(write.calls, [])

    def test_nested_parent_paste_remaps_each_generation_on_both_backends(self):
        payload = parity.MdbSqlBehaviorParityTests._mixed_paste_payload()
        payload = replace(
            payload,
            takeoff_source_uids=("grandchild", "hole", "parent"),
            takeoff_specs=(
                replace(payload.takeoff_specs[1], parent_uid="hole"),
                payload.takeoff_specs[1],
                payload.takeoff_specs[0],
            ),
            annotation_source_uids=(),
            annotation_specs=(),
        )
        for sql in (False, True):
            with self.subTest(sql=sql):
                if sql:
                    service, provider = (
                        parity.MdbSqlBehaviorParityTests._queued_project_service()
                    )
                else:
                    service = (
                        parity.MdbSqlBehaviorParityTests._local_composite_service()
                    )
                service._insert_takeoffs = parity._SequenceUseCase(
                    ["p-new"], ["h-new"], ["g-new"]
                )
                if sql:
                    service.queue_plan_items_paste("database", payload, lambda _r: None)
                    result = provider.requests[-1][1]()
                else:
                    result = service.execute_plan_items_paste_local("database", payload)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    [call[2][0].parent_uid for call in service._insert_takeoffs.calls],
                    ["0", "p-new", "h-new"],
                )

    def test_deleting_any_ancestor_includes_complete_descendant_graph(self):
        for selected, expected in (
            ("parent", {"parent", "child", "grandchild"}),
            ("child", {"child", "grandchild"}),
        ):
            with self.subTest(selected=selected):
                handler, data, write, _undo = (
                    history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
                )
                data.takeoffs["grandchild"] = replace(
                    data.takeoffs["child"], uid="grandchild", parent_uid="child"
                )
                write.sql_collaboration_mutations = True
                handler.on_elements_deleted([selected])
                self.assertEqual(set(write.queued_deletes[-1][2]), expected)

    def test_queued_placement_retains_submission_snapshot_and_dependencies(self):
        queued = []
        written = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args, **kwargs: queued.append(args) or 1
        )

        def insert(_database, _bid, specs, **kwargs):
            written.extend(deepcopy(specs))
            return DatabaseMutationResult(
                operation_id=kwargs["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=["101"],
            )

        service._insert_takeoffs_mutation = insert
        spec = InsertTakeoffSpec(
            condition_uid="10",
            page_uid="20",
            area_uid="30",
            parent_uid="40",
            position=[1.25, 2.75],
            raw_extras={"FontName": "Original"},
        )
        specs = [spec]
        expected = deepcopy(spec)
        service.queue_takeoff_placement(
            "database",
            "8",
            specs,
            "7b3c5ac1-e623-44aa-8203-26a0125873b9",
            lambda _result: None,
        )
        spec.position[0] = 99
        spec.page_uid = "21"
        spec.parent_uid = "41"
        spec.raw_extras["FontName"] = "Changed"
        specs.append(deepcopy(spec))
        result = queued[0][1]()
        self.assertEqual(written, [expected])
        self.assertEqual(result.authoritative_result.affected_page_uids, ("20",))
        self.assertEqual(queued[0][0].payload, (expected,))

    def test_copy_parent_captures_detached_descendant_snapshot(self):
        handler, data, _write, _undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        handler._clipboard_svc = SelectionClipboardService()
        data.conditions["attachment"] = Condition(
            uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
        )
        data.takeoffs["attachment"] = Takeoff(
            uid="attachment",
            condition_uid="attachment",
            page_uid="p1",
            parent_uid="parent",
            position=[5, 5],
        )
        handler.on_copy_requested(["parent"])
        self.assertEqual(
            {item.uid for item in handler._clipboard_svc.items},
            {"parent", "child", "attachment"},
        )
        data.takeoffs["child"].position[0] = 99
        copied = {item.uid: item for item in handler._clipboard_svc.items}
        self.assertEqual(copied["child"].position[0], 1)
