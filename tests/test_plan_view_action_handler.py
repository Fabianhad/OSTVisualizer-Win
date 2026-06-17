import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as handler_module,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.page_selection_service import PageSelectionService
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.services.selection_commands import (
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
)


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
        self.annotations = {}
        self.restored_positions = []
        self.restored_rotations = []
        self.restored_condition_text_properties = []
        self.restored_text_properties = []
        self.restored_text_and_positions = []
        self.restored_annotation_styles = []
        self.activated_annotations = []
        self.named_view_name_validator = None

    def set_selected_uids(self, uids):
        self.selected = set(uids)

    def clear_selection(self):
        self.clears += 1
        self.selected = set()

    def get_takeoff(self, uid):
        if self.data is None:
            return None
        return self.data.get_takeoff(uid)

    def get_annotation(self, uid):
        return self.annotations.get(uid)

    def find_annotation_keys_by_uid_type(self, uid_type_set):
        return {
            self.annotation_key_map[(uid, ann_type)]
            for uid, ann_type in uid_type_set
            if (uid, ann_type) in self.annotation_key_map
        }

    def restore_flushed_positions(self, takeoff_changes, ann_changes):
        self.restored_positions.append((list(takeoff_changes), list(ann_changes)))

    def restore_flushed_rotations(self, rotation_changes):
        self.restored_rotations.append(list(rotation_changes))

    def restore_condition_text_properties(self, changes):
        self.restored_condition_text_properties.append(list(changes))

    def restore_annotation_text_properties(self, changes):
        self.restored_text_properties.append(list(changes))

    def restore_annotation_text_and_positions(self, text_changes, ann_position_changes):
        self.restored_text_and_positions.append(
            (list(text_changes), list(ann_position_changes))
        )

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles.append(list(changes))

    def cancel_place_mode(self):
        self.cancel_place_mode_calls += 1

    def activate_annotation_placement(self, annotation_type):
        self.activated_annotations.append(annotation_type)
        return True

    def set_named_view_name_validator(self, validator):
        self.named_view_name_validator = validator

    def begin_paste_backout(self, holes, extras_by_uid, source_bid_uid):
        self.paste_backout_calls.append((holes, extras_by_uid, source_bid_uid))

    def current_mouse_ost_position(self):
        return self.mouse_ost_position

    def mark_intelligent_paste_drag_pending(self, pasted_uids, source_anchor_ost):
        self.intelligent_paste_calls.append((list(pasted_uids), source_anchor_ost))
        return True

    def get_coordinate_system(self):
        return SimpleNamespace(parse_position=lambda position: list(position))


class FakeUiState:
    place_condition_uids = []
    active_page_uid = "p1"

    def get_selected_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="7")


class FakeProjectData:
    def __init__(self):
        self.added_takeoffs = []
        self.takeoffs = {}
        self.extras = {}
        self.named_view_updates = []
        self.annotations = []
        self.added_annotations = []
        self.removed_annotation_uids = []
        self.page_names = {"p1": "Page 1"}
        self.pages = {"p1": SimpleNamespace(uid="p1", overlay_rect=None)}
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

    def get_page(self, page_uid):
        return self.pages.get(page_uid)

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
            if uid not in self.takeoffs:
                continue
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

    def add_annotations(self, annotations):
        self.added_annotations.extend(annotations)
        replacement_keys = {
            (str(annotation.uid), str(annotation.annotation_type))
            for annotation in annotations
        }
        self.annotations = [
            annotation
            for annotation in self.annotations
            if (str(annotation.uid), str(annotation.annotation_type))
            not in replacement_keys
        ]
        self.annotations.extend(annotations)

    def remove_annotations_by_keys(self, annotation_keys):
        page_uids = []
        wanted = {
            (str(uid), str(annotation_type)) for uid, annotation_type in annotation_keys
        }
        self.removed_annotation_uids.extend(uid for uid, _type in annotation_keys)
        kept = []
        for annotation in self.annotations:
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key not in wanted:
                kept.append(annotation)
                continue
            if annotation.page_uid not in page_uids:
                page_uids.append(annotation.page_uid)
        self.annotations = kept
        return page_uids

    def update_annotation_positions(self, positions):
        page_uids = []
        for uid, annotation_type, position in positions:
            for annotation in self.annotations:
                if (
                    annotation.uid == uid
                    and annotation.annotation_type == annotation_type
                ):
                    annotation.position = list(position)
                    if annotation.page_uid not in page_uids:
                        page_uids.append(annotation.page_uid)
        return page_uids

    def update_annotation_text_properties(self, updates):
        page_uids = []
        for uid, annotation_type, properties in updates:
            for annotation in self.annotations:
                if (
                    annotation.uid == uid
                    and annotation.annotation_type == annotation_type
                ):
                    annotation.properties.update(dict(properties))
                    if annotation.page_uid not in page_uids:
                        page_uids.append(annotation.page_uid)
        return page_uids

    def update_annotation_styles(self, updates):
        page_uids = []
        for uid, annotation_type, style in updates:
            for annotation in self.annotations:
                if (
                    annotation.uid == uid
                    and annotation.annotation_type == annotation_type
                ):
                    if "Color" in style:
                        annotation.color = style["Color"]
                    if "Width" in style:
                        annotation.width = float(style["Width"])
                    if annotation.page_uid not in page_uids:
                        page_uids.append(annotation.page_uid)
        return page_uids

    def remove_takeoffs(self, uids):
        page_uids = []
        for uid in uids:
            takeoff = self.takeoffs.pop(uid, None)
            if takeoff and takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def find_hotlinks_targeting(self, uids):
        target_uids = {str(uid) for uid in uids}
        return [
            annotation
            for annotation in self.annotations
            if annotation.is_hotlink
            and annotation.hotlink_target_view_uid in target_uids
        ]

    def get_all_annotations(self):
        return list(self.annotations)

    def get_page_name(self, page_uid):
        return self.page_names.get(page_uid, "")


