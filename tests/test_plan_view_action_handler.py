import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.services.selection_commands import (
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
)


class FakePlanView:
    def __init__(self, data=None):
        self.selected = set()
        self.clears = 0
        self.data = data
        self.current_page_uid = "p1"
        self.snap_increments = 1.0

    def set_selected_uids(self, uids):
        self.selected = set(uids)

    def clear_selection(self):
        self.clears += 1
        self.selected = set()

    def get_takeoff(self, uid):
        if self.data is None:
            return None
        return self.data.get_takeoff(uid)

    def get_annotation(self, _uid):
        return None

    def find_annotation_keys_by_uid_type(self, _uid_type_set):
        return set()


class FakeUiState:
    place_condition_uids = []

    def get_selected_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="7")


class FakeProjectData:
    def __init__(self):
        self.added_takeoffs = []
        self.takeoffs = {}
        self.extras = {}
        self.conditions = {
            "42": SimpleNamespace(layer_visible=True, condition_type="linear"),
            "c1": SimpleNamespace(layer_visible=True, condition_type="area"),
        }

    def add_takeoffs(self, takeoffs):
        self.added_takeoffs.extend(takeoffs)
        for takeoff in takeoffs:
            self.takeoffs[takeoff.uid] = takeoff

    def get_current_bid_file_path(self):
        return "bid.mdb"

    def get_takeoff(self, uid):
        return self.takeoffs.get(uid)

    def get_all_takeoffs(self):
        return list(self.takeoffs.values())

    def get_takeoff_extras(self, uid):
        return self.extras.get(uid, {})

    def get_bid_conditions(self):
        return dict(self.conditions)

    def update_takeoff_positions(self, positions):
        page_uids = []
        for uid, position in positions:
            takeoff = self.takeoffs[uid]
            takeoff.position = list(position)
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def update_takeoff_rotations(self, rotations):
        page_uids = []
        for uid, rotation in rotations:
            takeoff = self.takeoffs[uid]
            takeoff.rotation = rotation
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def remove_takeoffs(self, uids):
        page_uids = []
        for uid in uids:
            takeoff = self.takeoffs.pop(uid, None)
            if takeoff and takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def find_hotlinks_targeting(self, _uids):
        return []


class FakeWriteService:
    def __init__(self):
        self.calls = []
        self.condition_calls = []
        self.position_calls = []
        self.rotation_calls = []
        self.delete_calls = []
        self.next_uids = ["100"]
        self.uid_batches = []
        self._next_uid_index = 0

    def insert_takeoffs(self, db_path, bid_uid, specs, reload_database=True):
        self.calls.append((db_path, bid_uid, specs, reload_database))
        if self.uid_batches:
            return list(self.uid_batches.pop(0))
        start = self._next_uid_index
        end = start + len(specs)
        result = list(self.next_uids[start:end])
        while len(result) < len(specs):
            result.append(str(100 + self._next_uid_index + len(result)))
        self._next_uid_index += len(specs)
        return result

    def save_takeoff_positions(self, db_path, positions, reload_database=True):
        self.position_calls.append((db_path, positions, reload_database))
        return True

    def save_takeoff_rotations(self, db_path, rotations, reload_database=True):
        self.rotation_calls.append((db_path, rotations, reload_database))
        return True

    def save_takeoffs_condition(self, db_path, uids, condition_uid):
        self.condition_calls.append((db_path, list(uids), condition_uid))
        return True

    def delete_takeoffs(self, db_path, uids, reload_database=True):
        self.delete_calls.append((db_path, list(uids), reload_database))
        return True


class FakeAnnotationWriteService:
    def __init__(self):
        self.position_calls = []
        self.insert_calls = []
        self.delete_calls = []
        self.next_uids = ["ann-1"]

    def save_annotation_positions(self, db_path, positions):
        self.position_calls.append((db_path, positions))
        return True

    def insert_annotations(self, db_path, bid_uid, specs, ref_remap=None):
        self.insert_calls.append((db_path, bid_uid, specs, ref_remap))
        return list(self.next_uids[: len(specs)])

    def delete_annotations(self, db_path, annotation_keys):
        self.delete_calls.append((db_path, annotation_keys))
        return True


class FakePageSettingsBar:
    def get_current_area_uid(self):
        return "0"


class FakeUndoService:
    def __init__(self):
        self.count = 0
        self.undo = None
        self.redo = None

    def push(self, undo, redo):
        self.count += 1
        self.undo = undo
        self.redo = redo


class FakeClipboard:
    def __init__(
        self,
        items,
        extras=None,
        source_bid_uid="7",
        source_file_path="bid.mdb",
    ):
        self.items = items
        self.annotations = []
        self.source_bid_uid = source_bid_uid
        self.source_file_path = source_file_path
        self._extras = extras or {}

    def has_content(self):
        return bool(self.items or self.annotations)

    def get_extras(self, uid):
        return self._extras.get(uid, {})


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_name, **kwargs):
        self.events.append((event_name, kwargs))


