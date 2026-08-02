import unittest
import uuid
import weakref
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationExecutionResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceLock,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.page_selection_service import PageSelectionService
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as handler_module,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.services.selection_commands import (
    DeleteAnnotationsCommand,
    InsertAnnotationsCommand,
    InsertTakeoffsCommand,
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)


def _named_view_annotation(uid: str, name: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="namedview",
        page_uid="p1",
        position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
        properties={"Text": name},
    )


def _hotlink_annotation(uid: str, target_named_view_uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="hotlink",
        page_uid="p1",
        position=[5.0, 6.0],
        properties={"BidPageViewUID": target_named_view_uid},
    )


class SelectionCommandIdentityTests(unittest.TestCase):
    def test_takeoff_redo_rejects_incomplete_authoritative_identity_result(self):
        plan_view = SimpleNamespace(
            set_selected_uids=lambda _uids: self.fail(
                "Incomplete results must not be selected"
            )
        )
        command = InsertTakeoffsCommand(
            uids=["old-1", "old-2"],
            bid_ref=BidRef("bid.mdb", "7"),
            specs=[object(), object()],
            write_svc=None,
            plan_view=plan_view,
            insert_takeoffs_fn=lambda _bid_ref, _specs: ["new-1"],
            delete_takeoffs_fn=lambda _db_path, _uids: True,
        )
        with self.assertRaisesRegex(
            ValueError, "returned 1 identities for 2 requested"
        ):
            command.redo()
        self.assertEqual(command._current_uids, ["old-1", "old-2"])

    def test_annotation_restore_rejects_incomplete_authoritative_result(self):
        saved = [_rect_annotation("old-1"), _rect_annotation("old-2")]
        plan_view = SimpleNamespace(
            find_annotation_keys_by_uid_type=lambda _uids: self.fail(
                "Incomplete results must not be projected"
            ),
            set_selected_uids=lambda _uids: self.fail(
                "Incomplete results must not be selected"
            ),
        )
        command = DeleteAnnotationsCommand(
            saved_annotations=saved,
            bid_ref=BidRef("bid.mdb", "7"),
            plan_view=plan_view,
            insert_saved_annotations_fn=lambda _bid_ref, _saved: [saved[0]],
            delete_saved_annotations_fn=lambda _db_path, _saved: True,
        )
        with self.assertRaisesRegex(
            ValueError, "returned 1 annotations for 2 requested"
        ):
            command.undo()

    def test_annotation_redo_rejects_incomplete_authoritative_identity_result(self):
        plan_view = SimpleNamespace(
            find_annotation_keys_by_uid_type=lambda _uids: self.fail(
                "Incomplete results must not be projected"
            ),
            set_selected_uids=lambda _uids: self.fail(
                "Incomplete results must not be selected"
            ),
        )
        command = InsertAnnotationsCommand(
            uids=["old-1", "old-2"],
            bid_ref=BidRef("bid.mdb", "7"),
            specs=[
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="rect",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="rect",
                    position=[2.0, 2.0, 3.0, 3.0],
                    color="#000000",
                    width=1.0,
                ),
            ],
            write_svc=None,
            plan_view=plan_view,
            insert_annotations_fn=lambda _bid_ref, _specs, _remap: ["new-1"],
            delete_annotations_fn=lambda _db_path, _uids, _specs: True,
        )
        with self.assertRaisesRegex(
            ValueError, "returned 1 identities for 2 requested"
        ):
            command.redo()
        self.assertEqual(command._current_uids, ["old-1", "old-2"])