class FakeWriteService:
    def __init__(self):
        self.calls = []
        self.condition_calls = []
        self.condition_duplicate_calls = []
        self.update_condition_calls = []
        self.position_calls = []
        self.rotation_calls = []
        self.text_property_calls = []
        self.delete_calls = []
        self.curve_calls = []
        self.reloads = []
        self.next_uids = ["100"]
        self.uid_batches = []
        self._next_uid_index = 0

    def insert_takeoffs(
        self, db_path, bid_uid, specs, publish_database_refreshed_after_write=True
    ):
        self.calls.append(
            (db_path, bid_uid, specs, publish_database_refreshed_after_write)
        )
        if self.uid_batches:
            return list(self.uid_batches.pop(0))
        start = self._next_uid_index
        end = start + len(specs)
        result = list(self.next_uids[start:end])
        while len(result) < len(specs):
            result.append(str(100 + self._next_uid_index + len(result)))
        self._next_uid_index += len(specs)
        return result

    def save_takeoff_positions(
        self, db_path, positions, publish_database_refreshed_after_write=True
    ):
        self.position_calls.append(
            (db_path, positions, publish_database_refreshed_after_write)
        )
        return True

    def save_takeoff_rotations(
        self, db_path, rotations, publish_database_refreshed_after_write=True
    ):
        self.rotation_calls.append(
            (db_path, rotations, publish_database_refreshed_after_write)
        )
        return True

    def save_takeoff_text_properties(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.text_property_calls.append(
            (db_path, updates, publish_database_refreshed_after_write)
        )
        return True

    def save_takeoffs_condition(self, db_path, uids, condition_uid):
        self.condition_calls.append((db_path, list(uids), condition_uid))
        return True

    def delete_takeoffs(
        self, db_path, uids, publish_database_refreshed_after_write=True
    ):
        self.delete_calls.append(
            (db_path, list(uids), publish_database_refreshed_after_write)
        )
        return True

    def set_takeoff_curve(
        self,
        db_path,
        takeoff_uid,
        position,
        curve,
        publish_database_refreshed_after_write=True,
    ):
        self.curve_calls.append(
            (
                db_path,
                takeoff_uid,
                list(position),
                curve,
                publish_database_refreshed_after_write,
            )
        )
        return True

    def reload_and_notify(self, db_path):
        self.reloads.append(db_path)
        return True

    def duplicate_conditions_to_bid(
        self,
        db_path,
        source_bid_uid,
        target_bid_uid,
        source_condition_uids,
        publish_database_refreshed_after_write=True,
    ):
        self.condition_duplicate_calls.append(
            (
                db_path,
                source_bid_uid,
                target_bid_uid,
                list(source_condition_uids),
                publish_database_refreshed_after_write,
            )
        )
        return {str(uid): f"new-{uid}" for uid in source_condition_uids}

    def update_condition(
        self,
        db_path,
        bid_uid,
        condition_uid,
        updates,
        all_conditions=None,
        publish_database_refreshed_after_write=True,
    ):
        self.update_condition_calls.append(
            (
                db_path,
                bid_uid,
                condition_uid,
                updates.get_changes(),
                all_conditions,
                publish_database_refreshed_after_write,
            )
        )
        return SimpleNamespace(success=True)


class FakeDeferredPersistence:
    def __init__(self):
        self.overlay_rect_calls = []

    def schedule_page_overlay_rect(self, db_path, page_uid, overlay_rect):
        self.overlay_rect_calls.append((db_path, page_uid, overlay_rect))


class FakeAnnotationWriteService:
    def __init__(self):
        self.position_calls = []
        self.text_property_calls = []
        self.text_and_position_calls = []
        self.style_calls = []
        self.insert_calls = []
        self.delete_calls = []
        self.next_uids = ["ann-1"]

    def save_annotation_positions(
        self, db_path, positions, publish_database_refreshed_after_write=True
    ):
        self.position_calls.append(
            (db_path, positions, publish_database_refreshed_after_write)
        )
        return True

    def save_annotation_text_properties(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.text_property_calls.append(
            (db_path, updates, publish_database_refreshed_after_write)
        )
        return True

    def save_annotation_text_properties_and_positions(
        self, db_path, updates, positions, publish_database_refreshed_after_write=True
    ):
        self.text_and_position_calls.append(
            (db_path, updates, positions, publish_database_refreshed_after_write)
        )
        return True

    def save_annotation_styles(
        self, db_path, updates, publish_database_refreshed_after_write=True
    ):
        self.style_calls.append(
            (db_path, updates, publish_database_refreshed_after_write)
        )
        return True

    def insert_annotations(
        self,
        db_path,
        bid_uid,
        specs,
        ref_remap=None,
        publish_database_refreshed_after_write=True,
    ):
        self.insert_calls.append(
            (
                db_path,
                bid_uid,
                specs,
                ref_remap,
                publish_database_refreshed_after_write,
            )
        )
        return list(self.next_uids[: len(specs)])

    def delete_annotations(
        self, db_path, annotation_keys, publish_database_refreshed_after_write=True
    ):
        self.delete_calls.append(
            (db_path, annotation_keys, publish_database_refreshed_after_write)
        )
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
    def tearDown(self):
        for annotation_type in (
            "dimension",
            "text",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            set_annotation_style_for_tool(
                annotation_type,
                color="#ff0000",
                line_width=4.0,
                font_name="Arial",
                font_size=12,
                font_bold=False,
                font_italic=False,
                font_underline=False,
                text_align=0,
            )

    def test_markup_annotation_default_line_width_is_four_pixels(self):
        for annotation_type in (
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                spec = build_placed_annotation_spec(
                    annotation_type, "p1", [1.0, 2.0, 13.0, 14.0]
                )
                self.assertEqual(spec.width, 4.0)
                self.assertEqual(spec.color, "#ff0000")
        highlight_spec = build_placed_annotation_spec(
            "highlight", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(highlight_spec.width, 0.0)
        self.assertEqual(highlight_spec.color, "#ff0000")

    def test_per_tool_annotation_style_applies_to_new_markup_annotations(self):
        for annotation_type in (
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
            "highlight",
        ):
            with self.subTest(annotation_type=annotation_type):
                set_annotation_style_for_tool(
                    annotation_type, color="#336699", line_width=9.0
                )
                ann_write = FakeAnnotationWriteService()
                handler = PlanViewActionHandler(
                    plan_view=FakePlanView(),
                    ui_state_manager=FakeUiState(),
                    project_data_svc=FakeProjectData(),
                    project_write_svc=FakeWriteService(),
                    annotation_write_svc=ann_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=FakeUndoService(),
                    event_bus=FakeEventBus(),
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
                )
                position = (
                    [1.0, 2.0, 13.0, 2.0, 8.0, 9.0]
                    if annotation_type in ("polygon", "cloud")
                    else [1.0, 2.0, 13.0, 2.0]
                )
                handler.on_annotation_created(annotation_type, position, "p1")
                (
                    _db_path,
                    _bid_uid,
                    specs,
                    _ref_remap,
                    publish_database_refreshed_after_write,
                ) = ann_write.insert_calls[0]
                self.assertEqual(specs[0].color, "#336699")
                self.assertFalse(publish_database_refreshed_after_write)
                expected_width = 0.0 if annotation_type == "highlight" else 9.0
                self.assertEqual(specs[0].width, expected_width)

    def test_each_annotation_tool_default_is_independent(self):
        defaults = {
            "arrow": ("#110000", 2.0),
            "line": ("#002200", 3.0),
            "rect": ("#000033", 4.0),
            "oval": ("#445500", 5.0),
            "polygon": ("#006666", 6.0),
            "cloud": ("#770077", 7.0),
            "ink": ("#117777", 8.0),
            "highlight": ("#227788", 11.0),
            "text": ("#888800", 8.0),
            "dimension": ("#009999", 10.0),
        }
        for annotation_type, (color, width) in defaults.items():
            set_annotation_style_for_tool(
                annotation_type, color=color, line_width=width
            )
        set_annotation_style_for_tool(
            "text",
            font_name="Segoe UI",
            font_size=18,
            font_bold=True,
            font_italic=True,
            font_underline=True,
            text_align=1,
        )
        for annotation_type, (color, width) in defaults.items():
            with self.subTest(annotation_type=annotation_type):
                spec = build_placed_annotation_spec(
                    annotation_type, "p1", [1.0, 2.0, 13.0, 14.0]
                )
                self.assertEqual(spec.color, color)
                if annotation_type == "dimension":
                    self.assertEqual(spec.width, 1.0)
                elif annotation_type in ("text", "highlight"):
                    self.assertEqual(spec.width, 0.0)
                else:
                    self.assertEqual(spec.width, width)
        text_spec = build_placed_annotation_spec("text", "p1", [1.0, 2.0, 13.0, 14.0])
        self.assertEqual(text_spec.properties["FontColor"], 0x008888)
        self.assertEqual(text_spec.properties["FontName"], "Segoe UI")
        self.assertEqual(text_spec.properties["FontSize"], 18)
        self.assertTrue(text_spec.properties["FontBold"])
        self.assertTrue(text_spec.properties["FontItalic"])
        self.assertTrue(text_spec.properties["FontUnderline"])
        self.assertEqual(text_spec.properties["TextAlign"], 1)
        dimension_spec = build_placed_annotation_spec(
            "dimension", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(dimension_spec.properties["FontColor"], "#009999")
        self.assertEqual(dimension_spec.width, 1.0)
        set_annotation_style_for_tool(
            "dimension",
            font_name="Calibri",
            font_size=16,
            font_bold=True,
            font_italic=True,
            font_underline=True,
        )
        dimension_spec = build_placed_annotation_spec(
            "dimension", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(dimension_spec.properties["FontName"], "Calibri")
        self.assertEqual(dimension_spec.properties["FontSize"], 16)
        self.assertTrue(dimension_spec.properties["FontBold"])
        self.assertTrue(dimension_spec.properties["FontItalic"])
        self.assertTrue(dimension_spec.properties["FontUnderline"])

    def test_overlay_rect_updates_model_immediately_and_defers_persistence(self):
        data = FakeProjectData()
        write = FakeWriteService()
        deferred = FakeDeferredPersistence()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            ui_access_manager=FakeAccess({Feature.EDIT_PAGE_SETTINGS}),
            deferred_persistence_manager=deferred,
        )
        result = handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25))
        self.assertTrue(result.write_success)
        self.assertEqual(data.get_page("p1").overlay_rect, (1.0, 2.5, 3.0, 4.25))
        self.assertEqual(
            deferred.overlay_rect_calls,
            [("bid.mdb", "p1", (1.0, 2.5, 3.0, 4.25))],
        )

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_set_curved_batches_reload_until_after_all_curve_updates(self):
        data = FakeProjectData()
        data.takeoffs = {
            "t1": Takeoff(
                uid="t1",
                condition_uid="42",
                page_uid="p1",
                position=[0.0, 0.0, 10.0, 0.0],
            ),
            "t2": Takeoff(
                uid="t2",
                condition_uid="42",
                page_uid="p1",
                position=[0.0, 10.0, 10.0, 10.0],
            ),
        }
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_set_curved(["t1", "t2"], True)
        self.assertEqual(len(write.curve_calls), 2)
        self.assertEqual([call[4] for call in write.curve_calls], [False, False])
        self.assertEqual(write.reloads, ["bid.mdb"])

    def test_denied_plan_item_selection_access_blocks_plan_view_write_signals(self):
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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set()),
        )
        handler.on_elements_deleted(["t1"])
        handler.on_positions_flushed([("t1", [1.0, 2.0], [3.0, 4.0])], [])
        handler.on_takeoff_created("42", [1.0, 2.0], "p1")
        self.assertEqual(write.delete_calls, [])
        self.assertEqual(write.position_calls, [])
        self.assertEqual(write.calls, [])

    def test_annotation_created_uses_annotation_write_path(self):
        for annotation_type in (
            "dimension",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                plan_view = FakePlanView()
                plan_view.annotation_key_map = {("ann-1", annotation_type): "ann-1"}
                ann_write = FakeAnnotationWriteService()
                undo = FakeUndoService()
                handler = PlanViewActionHandler(
                    plan_view=plan_view,
                    ui_state_manager=FakeUiState(),
                    project_data_svc=FakeProjectData(),
                    project_write_svc=FakeWriteService(),
                    annotation_write_svc=ann_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=undo,
                    event_bus=FakeEventBus(),
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
                )
                position = (
                    [1.0, 2.0, 13.0, 2.0, 8.0, 9.0]
                    if annotation_type in ("polygon", "cloud")
                    else [1.0, 2.0, 13.0, 2.0]
                )
                handler.on_annotation_created(annotation_type, position, "p1")
                self.assertEqual(len(ann_write.insert_calls), 1)
                (
                    _db_path,
                    _bid_uid,
                    specs,
                    _ref_remap,
                    publish_database_refreshed_after_write,
                ) = ann_write.insert_calls[0]
                self.assertEqual(specs[0].annotation_type, annotation_type)
                self.assertEqual(specs[0].position, position)
                self.assertFalse(publish_database_refreshed_after_write)
                if annotation_type == "dimension":
                    self.assertEqual(specs[0].properties["FontName"], "Arial")
                    self.assertEqual(specs[0].properties["FontColor"], "#ff0000")
                self.assertEqual(plan_view.selected, {"ann-1"})
                self.assertEqual(undo.count, 1)

    def test_text_annotation_created_commits_non_empty_text_through_write_path(self):
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {("ann-1", "text"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        properties = {
            "Text": "Hello",
            "FontName": "Arial",
            "FontColor": 0x336699,
            "FontSize": 12,
            "FontBold": False,
            "FontItalic": False,
            "FontUnderline": False,
            "TextAlign": 0,
        }
        handler.on_text_annotation_created([7.0, 8.0, 12.0, 12.0], "p1", properties)
        self.assertEqual(len(ann_write.insert_calls), 1)
        (
            _db_path,
            _bid_uid,
            specs,
            _ref_remap,
            publish_database_refreshed_after_write,
        ) = ann_write.insert_calls[0]
        self.assertEqual(specs[0].annotation_type, "text")
        self.assertEqual(specs[0].position, [7.0, 8.0, 12.0, 12.0])
        self.assertEqual(specs[0].properties, properties)
        self.assertEqual(specs[0].color, "#996633")
        self.assertFalse(publish_database_refreshed_after_write)
        self.assertEqual(plan_view.selected, {"ann-1"})
        self.assertEqual(undo.count, 1)

    def test_non_navigation_annotation_placement_emits_only_annotation_refresh(self):
        data = FakeProjectData()
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {("ann-1", "rect"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["ann-1"],
                        "annotation_types": ["rect"],
                    },
                )
            ],
        )
        self.assertEqual(len(data.added_annotations), 1)
        self.assertEqual(data.added_annotations[0].annotation_type, "rect")
        self.assertEqual(data.added_annotations[0].position, [1.0, 2.0, 5.0, 6.0])

    def test_in_memory_annotation_add_replaces_existing_uid(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p1",
                    position=[1.0, 1.0],
                ),
                BidAnnotation(
                    uid="a1",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[4.0, 4.0],
                ),
                BidAnnotation(
                    uid="a2",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[2.0, 2.0],
                ),
            ]
        )
        service.add_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p2",
                    position=[3.0, 3.0],
                )
            ]
        )
        annotations = service.get_all_annotations()
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in annotations],
            [("a1", "oval"), ("a2", "oval"), ("a1", "rect")],
        )
        self.assertEqual(annotations[0].page_uid, "p1")
        self.assertEqual(annotations[0].position, [4.0, 4.0])
        self.assertEqual(annotations[-1].page_uid, "p2")
        self.assertEqual(annotations[-1].position, [3.0, 3.0])

    def test_in_memory_annotation_remove_by_key_preserves_same_uid_other_type(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1"),
                BidAnnotation(uid="a1", annotation_type="oval", page_uid="p2"),
            ]
        )
        page_uids = service.remove_annotations_by_keys([("a1", "rect")])
        self.assertEqual(page_uids, ["p1"])
        self.assertEqual(
            [
                (a.uid, a.annotation_type, a.page_uid)
                for a in service.get_all_annotations()
            ],
            [("a1", "oval", "p2")],
        )

    def test_unknown_annotation_update_does_not_emit_refresh(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="rect",
                page_uid="p1",
                position=[1.0, 2.0],
            )
        ]
        ann_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_annotation_styles_flushed(
            [("missing", "rect", {"Color": "#000000"}, {"Color": "#ffffff"})]
        )
        self.assertEqual(
            ann_write.style_calls,
            [("bid.mdb", [("missing", "rect", {"Color": "#ffffff"})], False)],
        )
        self.assertEqual(event_bus.events, [])
        self.assertEqual(data.annotations[0].color, "#FF0000")

    def test_unknown_annotation_delete_does_not_emit_refresh(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        ]
        page_uids = data.remove_annotations_by_keys([("missing", "rect")])
        self.assertEqual(page_uids, [])
        self.assertEqual([annotation.uid for annotation in data.annotations], ["a1"])

    def test_annotation_placement_undo_redo_uses_page_scoped_refresh(self):
        data = FakeProjectData()
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {
            ("ann-1", "rect"): "ann-1",
            ("ann-2", "rect"): "ann-2",
        }
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = ["ann-1", "ann-2"]
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        ann_write.next_uids = ["ann-2"]
        undo.undo()
        undo.redo()
        self.assertEqual([call[4] for call in ann_write.insert_calls], [False, False])
        self.assertEqual(
            ann_write.delete_calls, [("bid.mdb", [("ann-1", "rect")], False)]
        )
        self.assertEqual(
            [event[0] for event in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED] * 3,
        )
        self.assertEqual(data.removed_annotation_uids, ["ann-1"])
        self.assertEqual(plan_view.selected, {"ann-2"})

    def test_empty_text_annotation_commit_is_not_written(self):
        ann_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        handler.on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "   ", "FontColor": 0x336699},
        )
        self.assertEqual(ann_write.insert_calls, [])

    def test_named_view_created_commits_non_empty_name_through_write_path(self):
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {("ann-1", "namedview"): "ann-1_namedview"}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        handler.on_named_view_created(
            position,
            "p1",
            {"Text": " Lobby View ", "Color": "#008000"},
        )
        self.assertEqual(len(ann_write.insert_calls), 1)
        (
            _db_path,
            _bid_uid,
            specs,
            _ref_remap,
            publish_database_refreshed_after_write,
        ) = ann_write.insert_calls[0]
        self.assertEqual(specs[0].annotation_type, "namedview")
        self.assertEqual(specs[0].position, position)
        self.assertEqual(specs[0].properties, {"Text": "Lobby View"})
        self.assertEqual(specs[0].color, "#008000")
        self.assertFalse(publish_database_refreshed_after_write)
        self.assertEqual(plan_view.selected, {"ann-1_namedview"})
        self.assertEqual(undo.count, 1)
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["ann-1"],
                        "annotation_types": ["namedview"],
                    },
                ),
                (
                    AppEvents.NAMED_VIEW_CREATED,
                    {
                        "named_view_uid": "ann-1",
                        "page_uid": "p1",
                        "name": "Lobby View",
                    },
                ),
            ],
        )

    def test_empty_named_view_commit_is_not_written(self):
        ann_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )
        handler.on_named_view_created(
            [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            "p1",
            {"Text": "   "},
        )
        self.assertEqual(ann_write.insert_calls, [])

    def test_hotlink_request_uses_dialog_selection_and_write_path(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(
                uid="nv1",
                annotation_type="namedview",
                page_uid="p2",
                position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
                properties={"Text": "Lobby"},
            )
        ]
        data.page_names["p2"] = "A101"
        ann_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        plan_view = FakePlanView(data)
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )

        class FakeDialog:
            captured_named_views = None

            def __init__(self, named_views, parent=None):
                FakeDialog.captured_named_views = list(named_views)

            def exec(self):
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid="nv1")

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(
            FakeDialog.captured_named_views,
            [("nv1", "p2", "A101", "Lobby")],
        )
        self.assertEqual(len(ann_write.insert_calls), 1)
        (
            _db_path,
            _bid_uid,
            specs,
            _ref_remap,
            publish_database_refreshed_after_write,
        ) = ann_write.insert_calls[0]
        self.assertEqual(specs[0].annotation_type, "hotlink")
        self.assertEqual(specs[0].position, [9.0, 11.0])
        self.assertEqual(specs[0].properties, {"BidPageViewUID": "nv1"})
        self.assertFalse(publish_database_refreshed_after_write)
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["ann-1"],
                        "annotation_types": ["hotlink"],
                    },
                )
            ],
        )

    def test_hotlink_create_new_switches_to_named_view_tool_without_write(self):
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_PLAN_ITEMS}),
        )

        class FakeDialog:
            def __init__(self, named_views, parent=None):
                pass

            def exec(self):
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, ["namedview"])

    def test_denied_place_plan_items_access_blocks_text_commit_write(self):
        ann_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set()),
        )
        handler.on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "Hello", "FontColor": 0x336699},
        )
        self.assertEqual(ann_write.insert_calls, [])

    def test_denied_place_plan_items_access_blocks_annotation_placement_write(self):
        for annotation_type in (
            "dimension",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                ann_write = FakeAnnotationWriteService()
                handler = PlanViewActionHandler(
                    plan_view=FakePlanView(),
                    ui_state_manager=FakeUiState(),
                    project_data_svc=FakeProjectData(),
                    project_write_svc=FakeWriteService(),
                    annotation_write_svc=ann_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=FakeUndoService(),
                    event_bus=FakeEventBus(),
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess(set()),
                )
                handler.on_annotation_created(
                    annotation_type, [1.0, 2.0, 13.0, 2.0], "p1"
                )
                self.assertEqual(ann_write.insert_calls, [])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        handler.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        )
        self.assertEqual(annotation_write.text_property_calls, [])

    def test_annotation_style_change_writes_only_target_annotation(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        ]
        annotation_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        changes = [
            (
                "a1",
                "rect",
                {"Color": "#ff0000", "Width": 4.0},
                {"Color": "#336699", "Width": 7.0},
            )
        ]
        handler.on_annotation_styles_flushed(changes)
        self.assertEqual(
            annotation_write.style_calls,
            [
                (
                    "bid.mdb",
                    [("a1", "rect", {"Color": "#336699", "Width": 7.0})],
                    False,
                )
            ],
        )
        self.assertEqual(data.annotations[0].color, "#336699")
        self.assertEqual(data.annotations[0].width, 7.0)
        self.assertEqual(event_bus.events[0][0], AppEvents.ANNOTATIONS_CHANGED)
        self.assertEqual(undo.count, 1)
        undo.undo()
        undo.redo()
        self.assertEqual(
            annotation_write.style_calls[-2:],
            [
                (
                    "bid.mdb",
                    [("a1", "rect", {"Color": "#ff0000", "Width": 4.0})],
                    False,
                ),
                (
                    "bid.mdb",
                    [("a1", "rect", {"Color": "#336699", "Width": 7.0})],
                    False,
                ),
            ],
        )

    def test_annotation_style_change_page_scope_matches_uid_and_type(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1"),
            BidAnnotation(uid="a1", annotation_type="oval", page_uid="p2"),
        ]
        annotation_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        handler.on_annotation_styles_flushed(
            [("a1", "rect", {"Color": "#ff0000"}, {"Color": "#336699"})]
        )
        self.assertEqual(data.annotations[0].color, "#336699")
        self.assertEqual(data.annotations[1].color, "#FF0000")
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["a1"],
                        "annotation_types": ["rect"],
                    },
                )
            ],
        )

    def test_denied_plan_item_access_blocks_annotation_style_write(self):
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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set()),
        )
        handler.on_annotation_styles_flushed(
            [("a1", "rect", {"Color": "#ff0000"}, {"Color": "#336699"})]
        )
        self.assertEqual(annotation_write.style_calls, [])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_failed_condition_label_text_property_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_text_properties = lambda *args, **kwargs: False
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.EDIT_CONDITION}),
        )
        changes = [
            (
                "t1",
                "display_name",
                {"name_font_size": 9},
                {"name_font_size": 24},
            )
        ]
        handler.on_condition_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_unchecked_3d_page_fast_place_keeps_new_takeoff_selected(self):
        class ActiveUncheckedPageUiState(FakeUiState):
            active_page_uid = "p2"

        class ValidatingPlanView(FakePlanView):
            def __init__(self, data):
                super().__init__(data)
                self.current_page_uid = "p2"
                self._current_takeoffs = {}
                self.clear_calls = 0

            def set_selected_uids(self, uids):
                self.selected = {uid for uid in uids if uid in self._current_takeoffs}

            def clear(self):
                self.clear_calls += 1
                self.current_page_uid = None
                self._current_takeoffs = {}
                self.selected = set()

        class VisualizationService:
            def __init__(self):
                self.mesh_pages = []

            def refresh_mesh_view(self, page_uids):
                self.mesh_pages.append(list(page_uids))

        class OpenGLViewer:
            def __init__(self):
                self.clears = 0

            def clear_scene(self):
                self.clears += 1
                # Programmatic 3D clears must not emit mesh_clicked([]).

        class SyncEventBus(FakeEventBus):
            def __init__(self, on_takeoffs_changed):
                super().__init__()
                self._on_takeoffs_changed = on_takeoffs_changed

            def publish(self, event_name, **kwargs):
                super().publish(event_name, **kwargs)
                if event_name == AppEvents.TAKEOFFS_CHANGED:
                    self._on_takeoffs_changed(**kwargs)

        data = FakeProjectData()
        data.selected_page_uids = []
        plan_view = ValidatingPlanView(data)
        visualization = VisualizationService()
        viewer = ViewerSyncCoordinator(
            ui_state_manager=ActiveUncheckedPageUiState(),
            ui_access_manager=None,
            color_service=None,
            project_data=data,
            visualization_service=visualization,
        )
        viewer.plan_view = plan_view
        viewer.opengl_viewer = OpenGLViewer()

        def on_takeoffs_changed(page_uid, **_kwargs):
            plan_view.current_page_uid = page_uid
            plan_view._current_takeoffs = {
                uid: takeoff
                for uid, takeoff in data.takeoffs.items()
                if takeoff.page_uid == page_uid
            }
            viewer.update_viewers([])

        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ActiveUncheckedPageUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=SyncEventBus(on_takeoffs_changed),
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "p2")
        self.assertEqual(plan_view.selected, {"100"})
        self.assertEqual(plan_view.current_page_uid, "p2")
        self.assertEqual(plan_view.clear_calls, 0)
        self.assertEqual(viewer.opengl_viewer.clears, 1)
        self.assertEqual(visualization.mesh_pages, [[]])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_reassign_condition(["t1", "missing"], "42")
        handler.on_reassign_condition(["t1"], "missing-condition")
        self.assertEqual(write.condition_calls, [("bid.mdb", ["t1"], "42")])

    def test_set_curved_batches_reload_after_all_curve_writes(self):
        data = FakeProjectData()
        for index in range(3):
            uid = f"t{index + 1}"
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="42",
                page_uid="p1",
                position=[0.0, 0.0, 10.0, 0.0],
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_set_curved(["t1", "t2", "t3"], True)
        self.assertEqual(len(write.curve_calls), 3)
        self.assertTrue(all(call[4] is False for call in write.curve_calls))
        self.assertEqual(write.reloads, ["bid.mdb"])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_failed_takeoff_position_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_positions = lambda *args, **kwargs: False
        handler = self._paste_handler(plan_view=plan_view, write=write)
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        self.assertEqual(plan_view.restored_positions, [(changes, [])])

    def test_mixed_takeoff_annotation_position_uses_page_scoped_events(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="annotation",
                page_uid="p1",
                position=[1.0, 1.0],
            )
        ]
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_positions_flushed(
            [("t1", [0.0, 0.0], [5.0, 6.0])],
            [("a1", "annotation", [1.0, 1.0], [2.0, 2.0])],
        )
        self.assertEqual(write.position_calls[0][2], False)
        self.assertEqual(ann_write.position_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])
        self.assertEqual(data.annotations[0].position, [2.0, 2.0])
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED, AppEvents.ANNOTATIONS_CHANGED],
        )

    def test_failed_annotation_position_save_restores_only_annotations(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_positions = lambda *args, **kwargs: False
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write
        )
        takeoff_changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        ann_changes = [("a1", "annotation", [1.0, 1.0], [2.0, 2.0])]
        handler.on_positions_flushed(takeoff_changes, ann_changes)
        self.assertEqual(plan_view.restored_positions, [([], ann_changes)])

    def test_failed_annotation_position_save_registers_takeoff_position_undo(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_positions = lambda *args, **kwargs: False
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        takeoff_changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        ann_changes = [("a1", "annotation", [1.0, 1.0], [2.0, 2.0])]
        handler.on_positions_flushed(takeoff_changes, ann_changes)
        undo.undo()
        undo.redo()
        self.assertEqual(undo.count, 1)
        self.assertEqual(plan_view.restored_positions, [([], ann_changes)])
        self.assertEqual(
            write.position_calls,
            [
                ("bid.mdb", [("t1", [5.0, 6.0])], False),
                ("bid.mdb", [("t1", [0.0, 0.0])], False),
                ("bid.mdb", [("t1", [5.0, 6.0])], False),
            ],
        )
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])

    def test_annotation_text_property_changes_use_annotation_write_service(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="text",
                page_uid="p1",
                properties={"Text": "Old", "FontBold": False},
            )
        ]
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
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
            ("bid.mdb", [("a1", "text", {"Text": "New", "FontBold": True})], False),
        )
        self.assertEqual(data.annotations[0].properties["Text"], "New")
        self.assertEqual(event_bus.events[0][0], AppEvents.ANNOTATIONS_CHANGED)
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.text_property_calls[1:],
            [
                (
                    "bid.mdb",
                    [("a1", "text", {"Text": "Old", "FontBold": False})],
                    False,
                ),
                (
                    "bid.mdb",
                    [("a1", "text", {"Text": "New", "FontBold": True})],
                    False,
                ),
            ],
        )

    def test_failed_annotation_text_property_save_restores_plan_view(self):
        plan_view = FakePlanView()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_text_properties = lambda *args, **kwargs: False
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        changes = [
            (
                "a1",
                "text",
                {"Text": "Old", "FontBold": False},
                {"Text": "New", "FontBold": True},
            )
        ]
        handler.on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_text_properties, [changes])

    def test_named_view_rename_publishes_combo_refresh_event(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(
                uid="nv1",
                annotation_type="namedview",
                page_uid="p1",
                properties={"Text": "Old"},
            )
        ]
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_annotation_text_properties_flushed(
            [("nv1", "namedview", {"Text": "Old"}, {"Text": "New"})]
        )
        self.assertEqual(data.named_view_updates, [("nv1", "New")])
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["nv1"],
                        "annotation_types": ["namedview"],
                    },
                ),
                (
                    AppEvents.NAMED_VIEW_RENAMED,
                    {"named_view_uid": "nv1", "name": "New"},
                ),
            ],
        )

    def test_annotation_text_and_box_changes_are_saved_together(self):
        data = FakeProjectData()
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="text", page_uid="p1")
        ]
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
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
                False,
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
                    False,
                ),
                (
                    "bid.mdb",
                    [("a1", "text", {"FontSize": 24, "FontColor": 0x332211})],
                    [("a1", "text", [100.0, 100.0, 80.0, 30.0])],
                    False,
                ),
            ],
        )

    def test_failed_annotation_text_and_box_save_restores_plan_view(self):
        plan_view = FakePlanView()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_text_properties_and_positions = (
            lambda *args, **kwargs: False
        )
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        text_changes = [
            (
                "a1",
                "text",
                {"FontSize": 12, "FontColor": 0},
                {"FontSize": 24, "FontColor": 0x332211},
            )
        ]
        position_changes = [
            ("a1", "text", [100.0, 100.0, 40.0, 15.0], [100.0, 100.0, 80.0, 30.0])
        ]
        handler.on_annotation_text_and_positions_flushed(text_changes, position_changes)
        self.assertEqual(
            plan_view.restored_text_and_positions,
            [(text_changes, position_changes)],
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_rotations_flushed([("t1", 0.0, 90.0)])
        self.assertEqual(write.rotation_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].rotation, 90.0)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_bus.events[0][1]["page_uid"], "p1")

    def test_failed_takeoff_rotation_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_rotations = lambda *args, **kwargs: False
        handler = self._paste_handler(plan_view=plan_view, write=write)
        changes = [("t1", 0.0, 90.0)]
        handler.on_rotations_flushed(changes)
        self.assertEqual(plan_view.restored_rotations, [changes])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_group_rotation_failure_keeps_persisted_position_change(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.save_takeoff_rotations = lambda *args, **kwargs: False
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        position_changes = [("t1", [0.0, 0.0], [3.0, 4.0])]
        rotation_changes = [("t1", 0.0, 45.0)]
        handler.on_group_rotation_flushed(position_changes, [], rotation_changes)
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

    def test_group_rotation_failure_registers_position_undo(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        write = FakeWriteService()
        write.save_takeoff_rotations = lambda *args, **kwargs: False
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])],
            [],
            [("t1", 0.0, 45.0)],
        )
        undo.undo()
        undo.redo()
        self.assertEqual(undo.count, 1)
        self.assertEqual(
            write.position_calls,
            [
                ("bid.mdb", [("t1", [3.0, 4.0])], False),
                ("bid.mdb", [("t1", [0.0, 0.0])], False),
                ("bid.mdb", [("t1", [3.0, 4.0])], False),
            ],
        )
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls[0][2], False)
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

    def test_count_takeoff_delete_with_known_extras_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="count", page_uid="p1", position=[4.0, 5.0]
        )
        data.extras["t1"] = {
            "Count": 0.0,
            "Quantity": 0.0,
            "GUID": "{OLD}",
            "NameFontName": "Arial",
            "NameFontSize": 12,
        }
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_elements_deleted(["t1"])
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertNotIn("t2", data.takeoffs)
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_takeoff_delete_with_unknown_extras_keeps_full_reload(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.extras["t1"] = {"UnsupportedColumn": "value"}
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], True)])
        self.assertIn("t1", data.takeoffs)
        self.assertEqual(event_bus.events, [])

    def test_failed_simple_takeoff_delete_reselects_original_uids(self):
        class FailingDeleteWriteService(FakeWriteService):
            def delete_takeoffs(
                self, db_path, uids, publish_database_refreshed_after_write=True
            ):
                super().delete_takeoffs(
                    db_path, uids, publish_database_refreshed_after_write
                )
                return False

        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FailingDeleteWriteService()
        plan_view = FakePlanView(data)
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(plan_view.selected, {"t1"})
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], False)])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_named_view_delete_with_linked_hotlink_no_or_close_cancels_delete(self):
        for response in (False, None):
            with self.subTest(response=response):
                data = FakeProjectData()
                named_view = BidAnnotation(
                    uid="nv1",
                    annotation_type="namedview",
                    page_uid="p1",
                    position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
                    properties={"Text": "Lobby"},
                )
                hotlink = BidAnnotation(
                    uid="hl1",
                    annotation_type="hotlink",
                    page_uid="p1",
                    position=[5.0, 6.0],
                    properties={"BidPageViewUID": "nv1"},
                )
                data.annotations = [named_view, hotlink]
                plan_view = FakePlanView(data)
                plan_view.annotations = {"nv1": named_view}
                ann_write = FakeAnnotationWriteService()
                handler = PlanViewActionHandler(
                    plan_view=plan_view,
                    ui_state_manager=FakeUiState(),
                    project_data_svc=data,
                    project_write_svc=FakeWriteService(),
                    annotation_write_svc=ann_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=FakeUndoService(),
                    event_bus=FakeEventBus(),
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
                )
                with patch.object(
                    handler_module, "confirm", return_value=response
                ) as confirm:
                    handler.on_elements_deleted(["nv1"])
                confirm.assert_called_once_with(
                    plan_view,
                    "Delete Named View",
                    "This named view has hotlinks connected to it.\n"
                    "Do you want to delete it and the associated hotlinks?",
                )
                self.assertEqual(ann_write.delete_calls, [])
                self.assertEqual(plan_view.selected, {"nv1"})

    def test_annotation_delete_uses_page_scoped_refresh_and_model_remove(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1": annotation}
        plan_view.annotation_key_map = {("ann-1", "rect"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        handler.on_elements_deleted(["a1"])
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.delete_calls,
            [
                ("bid.mdb", [("a1", "rect")], False),
                ("bid.mdb", [("ann-1", "rect")], False),
            ],
        )
        self.assertEqual([call[4] for call in ann_write.insert_calls], [False])
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED] * 3,
        )
        self.assertEqual(data.removed_annotation_uids, ["a1", "ann-1"])
        self.assertEqual(plan_view.selected, set())

    def test_annotation_delete_matches_uid_and_type(self):
        data = FakeProjectData()
        rect = BidAnnotation(
            uid="shared",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        oval = BidAnnotation(
            uid="shared",
            annotation_type="oval",
            page_uid="p2",
            position=[5.0, 6.0, 7.0, 8.0],
        )
        data.annotations = [rect, oval]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"rect-item": rect}
        ann_write = FakeAnnotationWriteService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        handler.on_elements_deleted(["rect-item"])
        self.assertEqual(
            ann_write.delete_calls,
            [("bid.mdb", [("shared", "rect")], False)],
        )
        self.assertEqual(
            [(a.uid, a.annotation_type, a.page_uid) for a in data.annotations],
            [("shared", "oval", "p2")],
        )
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["shared"],
                        "annotation_types": ["rect"],
                    },
                )
            ],
        )

    def test_named_view_delete_with_linked_hotlink_deletes_hotlink_first(self):
        data = FakeProjectData()
        named_view = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            properties={"Text": "Lobby"},
        )
        hotlink = BidAnnotation(
            uid="hl1",
            annotation_type="hotlink",
            page_uid="p1",
            position=[5.0, 6.0],
            properties={"BidPageViewUID": "nv1"},
        )
        data.annotations = [named_view, hotlink]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"nv1": named_view}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        with patch.object(handler_module, "confirm", return_value=True) as confirm:
            handler.on_elements_deleted(["nv1"])
        confirm.assert_called_once_with(
            plan_view,
            "Delete Named View",
            "This named view has hotlinks connected to it.\n"
            "Do you want to delete it and the associated hotlinks?",
        )
        self.assertEqual(
            ann_write.delete_calls,
            [("bid.mdb", [("hl1", "hotlink"), ("nv1", "namedview")], False)],
        )
        self.assertEqual(data.annotations, [])
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED, AppEvents.NAMED_VIEW_DELETED],
        )
        self.assertEqual(undo.count, 1)

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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_paste_parent_child_with_known_extras_keeps_full_reload(self):
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
        data = FakeProjectData()
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard(
            [parent, hole],
            extras={"old-parent": {"GUID": "{P}"}, "old-hole": {"GUID": "{H}"}},
        )
        handler.on_paste_requested()
        self.assertEqual([call[3] for call in write.calls], [True, True])
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(event_bus.events, [])

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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(len(write.calls), 1)
        self.assertEqual(write.calls[0][2][0].position, [50.0, 75.0, 54.0, 75.0])
        self.assertEqual(plan_view.intelligent_paste_calls, [(["100"], (10.0, 20.0))])

    def test_count_takeoff_paste_with_known_extras_uses_targeted_path(self):
        source = Takeoff(
            uid="source-count",
            condition_uid="count",
            page_uid="source-page",
            position=[10.0, 20.0],
            parent_uid="0",
        )
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.mouse_ost_position = (50.0, 75.0)
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard(
            [source],
            extras={
                "source-count": {
                    "Count": 0.0,
                    "Quantity": 0.0,
                    "GUID": "{OLD}",
                    "NameFontName": "Arial",
                    "NameFontSize": 12,
                }
            },
        )
        handler.on_paste_requested()
        undo.undo()
        undo.redo()
        self.assertEqual([call[3] for call in write.calls], [False, False])
        self.assertEqual([call[2] for call in write.delete_calls], [False])
        self.assertEqual(write.calls[0][2][0].position, [50.0, 75.0])
        self.assertEqual(plan_view.selected, {"101"})
        self.assertEqual(len(data.takeoffs), 1)
        pasted = data.takeoffs["101"]
        self.assertEqual(pasted.condition_uid, "count")
        self.assertEqual(pasted.name_font_name, "Arial")
        self.assertEqual(pasted.name_font_size, 12)
        self.assertEqual(
            [event for event, _kwargs in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_takeoff_paste_with_unknown_extras_keeps_full_reload(self):
        source = self._copied_takeoff()
        data = FakeProjectData()
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard(
            [source], extras={"source": {"UnsupportedColumn": "value"}}
        )
        handler.on_paste_requested()
        self.assertEqual(write.calls[0][3], True)
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(event_bus.events, [])

    def test_cross_bid_takeoff_paste_after_condition_remap_keeps_full_reload(self):
        source = self._copied_takeoff()
        data = FakeProjectData()
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard(
            [source],
            source_bid_uid="source-bid",
            source_file_path="bid.mdb",
        )
        handler.on_paste_requested()
        self.assertEqual(
            write.condition_duplicate_calls,
            [("bid.mdb", "source-bid", "7", ["c1"], False)],
        )
        self.assertEqual(write.calls[0][2][0].condition_uid, "new-c1")
        self.assertEqual(write.calls[0][3], True)
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(event_bus.events, [])

    def test_intelligent_paste_disabled_uses_standard_offset_paste(self):
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
            deferred_persistence_manager=FakeDeferredPersistence(),
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

    def test_paste_bid_dimension_preserves_style_properties(self):
        source = self._copied_annotation(
            annotation_type="dimension",
            position=[10.0, 20.0, 22.0, 20.0],
        )
        source.properties = {
            "BidTakeoffFromUID": "",
            "BidTakeoffToUID": "",
            "FontName": "Segoe UI",
            "FontColor": "#112233",
            "FontSize": 14,
            "FontBold": True,
            "FontItalic": True,
            "FontUnderline": False,
        }
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = (50.0, 75.0)
        plan_view.annotation_key_map = {("ann-1", "dimension"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(plan_view=plan_view, ann_write=ann_write)
        handler._clipboard_svc = FakeClipboard([], annotations=[source])
        handler.on_paste_requested()
        self.assertEqual(len(ann_write.insert_calls), 1)
        spec = ann_write.insert_calls[0][2][0]
        self.assertEqual(spec.annotation_type, "dimension")
        self.assertEqual(spec.position, [50.0, 75.0, 62.0, 75.0])
        self.assertEqual(spec.properties, source.properties)
        self.assertEqual(plan_view.selected, {"ann-1"})

    def test_intelligent_paste_disabled_pastes_annotation_with_standard_offset(self):
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
        self.assertFalse(write.calls[0][3])
        self.assertFalse(ann_write.insert_calls[0][4])
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

    def test_intelligent_paste_disabled_pastes_mixed_clipboard_with_standard_offset(
        self,
    ):
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

    def test_intelligent_paste_off_starts_holes_only_backout_paste(self):
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard([hole])
        handler.on_paste_requested()
        self.assertEqual(len(plan_view.paste_backout_calls), 1)
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
            deferred_persistence_manager=FakeDeferredPersistence(),
        )
        handler._clipboard_svc = FakeClipboard([hole])
        handler.on_paste_requested()
        self.assertEqual(len(plan_view.paste_backout_calls), 1)
        self.assertEqual(write.calls, [])

    def test_holes_only_backout_paste_requires_place_plan_items_access(self):
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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.SELECT_PLAN_ITEMS}),
        )
        handler._clipboard_svc = FakeClipboard([hole])
        handler.on_paste_requested()
        self.assertEqual(plan_view.paste_backout_calls, [])
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
