import unittest
from types import SimpleNamespace

from ost_visualizer.application.dtos.insert_annotation_spec_dto import \
    InsertAnnotationSpec
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import \
    InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.handlers.plan_view_action_handler import \
    PlanViewActionHandler
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.services.selection_commands import (
    PasteAnnotationsCommand, PasteTakeoffsCommand)


class FakePlanView:
    def __init__(self, data=None):
        self.selected = set()
        self.clears = 0
        self.data = data
        self.current_page_uid = "p1"
        self.snap_increments = 1.0
        self.intelligent_paste_enabled = True
        self.cancel_place_mode_calls = 0
        self.paste_backout_calls = []
        self.mouse_ost_position = (100.0, 200.0)
        self.intelligent_paste_calls = []
        self.annotation_key_map = {}

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

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }

    def cancel_place_mode(self):
        self.cancel_place_mode_calls += 1

    def begin_paste_backout(self, holes, extras_by_uid, source_bid_uid):
        self.paste_backout_calls.append((holes, extras_by_uid, source_bid_uid))

    def current_mouse_ost_position(self):
        return self.mouse_ost_position

    def mark_intelligent_paste_drag_pending(self, pasted_uids, source_anchor_ost):
        self.intelligent_paste_calls.append((list(pasted_uids), source_anchor_ost))
        return True


class FakeUiState:
    place_condition_uids = []

    def get_selected_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="7")


class FakeProjectData:
    def __init__(self):
        self.added_takeoffs = []
        self.takeoffs = {}
        self.extras = {}
        self.named_view_updates = []
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

    def update_takeoff_text_properties(self, updates):
        page_uids = []
        for uid, properties in updates:
            takeoff = self.takeoffs[uid]
            for key, value in properties.items():
                if key == "dimension_font_name":
                    takeoff.dimension_font_name = str(value)
                elif key == "dimension_font_color":
                    takeoff.dimension_font_color = int(value)
                elif key == "dimension_font_size":
                    takeoff.dimension_font_size = int(value)
                elif key == "dimension_font_bold":
                    takeoff.dimension_font_bold = bool(value)
                elif key == "dimension_font_italic":
                    takeoff.dimension_font_italic = bool(value)
                elif key == "dimension_font_underline":
                    takeoff.dimension_font_underline = bool(value)
                elif key == "name_font_name":
                    takeoff.name_font_name = str(value)
                elif key == "name_font_color":
                    takeoff.name_font_color = int(value)
                elif key == "name_font_size":
                    takeoff.name_font_size = int(value)
                elif key == "name_font_bold":
                    takeoff.name_font_bold = bool(value)
                elif key == "name_font_italic":
                    takeoff.name_font_italic = bool(value)
                elif key == "name_font_underline":
                    takeoff.name_font_underline = bool(value)
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def update_named_view_names(self, updates):
        self.named_view_updates.extend(list(updates))
        return []

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
        self.update_condition_calls = []
        self.position_calls = []
        self.rotation_calls = []
        self.text_property_calls = []
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

    def save_takeoff_text_properties(self, db_path, updates, reload_database=True):
        self.text_property_calls.append((db_path, updates, reload_database))
        return True

    def save_takeoffs_condition(self, db_path, uids, condition_uid):
        self.condition_calls.append((db_path, list(uids), condition_uid))
        return True

    def delete_takeoffs(self, db_path, uids, reload_database=True):
        self.delete_calls.append((db_path, list(uids), reload_database))
        return True

    def update_condition(
        self, db_path, bid_uid, condition_uid, updates, all_conditions=None
    ):
        self.update_condition_calls.append(
            (
                db_path,
                bid_uid,
                condition_uid,
                updates.get_changes(),
                all_conditions,
            )
        )
        return SimpleNamespace(success=True)


class FakeAnnotationWriteService:
    def __init__(self):
        self.position_calls = []
        self.text_property_calls = []
        self.text_and_position_calls = []
        self.insert_calls = []
        self.delete_calls = []
        self.next_uids = ["ann-1"]

    def save_annotation_positions(self, db_path, positions):
        self.position_calls.append((db_path, positions))
        return True

    def save_annotation_text_properties(self, db_path, updates):
        self.text_property_calls.append((db_path, updates))
        return True

    def save_annotation_text_properties_and_positions(
        self, db_path, updates, positions
    ):
        self.text_and_position_calls.append((db_path, updates, positions))
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
        annotations=None,
        extras=None,
        source_bid_uid="7",
        source_file_path="bid.mdb",
    ):
        self.items = items
        self.annotations = list(annotations or [])
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