def _rect_annotation(uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid="p1",
        position=[1.0, 2.0, 3.0, 4.0],
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
        self.restored_annotation_styles = []
        self.activated_annotations = []
        self.named_view_name_validator = None
        self.placement_flow = []
        self.pending_mutation_uids = set()
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()
        self.clipboard_changed = SimpleNamespace(emit=lambda: None)

    def set_selected_uids(self, uids):
        self.selected = set(uids)

    def get_selected_uids(self):
        return set(self.selected)

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

    def restore_annotation_styles(self, changes):
        self.restored_annotation_styles.append(list(changes))

    def cancel_place_mode(self):
        self.placement_flow.append("cancel_place_mode")
        self.cancel_place_mode_calls += 1

    def activate_annotation_placement(self, annotation_type):
        self.placement_flow.append(f"activate_annotation_placement:{annotation_type}")
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

    def set_pending_mutation_uids(self, uids):
        self.pending_mutation_uids = set(uids)

    def set_geometry_edit_lease_pending(self, uids):
        self.geometry_lease_pending = set(uids)
        self.geometry_lease_granted = set()

    def set_geometry_edit_lease_granted(self, uids):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set(uids)

    def disable_geometry_edit_leasing(self):
        self.geometry_lease_pending = set()
        self.geometry_lease_granted = set()


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
        self.annotation_layer_uid = "annotation-layer"
        self.page_names = {"p1": "Page 1"}
        self.pages = {
            "p1": SimpleNamespace(
                uid="p1",
                overlay_rect=None,
                scale_factor1=1.0,
                scale_factor2=1.0,
            )
        }
        self.conditions = {
            "42": Condition(
                uid="42", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
            "c1": Condition(
                uid="c1", layer_visible=True, condition_type=Condition.TYPE_AREA
            ),
        }

    def add_takeoffs(self, takeoffs):
        self.added_takeoffs.extend(takeoffs)
        for takeoff in takeoffs:
            self.takeoffs[takeoff.uid] = takeoff

    def add_transient_takeoffs(self, takeoffs):
        self.add_takeoffs(takeoffs)

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

    def get_condition_uids_for_takeoffs(self, uids):
        wanted = {str(uid) for uid in uids if uid}
        result = []
        for takeoff in self.takeoffs.values():
            if takeoff.uid in wanted and takeoff.condition_uid not in result:
                result.append(takeoff.condition_uid)
        return result

    def update_takeoffs_area(self, uids, area_uid):
        page_uids = []
        for uid in uids:
            takeoff = self.takeoffs.get(uid)
            if takeoff is None:
                continue
            takeoff.area_uid = str(area_uid or "0")
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def update_takeoffs_condition(self, uids, condition_uid):
        page_uids = []
        for uid in uids:
            takeoff = self.takeoffs.get(uid)
            if takeoff is None:
                continue
            takeoff.condition_uid = str(condition_uid)
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def update_takeoffs_negative(self, uids, is_negative):
        page_uids = []
        for uid in uids:
            takeoff = self.takeoffs.get(uid)
            if takeoff is None:
                continue
            takeoff.is_negative = bool(is_negative)
            if takeoff.page_uid not in page_uids:
                page_uids.append(takeoff.page_uid)
        return page_uids

    def update_takeoff_curve(self, uid, position, curve):
        takeoff = self.takeoffs.get(uid)
        if takeoff is None:
            return []
        takeoff.position = list(position)
        takeoff.curve = int(curve)
        return [takeoff.page_uid]

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

    def get_annotation_layer_uid(self):
        return self.annotation_layer_uid

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
        self.area_calls = []
        self.negative_calls = []
        self.delete_calls = []
        self.curve_calls = []
        self.reloads = []
        self.next_uids = ["100"]
        self.uid_batches = []
        self._next_uid_index = 0
        self.sql_collaboration_mutations = False
        self.queued_takeoff_callbacks = []
        self.cancelled_mutations = []
        self.cancel_queued_mutation_result = True
        self.queued_runtime_generation = 3
        self.queued_geometry = []
        self.queued_properties = []
        self.queued_deletes = []
        self.queued_pastes = []
        self.local_deletes = []
        self.local_pastes = []
        self.local_annotation_delete_calls = []
        self.next_annotation_uids = ["ann-1"]
        self.annotation_write_service = None
        self.edit_lease_requests = []
        self.ended_edit_leases = []

    def uses_sql_collaboration_mutations(self, _database_id):
        return self.sql_collaboration_mutations

    def queue_takeoff_placement(
        self,
        database_id,
        bid_uid,
        specs,
        operation_id,
        callback,
    ):
        self.calls.append((database_id, bid_uid, specs, "queued"))
        self.queued_takeoff_callbacks.append((operation_id, callback))
        return self.queued_runtime_generation

    def cancel_queued_sql_mutation(self, database_id, operation_id):
        self.cancelled_mutations.append((database_id, operation_id))
        return self.cancel_queued_mutation_result

    def queue_plan_geometry(self, database_id, bid_uid, callback, **updates):
        self.queued_geometry.append((database_id, bid_uid, updates, callback))
        return len(self.queued_geometry)

    def request_plan_edit_lease(
        self,
        database_id,
        resources,
        dependency_resources,
        callback,
        **options,
    ):
        self.edit_lease_requests.append(
            (database_id, resources, dependency_resources, options, callback)
        )

    def end_plan_edit_lease(self, handle):
        self.ended_edit_leases.append(handle)

    def queue_plan_properties(
        self,
        database_id,
        bid_uid,
        property_kind,
        updates,
        callback,
        **options,
    ):
        self.queued_properties.append(
            (database_id, bid_uid, property_kind, updates, options, callback)
        )
        return len(self.queued_properties)

    def queue_plan_items_delete(
        self,
        database_id,
        bid_uid,
        takeoff_uids,
        annotations,
        callback,
        **options,
    ):
        self.queued_deletes.append(
            (database_id, bid_uid, takeoff_uids, annotations, options, callback)
        )
        return len(self.queued_deletes)

    def queue_plan_items_paste(
        self,
        database_id,
        payload,
        callback,
        **options,
    ):
        self.queued_pastes.append((database_id, payload, options, callback))
        return len(self.queued_pastes)

    def execute_plan_items_delete_local(
        self,
        database_id,
        bid_uid,
        takeoff_uids,
        annotations,
        **options,
    ):
        self.local_deletes.append(
            (database_id, bid_uid, list(takeoff_uids), list(annotations), options)
        )
        if takeoff_uids:
            self.delete_takeoffs(
                database_id,
                list(takeoff_uids),
                publish_database_refreshed_after_write=False,
            )
        if annotations:
            self.local_annotation_delete_calls.append(
                (database_id, list(annotations), False)
            )
        if options.get("publish_database_refreshed_after_write", True):
            self.reload_and_notify(database_id)
        return MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=AuthoritativeMutationResult(
                affected_page_uids=tuple(options.get("page_uids", ())),
                affected_families=tuple(
                    family
                    for family, present in (
                        ("takeoffs", bool(takeoff_uids)),
                        ("annotations", bool(annotations)),
                    )
                    if present
                ),
            ),
        )

    def execute_plan_items_paste_local(self, database_id, payload, **options):
        self.local_pastes.append((database_id, payload, options))
        condition_map = {}
        if payload.source_bid_uid != payload.destination_bid_uid:
            source_condition_uids = list(
                dict.fromkeys(spec.condition_uid for spec in payload.takeoff_specs)
            )
            condition_map = self.duplicate_conditions_to_bid(
                database_id,
                payload.source_bid_uid,
                payload.destination_bid_uid,
                source_condition_uids,
                publish_database_refreshed_after_write=False,
            )
        specs = tuple(
            replace(
                spec,
                condition_uid=condition_map.get(spec.condition_uid, spec.condition_uid),
            )
            for spec in payload.takeoff_specs
        )
        regular_indexes = tuple(
            index
            for index, spec in enumerate(specs)
            if str(spec.parent_uid or "0") in {"", "0", "None"}
        )
        hole_indexes = tuple(
            index for index in range(len(specs)) if index not in regular_indexes
        )
        regular_uids = (
            self.insert_takeoffs(
                database_id,
                payload.destination_bid_uid,
                [specs[index] for index in regular_indexes],
                publish_database_refreshed_after_write=False,
            )
            if regular_indexes
            else []
        )
        if len(regular_uids) != len(regular_indexes):
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                message="Incomplete parent identity map",
            )
        takeoff_map = {
            payload.takeoff_source_uids[index]: uid
            for index, uid in zip(regular_indexes, regular_uids)
        }
        hole_specs = []
        for index in hole_indexes:
            parent_uid = takeoff_map.get(str(specs[index].parent_uid))
            if parent_uid is None:
                return MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                    message="Missing authoritative parent",
                )
            hole_specs.append(replace(specs[index], parent_uid=parent_uid))
        hole_uids = (
            self.insert_takeoffs(
                database_id,
                payload.destination_bid_uid,
                hole_specs,
                publish_database_refreshed_after_write=False,
            )
            if hole_specs
            else []
        )
        if len(hole_uids) != len(hole_indexes):
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                message="Incomplete hole identity map",
            )
        takeoff_map.update(
            {
                payload.takeoff_source_uids[index]: uid
                for index, uid in zip(hole_indexes, hole_uids)
            }
        )
        annotation_uids = []
        if payload.annotation_specs and self.annotation_write_service is not None:
            remap = PasteRefRemap(takeoff_uids=dict(takeoff_map))
            named_indexes = tuple(
                index
                for index, spec in enumerate(payload.annotation_specs)
                if spec.annotation_type == "namedview"
            )
            other_indexes = tuple(
                index
                for index in range(len(payload.annotation_specs))
                if index not in named_indexes
            )
            by_index = {}
            if named_indexes:
                named_uids = self.annotation_write_service.insert_annotations(
                    database_id,
                    payload.destination_bid_uid,
                    [payload.annotation_specs[index] for index in named_indexes],
                    remap,
                    False,
                )
                for index, uid in zip(named_indexes, named_uids):
                    by_index[index] = uid
                    remap.namedview_uids[payload.annotation_source_uids[index]] = uid
            if other_indexes:
                other_uids = self.annotation_write_service.insert_annotations(
                    database_id,
                    payload.destination_bid_uid,
                    [payload.annotation_specs[index] for index in other_indexes],
                    remap,
                    False,
                )
                by_index.update(dict(zip(other_indexes, other_uids)))
            annotation_uids = [
                by_index[index] for index in range(len(payload.annotation_specs))
            ]
        elif payload.annotation_specs:
            annotation_uids = self.next_annotation_uids[: len(payload.annotation_specs)]
        if len(annotation_uids) != len(payload.annotation_specs):
            return MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                message="Incomplete annotation identity map",
            )
        annotation_map = dict(zip(payload.annotation_source_uids, annotation_uids))
        if options.get("publish_database_refreshed_after_write", True):
            self.reload_and_notify(database_id)
        created_ids = tuple((*takeoff_map.values(), *annotation_map.values()))
        return MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.COMMITTED,
            created_resource_ids=created_ids,
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=created_ids,
                created_uid_maps=(
                    ("takeoffs", tuple(takeoff_map.items())),
                    ("annotations", tuple(annotation_map.items())),
                    ("conditions", tuple(condition_map.items())),
                ),
            ),
        )

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

    def save_takeoffs_area(
        self, db_path, uids, area_uid, publish_database_refreshed_after_write=True
    ):
        self.area_calls.append(
            (db_path, list(uids), area_uid, publish_database_refreshed_after_write)
        )
        return True

    def save_takeoffs_condition(
        self, db_path, uids, condition_uid, publish_database_refreshed_after_write=True
    ):
        self.condition_calls.append(
            (db_path, list(uids), condition_uid, publish_database_refreshed_after_write)
        )
        return True

    def set_takeoffs_negative(
        self, db_path, uids, is_negative, publish_database_refreshed_after_write=True
    ):
        self.negative_calls.append(
            (db_path, list(uids), is_negative, publish_database_refreshed_after_write)
        )
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
    def __init__(self, accepts_writes=True):
        self.overlay_rect_calls = []
        self.accepts_writes = accepts_writes

    def schedule_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: tuple[float, float, float, float],
    ) -> bool:
        self.overlay_rect_calls.append((db_path, page_uid, overlay_rect))
        return self.accepts_writes


