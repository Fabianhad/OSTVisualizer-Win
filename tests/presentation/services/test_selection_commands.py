import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
    hex_color_to_int,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.selection_commands import (
    DeleteAnnotationsCommand,
    InsertAnnotationsCommand,
    InsertTakeoffsCommand,
    PasteAnnotationsCommand,
    PasteTakeoffsCommand,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from dataclasses import replace
from pathlib import Path
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    QueuedMutationResult,
    ResourceLock,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    parse_annotation_resource_id,
)
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.application.dtos.write_reload_result import WriteReloadResult
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


def _command_annotation_history(uids, kind="rect"):
    from ost_visualizer.presentation.services.annotation_history import (
        AnnotationHistoryBinding,
    )
    from ost_visualizer.presentation.services.undo_redo_service import (
        AnnotationHistoryTarget,
        UndoRedoService,
    )

    data = FakeProjectData()
    bid_ref = BidRef("bid.mdb", "7")
    undo = UndoRedoService()
    undo.set_active_bid(bid_ref)
    return AnnotationHistoryBinding(
        data,
        undo,
        bid_ref,
        {
            (uid, kind): AnnotationHistoryTarget(bid_ref, "p1", kind, uid)
            for uid in uids
        },
    )


def _rect_annotation(uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid="p1",
        position=[1.0, 2.0, 3.0, 4.0],
    )


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
            ),
            "9": SimpleNamespace(
                uid="9",
                overlay_rect=None,
                scale_factor1=1.0,
                scale_factor2=1.0,
            ),
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

    def get_current_bid_ref(self):
        return BidRef(file_path="bid.mdb", bid_uid="7")

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

    def get_bid_annotation_layer_uid(self, _bid_ref):
        return self.annotation_layer_uid

    def get_page_name(self, page_uid):
        return self.page_names.get(page_uid, "")