class FakeAccess:
    def __init__(self, allowed_features):
        self.allowed_features = set(allowed_features)

    def is_allowed(self, feature):
        return feature in self.allowed_features


class PlanViewActionHandlerTests(unittest.TestCase):
    def _paste_handler(
        self,
        plan_view=None,
        write=None,
        ann_write=None,
    ):
        return PlanViewActionHandler(
            plan_view=FakePlanView() if plan_view is None else plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService() if write is None else write,
            annotation_write_svc=(
                FakeAnnotationWriteService() if ann_write is None else ann_write
            ),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )

    def _copied_takeoff(self, position=None):
        copied_position = [10.0, 20.0, 14.0, 20.0] if position is None else position
        return Takeoff(
            uid="source",
            condition_uid="c1",
            page_uid="source-page",
            position=list(copied_position),
            parent_uid="0",
        )

    def _copied_annotation(
        self,
        annotation_type="line",
        position=None,
        uid="source-ann",
        color="#ff0000",
    ):
        copied_position = [10.0, 20.0, 14.0, 20.0] if position is None else position
        return BidAnnotation(
            uid=uid,
            annotation_type=annotation_type,
            page_uid="source-page",
            position=list(copied_position),
            color=color,
            width=1.0,
        )

    def test_denied_takeoff_selection_access_blocks_plan_view_write_signals(self):
        data = FakeProjectData()
        takeoff = Takeoff(
            uid="t1",
            condition_uid="42",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
        )
        data.takeoffs[takeoff.uid] = takeoff
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            ui_access_manager=FakeAccess(set()),
        )
        handler.on_elements_deleted(["t1"])
        handler.on_positions_flushed([("t1", [1.0, 2.0], [3.0, 4.0])], [])
        handler.on_takeoff_created("42", [1.0, 2.0], "p1")
        self.assertEqual(write.delete_calls, [])
        self.assertEqual(write.position_calls, [])
        self.assertEqual(write.calls, [])

    def test_denied_annotation_text_access_blocks_text_property_write(self):
        annotation_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            ui_access_manager=FakeAccess({Feature.SELECT_TAKEOFFS}),
        )
        handler.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        )
        self.assertEqual(annotation_write.text_property_calls, [])

    def test_condition_label_text_properties_write_takeoff_style_fields(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        write = FakeWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            ui_access_manager=FakeAccess({Feature.EDIT_CONDITION}),
        )
        handler.on_condition_text_properties_flushed(
            [
                (
                    "t1",
                    "display_name",
                    {},
                    {
                        "name_font_name": "Segoe UI",
                        "name_font_color": 0x332211,
                        "name_font_size": 24,
                        "name_font_bold": True,
                        "name_font_italic": False,
                        "name_font_underline": True,
                    },
                )
            ]
        )
        self.assertEqual(
            write.text_property_calls,
            [
                (
                    "bid.mdb",
                    [
                        (
                            "t1",
                            {
                                "name_font_name": "Segoe UI",
                                "name_font_color": 0x332211,
                                "name_font_size": 24,
                                "name_font_bold": True,
                                "name_font_italic": False,
                                "name_font_underline": True,
                            },
                        )
                    ],
                    False,
                )
            ],
        )
        self.assertEqual(data.takeoffs["t1"].name_font_size, 24)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

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
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)

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

    def test_annotation_text_property_changes_use_annotation_write_service(self):
        data = FakeProjectData()
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
        )
        handler.on_annotation_text_properties_flushed(
            [
                (
                    "a1",
                    "text",
                    {"Text": "Old", "FontBold": False},
                    {"Text": "New", "FontBold": True},
                )
            ]
        )
        self.assertEqual(
            ann_write.text_property_calls[0],
            ("bid.mdb", [("a1", "text", {"Text": "New", "FontBold": True})]),
        )
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.text_property_calls[1:],
            [
                ("bid.mdb", [("a1", "text", {"Text": "Old", "FontBold": False})]),
                ("bid.mdb", [("a1", "text", {"Text": "New", "FontBold": True})]),
            ],
        )

    def test_named_view_rename_publishes_combo_refresh_event(self):
        data = FakeProjectData()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
        )
        handler.on_annotation_text_properties_flushed(
            [("nv1", "namedview", {"Text": "Old"}, {"Text": "New"})]
        )
        self.assertEqual(data.named_view_updates, [("nv1", "New")])
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.NAMED_VIEW_RENAMED,
                    {"named_view_uid": "nv1", "name": "New"},
                )
            ],
        )

    def test_annotation_text_and_box_changes_are_saved_together(self):
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
        )
        handler.on_annotation_text_and_positions_flushed(
            [
                (
                    "a1",
                    "text",
                    {"FontSize": 12, "FontColor": 0},
                    {"FontSize": 24, "FontColor": 0x332211},
                )
            ],
            [("a1", "text", [100.0, 100.0, 40.0, 15.0], [100.0, 100.0, 80.0, 30.0])],
        )
        self.assertEqual(
            ann_write.text_and_position_calls[0],
            (
                "bid.mdb",
                [("a1", "text", {"FontSize": 24, "FontColor": 0x332211})],
                [("a1", "text", [100.0, 100.0, 80.0, 30.0])],
            ),
        )
        self.assertEqual(ann_write.text_property_calls, [])
        self.assertEqual(ann_write.position_calls, [])
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.text_and_position_calls[1:],
            [
                (
                    "bid.mdb",
                    [("a1", "text", {"FontSize": 12, "FontColor": 0})],
                    [("a1", "text", [100.0, 100.0, 40.0, 15.0])],
                ),
                (
                    "bid.mdb",
                    [("a1", "text", {"FontSize": 24, "FontColor": 0x332211})],
                    [("a1", "text", [100.0, 100.0, 80.0, 30.0])],
                ),
            ],
        )

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
        self.assertEqual(write.calls[0][2][0].position[:2], [100.0, 200.0])
        self.assertEqual(write.calls[1][2][0].parent_uid, "new-parent")
        self.assertEqual(write.calls[1][2][0].position[:2], [100.5, 200.5])
        self.assertEqual(write.calls[1][2][0].raw_extras, {"Raw": "kept"})
        self.assertEqual(
            plan_view.intelligent_paste_calls,
            [(["new-parent", "new-hole"], (0.0, 0.0))],
        )
        self.assertEqual(plan_view.selected, {"new-parent", "new-hole"})
        undo.undo()
        self.assertEqual(write.delete_calls[-1][1], ["new-parent", "new-hole"])
        write.uid_batches = [["redo-parent"], ["redo-hole"]]
        undo.redo()
        self.assertEqual(write.calls[-2][2][0].parent_uid, "0")
        self.assertEqual(write.calls[-1][2][0].parent_uid, "redo-parent")
        self.assertEqual(write.calls[-1][2][0].raw_extras, {"Raw": "kept"})
        self.assertEqual(plan_view.selected, {"redo-parent", "redo-hole"})

    def test_intelligent_paste_enabled_pastes_regular_takeoff_at_mouse(self):
        source = Takeoff(
            uid="source",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 14.0, 20.0],
            parent_uid="0",
        )
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = (50.0, 75.0)
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(len(write.calls), 1)
        self.assertEqual(write.calls[0][2][0].position, [50.0, 75.0, 54.0, 75.0])
        self.assertEqual(plan_view.intelligent_paste_calls, [(["100"], (10.0, 20.0))])

    def test_intelligent_paste_disabled_uses_existing_offset_paste(self):
        source = Takeoff(
            uid="source",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 14.0, 20.0],
            parent_uid="0",
        )
        plan_view = FakePlanView()
        plan_view.intelligent_paste_enabled = False
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(len(write.calls), 1)
        self.assertEqual(write.calls[0][2][0].position, [11.0, 21.0, 15.0, 21.0])
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def test_intelligent_paste_enabled_pastes_annotation_at_mouse(self):
        source = self._copied_annotation()
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = (50.0, 75.0)
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        handler._clipboard_svc = FakeClipboard([], annotations=[source])

        handler.on_paste_requested()

        self.assertEqual(len(ann_write.insert_calls), 1)
        specs = ann_write.insert_calls[0][2]
        self.assertEqual(specs[0].position, [50.0, 75.0, 54.0, 75.0])
        self.assertEqual(plan_view.selected, {"ann-1"})
        self.assertEqual(
            plan_view.intelligent_paste_calls,
            [(["ann-1"], (10.0, 20.0))],
        )

    def test_intelligent_paste_disabled_pastes_annotation_with_legacy_offset(self):
        source = self._copied_annotation()
        plan_view = FakePlanView()
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        handler._clipboard_svc = FakeClipboard([], annotations=[source])

        handler.on_paste_requested()

        self.assertEqual(len(ann_write.insert_calls), 1)
        specs = ann_write.insert_calls[0][2]
        self.assertEqual(specs[0].position, [11.0, 21.0, 15.0, 21.0])
        self.assertEqual(plan_view.selected, {"ann-1"})
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def test_intelligent_paste_enabled_pastes_mixed_clipboard_at_mouse(self):
        takeoff = self._copied_takeoff()
        annotation = self._copied_annotation(position=[20.0, 30.0, 24.0, 30.0])
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = (50.0, 75.0)
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write
        )
        handler._clipboard_svc = FakeClipboard([takeoff], annotations=[annotation])

        handler.on_paste_requested()

        self.assertEqual(len(write.calls), 1)
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(write.calls[0][2][0].position, [50.0, 75.0, 54.0, 75.0])
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [60.0, 85.0, 64.0, 85.0],
        )
        self.assertEqual(plan_view.selected, {"100", "ann-1"})
        self.assertEqual(
            plan_view.intelligent_paste_calls,
            [(["100", "ann-1"], (10.0, 20.0))],
        )

    def test_intelligent_paste_disabled_pastes_mixed_clipboard_with_legacy_offset(self):
        takeoff = self._copied_takeoff()
        annotation = self._copied_annotation(position=[20.0, 30.0, 24.0, 30.0])
        plan_view = FakePlanView()
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write
        )
        handler._clipboard_svc = FakeClipboard([takeoff], annotations=[annotation])

        handler.on_paste_requested()

        self.assertEqual(len(write.calls), 1)
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(write.calls[0][2][0].position, [11.0, 21.0, 15.0, 21.0])
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [21.0, 31.0, 25.0, 31.0],
        )
        self.assertEqual(plan_view.selected, {"100", "ann-1"})
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def test_intelligent_paste_text_annotation_moves_center_only(self):
        source = self._copied_annotation(
            uid="source-text",
            annotation_type="text",
            position=[10.0, 20.0, 100.0, 50.0],
            color="#000000",
        )
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = (50.0, 75.0)
        plan_view.annotation_key_map = {("ann-1", "text"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        handler._clipboard_svc = FakeClipboard([], annotations=[source])

        handler.on_paste_requested()

        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [50.0, 75.0, 100.0, 50.0],
        )

    def test_intelligent_paste_off_blocks_holes_only_backout_paste(self):
        hole = Takeoff(
            uid="old-hole",
            condition_uid="c1",
            page_uid="source-page",
            position=[0.5, 0.5, 1.0, 0.5, 1.0, 1.0],
            parent_uid="old-parent",
        )
        plan_view = FakePlanView()
        plan_view.intelligent_paste_enabled = False
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        handler._clipboard_svc = FakeClipboard([hole])
        handler.on_paste_requested()
        self.assertEqual(plan_view.paste_backout_calls, [])
        self.assertEqual(write.calls, [])

    def test_intelligent_paste_on_uses_holes_only_backout_paste(self):
        hole = Takeoff(
            uid="old-hole",
            condition_uid="c1",
            page_uid="source-page",
            position=[0.5, 0.5, 1.0, 0.5, 1.0, 1.0],
            parent_uid="old-parent",
        )
        plan_view = FakePlanView()
        write = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
        )
        handler._clipboard_svc = FakeClipboard([hole])
        handler.on_paste_requested()
        self.assertEqual(len(plan_view.paste_backout_calls), 1)
        self.assertEqual(write.calls, [])

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