class FakeAnnotationWriteService:
    def __init__(self):
        self.position_calls = []
        self.text_property_calls = []
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

    def push_local(self, undo, redo):
        self.count += 1
        self.undo = undo
        self.redo = redo

    def push(self, undo_submit, redo_submit):
        self.count += 1
        self.undo = lambda: undo_submit(lambda _success: None)
        self.redo = lambda: redo_submit(lambda _success: None)


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

    def publish(self, event_name, **event_payload):
        self.events.append((event_name, event_payload))


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

    def test_multi_page_changes_publish_one_event_per_transaction(self):
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._publish_takeoffs_changed_for_pages(
            ["p1", "p2", "p1"], ["t1", "t2"], ["c1"]
        )
        handler._annotation_writes.publish_annotations_changed_for_pages(
            ["p1", "p2", "p1"], ["a1", "a2"], ["rect", "text"]
        )
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "",
                        "page_uids": ["p1", "p2"],
                        "takeoff_uids": ["t1", "t2"],
                        "condition_uids": ["c1"],
                    },
                ),
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "",
                        "page_uids": ["p1", "p2"],
                        "annotation_uids": ["a1", "a2"],
                        "annotation_types": ["rect", "text"],
                    },
                ),
            ],
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
                    ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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

    def test_annotation_style_restore_ignores_retired_tool_keys(self):
        try:
            styles = set_annotation_styles_by_tool(
                {
                    "rect": AnnotationStyle(color="#123456", line_width=6.0),
                    "retired-tool": AnnotationStyle(color="#abcdef"),
                }
            )
            self.assertEqual(styles["rect"].color, "#123456")
            self.assertNotIn("retired-tool", styles)
        finally:
            set_annotation_styles_by_tool({})

    def _overlay_handler(self, data, deferred, *, allowed=True):
        return PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            ui_access_manager=FakeAccess(
                {Feature.EDIT_PAGE_SETTINGS} if allowed else set()
            ),
            deferred_persistence_manager=deferred,
        )

    def test_overlay_rect_updates_model_immediately_and_defers_persistence(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred)
        accepted = handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25))
        self.assertTrue(accepted)
        self.assertEqual(data.get_page("p1").overlay_rect, (1.0, 2.5, 3.0, 4.25))
        self.assertEqual(
            deferred.overlay_rect_calls,
            [("bid.mdb", "p1", (1.0, 2.5, 3.0, 4.25))],
        )

    def test_overlay_rect_rejected_deferred_write_does_not_update_model(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence(accepts_writes=False)
        handler = self._overlay_handler(data, deferred)
        original_rect = data.get_page("p1").overlay_rect
        accepted = handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25))
        self.assertFalse(accepted)
        self.assertEqual(data.get_page("p1").overlay_rect, original_rect)

    def test_overlay_rect_permission_denial_returns_rejected_without_scheduling(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred, allowed=False)
        original_rect = data.get_page("p1").overlay_rect
        self.assertFalse(handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25)))
        self.assertEqual(deferred.overlay_rect_calls, [])
        self.assertEqual(data.get_page("p1").overlay_rect, original_rect)

    def _paste_handler(
        self,
        plan_view=None,
        write=None,
        ann_write=None,
        allowed_features=None,
        data=None,
    ):
        plan_view = FakePlanView() if plan_view is None else plan_view
        write = FakeWriteService() if write is None else write
        ann_write = FakeAnnotationWriteService() if ann_write is None else ann_write
        write.annotation_write_service = ann_write
        return PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData() if data is None else data,
            project_write_svc=write,
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(
                set(Feature) if allowed_features is None else allowed_features
            ),
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

    def test_copy_ignores_takeoff_uid_not_loaded_on_current_plan_page(self):
        data = FakeProjectData()
        data.takeoffs["other-page"] = Takeoff(
            uid="other-page",
            condition_uid="c1",
            page_uid="p2",
            position=[1.0, 2.0],
        )
        plan_view = FakePlanView()
        handler = self._paste_handler(plan_view=plan_view)
        handler._data_svc = data
        handler.on_copy_requested(["other-page"])
        self.assertFalse(handler._clipboard_svc.has_content())

    def test_copy_keeps_current_page_text_annotation_without_off_page_takeoff(self):
        data = FakeProjectData()
        data.takeoffs["other-page"] = Takeoff(
            uid="other-page",
            condition_uid="c1",
            page_uid="p2",
            position=[99.0, 100.0],
        )
        current_takeoff = Takeoff(
            uid="current",
            condition_uid="c1",
            page_uid="p1",
            position=[1.0, 2.0],
        )
        text_annotation = BidAnnotation(
            uid="text-1",
            annotation_type="text",
            page_uid="p1",
            position=[10.0, 20.0, 80.0, 24.0],
            properties={"Text": "Copied note"},
        )
        plan_view = FakePlanView()
        plan_view.get_takeoff = lambda uid: (
            current_takeoff if uid == "current" else None
        )
        plan_view.annotations["text-1"] = text_annotation
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write
        )
        handler._data_svc = data
        handler.on_copy_requested(["current", "text-1", "other-page"])
        self.assertEqual(
            [takeoff.uid for takeoff in handler._clipboard_svc.items],
            ["current"],
        )
        self.assertEqual(
            [
                (annotation.uid, annotation.annotation_type)
                for annotation in handler._clipboard_svc.annotations
            ],
            [("text-1", "text")],
        )
        plan_view.current_page_uid = "p2"
        plan_view.annotation_key_map = {("ann-1", "text"): "ann-1"}
        handler.on_paste_requested()
        self.assertEqual(len(write.calls), 1)
        self.assertEqual(len(write.calls[0][2]), 1)
        self.assertEqual(write.calls[0][2][0].page_uid, "p2")
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(len(ann_write.insert_calls[0][2]), 1)
        self.assertEqual(ann_write.insert_calls[0][2][0].annotation_type, "text")
        self.assertEqual(ann_write.insert_calls[0][2][0].page_uid, "p2")

    def test_set_curved_uses_targeted_update_after_curve_writes(self):
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
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_set_curved(["t1", "t2"], True)
        self.assertEqual(len(write.curve_calls), 2)
        self.assertEqual([call[4] for call in write.curve_calls], [False, False])
        self.assertEqual(write.reloads, [])
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1", "t2"],
                        "condition_uids": ["42"],
                    },
                )
            ],
        )

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
                    ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
        self.assertEqual(plan_view.activated_annotations, ["text"])
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
        self.assertEqual(data.added_annotations[0].layer_uid, "annotation-layer")
        self.assertEqual(ann_write.insert_calls[0][2][0].layer_uid, "annotation-layer")

    def test_sql_annotation_creation_uses_atomic_paste_queue(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        self.assertEqual(len(write.queued_pastes), 1)
        payload = write.queued_pastes[0][1]
        self.assertEqual(len(payload.annotation_specs), 1)
        self.assertEqual(payload.annotation_specs[0].annotation_type, "rect")

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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )
        handler.on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0],
            "p1",
            {"Text": "   ", "FontColor": 0x336699},
        )
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])

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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
        self.assertEqual(plan_view.activated_annotations, ["namedview"])
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
            ],
        )

    def test_named_view_write_failure_does_not_refresh_or_reactivate_tool(self):
        plan_view = FakePlanView()
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = []
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )
        handler.on_named_view_created(
            [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            "p1",
            {"Text": "Lobby View", "Color": "#008000"},
        )
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(event_bus.events, [])
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(plan_view.selected, set())

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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class FakeDialog:
            captured_named_views = None

            def __init__(self, named_views, parent=None):
                FakeDialog.captured_named_views = list(named_views)

            def exec(self):
                plan_view.placement_flow.append("dialog_exec")
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid="nv1")

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(
            plan_view.placement_flow[:2], ["cancel_place_mode", "dialog_exec"]
        )
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
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(plan_view.activated_annotations, ["hotlink"])
        self.assertEqual(
            plan_view.placement_flow,
            [
                "cancel_place_mode",
                "dialog_exec",
                "activate_annotation_placement:hotlink",
            ],
        )

    def test_hotlink_write_failure_does_not_reactivate_tool(self):
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
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = []
        plan_view = FakePlanView(data)
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class FakeDialog:
            def __init__(self, named_views, parent=None):
                pass

            def exec(self):
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid="nv1")

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(plan_view.activated_annotations, [])

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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class FakeDialog:
            def __init__(self, named_views, parent=None):
                pass

            def exec(self):
                plan_view.placement_flow.append("dialog_exec")
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, ["namedview"])
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(
            plan_view.placement_flow,
            [
                "cancel_place_mode",
                "dialog_exec",
                "activate_annotation_placement:namedview",
            ],
        )

    def test_hotlink_dialog_cancel_exits_annotation_placement_without_write(self):
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
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class FakeDialog:
            def __init__(self, named_views, parent=None):
                pass

            def exec(self):
                plan_view.placement_flow.append("dialog_exec")
                return handler_module.QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(plan_view.placement_flow, ["cancel_place_mode", "dialog_exec"])

    def test_denied_place_annotations_access_blocks_text_commit_write(self):
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

    def test_denied_place_annotations_access_blocks_annotation_placement_write(self):
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
        write.save_takeoff_text_properties = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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

    def test_sql_takeoff_placement_projects_pending_then_committed_identity(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        events = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=events,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(len(write.queued_takeoff_callbacks), 1)
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uids = tuple(data.takeoffs)
        self.assertEqual(len(pending_uids), 1)
        self.assertTrue(pending_uids[0].startswith("pending:takeoff-placement:"))
        self.assertEqual(plan_view.pending_mutation_uids, set(pending_uids))
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan_view.selected, set())
        data.add_takeoffs(
            [
                Takeoff(
                    uid="501",
                    condition_uid="42",
                    page_uid="9",
                    position=[1.0, 2.0],
                )
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertNotIn(pending_uids[0], data.takeoffs)
        self.assertIn("501", data.takeoffs)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"501"})
        self.assertEqual(undo.count, 1)
        self.assertEqual(
            [
                event[1]["takeoff_uids"]
                for event in events.events
                if event[0] == AppEvents.TAKEOFFS_CHANGED
            ],
            [[pending_uids[0]]],
        )

    def test_deleting_queued_takeoff_preview_cancels_before_execution(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        handler.on_elements_deleted([pending_uid])
        self.assertNotIn(pending_uid, data.takeoffs)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(
            write.cancelled_mutations,
            [("bid.mdb", operation_id)],
        )
        self.assertEqual(write.queued_deletes, [])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.CANCELLED_BEFORE_START,
            )
        )
        self.assertEqual(undo.count, 0)

    def test_duplicate_pending_takeoff_delete_intent_does_not_repeat_side_effects(
        self,
    ):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        events = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=events,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        pending_uid = next(iter(data.takeoffs))
        handler.on_elements_deleted([pending_uid])
        self.assertEqual(
            handler._request_pending_takeoff_deletions([pending_uid]),
            [],
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in events.events
                    if event[0] == AppEvents.TAKEOFFS_CHANGED
                ]
            ),
            2,
        )
        self.assertEqual(len(write.cancelled_mutations), 1)

    def test_rapid_sql_placements_keep_each_uncommitted_preview_pending(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        handler.on_takeoff_created("42", [3.0, 4.0], "9")
        previews = set(data.takeoffs)
        self.assertEqual(len(previews), 2)
        self.assertEqual(plan_view.pending_mutation_uids, previews)
        first_operation_id, first_callback = write.queued_takeoff_callbacks[0]
        first_preview = next(uid for uid in previews if first_operation_id in uid)
        data.add_takeoffs(
            [
                Takeoff(
                    uid="501",
                    condition_uid="42",
                    page_uid="9",
                    position=[1.0, 2.0],
                )
            ]
        )
        first_callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=first_operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(
            plan_view.pending_mutation_uids,
            previews - {first_preview},
        )

    def test_deleting_executing_takeoff_preview_queues_delete_after_commit(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        handler.on_elements_deleted([pending_uid])
        self.assertNotIn(pending_uid, data.takeoffs)
        data.add_takeoffs(
            [
                Takeoff(
                    uid="501",
                    condition_uid="42",
                    page_uid="9",
                    position=[1.0, 2.0],
                )
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.queued_deletes[0][2], ["501"])
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 0)

    def test_bid_switch_retains_delete_intent_for_committed_recovery(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        handler.on_elements_deleted([pending_uid])
        handler.hide_pending_takeoff_placement_previews()
        handler._ui_state = SimpleNamespace(
            active_page_uid=None,
            get_selected_bid_ref=lambda: BidRef("other.mdb", "8"),
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.queued_deletes[0][2], ["501"])

    def test_sql_placement_completion_does_not_select_on_another_page(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        plan_view.current_page_uid = "10"
        data.add_takeoffs(
            [
                Takeoff(
                    uid="501",
                    condition_uid="42",
                    page_uid="9",
                    position=[1.0, 2.0],
                )
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 1)

    def test_committed_placement_projection_failure_waits_for_recovery(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                created_resource_ids=("501",),
                commit_attempted=True,
            )
        )
        self.assertIn(pending_uid, data.takeoffs)
        self.assertEqual(undo.count, 0)
        data.remove_takeoffs([pending_uid])
        data.add_takeoffs(
            [
                Takeoff(
                    uid="501",
                    condition_uid="42",
                    page_uid="9",
                    position=[1.0, 2.0],
                )
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
                commit_attempted=True,
            )
        )
        self.assertNotIn(pending_uid, data.takeoffs)
        self.assertIn("501", data.takeoffs)
        self.assertEqual(plan_view.selected, {"501"})
        self.assertEqual(undo.count, 1)

    def test_failed_pending_projection_removes_preview_before_queueing_sql(self):
        class FailingEventBus:
            def publish(self, _event_name, **_event_payload):
                raise RuntimeError("plan projection failed")

        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FailingEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        with self.assertRaisesRegex(RuntimeError, "plan projection failed"):
            handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(write.queued_takeoff_callbacks, [])
        self.assertEqual(handler._pending_takeoff_placements, {})

    def test_failed_or_invalidated_sql_placement_never_projects_authoritative_item(
        self,
    ):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        events = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=events,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        handler.invalidate_pending_takeoff_placements()
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(data.takeoffs, {})
        handler.on_takeoff_created("42", [3.0, 4.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[1]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.REJECTED,
                message="conflict",
            )
        )
        self.assertEqual(data.takeoffs, {})

    def test_stale_runtime_completion_removes_preview_without_projecting_commit(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=write.queued_runtime_generation + 1,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertNotIn(pending_uid, data.takeoffs)
        self.assertNotIn("501", data.takeoffs)

    def test_mismatched_database_completion_cannot_orphan_pending_preview(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        pending_uid = next(iter(data.takeoffs))
        callback(
            QueuedMutationResult(
                database_id="another-database",
                runtime_generation=write.queued_runtime_generation,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertNotIn(pending_uid, data.takeoffs)
        self.assertNotIn("501", data.takeoffs)

    def test_pending_invalidation_preserves_condition_summary_dependencies(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        events = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=events,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        handler.invalidate_pending_takeoff_placements()
        invalidation = events.events[-1]
        self.assertEqual(invalidation[0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(invalidation[1]["condition_uids"], ["42"])

    def test_pending_queue_callback_does_not_retain_closed_plan_handler(self):
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        handler_reference = weakref.ref(handler)
        del handler
        self.assertIsNone(handler_reference())

    def test_new_area_takeoff_keeps_curve_disabled_for_polygon_position(self):
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        position = [0.0, 0.0, 10.0, 0.0, 10.0, 8.0, 0.0, 8.0]
        handler.on_takeoff_created("42", position, "9")
        spec = write.calls[0][2][0]
        self.assertEqual(spec.position, position)
        self.assertEqual(spec.curve, Takeoff.CURVE_DISABLED)
        self.assertEqual(data.added_takeoffs[0].curve, Takeoff.CURVE_DISABLED)

    def test_new_curved_linear_takeoff_enables_curve(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        data.conditions["linear"] = Condition(
            uid="linear",
            layer_visible=True,
            condition_type=Condition.TYPE_LINEAR,
            is_curved_segment=True,
        )
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        position = [0.0, 0.0, 10.0, 0.0, 5.0, 5.0]
        handler.on_takeoff_created("linear", position, "9")
        spec = write.calls[0][2][0]
        self.assertEqual(spec.curve, Takeoff.CURVE_ENABLED)
        self.assertEqual(data.added_takeoffs[0].curve, Takeoff.CURVE_ENABLED)

    def test_multi_condition_takeoff_includes_active_when_place_list_is_stale(self):
        data = FakeProjectData()
        data.conditions["c2"] = Condition(
            uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        data.conditions["linear"] = Condition(
            uid="linear", layer_visible=True, condition_type=Condition.TYPE_LINEAR
        )
        ui_state = FakeUiState()
        ui_state.place_condition_uids = ["c1", "c1", "linear"]
        write = FakeWriteService()
        write.next_uids = ["100", "101"]
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("c2", [1.0, 2.0], "9")
        specs = write.calls[0][2]
        self.assertEqual([spec.condition_uid for spec in specs], ["c1", "c2"])
        self.assertEqual(
            [takeoff.condition_uid for takeoff in data.added_takeoffs],
            ["c1", "c2"],
        )

    def test_backout_create_undo_redo_uses_targeted_path(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.next_uids = ["hole", "redo-hole"]
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_hole_created("c1", [2.0, 2.0, 4.0, 4.0], "p1", "parent")
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(data.takeoffs["hole"].parent_uid, "parent")
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False])
        self.assertEqual([call[3] for call in write.calls], [False, False])
        self.assertEqual(data.takeoffs["redo-hole"].parent_uid, "parent")
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_same_bid_paste_backouts_placed_uses_targeted_path(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.next_uids = ["pasted-hole", "redo-hole"]
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._clipboard_svc = FakeClipboard([])
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "c1",
                    "page_uid": "p1",
                    "position": [2.0, 2.0, 4.0, 4.0],
                    "parent_uid": "parent",
                    "rotation": 0.0,
                    "is_negative": True,
                    "extras": {},
                }
            ],
            "7",
        )
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(data.takeoffs["pasted-hole"].parent_uid, "parent")
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False])
        self.assertEqual([call[3] for call in write.calls], [False, False])
        self.assertEqual(data.takeoffs["redo-hole"].parent_uid, "parent")
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_sql_paste_backout_uses_atomic_queue_without_sync_condition_clone(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._clipboard_svc = FakeClipboard(
            [], source_bid_uid="6", source_file_path="bid.mdb"
        )
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "source-condition",
                    "page_uid": "p1",
                    "position": [2.0, 2.0, 4.0, 4.0],
                    "parent_uid": "existing-parent",
                    "rotation": 0.0,
                    "is_negative": True,
                    "extras": {},
                }
            ],
            "6",
        )
        self.assertEqual(write.calls, [])
        self.assertEqual(write.condition_duplicate_calls, [])
        self.assertEqual(len(write.queued_pastes), 1)
        _database_id, payload, options, _callback = write.queued_pastes[0]
        self.assertEqual(payload.source_bid_uid, "6")
        self.assertEqual(payload.takeoff_specs[0].parent_uid, "existing-parent")
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in options["dependency_resources"]
            },
            {("condition", "source-condition")},
        )

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

            def publish(self, event_name, **event_payload):
                super().publish(event_name, **event_payload)
                if event_name == AppEvents.TAKEOFFS_CHANGED:
                    self._on_takeoffs_changed(**event_payload)

        data = FakeProjectData()
        data.selected_page_uids = []
        plan_view = ValidatingPlanView(data)
        visualization = VisualizationService()
        viewer = ViewerSyncCoordinator(
            ui_state_manager=ActiveUncheckedPageUiState(),
            ui_access_manager=None,
            color_service=None,
            project_data=data,
            callback_bridge=SimpleNamespace(
                dispatch=lambda callback, payload: callback(payload)
            ),
        )
        viewer.plan_view = plan_view
        viewer.opengl_viewer = OpenGLViewer()

        def on_takeoffs_changed(page_uid, **_call_options):
            plan_view.current_page_uid = page_uid
            plan_view._current_takeoffs = {
                uid: takeoff
                for uid, takeoff in data.takeoffs.items()
                if takeoff.page_uid == page_uid
            }
            viewer.opengl_viewer.clear_scene()
            visualization.refresh_mesh_view([])

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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        event_bus = handler._event_bus
        handler.on_reassign_condition(["t1", "missing"], "42")
        handler.on_reassign_condition(["t1"], "missing-condition")
        self.assertEqual(write.condition_calls, [("bid.mdb", ["t1"], "42", False)])
        self.assertEqual(data.takeoffs["t1"].condition_uid, "42")
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1"],
                        "condition_uids": ["c1", "42"],
                    },
                )
            ],
        )

    def test_assign_to_area_uses_targeted_update_without_quantity_refresh(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="0"
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_assign_to_area(["t1"])
        self.assertEqual(write.area_calls, [("bid.mdb", ["t1"], "0", False)])
        self.assertEqual(data.takeoffs["t1"].area_uid, "0")
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1"],
                        "condition_uids": [],
                    },
                )
            ],
        )

    def test_set_negative_uses_targeted_update_for_affected_condition(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", is_negative=False
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_set_negative(["t1"], True)
        self.assertEqual(write.negative_calls, [("bid.mdb", ["t1"], True, False)])
        self.assertTrue(data.takeoffs["t1"].is_negative)
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1"],
                        "condition_uids": ["c1"],
                    },
                )
            ],
        )

    def test_reassign_condition_rejects_incompatible_target_type(self):
        data = FakeProjectData()
        data.conditions["linear"] = Condition(
            uid="linear",
            layer_visible=True,
            condition_type=Condition.TYPE_LINEAR,
        )
        position = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0]
        data.takeoffs["area"] = Takeoff(
            uid="area",
            condition_uid="c1",
            page_uid="p1",
            position=list(position),
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        plan_view = FakePlanView(data)
        plan_view.selected = {"area"}
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_reassign_condition(["area"], "linear")
        self.assertEqual(write.condition_calls, [])
        self.assertEqual(data.takeoffs["area"].position, position)
        self.assertEqual(data.takeoffs["area"].condition_uid, "c1")
        self.assertEqual(plan_view.selected, {"area"})
        self.assertEqual(undo.count, 0)
        self.assertEqual(event_bus.events, [])

    def test_reassign_condition_rejects_mixed_geometry_selection(self):
        data = FakeProjectData()
        data.conditions["count"] = Condition(
            uid="count",
            layer_visible=True,
            condition_type=Condition.TYPE_COUNT,
        )
        data.takeoffs["area"] = Takeoff(
            uid="area",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["count"] = Takeoff(
            uid="count",
            condition_uid="count",
            page_uid="p1",
            position=[5.0, 5.0],
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_reassign_condition(["area", "count"], "42")
        self.assertEqual(write.condition_calls, [])
        self.assertEqual(data.takeoffs["area"].condition_uid, "c1")
        self.assertEqual(data.takeoffs["count"].condition_uid, "count")
        self.assertEqual(undo.count, 0)
        self.assertEqual(event_bus.events, [])

    def test_set_curved_batches_targeted_update_after_all_curve_writes(self):
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_set_curved(["t1", "t2", "t3"], True)
        self.assertEqual(len(write.curve_calls), 3)
        self.assertTrue(all(call[4] is False for call in write.curve_calls))
        self.assertEqual(write.reloads, [])
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1", "t2", "t3"],
                        "condition_uids": ["42"],
                    },
                )
            ],
        )

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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.position_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1"],
                        "condition_uids": ["c1"],
                    },
                )
            ],
        )

    def test_sql_position_edit_is_queued_and_history_waits_for_commit(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        self.assertEqual(write.position_calls, [])
        self.assertEqual(len(write.queued_geometry), 1)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(undo.count, 0)
        callback = write.queued_geometry[0][-1]
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
        )
        callback(result)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 1)
        callback(result)
        self.assertEqual(undo.count, 1)

    def test_sql_geometry_lease_is_acquired_before_preview_and_consumed_by_write(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(plan_view.geometry_lease_pending, {"t1"})
        self.assertEqual(len(write.edit_lease_requests), 1)
        database_id, resources, dependencies, options, lease_callback = (
            write.edit_lease_requests[0]
        )
        locks = tuple(
            ResourceLock(database_id, resource, f"lock-{index}")
            for index, resource in enumerate(resources)
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-1",
            runtime_generation=3,
            operation_id=options["operation_id"],
            owning_surface="main-plan",
            resources=resources,
            dependency_resources=dependencies,
            locks=locks,
        )
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(plan_view.geometry_lease_granted, {"t1"})
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        self.assertEqual(len(write.queued_geometry), 1)
        queued_options = write.queued_geometry[0][2]
        self.assertIs(queued_options["edit_lease_handle"], handle)
        self.assertEqual(queued_options["dependency_resources"], dependencies)
        self.assertEqual(write.ended_edit_leases, [])

    def test_sql_geometry_lease_is_released_when_selection_changes(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_geometry_edit_lease_requested(["t1"])
        database_id, resources, dependencies, options, lease_callback = (
            write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-1",
            runtime_generation=3,
            operation_id=options["operation_id"],
            owning_surface="main-plan",
            resources=resources,
            dependency_resources=dependencies,
            locks=tuple(
                ResourceLock(database_id, resource, f"lock-{index}")
                for index, resource in enumerate(resources)
            ),
        )
        lease_callback(EditLeaseResult(True, handle=handle))
        handler.on_plan_item_selection_changed([])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_sql_position_failure_restores_preview_after_confirmed_failure(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        write.queued_geometry[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [(changes, [])])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_takeoff_property_edit_uses_queue_not_qt_thread_writer(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", is_negative=False
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_set_negative(["t1"], True)
        self.assertEqual(write.negative_calls, [])
        self.assertEqual(len(write.queued_properties), 1)
        queued = write.queued_properties[0]
        self.assertEqual(queued[2], "takeoff_negative")
        self.assertEqual(queued[3], [("t1", True)])
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})

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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        undo.undo()
        undo.redo()
        self.assertEqual(
            [call[2] for call in write.position_calls], [False, False, False]
        )
        self.assertEqual(data.takeoffs["t1"].position, [5.0, 6.0])
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_takeoff_position_undo_redo_after_page_scale_change_uses_current_scale(
        self,
    ):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 96.0, 0.0, 96.0, 96.0, 0.0, 96.0],
        )
        write = FakeWriteService()
        undo = FakeUndoService()
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
        old_position = [0.0, 0.0, 96.0, 0.0, 96.0, 96.0, 0.0, 96.0]
        edited_position = [0.0, 0.0, 120.0, 0.0, 120.0, 120.0, 0.0, 120.0]
        handler.on_positions_flushed([("t1", old_position, edited_position)], [])
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"].position = [
            0.0,
            0.0,
            80.0,
            0.0,
            80.0,
            80.0,
            0.0,
            80.0,
        ]
        undo.undo()
        undo.redo()
        self.assertEqual(
            write.position_calls[1],
            (
                "bid.mdb",
                [("t1", [0.0, 0.0, 64.0, 0.0, 64.0, 64.0, 0.0, 64.0])],
                False,
            ),
        )
        self.assertEqual(
            write.position_calls[2],
            (
                "bid.mdb",
                [("t1", [0.0, 0.0, 80.0, 0.0, 80.0, 80.0, 0.0, 80.0])],
                False,
            ),
        )

    def test_failed_takeoff_position_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_positions = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED, AppEvents.ANNOTATIONS_CHANGED],
        )

    def test_failed_annotation_position_save_restores_only_annotations(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_positions = lambda *args, **_call_options: False
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write
        )
        takeoff_changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        ann_changes = [("a1", "annotation", [1.0, 1.0], [2.0, 2.0])]
        handler.on_positions_flushed(takeoff_changes, ann_changes)
        self.assertEqual(plan_view.restored_positions, [([], ann_changes)])

    def test_shape_annotation_position_undo_redo_after_page_scale_change_uses_current_scale(
        self,
    ):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type=ANNOTATION_TYPE_RECT,
                page_uid="p1",
                position=[0.0, 0.0, 96.0, 96.0],
            )
        ]
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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_positions_flushed(
            [],
            [
                (
                    "a1",
                    ANNOTATION_TYPE_RECT,
                    [0.0, 0.0, 96.0, 96.0],
                    [0.0, 0.0, 120.0, 120.0],
                )
            ],
        )
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        data.annotations[0].position = [0.0, 0.0, 80.0, 80.0]
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.position_calls[1],
            (
                "bid.mdb",
                [("a1", ANNOTATION_TYPE_RECT, [0.0, 0.0, 64.0, 64.0])],
                False,
            ),
        )
        self.assertEqual(
            ann_write.position_calls[2],
            (
                "bid.mdb",
                [("a1", ANNOTATION_TYPE_RECT, [0.0, 0.0, 80.0, 80.0])],
                False,
            ),
        )

    def test_failed_annotation_position_save_registers_takeoff_position_undo(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_positions = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess(set(Feature)),
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
        ann_write.save_annotation_text_properties = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_rotations_flushed([("t1", 0.0, 90.0)])
        self.assertEqual(write.rotation_calls[0][2], False)
        self.assertEqual(data.takeoffs["t1"].rotation, 90.0)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_bus.events[0][1]["page_uid"], "p1")

    def test_failed_takeoff_rotation_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_rotations = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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

    def test_group_rotation_undo_redo_after_page_scale_change_uses_current_scale(
        self,
    ):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 96.0, 0.0],
            rotation=0.0,
        )
        write = FakeWriteService()
        undo = FakeUndoService()
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
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0, 96.0, 0.0], [0.0, 0.0, 120.0, 0.0])],
            [],
            [("t1", 0.0, 45.0)],
        )
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"].position = [0.0, 0.0, 80.0, 0.0]
        undo.undo()
        undo.redo()
        self.assertEqual(
            write.position_calls[1],
            (
                "bid.mdb",
                [("t1", [0.0, 0.0, 64.0, 0.0])],
                False,
            ),
        )
        self.assertEqual(
            write.position_calls[2],
            (
                "bid.mdb",
                [("t1", [0.0, 0.0, 80.0, 0.0])],
                False,
            ),
        )

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
        write.save_takeoff_rotations = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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
        write.save_takeoff_rotations = lambda *args, **_call_options: False
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_group_rotation_takeoff_failure_stops_later_writes(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type=ANNOTATION_TYPE_RECT,
                page_uid="p1",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.save_takeoff_positions = lambda *_args, **_kwargs: False
        annotation_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        takeoff_changes = [("t1", [0.0, 0.0], [3.0, 4.0])]
        annotation_changes = [
            (
                "a1",
                ANNOTATION_TYPE_RECT,
                [1.0, 2.0, 3.0, 4.0],
                [5.0, 6.0, 7.0, 8.0],
            )
        ]
        rotation_changes = [("t1", 0.0, 45.0)]
        handler.on_group_rotation_flushed(
            takeoff_changes, annotation_changes, rotation_changes
        )
        self.assertEqual(annotation_write.position_calls, [])
        self.assertEqual(write.rotation_calls, [])
        self.assertEqual(
            plan_view.restored_positions,
            [(takeoff_changes, annotation_changes)],
        )
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])

    def test_group_rotation_annotation_failure_stops_rotation_write(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type=ANNOTATION_TYPE_RECT,
                page_uid="p1",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        annotation_write = FakeAnnotationWriteService()
        annotation_write.save_annotation_positions = lambda *_args, **_kwargs: False
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        takeoff_changes = [("t1", [0.0, 0.0], [3.0, 4.0])]
        annotation_changes = [
            (
                "a1",
                ANNOTATION_TYPE_RECT,
                [1.0, 2.0, 3.0, 4.0],
                [5.0, 6.0, 7.0, 8.0],
            )
        ]
        rotation_changes = [("t1", 0.0, 45.0)]
        handler.on_group_rotation_flushed(
            takeoff_changes, annotation_changes, rotation_changes
        )
        self.assertEqual(write.rotation_calls, [])
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(plan_view.restored_positions, [([], annotation_changes)])
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])
        self.assertEqual(undo.count, 1)

    def test_group_rotation_undo_rotation_failure_projects_saved_position(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        events = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=events,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])],
            [],
            [("t1", 0.0, 45.0)],
        )
        write.save_takeoff_rotations = lambda *_args, **_kwargs: False
        undo.undo()
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 45.0)
        self.assertEqual(
            [event for event, _payload in events.events],
            [AppEvents.TAKEOFFS_CHANGED, AppEvents.TAKEOFFS_CHANGED],
        )

    def test_group_rotation_undo_takeoff_failure_stops_later_writes(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type=ANNOTATION_TYPE_RECT,
                page_uid="p1",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        write = FakeWriteService()
        annotation_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])],
            [
                (
                    "a1",
                    ANNOTATION_TYPE_RECT,
                    [1.0, 2.0, 3.0, 4.0],
                    [5.0, 6.0, 7.0, 8.0],
                )
            ],
            [("t1", 0.0, 45.0)],
        )
        write.save_takeoff_positions = lambda *_args, **_kwargs: False
        undo.undo()
        self.assertEqual(len(annotation_write.position_calls), 1)
        self.assertEqual(len(write.rotation_calls), 1)

    def test_partial_group_rotation_undo_takeoff_failure_stops_annotation_write(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type=ANNOTATION_TYPE_RECT,
                page_uid="p1",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        write = FakeWriteService()
        annotation_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        write.save_takeoff_rotations = lambda *_args, **_kwargs: False
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])],
            [
                (
                    "a1",
                    ANNOTATION_TYPE_RECT,
                    [1.0, 2.0, 3.0, 4.0],
                    [5.0, 6.0, 7.0, 8.0],
                )
            ],
            [("t1", 0.0, 45.0)],
        )
        write.save_takeoff_positions = lambda *_args, **_kwargs: False
        undo.undo()
        self.assertEqual(len(annotation_write.position_calls), 1)

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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls[0][2], False)
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

    def test_committed_delete_projection_failure_does_not_restore_deleted_intent(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_elements_deleted(["t1"])
        callback = write.queued_deletes[0][-1]
        operation_id = str(uuid.uuid4())
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=operation_id,
                outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                commit_attempted=True,
            )
        )
        self.assertIn("t1", data.takeoffs)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(undo.count, 0)
        data.remove_takeoffs(["t1"])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 1)

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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1"])
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertNotIn("t2", data.takeoffs)
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_backout_takeoff_delete_undo_redo_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            parent_uid="0",
        )
        data.takeoffs["hole"] = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="parent",
            is_negative=True,
        )
        write = FakeWriteService()
        write.next_uids = ["new-hole"]
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["hole"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["hole"], False)])
        self.assertNotIn("hole", data.takeoffs)
        self.assertIn("parent", data.takeoffs)
        undo.undo()
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(data.takeoffs["new-hole"].parent_uid, "parent")
        self.assertEqual(plan_view.selected, {"new-hole"})
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertNotIn("new-hole", data.takeoffs)
        self.assertIn("parent", data.takeoffs)
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_parent_takeoff_with_backout_delete_uses_targeted_projection(
        self,
    ):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            parent_uid="0",
        )
        data.takeoffs["hole"] = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="parent",
            is_negative=True,
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["parent"])
        self.assertEqual(len(write.delete_calls), 1)
        self.assertEqual(write.delete_calls[0][0], "bid.mdb")
        self.assertEqual(set(write.delete_calls[0][1]), {"parent", "hole"})
        self.assertFalse(write.delete_calls[0][2])
        self.assertEqual(write.reloads, [])
        self.assertEqual(set(data.takeoffs), set())
        self.assertEqual(
            [event for event, _payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED],
        )

    def test_takeoff_delete_with_unknown_extras_uses_targeted_removal(self):
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], False)])
        self.assertEqual(write.reloads, [])
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)

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
            ui_access_manager=FakeAccess(set(Feature)),
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
        write.next_annotation_uids = ["ann-2"]
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1"])
        undo.undo()
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertNotIn("t2", data.takeoffs)
        self.assertEqual(plan_view.clears, 1)
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_takeoff_delete_undo_after_page_scale_change_uses_current_scale(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 96.0, 0.0],
        )
        write = FakeWriteService()
        write.next_uids = ["t2"]
        undo = FakeUndoService()
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
        handler.on_elements_deleted(["t1"])
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        undo.undo()
        self.assertEqual(write.calls[0][2][0].position, [0.0, 0.0, 64.0, 0.0])

    def test_annotation_delete_undo_after_page_scale_change_uses_current_scale(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_RECT,
            page_uid="p1",
            position=[0.0, 0.0, 96.0, 96.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        plan_view.annotation_key_map = {("ann-1", ANNOTATION_TYPE_RECT): "rect-item"}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["rect-item"])
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        undo.undo()
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [0.0, 0.0, 64.0, 64.0],
        )

    def test_mixed_delete_undo_uses_canonical_annotation_projection(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
        )
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_RECT,
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        plan_view.annotation_key_map[("ann-2", ANNOTATION_TYPE_RECT)] = "rect-item"
        write = FakeWriteService()
        write.next_uids = ["t2"]
        write.next_annotation_uids = ["ann-2"]
        annotation_write = FakeAnnotationWriteService()
        annotation_write.next_uids = ["ann-2"]
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1", "rect-item"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], False)])
        self.assertEqual(write.local_annotation_delete_calls[0][2], False)
        self.assertEqual(write.reloads, [])
        data.annotations = []
        undo.undo()
        self.assertEqual(
            [(item.uid, item.annotation_type) for item in data.annotations],
            [("ann-2", ANNOTATION_TYPE_RECT)],
        )
        self.assertEqual(plan_view.selected, {"t2", "rect-item"})
        undo.redo()
        self.assertEqual(data.annotations, [])
        self.assertEqual(
            [event for event, _payload in event_bus.events],
            [
                AppEvents.TAKEOFFS_CHANGED,
                AppEvents.ANNOTATIONS_CHANGED,
                AppEvents.TAKEOFFS_CHANGED,
                AppEvents.ANNOTATIONS_CHANGED,
                AppEvents.TAKEOFFS_CHANGED,
                AppEvents.ANNOTATIONS_CHANGED,
            ],
        )
        self.assertEqual(
            [call[2] for call in write.local_annotation_delete_calls],
            [False, False],
        )

    def test_mixed_delete_snapshots_takeoff_extras_before_reload(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
        )
        data.extras["t1"] = {"CustomColumn": "preserve-me"}
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_RECT,
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        write = FakeWriteService()

        def reload_and_clear_extras(db_path):
            write.reloads.append(db_path)
            data.extras.clear()
            return True

        write.reload_and_notify = reload_and_clear_extras
        annotation_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_elements_deleted(["t1", "rect-item"])
        undo.undo()
        self.assertEqual(
            write.calls[0][2][0].raw_extras,
            {"CustomColumn": "preserve-me"},
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
                    ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            [event for event, _event_payload in event_bus.events],
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
            [event for event, _event_payload in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED],
        )
        self.assertEqual(undo.count, 1)

    def test_named_view_delete_undo_remaps_hotlink_in_memory_on_every_restore(self):
        data = FakeProjectData()
        named_view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [named_view, hotlink]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"nv1": named_view}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        with patch.object(handler_module, "confirm", return_value=True):
            handler.on_elements_deleted(["nv1"])
        with patch.object(
            ann_write,
            "insert_annotations",
            side_effect=[["nv-restored-1"], ["hl-restored-1"]],
        ):
            undo.undo()
        restored = {
            annotation.annotation_type: annotation for annotation in data.annotations
        }
        self.assertEqual(restored["namedview"].uid, "nv-restored-1")
        self.assertEqual(restored["hotlink"].uid, "hl-restored-1")
        self.assertEqual(
            restored["hotlink"].properties["BidPageViewUID"], "nv-restored-1"
        )
        undo.redo()
        with patch.object(
            ann_write,
            "insert_annotations",
            side_effect=[["nv-restored-2"], ["hl-restored-2"]],
        ):
            undo.undo()
        restored = {
            annotation.annotation_type: annotation for annotation in data.annotations
        }
        self.assertEqual(restored["namedview"].uid, "nv-restored-2")
        self.assertEqual(restored["hotlink"].uid, "hl-restored-2")
        self.assertEqual(
            restored["hotlink"].properties["BidPageViewUID"], "nv-restored-2"
        )

    def test_bulk_named_view_delete_decline_skips_only_that_view(self):
        data = FakeProjectData()
        skipped_view = _named_view_annotation("nv1", "Lobby")
        skipped_hotlink = _hotlink_annotation("hl1", "nv1")
        confirmed_view = _named_view_annotation("nv2", "Office")
        confirmed_hotlink = _hotlink_annotation("hl2", "nv2")
        rect = _rect_annotation("r1")
        data.annotations = [
            skipped_view,
            skipped_hotlink,
            confirmed_view,
            confirmed_hotlink,
            rect,
        ]
        plan_view = FakePlanView(data)
        plan_view.annotations = {
            "nv1": skipped_view,
            "nv2": confirmed_view,
            "r1": rect,
        }
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        with patch.object(handler_module, "confirm", side_effect=[False, True]):
            handler.on_elements_deleted(["nv1", "nv2", "r1"])
        self.assertEqual(
            ann_write.delete_calls,
            [
                (
                    "bid.mdb",
                    [("hl2", "hotlink"), ("r1", "rect"), ("nv2", "namedview")],
                    False,
                )
            ],
        )
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in data.annotations],
            [("nv1", "namedview"), ("hl1", "hotlink")],
        )
        self.assertEqual(plan_view.selected, {"nv1"})
        self.assertEqual(undo.count, 1)
        self.assertEqual(
            [event for event, _event_payload in event_bus.events],
            [AppEvents.ANNOTATIONS_CHANGED],
        )

    def test_bulk_named_view_delete_all_skipped_does_not_write_or_refresh(self):
        data = FakeProjectData()
        first_view = _named_view_annotation("nv1", "Lobby")
        first_hotlink = _hotlink_annotation("hl1", "nv1")
        second_view = _named_view_annotation("nv2", "Office")
        second_hotlink = _hotlink_annotation("hl2", "nv2")
        data.annotations = [first_view, first_hotlink, second_view, second_hotlink]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"nv1": first_view, "nv2": second_view}
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        with patch.object(handler_module, "confirm", side_effect=[False, False]):
            handler.on_elements_deleted(["nv1", "nv2"])
        self.assertEqual(ann_write.delete_calls, [])
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in data.annotations],
            [
                ("nv1", "namedview"),
                ("hl1", "hotlink"),
                ("nv2", "namedview"),
                ("hl2", "hotlink"),
            ],
        )
        self.assertEqual(plan_view.selected, {"nv1", "nv2"})
        self.assertEqual(undo.count, 0)
        self.assertEqual(event_bus.events, [])

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
            ui_access_manager=FakeAccess(set(Feature)),
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

    def test_parent_child_paste_stops_after_incomplete_authoritative_id_batch(self):
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
        for uid_batches, expected_insert_count in (
            ([[], ["must-not-be-used"]], 1),
            ([["new-parent"], []], 2),
        ):
            with self.subTest(uid_batches=uid_batches):
                plan_view = FakePlanView()
                write = FakeWriteService()
                write.uid_batches = uid_batches
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
                    ui_access_manager=FakeAccess(set(Feature)),
                )
                handler._clipboard_svc = FakeClipboard([parent, hole])
                handler.on_paste_requested()
                self.assertEqual(len(write.calls), expected_insert_count)
                self.assertEqual(write.reloads, [])
                self.assertEqual(plan_view.selected, set())
                self.assertEqual(undo.count, 0)

    def test_paste_parent_child_with_known_extras_uses_targeted_projection(self):
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._clipboard_svc = FakeClipboard(
            [parent, hole],
            extras={"old-parent": {"GUID": "{P}"}, "old-hole": {"GUID": "{H}"}},
        )
        handler.on_paste_requested()
        self.assertEqual([call[3] for call in write.calls], [False, False])
        self.assertEqual(write.reloads, [])
        self.assertEqual(
            [takeoff.uid for takeoff in data.added_takeoffs],
            ["100", "101"],
        )
        self.assertEqual(
            [event for event, _payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED],
        )

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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            [event for event, _event_payload in event_bus.events],
            [AppEvents.TAKEOFFS_CHANGED] * 3,
        )

    def test_takeoff_paste_redo_after_page_scale_change_uses_current_scale(self):
        source = Takeoff(
            uid="source",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 106.0, 20.0],
            parent_uid="0",
        )
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        undo.undo()
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        undo.redo()
        self.assertEqual(
            write.calls[1][2][0].position,
            [
                7.333333333333333,
                14.0,
                71.33333333333333,
                14.0,
            ],
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._clipboard_svc = FakeClipboard(
            [source], extras={"source": {"UnsupportedColumn": "value"}}
        )
        handler.on_paste_requested()
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(write.reloads, ["bid.mdb"])
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler._clipboard_svc = FakeClipboard(
            [source],
            source_bid_uid="6",
            source_file_path="bid.mdb",
        )
        handler.on_paste_requested()
        self.assertEqual(
            write.condition_duplicate_calls,
            [("bid.mdb", "6", "7", ["c1"], False)],
        )
        self.assertEqual(write.calls[0][2][0].condition_uid, "new-c1")
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(write.reloads, ["bid.mdb"])
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
            ui_access_manager=FakeAccess(set(Feature)),
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

    def test_annotation_only_paste_uses_placement_not_plan_edit_permission(self):
        source = self._copied_annotation()
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view,
            ann_write=ann_write,
            allowed_features={Feature.PLACE_ANNOTATIONS},
        )
        handler._clipboard_svc = FakeClipboard([], annotations=[source])
        self.assertTrue(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(len(ann_write.insert_calls), 1)

    def test_annotation_only_paste_is_denied_without_placement_permission(self):
        source = self._copied_annotation()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            ann_write=ann_write,
            allowed_features={Feature.EDIT_PLAN_ITEMS},
        )
        handler._clipboard_svc = FakeClipboard([], annotations=[source])
        self.assertFalse(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(ann_write.insert_calls, [])

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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess(set(Feature)),
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
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