class FakePlanView:
    def __init__(self, data=None):
        self._is_cleaning_up = False
        self.selected = set()
        self.selection_revision = 0
        self.tool_revision = 0
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
        self.projected_overlay_rects = []
        self.clipboard_changed = SimpleNamespace(emit=lambda: None)

    def set_selected_uids(self, uids):
        if self.selected != set(uids):
            self.selection_revision += 1
        self.selected = set(uids)

    def begin_deferred_selection(self):
        self.selection_revision += 1
        return self.selection_revision

    def get_selected_uids(self):
        return set(self.selected)

    def clear_selection(self):
        self.clears += 1
        self.set_selected_uids(set())

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

    def begin_paste_backout(
        self, holes, extras_by_uid, source_bid_uid, *, conditions=None
    ):
        self.paste_backout_calls.append((holes, extras_by_uid, source_bid_uid))

    def current_mouse_ost_position(self):
        return self.mouse_ost_position

    def mark_intelligent_paste_drag_pending(self, pasted_uids, source_anchor_ost):
        self.intelligent_paste_calls.append((list(pasted_uids), source_anchor_ost))
        return True

    def project_overlay_rect(self, page_uid, overlay_rect):
        self.projected_overlay_rects.append((page_uid, overlay_rect))
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
        self.local_geometry = []
        self.local_properties = []
        self.local_deletes = []
        self.local_pastes = []
        self.local_annotation_delete_calls = []
        self.next_annotation_uids = ["ann-1"]
        self.annotation_write_service = None
        self.insert_takeoffs_failure_reason = None
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

    def queue_plan_geometry(
        self,
        database_id,
        bid_uid,
        callback,
        *,
        takeoff_positions=(),
        takeoff_rotations=(),
        annotation_positions=(),
        page_uids=(),
        dependency_resources=(),
        owning_surface="main-plan",
        edit_lease_handle=None,
    ):
        updates = {
            "takeoff_positions": takeoff_positions,
            "takeoff_rotations": takeoff_rotations,
            "annotation_positions": annotation_positions,
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "owning_surface": owning_surface,
            "edit_lease_handle": edit_lease_handle,
        }
        self.queued_geometry.append((database_id, bid_uid, updates, callback))
        return len(self.queued_geometry)

    def execute_plan_geometry_local(
        self,
        database_id,
        bid_uid,
        *,
        takeoff_positions=(),
        takeoff_rotations=(),
        annotation_positions=(),
        page_uids=(),
        dependency_resources=(),
        publish_database_refreshed_after_write=True,
    ):
        options = {
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "publish_database_refreshed_after_write": (
                publish_database_refreshed_after_write
            ),
        }
        self.local_geometry.append(
            (
                database_id,
                bid_uid,
                list(takeoff_positions),
                list(takeoff_rotations),
                list(annotation_positions),
                options,
            )
        )
        success = True
        if takeoff_positions:
            success = self.save_takeoff_positions(
                database_id,
                list(takeoff_positions),
                publish_database_refreshed_after_write=False,
            )
        if success and takeoff_rotations:
            success = self.save_takeoff_rotations(
                database_id,
                list(takeoff_rotations),
                publish_database_refreshed_after_write=False,
            )
        if success and annotation_positions:
            if self.annotation_write_service is None:
                raise AssertionError("The test must supply its annotation writer")
            success = self.annotation_write_service.save_annotation_positions(
                database_id,
                list(annotation_positions),
                publish_database_refreshed_after_write=False,
            )
        return MutationExecutionResult(
            outcome_status=(
                MutationOutcomeStatus.COMMITTED
                if success
                else MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )

    def execute_plan_properties_local(
        self,
        database_id,
        bid_uid,
        property_kind,
        updates,
        *,
        page_uids=(),
        dependency_resources=(),
        publish_database_refreshed_after_write=True,
    ):
        self.local_properties.append(
            (database_id, bid_uid, property_kind, list(updates))
        )
        success = True
        if property_kind == "takeoff_text":
            success = self.save_takeoff_text_properties(
                database_id,
                list(updates),
                publish_database_refreshed_after_write=False,
            )
        elif property_kind in {"takeoff_area", "takeoff_condition"}:
            assignments = {}
            for takeoff_uid, target_uid in updates:
                assignments.setdefault(str(target_uid), []).append(str(takeoff_uid))
            for target_uid, assigned_uids in assignments.items():
                if property_kind == "takeoff_area":
                    success = self.save_takeoffs_area(
                        database_id,
                        assigned_uids,
                        target_uid,
                        publish_database_refreshed_after_write=False,
                    )
                else:
                    success = self.save_takeoffs_condition(
                        database_id,
                        assigned_uids,
                        target_uid,
                        publish_database_refreshed_after_write=False,
                    )
                if not success:
                    break
        elif property_kind == "takeoff_negative":
            assignments = {}
            for takeoff_uid, value in updates:
                assignments.setdefault(bool(value), []).append(str(takeoff_uid))
            for value, assigned_uids in assignments.items():
                success = self.set_takeoffs_negative(
                    database_id,
                    assigned_uids,
                    value,
                    publish_database_refreshed_after_write=False,
                )
                if not success:
                    break
        elif property_kind == "takeoff_curve":
            for takeoff_uid, position, curve in updates:
                success = self.set_takeoff_curve(
                    database_id,
                    takeoff_uid,
                    position,
                    curve,
                    publish_database_refreshed_after_write=False,
                )
                if not success:
                    break
        else:
            raise AssertionError(f"Unsupported fake property kind: {property_kind}")
        return MutationExecutionResult(
            outcome_status=(
                MutationOutcomeStatus.COMMITTED
                if success
                else MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )

    def request_plan_edit_lease(
        self,
        database_id,
        resources,
        dependency_resources,
        callback,
        *,
        operation_id,
        owning_surface,
    ):
        options = {
            "operation_id": operation_id,
            "owning_surface": owning_surface,
        }
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
        *,
        page_uids=(),
        dependency_resources=(),
        owning_surface="main-plan",
    ):
        options = {
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "owning_surface": owning_surface,
        }
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
        *,
        page_uids=(),
        dependency_resources=(),
        owning_surface="main-plan",
    ):
        options = {
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "owning_surface": owning_surface,
        }
        self.queued_deletes.append(
            (database_id, bid_uid, takeoff_uids, annotations, options, callback)
        )
        return len(self.queued_deletes)

    def queue_plan_items_paste(
        self,
        database_id,
        payload,
        callback,
        *,
        dependency_resources=(),
        owning_surface="main-plan",
    ):
        options = {
            "dependency_resources": dependency_resources,
            "owning_surface": owning_surface,
        }
        self.queued_pastes.append((database_id, payload, options, callback))
        return len(self.queued_pastes)

    def execute_plan_items_delete_local(
        self,
        database_id,
        bid_uid,
        takeoff_uids,
        annotations,
        *,
        page_uids=(),
        dependency_resources=(),
        publish_database_refreshed_after_write=True,
    ):
        options = {
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "publish_database_refreshed_after_write": (
                publish_database_refreshed_after_write
            ),
        }
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

    def execute_plan_items_paste_local(
        self,
        database_id,
        payload,
        *,
        dependency_resources=(),
        publish_database_refreshed_after_write=True,
    ):
        options = {
            "dependency_resources": dependency_resources,
            "publish_database_refreshed_after_write": (
                publish_database_refreshed_after_write
            ),
        }
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
            or str(spec.parent_uid) not in payload.takeoff_source_uids
            or payload.takeoff_source_uids[index]
            in payload.takeoff_external_parent_sources
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
                    remap.namedview_uids[
                        parse_annotation_resource_id(
                            payload.annotation_source_uids[index]
                        )[1]
                    ] = uid
            if other_indexes:
                other_uids = self.annotation_write_service.insert_annotations(
                    database_id,
                    payload.destination_bid_uid,
                    [payload.annotation_specs[index] for index in other_indexes],
                    remap,
                    False,
                )
                by_index.update(dict(zip(other_indexes, other_uids)))
            if len(by_index) != len(payload.annotation_specs):
                return MutationExecutionResult(
                    outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                    message="Incomplete annotation identity map",
                )
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

    def insert_takeoffs_result(
        self, db_path, bid_uid, specs, publish_database_refreshed_after_write=True
    ):
        if self.insert_takeoffs_failure_reason:
            return WriteReloadResult(
                [],
                write_success=False,
                reload_success=False,
                failure_reason=self.insert_takeoffs_failure_reason,
            )
        values = self.insert_takeoffs(
            db_path,
            bid_uid,
            specs,
            publish_database_refreshed_after_write,
        )
        return WriteReloadResult(
            values,
            write_success=True,
            reload_success=True,
        )

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
            history=_command_annotation_history(["old-1", "old-2"]),
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
            history=_command_annotation_history(["old-1", "old-2"]),
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


class SelectionCommandsParentRemapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(r"C:\Windows\Fonts")
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def setUp(self):
        apply_config_owned_annotation_defaults(Config())

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
        apply_config_owned_annotation_defaults(Config())

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
            history=_command_annotation_history(["initial-ann"], "hotlink"),
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