class PlanViewActionHandlerTests(unittest.TestCase):
    def test_new_takeoff_uses_fast_refresh_and_updates_model(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        write = FakeWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(plan_view.selected, {"100"})
        self.assertEqual(undo.count, 1)
        self.assertEqual(len(data.added_takeoffs), 1)
        self.assertEqual(data.added_takeoffs[0].uid, "100")
        self.assertEqual(data.added_takeoffs[0].condition_uid, "42")
        self.assertEqual(data.added_takeoffs[0].page_uid, "9")
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_bus.events[0][1]["takeoff_uids"], ["100"])

    def test_raw_extra_insert_keeps_full_reload(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        spec = InsertTakeoffSpec(
            condition_uid="42",
            page_uid="9",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={"GUID": "{OLD}"},
        )
        handler._insert_takeoffs_with_undo(
            BidRef(file_path="bid.mdb", bid_uid="7"),
            [spec],
            fast_refresh=True,
        )
        self.assertEqual(write.calls[0][3], True)
        self.assertEqual(data.added_takeoffs, [])

    def test_reassign_condition_writes_selected_takeoffs(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        handler.on_reassign_condition(["t1", "missing"], "42")
        handler.on_reassign_condition(["t1"], "missing-condition")
        self.assertEqual(write.condition_calls, [("bid.mdb", ["t1"], "42")])

    def test_pure_takeoff_position_edit_uses_takeoffs_changed(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.position_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])
        self.assertEqual(
            event_bus.events,
            [(AppEvents.TAKEOFFS_CHANGED, {"page_uid": "p1", "takeoff_uids": ["t1"]})],
        )

    def test_takeoff_position_undo_redo_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
        )
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        undo.undo()
        undo.redo()
        self.assertEqual(
            [call[2] for call in write.position_calls], [False, False, False]
        )
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_mixed_takeoff_annotation_position_keeps_reload_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_positions_flushed(
            [("t1", [0.0, 0.0], [5.0, 6.0])],
            [("a1", "annotation", [1.0, 1.0], [2.0, 2.0])],
        )
        self.assertEqual(write.position_calls[0][2], True)
        self.assertEqual(ann_write.position_calls[0][0], "bid.mdb")
        self.assertEqual(event_bus.events, [])

    def test_pure_takeoff_rotation_uses_takeoffs_changed(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", rotation=0.0
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_rotations_flushed([("t1", 0.0, 90.0)])
        self.assertEqual(write.rotation_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].rotation, 90.0)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_bus.events[0][1]["page_uid"], "p1")

    def test_group_rotation_updates_positions_and_rotations_targeted(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])],
            [],
            [("t1", 0.0, 45.0)],
        )
        self.assertEqual(write.position_calls[0][2], False)
        self.assertEqual(write.rotation_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 45.0)
        self.assertEqual(len(event_bus.events), 1)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

    def test_simple_takeoff_delete_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls[0][2], False)
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

    def test_takeoff_delete_undo_redo_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        write.next_uids = ["t2"]
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        plan_view = FakePlanView(data)
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
        )
        handler.on_elements_deleted(["t1"])
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertNotIn("t2", data.takeoffs)
        self.assertEqual(plan_view.clears, 1)
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_paste_parent_child_undo_redo_preserves_parent_remap(self):
        parent = Takeoff(
            uid="old-parent",
            condition_uid="c1",
            page_uid="source-page",
            position=[0.0, 0.0, 2.0, 0.0, 2.0, 2.0],
            parent_uid="0",
        )
        hole = Takeoff(
            uid="old-hole",
            condition_uid="c1",
            page_uid="source-page",
            position=[0.5, 0.5, 1.0, 0.5, 1.0, 1.0],
            parent_uid="old-parent",
        )
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.next_uids = ["new-parent", "new-hole"]
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
        )
        handler._clipboard_svc = FakeClipboard(
            [parent, hole],
            extras={"old-hole": {"Raw": "kept"}},
        )
        handler.on_paste_requested()
        self.assertEqual(write.calls[0][2][0].parent_uid, "0")
        self.assertEqual(write.calls[1][2][0].parent_uid, "new-parent")
        self.assertEqual(write.calls[1][2][0].raw_extras, {"Raw": "kept"})
        self.assertEqual(plan_view.selected, {"new-parent", "new-hole"})
        undo.undo()
        self.assertEqual(write.delete_calls[-1][1], ["new-parent", "new-hole"])
        write.uid_batches = [["redo-parent"], ["redo-hole"]]
        undo.redo()
        self.assertEqual(write.calls[-2][2][0].parent_uid, "0")
        self.assertEqual(write.calls[-1][2][0].parent_uid, "redo-parent")
        self.assertEqual(write.calls[-1][2][0].raw_extras, {"Raw": "kept"})
        self.assertEqual(plan_view.selected, {"redo-parent", "redo-hole"})

    def test_paste_annotation_redo_uses_source_to_current_takeoff_remap(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.uid_batches = [["redo-takeoff"]]
        ann_write = FakeAnnotationWriteService()
        bid_ref = BidRef(file_path="bid.mdb", bid_uid="7")
        takeoff_cmd = PasteTakeoffsCommand(
            pasted_takeoffs=[
                Takeoff(
                    uid="initial-takeoff",
                    condition_uid="c1",
                    page_uid="p1",
                    position=[0.0, 0.0],
                    parent_uid="0",
                )
            ],
            bid_ref=bid_ref,
            write_svc=write,
            plan_view=plan_view,
            source_uids=["source-takeoff"],
            source_parent_uids=["0"],
            source_bid_uid="7",
        )
        ann_cmd = PasteAnnotationsCommand(
            specs=[
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="hotlink",
                    position=[],
                    color="#000000",
                    width=1.0,
                    properties={"takeoff_uid": "source-takeoff"},
                )
            ],
            new_uids=["initial-ann"],
            bid_ref=bid_ref,
            write_svc=ann_write,
            plan_view=plan_view,
            sibling_takeoff_cmd=takeoff_cmd,
        )
        takeoff_cmd.redo()
        ann_cmd.redo()
        ref_remap = ann_write.insert_calls[-1][3]
        self.assertEqual(
            ref_remap.takeoff_uids,
            {"source-takeoff": "redo-takeoff"},
        )


if __name__ == "__main__":
    unittest.main()
