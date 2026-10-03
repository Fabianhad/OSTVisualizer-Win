import dataclasses
import gc
import math
import unittest
import uuid
import weakref
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
    locked_bid_refusal_result,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PlanGeometryPayload,
    PlanItemsDeletePayload,
    PlanItemsPastePayload,
    PlanPropertyPayload,
    QueuedMutationResult,
    ResourceLock,
    ResourceRef,
    queued_takeoff_preview_uid,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
    parse_annotation_resource_id,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.application.dtos.write_reload_result import WriteReloadResult
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
    hex_color_to_int,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.file_state import normalize_path
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as handler_module,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.services.annotation_history import (
    HOTLINK_VIEW_UNAVAILABLE_MESSAGE,
    AnnotationHistoryDependencyError,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)
from ost_visualizer.presentation.utils.annotation_paste import annotation_paste_anchor
from ost_visualizer.presentation.utils.font_catalog import resolve_font_definition
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.application.dtos.collaboration_dtos import (
    PlanItemsPastePayload,
    AuthoritativeMutationResult,
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


def _rect_annotation(uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid="p1",
        position=[1.0, 2.0, 3.0, 4.0],
    )


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


class _FakeConfigModel:
    def __init__(self, config: Config):
        self._config = config

    def snapshot(self) -> Config:
        return self._config


class FakeUiState:
    place_condition_uids = []
    active_page_uid = "p1"
    config_model = _FakeConfigModel(Config())

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
            self.extras.pop(uid, None)
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
        self.cleanup_delete_calls = []
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

    def queue_cancelled_placement_cleanup_delete(
        self,
        database_id,
        bid_uid,
        takeoff_uids,
        callback,
        *,
        page_uids=(),
        dependency_resources=(),
    ):
        # The locked-Bid exempt entry point (decision B5): never refused here, even
        # in _LockedBidWriteService. It lands in queued_deletes like a plain delete
        # (so the placement tests keep reading one list) and is also recorded apart.
        options = {
            "page_uids": page_uids,
            "dependency_resources": dependency_resources,
            "owning_surface": "main-plan",
        }
        self.cleanup_delete_calls.append(
            (database_id, bid_uid, takeoff_uids, options, callback)
        )
        self.queued_deletes.append(
            (database_id, bid_uid, takeoff_uids, [], options, callback)
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


class FakeDeferredPersistence:
    def __init__(self, accepts_writes=True):
        self.overlay_rect_calls = []
        self.overlay_rect_callbacks = []
        self.accepts_writes = accepts_writes

    def schedule_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: tuple[float, float, float, float],
        **callbacks,
    ) -> bool:
        self.overlay_rect_calls.append((db_path, page_uid, overlay_rect))
        self.overlay_rect_callbacks.append(callbacks)
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
        self.forward_mutations = []
        self.takeoff_targets = []
        self.annotation_targets = []

    def push_local(self, undo, redo, *, takeoff_targets=(), annotation_targets=()):
        self.takeoff_targets.extend(takeoff_targets)
        self.annotation_targets.extend(annotation_targets)
        self.count += 1
        self.undo = undo
        self.redo = redo

    def push(
        self, undo_submit, redo_submit, *, takeoff_targets=(), annotation_targets=()
    ):
        self.takeoff_targets.extend(takeoff_targets)
        self.annotation_targets.extend(annotation_targets)
        self.count += 1
        self.undo = lambda: undo_submit(lambda _success: None)
        self.redo = lambda: redo_submit(lambda _success: None)

    def push_for_bid(
        self,
        _bid_ref,
        undo_submit,
        redo_submit,
        *,
        takeoff_targets=(),
        annotation_targets=(),
    ):
        self.push(
            undo_submit,
            redo_submit,
            takeoff_targets=takeoff_targets,
            annotation_targets=annotation_targets,
        )

    def notify_annotation_deletion(self, bid_ref, identities):
        pass

    def suspend_deleted_annotations(self, bid_ref, deleted):
        identities = {target.identity for target in deleted if target.available}
        suspended = []
        for target in (*deleted, *self.annotation_targets):
            if (
                target.available
                and target.bid_ref == bid_ref
                and target.identity in identities
            ):
                target.available = False
                suspended.append(target)
        return tuple(suspended)

    def rebind_restored_annotations(self, bid_ref, restored, targets):
        replacements = [
            (target, restored[target.identity])
            for target in targets
            if target.bid_ref == bid_ref
        ]
        for target, uid in replacements:
            target.uid = uid
            target.available = True

    def suspend_deleted_takeoffs(self, bid_ref, deleted):
        identities = {(target.page_uid, target.uid) for target in deleted}
        result = []
        for target in (*deleted, *self.takeoff_targets):
            if (
                target.available
                and target.bid_ref == bid_ref
                and (target.page_uid, target.uid) in identities
            ):
                target.available = False
                result.append(target)
        return tuple(result)

    def rebind_restored_takeoffs(self, bid_ref, restored, targets):
        replacements = [
            (target, restored[(target.page_uid, target.uid)])
            for target in targets
            if target.bid_ref == bid_ref
        ]
        for target, uid in replacements:
            target.uid = uid
            target.available = True

    def begin_forward_mutation(self, bid_ref):
        token = object()
        self.forward_mutations.append((token, bid_ref))
        return token

    def finish_forward_mutation(self, token):
        self.forward_mutations = [
            item for item in self.forward_mutations if item[0] is not token
        ]

    def bind_latest_history_to_forward_mutation(self, _token):
        pass

    def is_forward_mutation_current(self, token):
        return any(item[0] is token for item in self.forward_mutations)


class FakeClipboard:
    conditions = {}

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

    def source_matches_database(self, file_path):
        return bool(
            self.source_file_path
            and file_path
            and normalize_path(self.source_file_path) == normalize_path(file_path)
        )

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


class _PlanViewActionHandlerFixture(unittest.TestCase):
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

    def _paste_handler(
        self,
        plan_view=None,
        write=None,
        ann_write=None,
        allowed_features=None,
        data=None,
        undo=None,
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
            undo_svc=FakeUndoService() if undo is None else undo,
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

    def _make_group_transform_handler(self, takeoff_states, sql_mutations):
        data = FakeProjectData()
        data.takeoffs = {
            uid: Takeoff(
                uid=uid,
                condition_uid=f"{uid}-condition",
                page_uid="p1",
                position=list(position),
                rotation=rotation,
            )
            for uid, (position, rotation) in takeoff_states.items()
        }
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql_mutations
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
        return handler, write, undo


class PlanViewActionHandlerTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler: lifecycle and combined contracts."""

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

    def test_single_page_changes_publish_page_uid_without_page_uid_list(self):
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
        handler._publish_takeoffs_changed_for_pages(["p1", "p1"], ["t1"], ["c1"])
        handler._annotation_writes.publish_annotations_changed_for_pages(
            ["p1", "p1"], ["a1"], ["rect"]
        )
        handler._publish_takeoffs_changed_for_pages([], ["t1"], ["c1"])
        handler._annotation_writes.publish_annotations_changed_for_pages(
            [], ["a1"], ["rect"]
        )
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
                ),
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["a1"],
                        "annotation_types": ["rect"],
                    },
                ),
            ],
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
        self.assertEqual(
            [call[1:4] for call in write.curve_calls],
            [
                ("t1", [0.0, 0.0, 10.0, 0.0, 5.0, 0.0, 0.0], Takeoff.CURVE_ENABLED),
                ("t2", [0.0, 10.0, 10.0, 10.0, 5.0, 10.0, 0.0], Takeoff.CURVE_ENABLED),
            ],
        )
        self.assertEqual(
            [(uid, data.takeoffs[uid].curve) for uid in ("t1", "t2")],
            [("t1", Takeoff.CURVE_ENABLED), ("t2", Takeoff.CURVE_ENABLED)],
        )
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

    def test_unknown_annotation_delete_does_not_emit_refresh(self):
        data = FakeProjectData()
        annotation = BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1": annotation}
        ann_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        handler.on_elements_deleted(["missing"])
        self.assertEqual(ann_write.delete_calls, [])
        self.assertEqual(write.delete_calls, [])
        self.assertEqual(write.local_deletes, [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._event_bus.events, [])
        self.assertEqual([item.uid for item in data.annotations], ["a1"])

    def test_backout_create_undo_redo_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent", page_uid="p1", condition_uid="c1"
        )
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
        data.takeoffs["parent"] = Takeoff(
            uid="parent", page_uid="p1", condition_uid="c1"
        )
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
        self.assertEqual(write.local_pastes[0][2]["dependency_resources"], ())
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

    def test_approved_raw_extra_insert_keeps_fast_refresh(self):
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
        self.assertEqual(write.calls[0][3], False)
        self.assertEqual(len(data.added_takeoffs), 1)

    def test_unapproved_raw_extra_insert_requests_full_refresh(self):
        data = FakeProjectData()
        write = FakeWriteService()
        handler = self._paste_handler(write=write, data=data)
        spec = InsertTakeoffSpec(
            condition_uid="42",
            page_uid="9",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={"UnsupportedColumn": "value"},
        )
        handler._insert_takeoffs_with_undo(
            BidRef(file_path="bid.mdb", bid_uid="7"),
            [spec],
            fast_refresh=True,
        )
        self.assertEqual(write.calls[0][3], True)
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(handler._event_bus.events, [])
        self.assertEqual(handler._plan_view.selected, {"100"})

    def test_hole_creation_requires_parent_page_and_visible_condition(self):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent", page_uid="p1", condition_uid="c1"
        )
        write = FakeWriteService()
        handler = self._paste_handler(write=write, data=data)
        position = [2.0, 2.0, 4.0, 4.0]
        handler.on_hole_created("c1", position, "p1", "")
        handler.on_hole_created("c1", position, "", "parent")
        handler.on_hole_created("missing", position, "p1", "parent")
        self.assertEqual(write.calls, [])
        self.assertEqual(data.added_takeoffs, [])
        handler.on_hole_created("c1", position, "p1", "parent")
        self.assertEqual(len(write.calls), 1)
        self.assertEqual(write.calls[0][2][0].parent_uid, "parent")

    def test_assign_to_area_uses_targeted_update_without_quantity_refresh(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-1"
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
        self.assertEqual(write.reloads, [])
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

    def test_assign_to_area_undo_restores_each_original_area(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-1"
        )
        data.takeoffs["t2"] = Takeoff(
            uid="t2", condition_uid="c1", page_uid="p1", area_uid="area-2"
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
        handler.on_assign_to_area(["t1", "t2"])
        self.assertEqual(
            (data.takeoffs["t1"].area_uid, data.takeoffs["t2"].area_uid),
            ("0", "0"),
        )
        undo.undo()
        self.assertEqual(
            (data.takeoffs["t1"].area_uid, data.takeoffs["t2"].area_uid),
            ("area-1", "area-2"),
        )
        undo.redo()
        self.assertEqual(
            (data.takeoffs["t1"].area_uid, data.takeoffs["t2"].area_uid),
            ("0", "0"),
        )

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
        self.assertEqual(
            [call[1:4] for call in write.curve_calls],
            [
                (uid, [0.0, 0.0, 10.0, 0.0, 5.0, 0.0, 0.0], Takeoff.CURVE_ENABLED)
                for uid in ("t1", "t2", "t3")
            ],
        )
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

    def test_set_curved_false_restores_straight_segment_and_undo_recurves(self):
        curved_position = [0.0, 0.0, 10.0, 0.0, 5.0, 3.0, 0.0]
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="42",
            page_uid="p1",
            position=list(curved_position),
            curve=Takeoff.CURVE_ENABLED,
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(data),
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
        handler.on_set_curved(["t1"], False)
        self.assertEqual(
            [call[1:4] for call in write.curve_calls],
            [("t1", [0.0, 0.0, 10.0, 0.0], Takeoff.CURVE_DISABLED)],
        )
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0, 10.0, 0.0])
        self.assertEqual(data.takeoffs["t1"].curve, Takeoff.CURVE_DISABLED)
        self.assertEqual(undo.count, 1)
        self.assertTrue(undo.undo())
        self.assertEqual(data.takeoffs["t1"].position, curved_position)
        self.assertEqual(data.takeoffs["t1"].curve, Takeoff.CURVE_ENABLED)

    def test_set_curved_denied_without_edit_access_writes_nothing(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="42",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=FakePlanView(data),
            write=write,
            data=data,
            undo=undo,
            allowed_features=set(),
        )
        handler.on_set_curved(["t1"], True)
        self.assertEqual(write.curve_calls, [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0, 10.0, 0.0])

    def test_small_resize_geometry_payload_matches_mdb_and_sql(self):
        old_position = [0.0, 0.0, 10.0, 0.0]
        resized_position = [0.0, 0.0, 11.0, 0.0]
        changes = [("t1", old_position, resized_position)]

        def make_handler(sql_collaboration_mutations):
            data = FakeProjectData()
            data.takeoffs["t1"] = Takeoff(
                uid="t1",
                condition_uid="c1",
                page_uid="p1",
                position=list(old_position),
            )
            write = FakeWriteService()
            write.sql_collaboration_mutations = sql_collaboration_mutations
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
                ui_access_manager=FakeAccess(set(Feature)),
            )
            return handler, write

        mdb_handler, mdb_write = make_handler(False)
        sql_handler, sql_write = make_handler(True)
        mdb_handler.on_positions_flushed(changes, [])
        sql_handler.on_positions_flushed(changes, [])
        mdb_geometry = mdb_write.position_calls[0][1]
        sql_geometry = sql_write.queued_geometry[0][2]["takeoff_positions"]
        expected_geometry = [("t1", resized_position)]
        self.assertEqual(mdb_geometry, expected_geometry)
        self.assertEqual(sql_geometry, expected_geometry)

    def test_sql_paste_failure_restores_selection_by_authoritative_identity(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Old"},
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("shared", "text"): "shared"}
        plan_view.annotations = {"shared": annotation}
        plan_view.selected = {"shared"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(
                InsertTakeoffSpec(
                    condition_uid="c1",
                    page_uid="p1",
                    area_uid=None,
                    position=[1.0, 2.0],
                ),
            ),
        )
        handler._queue_sql_plan_items_paste_payload(
            BidRef("bid.mdb", "7"),
            "p1",
            payload,
            (),
        )
        self.assertEqual(plan_view.selected, set())
        data.takeoffs["shared"] = Takeoff(
            uid="shared",
            condition_uid="c1",
            page_uid="p1",
        )
        plan_view.annotation_key_map = {("shared", "text"): "shared_text"}
        plan_view.annotations = {"shared_text": annotation}
        write.queued_pastes[0][3](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.selected, {"shared_text"})

    def test_pure_takeoff_rotation_uses_takeoffs_changed(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", rotation=0.0
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        undo = FakeUndoService()
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
        handler.on_rotations_flushed([("t1", 0.0, 90.0)])
        self.assertEqual(write.rotation_calls, [("bid.mdb", [("t1", 90.0)], False)])
        self.assertEqual(write.reloads, [])
        self.assertEqual(data.takeoffs["t1"].rotation, 90.0)
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
        self.assertEqual(undo.count, 1)
        self.assertTrue(undo.undo())
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertTrue(undo.redo())
        self.assertEqual(data.takeoffs["t1"].rotation, 90.0)
        self.assertEqual(
            [call[1] for call in write.rotation_calls],
            [[("t1", 90.0)], [("t1", 0.0)], [("t1", 90.0)]],
        )

    def test_sql_rotation_edit_is_queued_and_failure_restores_preview(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", rotation=0.0
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        changes = [("t1", 0.0, 90.0)]
        handler.on_rotations_flushed(changes)
        self.assertEqual(write.rotation_calls, [])
        self.assertEqual(len(write.queued_geometry), 1)
        queued_payload = write.queued_geometry[0][2]
        self.assertEqual(queued_payload["takeoff_rotations"], [("t1", 90.0)])
        self.assertEqual(queued_payload["takeoff_positions"], [])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        write.queued_geometry[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.restored_rotations, [changes])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 0)

    def test_rotation_and_position_edits_of_queued_previews_or_denied_are_restored(
        self,
    ):
        preview_uid = queued_takeoff_preview_uid(str(uuid.uuid4()), 0)
        for sql_mutations, allowed, uid in (
            (True, set(Feature), preview_uid),
            (False, set(Feature), preview_uid),
            (False, set(), "t1"),
            (True, set(), "t1"),
        ):
            with self.subTest(sql=sql_mutations, allowed=bool(allowed), uid=uid[:7]):
                plan_view = FakePlanView()
                write = FakeWriteService()
                write.sql_collaboration_mutations = sql_mutations
                undo = FakeUndoService()
                handler = self._paste_handler(
                    plan_view=plan_view,
                    write=write,
                    undo=undo,
                    allowed_features=allowed,
                )
                rotation_changes = [(uid, 0.0, 90.0)]
                position_changes = [(uid, [0.0, 0.0], [1.0, 2.0])]
                handler.on_rotations_flushed(rotation_changes)
                handler.on_positions_flushed(position_changes, [])
                self.assertEqual(plan_view.restored_rotations, [rotation_changes])
                self.assertEqual(plan_view.restored_positions, [(position_changes, [])])
                self.assertEqual(write.rotation_calls, [])
                self.assertEqual(write.position_calls, [])
                self.assertEqual(write.queued_geometry, [])
                self.assertEqual(undo.count, 0)

    def test_failed_takeoff_rotation_save_restores_plan_view(self):
        plan_view = FakePlanView()
        write = FakeWriteService()
        write.save_takeoff_rotations = lambda *args, **_call_options: False
        undo = FakeUndoService()
        handler = self._paste_handler(plan_view=plan_view, write=write, undo=undo)
        changes = [("t1", 0.0, 90.0)]
        handler.on_rotations_flushed(changes)
        self.assertEqual(plan_view.restored_rotations, [changes])
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._event_bus.events, [])

    def test_group_move_payload_matches_mdb_sql_and_mdb_undo_redo(self):
        first_old = [3.0, 3.0, 13.0, 3.0]
        second_old = [22.0, 22.0, 32.0, 22.0]
        first_new = [13.0, 13.0, 23.0, 13.0]
        second_new = [32.0, 32.0, 42.0, 32.0]
        takeoff_states = {
            "first": (first_old, 0.0),
            "second": (second_old, 0.0),
        }
        changes = [
            ("first", first_old, first_new),
            ("second", second_old, second_new),
        ]
        expected = [("first", first_new), ("second", second_new)]
        mdb_handler, mdb_write, mdb_undo = self._make_group_transform_handler(
            takeoff_states, False
        )
        sql_handler, sql_write, _sql_undo = self._make_group_transform_handler(
            takeoff_states, True
        )
        mdb_handler.on_positions_flushed(changes, [])
        sql_handler.on_positions_flushed(changes, [])
        self.assertEqual(mdb_write.position_calls[0][1], expected)
        self.assertEqual(sql_write.queued_geometry[0][2]["takeoff_positions"], expected)
        self.assertEqual(mdb_undo.count, 1)
        self.assertTrue(mdb_undo.undo())
        self.assertTrue(mdb_undo.redo())
        self.assertEqual(
            mdb_write.position_calls[1][1],
            [("first", first_old), ("second", second_old)],
        )
        self.assertEqual(mdb_write.position_calls[2][1], expected)

    def test_curved_linear_flip_payload_matches_mdb_sql_and_mdb_undo_redo(self):
        old_position = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, -8.0]
        new_position = [40.0, 0.0, 20.0, 0.0, 30.0, 8.0, 8.0]
        takeoff_states = {"linear": (old_position, 0.0)}
        changes = [("linear", old_position, new_position)]
        expected = [("linear", new_position)]
        mdb_handler, mdb_write, mdb_undo = self._make_group_transform_handler(
            takeoff_states, False
        )
        sql_handler, sql_write, _sql_undo = self._make_group_transform_handler(
            takeoff_states, True
        )
        mdb_handler.on_group_rotation_flushed(changes, [], [])
        sql_handler.on_group_rotation_flushed(changes, [], [])
        self.assertEqual(mdb_write.position_calls[0][1], expected)
        self.assertEqual(sql_write.queued_geometry[0][2]["takeoff_positions"], expected)
        self.assertTrue(mdb_undo.undo())
        self.assertTrue(mdb_undo.redo())
        self.assertEqual(mdb_write.position_calls[1][1], [("linear", old_position)])
        self.assertEqual(mdb_write.position_calls[2][1], expected)

    def test_group_flip_payload_matches_mdb_sql_and_mdb_undo_redo(self):
        area_old = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        area_new = [50.0, 0.0, 40.0, 0.0, 40.0, 10.0, 50.0, 10.0]
        count_old = [30.0, 5.0]
        count_new = [20.0, 5.0]
        position_changes = [
            ("area", area_old, area_new),
            ("count", count_old, count_new),
        ]
        rotation_changes = [("count", math.radians(32.0), math.radians(-32.0))]
        takeoff_states = {
            "area": (area_old, 0.0),
            "count": (count_old, math.radians(32.0)),
        }
        mdb_handler, mdb_write, mdb_undo = self._make_group_transform_handler(
            takeoff_states, False
        )
        sql_handler, sql_write, _sql_undo = self._make_group_transform_handler(
            takeoff_states, True
        )
        mdb_handler.on_group_rotation_flushed(
            position_changes,
            [],
            rotation_changes,
        )
        sql_handler.on_group_rotation_flushed(
            position_changes,
            [],
            rotation_changes,
        )
        expected_positions = [("area", area_new), ("count", count_new)]
        expected_rotations = [("count", math.radians(-32.0))]
        self.assertEqual(mdb_write.position_calls[0][1], expected_positions)
        self.assertEqual(mdb_write.rotation_calls[0][1], expected_rotations)
        sql_payload = sql_write.queued_geometry[0][2]
        self.assertEqual(sql_payload["takeoff_positions"], expected_positions)
        self.assertEqual(sql_payload["takeoff_rotations"], expected_rotations)
        self.assertEqual(mdb_undo.count, 1)
        self.assertTrue(mdb_undo.undo())
        self.assertTrue(mdb_undo.redo())
        self.assertEqual(
            mdb_write.position_calls[1][1],
            [("area", area_old), ("count", count_old)],
        )
        self.assertEqual(
            mdb_write.rotation_calls[1][1],
            [("count", math.radians(32.0))],
        )
        self.assertEqual(mdb_write.position_calls[2][1], expected_positions)
        self.assertEqual(mdb_write.rotation_calls[2][1], expected_rotations)

    def test_group_rotate_payload_matches_mdb_sql_and_mdb_undo_redo(self):
        area_old = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        area_new = [25.0, -15.0, 25.0, -5.0, 15.0, -5.0, 15.0, -15.0]
        count_old = [30.0, 5.0]
        count_new = [20.0, 15.0]
        attachment_old = [40.0, 5.0]
        attachment_new = [20.0, 25.0]
        takeoff_states = {
            "area": (area_old, 0.0),
            "count": (count_old, math.radians(32.0)),
            "attachment": (attachment_old, math.radians(25.0)),
        }
        position_changes = [
            ("area", area_old, area_new),
            ("count", count_old, count_new),
            ("attachment", attachment_old, attachment_new),
        ]
        rotation_changes = [
            ("count", math.radians(32.0), math.radians(122.0)),
            ("attachment", math.radians(25.0), math.radians(115.0)),
        ]
        expected_positions = [
            ("area", area_new),
            ("count", count_new),
            ("attachment", attachment_new),
        ]
        expected_rotations = [
            ("count", math.radians(122.0)),
            ("attachment", math.radians(115.0)),
        ]
        mdb_handler, mdb_write, mdb_undo = self._make_group_transform_handler(
            takeoff_states, False
        )
        sql_handler, sql_write, _sql_undo = self._make_group_transform_handler(
            takeoff_states, True
        )
        mdb_handler.on_group_rotation_flushed(position_changes, [], rotation_changes)
        sql_handler.on_group_rotation_flushed(position_changes, [], rotation_changes)
        self.assertEqual(mdb_write.position_calls[0][1], expected_positions)
        self.assertEqual(mdb_write.rotation_calls[0][1], expected_rotations)
        sql_payload = sql_write.queued_geometry[0][2]
        self.assertEqual(sql_payload["takeoff_positions"], expected_positions)
        self.assertEqual(sql_payload["takeoff_rotations"], expected_rotations)
        self.assertEqual(mdb_undo.count, 1)
        self.assertTrue(mdb_undo.undo())
        self.assertTrue(mdb_undo.redo())
        self.assertEqual(
            mdb_write.position_calls[1][1],
            [
                ("area", area_old),
                ("count", count_old),
                ("attachment", attachment_old),
            ],
        )
        self.assertEqual(
            mdb_write.rotation_calls[1][1],
            [
                ("count", math.radians(32.0)),
                ("attachment", math.radians(25.0)),
            ],
        )
        self.assertEqual(mdb_write.position_calls[2][1], expected_positions)
        self.assertEqual(mdb_write.rotation_calls[2][1], expected_rotations)


class PlanViewActionHandlerOnAnnotationCreatedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_annotation_created."""

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
                    expected_font = resolve_font_definition(
                        Config().default_dimension_annotation_font
                    )
                    self.assertEqual(
                        specs[0].properties["FontName"], expected_font.family
                    )
                    self.assertEqual(specs[0].properties["FontColor"], "#000080")
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

    def test_local_annotation_history_does_not_replace_new_page_selection(self):
        data = FakeProjectData()
        data.pages["p2"] = SimpleNamespace(
            uid="p2",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map[("ann-1", "line")] = "ann-1_line"
        ann_write = FakeAnnotationWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view,
            ann_write=ann_write,
            data=data,
            undo=undo,
        )
        handler.on_annotation_created("line", [1.0, 2.0, 5.0, 6.0], "p1")
        self.assertEqual(plan_view.selected, {"ann-1_line"})
        plan_view.current_page_uid = "p2"
        plan_view.set_selected_uids({"page-2-selection"})
        for _cycle in range(50):
            self.assertTrue(undo.can_undo())
            undo.undo()
            self.assertTrue(undo.can_redo())
            self.assertEqual(plan_view.selected, {"page-2-selection"})
            undo.redo()
            self.assertTrue(undo.can_undo())
            self.assertEqual(plan_view.selected, {"page-2-selection"})
        self.assertEqual(len(ann_write.delete_calls), 50)
        self.assertEqual(len(ann_write.insert_calls), 51)
        self.assertEqual(
            [(item.uid, item.annotation_type) for item in data.annotations],
            [("ann-1", "line")],
        )

    def test_local_annotation_history_rejects_same_uid_page_replacement_selection(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map[("ann-1", "line")] = "ann-1_line"
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view,
            data=data,
            undo=undo,
        )
        original_page = data.pages["p1"]
        handler.on_annotation_created("line", [1.0, 2.0, 5.0, 6.0], "p1")
        self.assertEqual(plan_view.selected, {"ann-1_line"})
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        plan_view.set_selected_uids({"replacement-page-selection"})
        self.assertTrue(undo.undo())
        self.assertEqual(data.annotations, [])
        self.assertEqual(plan_view.selected, {"replacement-page-selection"})

    def test_sql_annotation_creation_uses_atomic_paste_queue(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(data.added_annotations, [])
        self.assertEqual(len(write.queued_pastes), 1)
        database_id, payload, options, _callback = write.queued_pastes[0]
        self.assertEqual(database_id, "bid.mdb")
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        self.assertEqual(payload.takeoff_specs, ())
        self.assertEqual(len(payload.annotation_specs), 1)
        spec = payload.annotation_specs[0]
        self.assertEqual(spec.annotation_type, "rect")
        self.assertEqual(spec.position, [1.0, 2.0, 5.0, 6.0])
        self.assertEqual(spec.page_uid, "p1")
        self.assertEqual(spec.layer_uid, "annotation-layer")
        self.assertEqual(len(payload.annotation_source_uids), 1)
        self.assertEqual(
            parse_annotation_resource_id(payload.annotation_source_uids[0])[0],
            "rect",
        )
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in options["dependency_resources"]
            },
            {("layer", "annotation-layer")},
        )

    def test_sql_annotation_completion_after_bid_switch_does_not_create_wrong_bid_undo(
        self,
    ):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        selected_bid = [BidRef("bid.mdb", "7")]
        ui_state = FakeUiState()
        ui_state.get_selected_bid_ref = lambda: selected_bid[0]
        undo = UndoRedoService()
        undo.set_active_bid(selected_bid[0])
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        source_uid = payload.annotation_source_uids[0]
        selected_bid[0] = BidRef("other.mdb", "9")
        undo.set_active_bid(selected_bid[0])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        ("annotations", ((source_uid, "annotation-1"),)),
                    ),
                ),
            )
        )
        self.assertFalse(undo.can_undo())

    def test_sql_annotation_completion_for_active_bid_selects_and_registers_undo(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("annotation-1", "rect"): "annotation-1_rect"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        source_uid = payload.annotation_source_uids[0]
        self.assertFalse(undo.can_undo())
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        ("annotations", ((source_uid, "annotation-1"),)),
                    ),
                ),
            )
        )
        self.assertTrue(undo.can_undo())
        self.assertEqual(plan_view.selected, {"annotation-1_rect"})

    def test_sql_annotation_completion_failure_registers_no_undo_or_selection(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("annotation-1", "rect"): "annotation-1_rect"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        write.queued_pastes[0][3](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertFalse(undo.can_undo())
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(data.added_annotations, [])

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

    def test_annotation_insert_redo_after_calibration_preserves_angle(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 1
        data.pages["p1"].scale_factor2 = 96
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
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0, 0.123456789], "p1")
        ann_write.next_uids = ["ann-2"]
        undo.undo()
        data.pages["p1"].scale_factor2 = 48
        undo.redo()
        self.assertEqual(
            ann_write.insert_calls[-1][2][0].position, [0.5, 1.0, 2.5, 3.0, 0.123456789]
        )
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
                data = FakeProjectData()
                undo = FakeUndoService()
                event_bus = FakeEventBus()
                write = FakeWriteService()
                write.sql_collaboration_mutations = True
                handler = PlanViewActionHandler(
                    plan_view=FakePlanView(),
                    ui_state_manager=FakeUiState(),
                    project_data_svc=data,
                    project_write_svc=write,
                    annotation_write_svc=ann_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=undo,
                    event_bus=event_bus,
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess(set()),
                )
                handler.on_annotation_created(
                    annotation_type, [1.0, 2.0, 13.0, 2.0], "p1"
                )
                self.assertEqual(ann_write.insert_calls, [])
                self.assertEqual(write.queued_pastes, [])
                self.assertEqual(data.added_annotations, [])
                self.assertEqual(undo.count, 0)
                self.assertEqual(event_bus.events, [])


class PlanViewActionHandlerSaveCurrentPageOverlayRectTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.save_current_page_overlay_rect."""

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
        self.assertEqual(deferred.overlay_rect_callbacks[0]["bid_uid"], "7")
        self.assertEqual(handler._plan_view.projected_overlay_rects, [])

    def test_overlay_rect_rejected_deferred_write_does_not_update_model(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence(accepts_writes=False)
        handler = self._overlay_handler(data, deferred)
        original_rect = data.get_page("p1").overlay_rect
        accepted = handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25))
        self.assertFalse(accepted)
        self.assertEqual(data.get_page("p1").overlay_rect, original_rect)

    def test_overlay_rect_terminal_failure_restores_current_plan_only(self):
        data = FakeProjectData()
        data.get_page("p1").overlay_rect = (0.0, 0.0, 10.0, 10.0)
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred)
        self.assertTrue(handler.save_current_page_overlay_rect((1, 2, 3, 4)))
        deferred.overlay_rect_callbacks[0]["restore_authoritative"]()
        self.assertEqual(
            data.get_page("p1").overlay_rect,
            (0.0, 0.0, 10.0, 10.0),
        )
        self.assertEqual(
            handler._plan_view.projected_overlay_rects,
            [("p1", (0.0, 0.0, 10.0, 10.0))],
        )
        handler._ui_state.active_page_uid = "p2"
        handler._plan_view.current_page_uid = "p2"
        deferred.overlay_rect_callbacks[0]["project_value"]()
        self.assertEqual(
            data.get_page("p1").overlay_rect,
            (1.0, 2.0, 3.0, 4.0),
        )
        self.assertEqual(
            handler._plan_view.projected_overlay_rects,
            [("p1", (0.0, 0.0, 10.0, 10.0))],
        )

    def test_overlay_rect_completion_rejects_same_uid_page_replacement(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred)
        self.assertTrue(handler.save_current_page_overlay_rect((1, 2, 3, 4)))
        replacement = SimpleNamespace(
            uid="p1",
            overlay_rect=(9.0, 9.0, 9.0, 9.0),
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        data.pages["p1"] = replacement
        callbacks = deferred.overlay_rect_callbacks[0]
        callbacks["restore_authoritative"]()
        callbacks["project_value"]()
        self.assertEqual(replacement.overlay_rect, (9.0, 9.0, 9.0, 9.0))
        self.assertEqual(handler._plan_view.projected_overlay_rects, [])

    def test_overlay_rect_failure_restores_inactive_originating_page_model(self):
        data = FakeProjectData()
        data.get_page("p1").overlay_rect = (0.0, 0.0, 10.0, 10.0)
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred)
        self.assertTrue(handler.save_current_page_overlay_rect((1, 2, 3, 4)))
        handler._ui_state.active_page_uid = "p2"
        handler._plan_view.current_page_uid = "p2"
        deferred.overlay_rect_callbacks[0]["restore_authoritative"]()
        self.assertEqual(
            data.get_page("p1").overlay_rect,
            (0.0, 0.0, 10.0, 10.0),
        )
        self.assertEqual(handler._plan_view.projected_overlay_rects, [])

    def test_overlay_rect_permission_denial_returns_rejected_without_scheduling(self):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence()
        handler = self._overlay_handler(data, deferred, allowed=False)
        original_rect = data.get_page("p1").overlay_rect
        self.assertFalse(handler.save_current_page_overlay_rect((1, 2.5, 3, 4.25)))
        self.assertEqual(deferred.overlay_rect_calls, [])
        self.assertEqual(data.get_page("p1").overlay_rect, original_rect)


class PlanViewActionHandlerOnElementsDeletedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_elements_deleted."""

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
        plan_view = handler._plan_view
        handler.on_elements_deleted(["t1"])
        handler.on_positions_flushed([("t1", [1.0, 2.0], [3.0, 4.0])], [])
        handler.on_takeoff_created("42", [1.0, 2.0], "p1")
        self.assertEqual(write.delete_calls, [])
        self.assertEqual(write.local_deletes, [])
        self.assertEqual(write.position_calls, [])
        self.assertEqual(write.calls, [])
        self.assertIn("t1", data.takeoffs)
        self.assertEqual(
            plan_view.restored_positions,
            [([("t1", [1.0, 2.0], [3.0, 4.0])], [])],
        )

    def test_sql_annotation_delete_failure_reselects_rekeyed_identity(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Old"},
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("shared", "text"): "shared"}
        plan_view.annotations = {"shared": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_elements_deleted(["shared"])
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map = {("shared", "text"): "shared_text"}
        plan_view.annotations = {"shared_text": annotation}
        write.queued_deletes[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"shared_text"})

    def test_sql_delete_failure_rejects_same_uid_page_replacement(self):
        data = FakeProjectData()
        original_page = data.pages["p1"]
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_elements_deleted(["t1"])
        plan_view.selected = {"replacement-selection"}
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        write.queued_deletes[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected, {"replacement-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_delete_failure_does_not_override_newer_selection(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_elements_deleted(["t1"])
        self.assertEqual(plan_view.selected, set())
        plan_view.set_selected_uids({"user-choice"})
        write.queued_deletes[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_takeoff_delete_history_does_not_replace_selection_on_another_page(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.next_uids = ["t2"]
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_elements_deleted(["t1"])
        plan_view.current_page_uid = "p2"
        plan_view.set_selected_uids({"page-2-selection"})
        undo.undo()
        self.assertEqual(set(data.takeoffs), {"t2"})
        self.assertEqual(plan_view.selected, {"page-2-selection"})
        undo.redo()
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.selected, {"page-2-selection"})
        self.assertEqual(plan_view.clears, 0)

    def test_annotation_delete_history_does_not_replace_selection_on_another_page(
        self,
    ):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_RECT,
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1": annotation}
        plan_view.annotation_key_map = {("ann-2", ANNOTATION_TYPE_RECT): "ann-2"}
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = ["ann-2"]
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data, undo=undo
        )
        handler.on_elements_deleted(["a1"])
        self.assertEqual(data.annotations, [])
        plan_view.current_page_uid = "p2"
        plan_view.set_selected_uids({"page-2-selection"})
        undo.undo()
        self.assertEqual(
            [(item.uid, item.annotation_type) for item in data.annotations],
            [("ann-2", ANNOTATION_TYPE_RECT)],
        )
        self.assertEqual(plan_view.selected, {"page-2-selection"})
        undo.redo()
        self.assertEqual(data.annotations, [])
        self.assertEqual(plan_view.selected, {"page-2-selection"})
        self.assertEqual(plan_view.clears, 0)

    def test_simple_takeoff_delete_uses_targeted_path(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        undo = FakeUndoService()
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
        handler.on_elements_deleted(["t1"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], False)])
        self.assertEqual(write.reloads, [])
        self.assertNotIn("t1", data.takeoffs)
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
        self.assertEqual(undo.count, 1)

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

    def test_sql_delete_failure_does_not_restore_selection_after_bid_switch(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        selected_bid = [BidRef("bid.mdb", "7")]
        ui_state = FakeUiState()
        ui_state.get_selected_bid_ref = lambda: selected_bid[0]
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        handler.on_elements_deleted(["t1"])
        callback = write.queued_deletes[0][-1]
        selected_bid[0] = BidRef("other.mdb", "9")
        plan_view.set_pending_mutation_uids(set())
        plan_view.selected = {"other-selection"}
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected, {"other-selection"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

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
        restored_spec = write.calls[0][2][0]
        self.assertEqual(
            restored_spec.raw_extras,
            {
                "Count": 0.0,
                "Quantity": 0.0,
                "GUID": "{OLD}",
                "NameFontName": "Arial",
                "NameFontSize": 12,
            },
        )
        self.assertEqual(restored_spec.position, [4.0, 5.0])
        self.assertEqual(data.takeoffs["t2"].position, [4.0, 5.0])
        self.assertEqual(data.takeoffs["t2"].name_font_name, "Arial")
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertEqual(write.reloads, [])
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
        payload = event_bus.events[0][1]
        self.assertEqual(payload["page_uid"], "p1")
        self.assertEqual(set(payload["takeoff_uids"]), {"parent", "hole"})
        self.assertEqual(payload["condition_uids"], ["c1"])

    def test_area_backout_delete_restore_projects_authoritative_parent_each_cycle(self):
        data = FakeProjectData()
        originals = []
        for parent_uid, offset in (("area-a", 0.0), ("area-b", 20.0)):
            originals.append(
                Takeoff(
                    uid=parent_uid,
                    condition_uid="c1",
                    page_uid="p1",
                    position=[offset, 0.0, offset + 10.0, 0.0, offset + 10.0, 10.0],
                )
            )
            for index in (1, 2):
                x = offset + index
                originals.append(
                    Takeoff(
                        uid=f"{parent_uid}-hole-{index}",
                        condition_uid="c1",
                        page_uid="p1",
                        position=[x, 2.0, x + 0.5, 2.0, x + 0.5, 3.0],
                        parent_uid=parent_uid,
                        is_negative=True,
                    )
                )
        data.takeoffs = {item.uid: item for item in originals}
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
        handler.on_elements_deleted(["area-b", "area-a"])
        self.assertEqual(data.takeoffs, {})
        for cycle in range(3):
            parents = [f"b-{cycle}", f"a-{cycle}"]
            holes = [f"hole-{cycle}-{index}" for index in range(4)]
            write.uid_batches = [parents, holes]
            undo.undo()
            self.assertEqual(set(data.takeoffs), set(parents + holes))
            # Persistence already receives remapped parents. Model projection
            # must agree with those rows, not the deleted snapshot's parent IDs.
            persisted_specs = write.calls[-2][2] + write.calls[-1][2]
            self.assertEqual(len(persisted_specs), len(parents + holes))
            for uid, spec in zip(parents + holes, persisted_specs):
                restored = data.takeoffs[uid]
                self.assertEqual(restored.parent_uid, spec.parent_uid)
                self.assertEqual(restored.position, spec.position)
                self.assertEqual(restored.is_negative, spec.is_negative)
                self.assertEqual(restored.rotation, spec.rotation)
                self.assertEqual(restored.curve, spec.curve)
                original = next(
                    item for item in originals if item.position == spec.position
                )
                expected_parent = (
                    "0"
                    if original.parent_uid == "0"
                    else (parents[0] if original.parent_uid == "area-b" else parents[1])
                )
                self.assertEqual(restored.parent_uid, expected_parent)
                if restored.is_negative:
                    self.assertIn(restored.parent_uid, data.takeoffs)
            self.assertEqual(write.reloads, [])
            undo.redo()
            self.assertEqual(data.takeoffs, {})
        # A fresh delete must discover children through their restored parent
        # identities, rather than leaving them behind as orphaned Backouts.
        write.uid_batches = [["b-next", "a-next"], ["h1", "h2", "h3", "h4"]]
        undo.undo()
        handler.on_elements_deleted(["a-next", "b-next"])
        self.assertEqual(data.takeoffs, {})
        write.uid_batches = [["a-final", "b-final"], ["h5", "h6", "h7", "h8"]]
        undo.undo()
        self.assertEqual(len(data.takeoffs), len(originals))
        for restored in data.takeoffs.values():
            if restored.is_negative:
                self.assertEqual(
                    restored.parent_uid,
                    "a-final" if restored.position[0] < 20.0 else "b-final",
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
        self.assertEqual(len(write.local_deletes), 1)
        handler._undo_svc.undo()
        restore_payload = write.local_pastes[0][1]
        self.assertEqual(
            restore_payload.takeoff_specs[0].raw_extras,
            {"UnsupportedColumn": "value"},
        )

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
        self.assertIn("t1", data.takeoffs)
        self.assertEqual(handler._undo_svc.count, 0)
        self.assertEqual(handler._event_bus.events, [])

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
        self.assertEqual(data.takeoffs["t2"].position, [0.0, 0.0])
        self.assertEqual(plan_view.selected, {"t2"})
        undo.redo()
        self.assertEqual([call[2] for call in write.delete_calls], [False, False])
        self.assertEqual([call[3] for call in write.calls], [False])
        self.assertEqual([call[1] for call in write.delete_calls], [["t1"], ["t2"]])
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
        handler._write_svc.annotation_write_service = ann_write
        handler.on_elements_deleted(["rect-item"])
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        undo.undo()
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [0.0, 0.0, 64.0, 64.0],
        )

    def test_rotated_annotation_delete_undo_preserves_angle(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        annotation = BidAnnotation(
            uid="a1",
            annotation_type=ANNOTATION_TYPE_RECT,
            page_uid="p1",
            position=[0.0, 0.0, 96.0, 96.0, 0.123456789],
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
        handler._write_svc.annotation_write_service = ann_write
        handler.on_elements_deleted(["rect-item"])
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        undo.undo()
        self.assertEqual(
            ann_write.insert_calls[0][2][0].position,
            [0.0, 0.0, 64.0, 64.0, 0.123456789],
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
        self.assertIn("t2", data.takeoffs)
        self.assertNotIn("t1", data.takeoffs)
        undo.redo()
        self.assertEqual(data.annotations, [])
        self.assertNotIn("t2", data.takeoffs)
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
        self.assertEqual(data.extras, {})
        undo.undo()
        self.assertEqual(
            write.local_pastes[0][1].takeoff_specs[0].raw_extras,
            {"CustomColumn": "preserve-me"},
        )
        self.assertEqual(
            write.calls[0][2][0].raw_extras,
            {"CustomColumn": "preserve-me"},
        )

    def test_failed_mixed_delete_reselects_requested_items_without_projection(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
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
        write = FakeWriteService()
        write.execute_plan_items_delete_local = lambda *args, **_options: (
            MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_elements_deleted(["t1", "rect-item"])
        self.assertEqual(plan_view.selected, {"t1", "rect-item"})
        self.assertIn("t1", data.takeoffs)
        self.assertEqual([item.uid for item in data.annotations], ["a1"])
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._event_bus.events, [])

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
        handler._write_svc.annotation_write_service = ann_write
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

    def test_annotation_delete_history_accepts_table_scoped_duplicate_uids(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
        )
        rect = BidAnnotation(
            uid="shared",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        oval = BidAnnotation(
            uid="shared",
            annotation_type="oval",
            page_uid="p1",
            position=[5.0, 6.0, 7.0, 8.0],
        )
        data.annotations = [rect, oval]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"rect-item": rect, "oval-item": oval}
        plan_view.annotation_key_map = {
            ("ann-rect", "rect"): "rect-item",
            ("ann-oval", "oval"): "oval-item",
        }
        write = FakeWriteService()
        write.next_uids = ["t2"]
        write.next_annotation_uids = ["ann-rect", "ann-oval"]
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
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        handler.on_elements_deleted(["t1", "rect-item", "oval-item"])
        self.assertEqual(undo.count, 1)
        self.assertTrue(undo.undo())
        self.assertEqual(
            {
                (annotation.uid, annotation.annotation_type)
                for annotation in data.annotations
            },
            {("ann-rect", "rect"), ("ann-oval", "oval")},
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
        handler._write_svc.annotation_write_service = ann_write
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


class PlanViewActionHandlerOnTextAnnotationCreatedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_text_annotation_created."""

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

    def test_sql_text_annotation_completion_reactivates_tool_on_originating_page(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("annotation-1", "text"): "annotation-1_text"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0],
            "p1",
            {"Text": "Delayed", "FontColor": 0x336699},
        )
        database_id, payload, _options, callback = write.queued_pastes[0]
        self.assertEqual(database_id, "bid.mdb")
        spec = payload.annotation_specs[0]
        self.assertEqual(spec.annotation_type, "text")
        self.assertEqual(spec.properties, {"Text": "Delayed", "FontColor": 0x336699})
        self.assertEqual(spec.color, "#996633")
        self.assertEqual(plan_view.activated_annotations, [])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        (
                            "annotations",
                            ((payload.annotation_source_uids[0], "annotation-1"),),
                        ),
                    ),
                ),
            )
        )
        self.assertEqual(plan_view.activated_annotations, ["text"])
        self.assertEqual(plan_view.selected, {"annotation-1_text"})
        self.assertEqual(undo.count, 1)

    def test_sql_text_annotation_completion_does_not_reactivate_tool_on_new_page(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0],
            "p1",
            {"Text": "Delayed"},
        )
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        source_uid = payload.annotation_source_uids[0]
        plan_view.current_page_uid = "p2"
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        ("annotations", ((source_uid, "annotation-1"),)),
                    ),
                ),
            )
        )
        self.assertEqual(plan_view.activated_annotations, [])

    def test_sql_text_annotation_completion_rejects_same_uid_page_replacement(self):
        data = FakeProjectData()
        original_page = data.pages["p1"]
        plan_view = FakePlanView(data)
        plan_view.selected = {"replacement-selection"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            data=data,
            undo=undo,
        )
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0],
            "p1",
            {"Text": "Delayed"},
        )
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        source_uid = payload.annotation_source_uids[0]
        plan_view.annotation_key_map[("annotation-1", "text")] = "annotation-1"
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        ("annotations", ((source_uid, "annotation-1"),)),
                    ),
                ),
            )
        )
        self.assertEqual(plan_view.selected, {"replacement-selection"})
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(undo.count, 0)

    def test_sql_text_annotation_completion_does_not_reactivate_after_access_loss(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0],
            "p1",
            {"Text": "Delayed"},
        )
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        source_uid = payload.annotation_source_uids[0]
        handler._ui_access_manager.allowed_features.discard(Feature.PLACE_ANNOTATIONS)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("annotation-1",),
                    created_uid_maps=(
                        ("annotations", ((source_uid, "annotation-1"),)),
                    ),
                ),
            )
        )
        self.assertEqual(plan_view.activated_annotations, [])

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
        handler.on_text_annotation_created(
            [7.0, 8.0, 12.0, 12.0], "p1", {"FontColor": 0x336699}
        )
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])

    def test_denied_place_annotations_access_blocks_text_commit_write(self):
        ann_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        plan_view = FakePlanView()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
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
        self.assertEqual(write.queued_pastes, [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan_view.activated_annotations, [])


class PlanViewActionHandlerOnAnnotationStylesFlushedTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.on_annotation_styles_flushed."""

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
        record_style = ann_write.save_annotation_styles

        def reject_missing(*args, **kwargs):
            record_style(*args, **kwargs)
            return False

        ann_write.save_annotation_styles = reject_missing
        event_bus = FakeEventBus()
        plan_view = FakePlanView(data)
        undo = FakeUndoService()
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
            ui_access_manager=FakeAccess(set(Feature)),
        )
        changes = [("missing", "rect", {"Color": "#000000"}, {"Color": "#ffffff"})]
        handler.on_annotation_styles_flushed(changes)
        self.assertEqual(plan_view.restored_annotation_styles, [changes])
        self.assertEqual(undo.count, 0)
        self.assertEqual(
            ann_write.style_calls,
            [("bid.mdb", [("missing", "rect", {"Color": "#ffffff"})], False)],
        )
        self.assertEqual(event_bus.events, [])
        self.assertEqual(data.annotations[0].color, "#FF0000")

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
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        event_bus = FakeEventBus()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set()),
        )
        handler.on_annotation_styles_flushed(
            [("a1", "rect", {"Color": "#ff0000"}, {"Color": "#336699"})]
        )
        self.assertEqual(annotation_write.style_calls, [])
        self.assertEqual(write.queued_properties, [])
        self.assertEqual(event_bus.events, [])

    def test_access_loss_restores_uncommitted_annotation_style_preview(self):
        plan_view = FakePlanView()
        annotation_write = FakeAnnotationWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
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
        changes = [("10", "line", {"Width": 1.0}, {"Width": 4.0})]
        handler.on_annotation_styles_flushed(changes)
        self.assertEqual(plan_view.restored_annotation_styles, [changes])
        self.assertEqual(annotation_write.style_calls, [])

    def _sql_style_handler(self):
        data = FakeProjectData()
        annotation = BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.annotations = {"a1_rect": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        annotation_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            ann_write=annotation_write,
            data=data,
            undo=undo,
        )
        return handler, plan_view, write, annotation_write, undo

    def test_sql_annotation_style_change_queues_then_registers_history(self):
        handler, plan_view, write, annotation_write, undo = self._sql_style_handler()
        changes = [
            (
                "a1",
                "rect",
                {"Color": "#ff0000", "Width": 4.0},
                {"Color": "#336699", "Width": 7.0},
            )
        ]
        handler.on_annotation_styles_flushed(changes)
        self.assertEqual(annotation_write.style_calls, [])
        self.assertEqual(len(write.queued_properties), 1)
        _db, bid_uid, kind, updates, options, callback = write.queued_properties[0]
        self.assertEqual((bid_uid, kind), ("7", "annotation_style"))
        self.assertEqual(updates, [("a1", "rect", {"Color": "#336699", "Width": 7.0})])
        self.assertEqual(options["page_uids"], ("p1",))
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_rect"})
        self.assertEqual(undo.count, 0)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"a1_rect"})
        self.assertEqual(plan_view.restored_annotation_styles, [])
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(
            write.queued_properties[1][3],
            [("a1", "rect", {"Color": "#ff0000", "Width": 4.0})],
        )

    def test_sql_annotation_style_failure_restores_preview(self):
        handler, plan_view, write, _annotation_write, undo = self._sql_style_handler()
        changes = [("a1", "rect", {"Width": 4.0}, {"Width": 7.0})]
        handler.on_annotation_styles_flushed(changes)
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_annotation_styles, [changes])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"a1_rect"})
        self.assertEqual(undo.count, 0)


class PlanViewActionHandlerOnNamedViewCreatedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_named_view_created."""

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

    @patch("ost_visualizer.presentation.handlers.plan_view_action_handler.show_warning")
    def test_named_view_write_failure_does_not_refresh_or_reactivate_tool(
        self, warning
    ):
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
        warning.assert_called_once()

    def test_duplicate_named_view_name_is_rejected_case_insensitively(self):
        data = FakeProjectData()
        data.annotations = [_named_view_annotation("nv1", "Lobby")]
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView(data)
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data
        )
        position = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
        with patch.object(handler_module, "show_duplicate_named_view_name") as warn:
            handler.on_named_view_created(position, "p1", {"Text": "  lobby "})
            warn.assert_called_once_with(plan_view)
            self.assertEqual(ann_write.insert_calls, [])
            self.assertEqual(plan_view.activated_annotations, [])
            handler.on_named_view_created(position, "p1", {"Text": "Office"})
            warn.assert_called_once_with(plan_view)
            self.assertTrue(handler._validate_named_view_name("Lobby", "nv1"))
            warn.assert_called_once_with(plan_view)
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(ann_write.insert_calls[0][2][0].properties, {"Text": "Office"})

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


class PlanViewActionHandlerOnHotlinkPlacementRequestedTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.on_hotlink_placement_requested."""

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

            def deleteLater(self):
                pass

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
        self.assertEqual(specs[0].page_uid, "p1")
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

    @patch("ost_visualizer.presentation.handlers.plan_view_action_handler.show_warning")
    def test_hotlink_write_failure_does_not_reactivate_tool(self, _warning):
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

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(plan_view.selected, set())
        _warning.assert_called_once()

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

            def deleteLater(self):
                pass

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

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", FakeDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(plan_view.cancel_place_mode_calls, 1)
        self.assertEqual(plan_view.placement_flow, ["cancel_place_mode", "dialog_exec"])

    def test_repeated_hotlink_dialog_cancellation_releases_picker_widgets(self):
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
        owner = QtWidgets.QWidget()
        dialog_type = handler_module.SelectNamedViewDialog

        def make_rejected_dialog(named_views, parent=None):
            del parent
            dialog = dialog_type(named_views, parent=owner)
            dialog.exec = lambda: QtWidgets.QDialog.DialogCode.Rejected
            return dialog

        try:
            with patch.object(
                handler_module, "SelectNamedViewDialog", make_rejected_dialog
            ):
                for _ in range(100):
                    handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(owner.findChildren(dialog_type), [])
        finally:
            owner.deleteLater()

    def test_hotlink_request_is_ignored_without_placement_access_or_position(self):
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView()
        access = FakeAccess(set())
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, allowed_features=set()
        )

        class ForbiddenDialog:
            def __init__(self, named_views, parent=None):
                raise AssertionError("the picker must not open")

        with patch.object(handler_module, "SelectNamedViewDialog", ForbiddenDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
            handler._ui_access_manager = access
            access.allowed_features.add(Feature.PLACE_ANNOTATIONS)
            handler.on_hotlink_placement_requested([9.0], "p1")
            handler.on_hotlink_placement_requested([9.0, 11.0], "")
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)
        self.assertEqual(ann_write.insert_calls, [])

    def test_hotlink_dialog_return_does_not_write_after_access_loss(self):
        data = FakeProjectData()
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView(data)
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data
        )

        class RevokingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                handler._ui_access_manager.allowed_features.discard(
                    Feature.PLACE_ANNOTATIONS
                )
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                raise AssertionError("stale hotlink dialog result must not be read")

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", RevokingDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])

    def test_sql_hotlink_request_queues_paste_with_named_view_dependency(self):
        data = FakeProjectData()
        data.annotations = [_named_view_annotation("nv1", "Lobby")]
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data
        )

        class AcceptingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid="nv1")

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", AcceptingDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0, 99.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(len(write.queued_pastes), 1)
        _database_id, payload, options, callback = write.queued_pastes[0]
        spec = payload.annotation_specs[0]
        self.assertEqual(spec.annotation_type, "hotlink")
        self.assertEqual(spec.position, [9.0, 11.0])
        self.assertEqual(spec.properties, {"BidPageViewUID": "nv1"})
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in options["dependency_resources"]
            },
            {("annotation", "namedview/nv1"), ("layer", "annotation-layer")},
        )
        self.assertEqual(plan_view.activated_annotations, [])
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("hl-new",),
                    created_uid_maps=(
                        (
                            "annotations",
                            ((payload.annotation_source_uids[0], "hl-new"),),
                        ),
                    ),
                ),
            )
        )
        self.assertEqual(plan_view.activated_annotations, ["hotlink"])

    def test_hotlink_dialog_return_does_not_write_after_page_retarget(self):
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView()
        ui_state = FakeUiState()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=FakeProjectData(),
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class RetargetingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                ui_state.active_page_uid = "p2"
                plan_view.current_page_uid = "p2"
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                raise AssertionError("stale hotlink dialog result must not be read")

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", RetargetingDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])

    def test_hotlink_dialog_return_does_not_write_after_same_uid_page_replacement(self):
        ann_write = FakeAnnotationWriteService()
        plan_view = FakePlanView()
        ui_state = FakeUiState()
        data = FakeProjectData()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=ann_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.PLACE_ANNOTATIONS}),
        )

        class RetargetingDialog(handler_module.QtWidgets.QDialog):
            def __init__(self, _named_views, parent=None):
                super().__init__()

            def exec(self):
                data.pages["p1"] = SimpleNamespace(uid="p1")
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=True, named_view_uid="")

        with patch.object(handler_module, "SelectNamedViewDialog", RetargetingDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])


class PlanViewActionHandlerOnAnnotationTextPropertiesFlushedTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.on_annotation_text_properties_flushed."""

    def test_denied_annotation_text_access_blocks_text_property_write(self):
        annotation_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        plan_view = FakePlanView()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.EDIT_PLAN_ITEMS}),
        )
        changes = [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        handler.on_annotation_text_properties_flushed(changes)
        handler.on_annotation_text_properties_flushed([])
        self.assertEqual(annotation_write.text_property_calls, [])
        self.assertEqual(write.queued_properties, [])
        self.assertEqual(plan_view.restored_text_properties, [changes])

    def test_sql_annotation_failure_reselects_rekeyed_typed_annotation(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Old"},
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("shared", "text"): "shared"}
        plan_view.annotations = {"shared": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        changes = [
            (
                "shared",
                "text",
                {"Text": "Old"},
                {"Text": "New"},
            )
        ]
        handler.on_annotation_text_properties_flushed(changes)
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map = {("shared", "text"): "shared_text"}
        plan_view.annotations = {"shared_text": annotation}
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"shared_text"})

    def test_new_pending_mutation_preserves_rekeyed_annotation_pending_state(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="shared",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Old"},
        )
        data.annotations = [annotation]
        data.takeoffs["t2"] = Takeoff(
            uid="t2",
            condition_uid="c1",
            page_uid="p1",
            is_negative=False,
        )
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("shared", "text"): "shared"}
        plan_view.annotations = {"shared": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_annotation_text_properties_flushed(
            [("shared", "text", {"Text": "Old"}, {"Text": "New"})]
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        plan_view.annotation_key_map = {("shared", "text"): "shared_text"}
        plan_view.annotations = {"shared_text": annotation}
        plan_view.pending_mutation_uids = {"shared_text"}
        handler.on_set_negative(["t2"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"shared_text", "t2"})

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
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["a1"],
                        "annotation_types": ["text"],
                    },
                )
            ],
        )
        undo.undo()
        self.assertEqual(
            data.annotations[0].properties, {"Text": "Old", "FontBold": False}
        )
        undo.redo()
        self.assertEqual(
            data.annotations[0].properties, {"Text": "New", "FontBold": True}
        )
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

    def test_sql_annotation_text_property_change_queues_then_registers_history(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Old"},
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("a1", "text"): "a1_text"}
        plan_view.annotations = {"a1_text": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Old"}, {"Text": "New"})]
        )
        _db, bid_uid, kind, updates, options, callback = write.queued_properties[0]
        self.assertEqual((bid_uid, kind), ("7", "annotation_text"))
        self.assertEqual(updates, [("a1", "text", {"Text": "New"})])
        self.assertEqual(options["page_uids"], ("p1",))
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_text"})
        self.assertEqual(undo.count, 0)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, {"a1_text"})
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(
            write.queued_properties[1][3], [("a1", "text", {"Text": "Old"})]
        )

    def test_failed_annotation_text_property_save_restores_plan_view(self):
        plan_view = FakePlanView()
        ann_write = FakeAnnotationWriteService()
        ann_write.save_annotation_text_properties = lambda *args, **_call_options: False
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, undo=undo
        )
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
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._event_bus.events, [])

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


class PlanViewActionHandlerOnConditionTextPropertiesFlushedTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.on_condition_text_properties_flushed."""

    def test_condition_label_text_properties_write_takeoff_style_fields(self):
        old_properties = {
            "name_font_name": "Arial",
            "name_font_color": 0x000000,
            "name_font_size": 9,
            "name_font_bold": False,
            "name_font_italic": False,
            "name_font_underline": False,
        }
        new_properties = {
            "name_font_name": "Segoe UI",
            "name_font_color": 0x332211,
            "name_font_size": 24,
            "name_font_bold": True,
            "name_font_italic": False,
            "name_font_underline": True,
        }
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            name_font_name="Arial",
            name_font_color=0x000000,
            name_font_size=9,
        )
        write = FakeWriteService()
        event_bus = FakeEventBus()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess({Feature.EDIT_CONDITION}),
        )
        handler.on_condition_text_properties_flushed(
            [("t1", "display_name", dict(old_properties), dict(new_properties))]
        )
        self.assertEqual(
            write.text_property_calls,
            [("bid.mdb", [("t1", new_properties)], False)],
        )
        self.assertEqual(write.reloads, [])
        self.assertEqual(data.takeoffs["t1"].name_font_size, 24)
        self.assertEqual(data.takeoffs["t1"].name_font_name, "Segoe UI")
        self.assertTrue(data.takeoffs["t1"].name_font_bold)
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
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(data.takeoffs["t1"].name_font_size, 9)
        self.assertEqual(data.takeoffs["t1"].name_font_name, "Arial")
        self.assertFalse(data.takeoffs["t1"].name_font_bold)
        undo.redo()
        self.assertEqual(data.takeoffs["t1"].name_font_size, 24)
        self.assertEqual(
            [call[1] for call in write.text_property_calls],
            [
                [("t1", new_properties)],
                [("t1", old_properties)],
                [("t1", new_properties)],
            ],
        )

    def test_condition_label_text_properties_denied_without_condition_access(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        plan_view = FakePlanView()
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
            ui_access_manager=FakeAccess(set(Feature) - {Feature.EDIT_CONDITION}),
        )
        changes = [
            ("t1", "display_name", {"name_font_size": 9}, {"name_font_size": 24})
        ]
        handler.on_condition_text_properties_flushed(changes)
        handler.on_condition_text_properties_flushed([])
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self.assertEqual(write.queued_properties, [])
        self.assertEqual(write.text_property_calls, [])
        self.assertEqual(undo.count, 0)
        self.assertIsNone(data.takeoffs["t1"].name_font_size)

    def test_sql_condition_label_text_properties_queue_then_register_history(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        changes = [("t1", "name", {"name_font_bold": False}, {"name_font_bold": True})]
        handler.on_condition_text_properties_flushed(changes)
        self.assertEqual(write.text_property_calls, [])
        self.assertEqual(len(write.queued_properties), 1)
        _db, bid_uid, kind, updates, options, callback = write.queued_properties[0]
        self.assertEqual((bid_uid, kind), ("7", "takeoff_text"))
        self.assertEqual(updates, [("t1", {"name_font_bold": True})])
        self.assertEqual(options["page_uids"], ("p1",))
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(undo.count, 0)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.restored_condition_text_properties, [])
        self.assertEqual(undo.count, 1)

    def test_sql_condition_label_text_properties_failure_restores_editor_state(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        changes = [("t1", "name", {"name_font_bold": False}, {"name_font_bold": True})]
        handler.on_condition_text_properties_flushed(changes)
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 0)

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

    def test_sql_property_failure_does_not_restore_editor_state_after_bid_switch(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        selected_bid = [BidRef("bid.mdb", "7")]
        ui_state = FakeUiState()
        ui_state.get_selected_bid_ref = lambda: selected_bid[0]
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        changes = [("t1", "name", {"FontBold": False}, {"FontBold": True})]
        handler.on_condition_text_properties_flushed(changes)
        selected_bid[0] = BidRef("other.mdb", "9")
        # Production load_page discards the previous Bid's pending identities.
        plan_view.set_pending_mutation_uids(set())
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_condition_text_properties, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_property_failure_does_not_override_newer_selection(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        changes = [("t1", "name", {"FontBold": False}, {"FontBold": True})]
        handler.on_condition_text_properties_flushed(changes)
        plan_view.set_selected_uids({"user-choice"})
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_property_failure_rejects_same_uid_page_replacement(self):
        data = FakeProjectData()
        original_page = data.pages["p1"]
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        changes = [("t1", "name", {"FontBold": False}, {"FontBold": True})]
        handler.on_condition_text_properties_flushed(changes)
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_condition_text_properties, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())


class PlanViewActionHandlerOnTakeoffCreatedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_takeoff_created."""

    def test_new_takeoff_uses_fast_refresh_and_updates_model(self):
        plan_view = FakePlanView()
        data = FakeProjectData()
        write = FakeWriteService()
        undo = FakeUndoService()
        event_bus = FakeEventBus()
        ui_state = FakeUiState()
        ui_state.config_model = _FakeConfigModel(
            Config(
                default_area_label_font=FontDefinition(
                    "Arial", "Bold Italic", 24, 700, True, True
                ),
                default_style_label_font=FontDefinition(
                    "Arial", "Regular", 18, 400, False, False
                ),
                default_area_label_color="#112233",
                default_style_label_color="#445566",
            )
        )
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
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
        extras = write.calls[0][2][0].raw_extras
        self.assertEqual(extras["FontColor"], hex_color_to_int("#112233"))
        self.assertEqual(extras["NameFontColor"], hex_color_to_int("#445566"))
        self.assertEqual((extras["FontSize"], extras["FontItalic"]), (24, True))
        self.assertEqual((extras["NameFontSize"], extras["NameFontBold"]), (18, False))
        self.assertEqual(event_bus.events[0][0], AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_bus.events[0][1]["takeoff_uids"], ["100"])
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)

    def test_takeoff_history_on_another_page_preserves_current_selection(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
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
        self.assertEqual(plan_view.selected, {"100"})
        plan_view.current_page_uid = "p1"
        plan_view.set_selected_uids({"page-1-selection"})
        undo.undo()
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.selected, {"page-1-selection"})
        undo.redo()
        self.assertEqual(len(data.takeoffs), 1)
        restored = next(iter(data.takeoffs.values()))
        self.assertEqual((restored.page_uid, restored.condition_uid), ("9", "42"))
        self.assertEqual(plan_view.selected, {"page-1-selection"})

    def test_access_connection_exhaustion_is_presented_once_without_projection(self):
        plan_view = FakePlanView()
        plan_view.selected = {"existing"}
        data = FakeProjectData()
        write = FakeWriteService()
        write.insert_takeoffs_failure_reason = (
            "Microsoft Access cannot open another database connection."
        )
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
        with patch.object(handler_module, "show_warning") as warning:
            handler.on_takeoff_created("42", [1.0, 2.0], "9")
        warning.assert_called_once_with(
            plan_view,
            "Database Write",
            write.insert_takeoffs_failure_reason,
        )
        self.assertEqual(plan_view.selected, {"existing"})
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)
        write.insert_takeoffs_failure_reason = None
        handler.on_takeoff_created("42", [3.0, 4.0], "9")
        self.assertEqual(plan_view.selected, {"100"})
        self.assertEqual(len(data.added_takeoffs), 1)
        self.assertEqual(undo.count, 1)
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
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501",),
            )
        )
        self.assertEqual(set(data.takeoffs), {"501"})
        self.assertEqual(undo.count, 1)

    def test_sql_takeoff_placement_history_deletes_then_requeues_placement(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
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
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.queued_deletes[0][2], ["501"])
        self.assertEqual(write.queued_deletes[0][4]["page_uids"], ("9",))
        write.queued_deletes[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertFalse(undo.takeoff_targets[0].available)
        undo.redo()
        self.assertEqual(len(write.queued_takeoff_callbacks), 2)
        redo_specs = write.calls[-1][2]
        self.assertEqual(
            [(spec.condition_uid, spec.page_uid, spec.position) for spec in redo_specs],
            [("42", "9", [1.0, 2.0])],
        )
        write.queued_takeoff_callbacks[1][1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=write.queued_takeoff_callbacks[1][0],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("502",),
            )
        )
        self.assertEqual(undo.takeoff_targets[0].uid, "502")
        self.assertTrue(undo.takeoff_targets[0].available)

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

    def _multi_condition_pending_handler(self):
        data = FakeProjectData()
        data.conditions["c2"] = Condition(
            uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler._ui_state.place_condition_uids = ["c1", "c2"]
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        return handler, data, plan_view, write, undo

    def test_partial_pending_preview_delete_does_not_cancel_whole_placement(self):
        handler, data, _view, write, _undo = self._multi_condition_pending_handler()
        operation_id, _callback = write.queued_takeoff_callbacks[0]
        first_pending, second_pending = list(data.takeoffs)
        handler.on_elements_deleted([first_pending])
        self.assertEqual(list(data.takeoffs), [second_pending])
        self.assertEqual(write.cancelled_mutations, [])
        handler.on_elements_deleted([second_pending])
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(write.cancelled_mutations, [("bid.mdb", operation_id)])

    def test_partially_deleted_pending_placement_commits_only_retained_takeoff(self):
        handler, data, plan_view, write, undo = self._multi_condition_pending_handler()
        operation_id, callback = write.queued_takeoff_callbacks[0]
        first_pending, _second_pending = list(data.takeoffs)
        handler.on_elements_deleted([first_pending])
        data.add_takeoffs(
            [
                Takeoff(
                    uid=uid,
                    condition_uid=condition_uid,
                    page_uid="9",
                    position=[1.0, 2.0],
                )
                for uid, condition_uid in (("501", "c1"), ("502", "c2"))
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501", "502"),
            )
        )
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.queued_deletes[0][2], ["501"])
        self.assertEqual(plan_view.selected, {"502"})
        self.assertEqual(undo.count, 1)
        self.assertEqual([target.uid for target in undo.takeoff_targets], ["502"])

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

    def test_sql_placement_completion_rejects_same_uid_page_replacement(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        plan_view.selected = {"replacement-selection"}
        data = FakeProjectData()
        original_page = data.pages["9"]
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
        data.pages["9"] = SimpleNamespace(
            uid="9",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["9"], original_page)
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
        self.assertEqual(plan_view.selected, {"replacement-selection"})
        self.assertEqual(undo.count, 0)

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
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=FakePlanView(),
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FailingEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        with self.assertRaisesRegex(RuntimeError, "plan projection failed"):
            handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(write.queued_takeoff_callbacks, [])
        self.assertEqual(handler._pending_takeoff_placements, {})
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(undo.count, 0)

    def test_committed_placement_before_authoritative_projection_raises(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        with self.assertRaisesRegex(RuntimeError, "before authoritative"):
            callback(
                QueuedMutationResult(
                    database_id="bid.mdb",
                    runtime_generation=3,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    created_resource_ids=("501",),
                )
            )
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(plan_view.selected, set())

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
        with self.assertLogs(
            "ost_visualizer.presentation.handlers.plan_view_action_handler",
            level="WARNING",
        ) as captured:
            callback(
                QueuedMutationResult(
                    database_id="bid.mdb",
                    runtime_generation=3,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                    message="conflict",
                )
            )
        self.assertIn("SQL takeoff placement failed: conflict", captured.output[0])
        self.assertEqual(data.takeoffs, {})

    def test_stale_runtime_completion_cannot_remove_pending_preview(self):
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
        self.assertIn(pending_uid, data.takeoffs)
        self.assertNotIn("501", data.takeoffs)
        self.assertIn(operation_id, handler._pending_takeoff_placements)

    def test_mismatched_database_completion_cannot_remove_pending_preview(self):
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
        self.assertIn(pending_uid, data.takeoffs)
        self.assertNotIn("501", data.takeoffs)
        self.assertIn(operation_id, handler._pending_takeoff_placements)

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

    def test_new_straight_segment_of_curved_linear_condition_keeps_curve_disabled(
        self,
    ):
        data = FakeProjectData()
        data.conditions["linear"] = Condition(
            uid="linear",
            layer_visible=True,
            condition_type=Condition.TYPE_LINEAR,
            is_curved_segment=True,
        )
        write = FakeWriteService()
        handler = self._paste_handler(write=write, data=data)
        handler.on_takeoff_created("linear", [0.0, 0.0, 10.0, 0.0], "9")
        self.assertEqual(write.calls[0][2][0].curve, Takeoff.CURVE_DISABLED)
        self.assertEqual(data.added_takeoffs[0].curve, Takeoff.CURVE_DISABLED)

    def test_takeoff_creation_ignores_hidden_layer_and_unknown_condition(self):
        data = FakeProjectData()
        data.conditions["hidden"] = Condition(
            uid="hidden", layer_visible=False, condition_type=Condition.TYPE_AREA
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(write=write, data=data, undo=undo)
        handler.on_takeoff_created("hidden", [1.0, 2.0], "9")
        handler.on_takeoff_created("unknown-condition", [1.0, 2.0], "9")
        handler.on_takeoff_created("42", [1.0, 2.0], "")
        self.assertEqual(write.calls, [])
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(undo.count, 0)

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


class PlanViewActionHandlerOnReassignConditionTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_reassign_condition."""

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

    def _area_with_backout_data(self):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["hole"] = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="parent",
            is_negative=True,
        )
        return data

    def test_reassign_area_condition_carries_backout_children_and_undoes(self):
        data = self._area_with_backout_data()
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data, undo=undo
        )
        handler.on_reassign_condition(["parent"], "42")
        self.assertEqual(
            write.condition_calls, [("bid.mdb", ["parent", "hole"], "42", False)]
        )
        self.assertEqual(data.takeoffs["parent"].condition_uid, "42")
        self.assertEqual(data.takeoffs["hole"].condition_uid, "42")
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(data.takeoffs["parent"].condition_uid, "c1")
        self.assertEqual(data.takeoffs["hole"].condition_uid, "c1")
        undo.redo()
        self.assertEqual(data.takeoffs["hole"].condition_uid, "42")

    def test_sql_reassign_condition_queues_with_condition_dependencies(self):
        data = self._area_with_backout_data()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_reassign_condition(["parent"], "42")
        self.assertEqual(write.condition_calls, [])
        self.assertEqual(len(write.queued_properties), 1)
        _db, bid_uid, kind, updates, options, _callback = write.queued_properties[0]
        self.assertEqual((bid_uid, kind), ("7", "takeoff_condition"))
        self.assertEqual(updates, [("parent", "42"), ("hole", "42")])
        self.assertEqual(options["page_uids"], ("p1",))
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in options["dependency_resources"]
            },
            {("condition", "c1"), ("condition", "42")},
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"parent", "hole"})
        self.assertEqual(data.takeoffs["parent"].condition_uid, "c1")
        self.assertEqual(undo.count, 0)

    def test_can_reassign_takeoffs_requires_access_loaded_takeoffs_and_no_pending(self):
        data = self._area_with_backout_data()
        plan_view = FakePlanView(data)
        plan_view.get_pending_mutation_uids = lambda: set(
            plan_view.pending_mutation_uids
        )
        handler = self._paste_handler(plan_view=plan_view, data=data)
        self.assertTrue(handler.can_reassign_takeoffs({"parent", "hole"}))
        self.assertFalse(handler.can_reassign_takeoffs({"parent", "missing"}))
        plan_view.pending_mutation_uids = {"hole"}
        self.assertFalse(handler.can_reassign_takeoffs({"parent", "hole"}))
        self.assertTrue(handler.can_reassign_takeoffs({"parent"}))
        plan_view.pending_mutation_uids = set()
        handler._ui_access_manager.allowed_features.discard(Feature.EDIT_PLAN_ITEMS)
        self.assertFalse(handler.can_reassign_takeoffs({"parent"}))


class PlanViewActionHandlerOnSetNegativeTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_set_negative."""

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
        self.assertEqual(write.reloads, [])
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
        handler._undo_svc.undo()
        self.assertFalse(data.takeoffs["t1"].is_negative)
        handler._undo_svc.redo()
        self.assertTrue(data.takeoffs["t1"].is_negative)
        self.assertEqual(
            [call[1:3] for call in write.negative_calls],
            [(["t1"], True), (["t1"], False), (["t1"], True)],
        )

    def test_property_history_refuses_replay_when_takeoff_left_its_page(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", is_negative=False
        )
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data, undo=undo
        )
        handler.on_set_negative(["t1"], True)
        data.takeoffs["t1"].page_uid = "p2"
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()
        data.takeoffs["t1"].page_uid = "p1"
        undo.takeoff_targets[0].available = False
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()
        undo.takeoff_targets[0].available = True
        del data.takeoffs["t1"]
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()
        self.assertEqual([call[2] for call in write.negative_calls], [True])

    def test_old_database_completion_cannot_clear_new_same_uid_pending_edit(self):
        data = FakeProjectData()
        data.takeoffs["shared"] = Takeoff(
            uid="shared",
            condition_uid="c1",
            page_uid="p1",
            is_negative=False,
        )
        selected_bid = [BidRef("first.mdb", "7")]
        ui_state = FakeUiState()
        ui_state.get_selected_bid_ref = lambda: selected_bid[0]
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_set_negative(["shared"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        selected_bid[0] = BidRef("second.mdb", "8")
        plan_view.pending_mutation_uids = set()
        handler.on_set_negative(["shared"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="first.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"shared"})

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
        self.assertEqual(queued[4]["page_uids"], ("p1",))
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertFalse(data.takeoffs["t1"].is_negative)


class PlanViewActionHandlerOnPositionsFlushedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_positions_flushed."""

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
        self.assertEqual(
            write.position_calls, [("bid.mdb", [("t1", [5.0, 6.0])], False)]
        )
        self.assertEqual(write.reloads, [])
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
        queued_payload = write.queued_geometry[0][2]
        self.assertEqual(queued_payload["takeoff_positions"], [("t1", [5.0, 6.0])])
        self.assertEqual(queued_payload["takeoff_rotations"], [])
        self.assertEqual(queued_payload["annotation_positions"], [])
        self.assertEqual(queued_payload["page_uids"], ("p1",))
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
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

    def test_sql_mixed_move_blocks_older_undo_until_typed_history_is_ready(self):
        data = FakeProjectData()
        data.takeoffs["10"] = Takeoff(
            uid="10", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.takeoffs["99"] = Takeoff(
            uid="99", condition_uid="c1", page_uid="p1", position=[9.0, 9.0]
        )
        annotations = [
            BidAnnotation(
                uid="10",
                annotation_type=annotation_type,
                page_uid="p1",
                position=[float(index), float(index)],
            )
            for index, annotation_type in enumerate(("line", "arrow", "text"), 1)
        ]
        data.annotations = annotations
        plan_view = FakePlanView(data)
        plan_view.annotations = {
            f"10_{annotation.annotation_type}": annotation for annotation in annotations
        }
        plan_view.annotation_key_map = {
            ("10", annotation.annotation_type): f"10_{annotation.annotation_type}"
            for annotation in annotations
        }
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        older_undos = []
        undo.push_local(lambda: older_undos.append("older") or True, lambda: True)
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            data=data,
            undo=undo,
        )
        takeoff_changes = [("10", [0.0, 0.0], [5.0, 6.0])]
        annotation_changes = [
            (
                annotation.uid,
                annotation.annotation_type,
                list(annotation.position),
                [annotation.position[0] + 5.0, annotation.position[1] + 6.0],
            )
            for annotation in annotations
        ]
        handler.on_positions_flushed(takeoff_changes, annotation_changes)
        undo.undo()
        self.assertEqual(older_undos, [])
        self.assertEqual(len(write.queued_geometry), 1)
        callback = write.queued_geometry[0][-1]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        undo.undo()
        self.assertEqual(len(write.queued_geometry), 2)
        undo_payload = write.queued_geometry[1][2]
        self.assertEqual(undo_payload["takeoff_positions"], [("10", [0.0, 0.0])])
        self.assertEqual(
            set(
                (uid, annotation_type, tuple(position))
                for uid, annotation_type, position in undo_payload[
                    "annotation_positions"
                ]
            ),
            {
                ("10", "line", (1.0, 1.0)),
                ("10", "arrow", (2.0, 2.0)),
                ("10", "text", (3.0, 3.0)),
            },
        )
        self.assertIn("99", data.takeoffs)
        self.assertEqual(write.queued_deletes, [])

    def test_rejected_mixed_move_restores_preview_instead_of_exposing_older_undo(self):
        plan_view = FakePlanView()
        access = FakeAccess(set(Feature).difference({Feature.EDIT_PLAN_ITEMS}))
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=FakeProjectData(),
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=access,
        )
        takeoff_changes = [("10", [0.0, 0.0], [5.0, 6.0])]
        annotation_changes = [("10", "line", [1.0, 1.0], [6.0, 7.0])]
        handler.on_positions_flushed(takeoff_changes, annotation_changes)
        self.assertEqual(
            plan_view.restored_positions,
            [(takeoff_changes, annotation_changes)],
        )
        self.assertEqual(write.queued_geometry, [])
        self.assertEqual(undo.count, 0)

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

    def test_sql_position_failure_does_not_restore_preview_after_page_switch(self):
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
        plan_view.current_page_uid = "p2"
        write.queued_geometry[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_position_failure_does_not_restore_same_uid_replacement_page(self):
        data = FakeProjectData()
        original_page = data.pages["p1"]
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        write.queued_geometry[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.selected, {"t1"})
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_sql_position_failure_does_not_restore_after_edit_access_revocation(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        access = FakeAccess(set(Feature))
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=access,
        )
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        access.allowed_features.discard(Feature.EDIT_PLAN_ITEMS)
        write.queued_geometry[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

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
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        undo.redo()
        self.assertEqual(
            [call[2] for call in write.position_calls], [False, False, False]
        )
        self.assertEqual(
            [call[1] for call in write.position_calls],
            [[("t1", [5.0, 6.0])], [("t1", [0.0, 0.0])], [("t1", [5.0, 6.0])]],
        )
        self.assertEqual(write.reloads, [])
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
        undo = FakeUndoService()
        handler = self._paste_handler(plan_view=plan_view, write=write, undo=undo)
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        self.assertEqual(plan_view.restored_positions, [(changes, [])])
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._event_bus.events, [])

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
        write.annotation_write_service = ann_write
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
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["t1"],
                        "condition_uids": ["c1"],
                    },
                ),
                (
                    AppEvents.ANNOTATIONS_CHANGED,
                    {
                        "page_uid": "p1",
                        "annotation_uids": ["a1"],
                        "annotation_types": ["annotation"],
                    },
                ),
            ],
        )
        self.assertEqual(write.reloads, [])

    def test_failed_annotation_position_save_restores_complete_mixed_preview(self):
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
        self.assertEqual(
            plan_view.restored_positions,
            [(takeoff_changes, ann_changes)],
        )

    def test_polygon_control_point_edits_use_mdb_annotation_undo_path(self):
        old_position = [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0]
        new_position = [
            0.0,
            0.0,
            50.0,
            0.0,
            100.0,
            0.0,
            100.0,
            100.0,
            0.0,
            100.0,
        ]
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                data = FakeProjectData()
                data.annotations = [
                    BidAnnotation(
                        uid="a1",
                        annotation_type=annotation_type,
                        page_uid="p1",
                        position=list(new_position),
                    )
                ]
                annotation_write = FakeAnnotationWriteService()
                undo = FakeUndoService()
                handler = PlanViewActionHandler(
                    plan_view=FakePlanView(data),
                    ui_state_manager=FakeUiState(),
                    project_data_svc=data,
                    project_write_svc=FakeWriteService(),
                    annotation_write_svc=annotation_write,
                    page_settings_bar=FakePageSettingsBar(),
                    undo_svc=undo,
                    event_bus=FakeEventBus(),
                    deferred_persistence_manager=FakeDeferredPersistence(),
                    ui_access_manager=FakeAccess(set(Feature)),
                )
                changes = [
                    (
                        "a1",
                        annotation_type,
                        list(old_position),
                        list(new_position),
                    )
                ]
                handler.on_positions_flushed([], changes)
                self.assertEqual(
                    annotation_write.position_calls[0],
                    (
                        "bid.mdb",
                        [("a1", annotation_type, new_position)],
                        False,
                    ),
                )
                self.assertEqual(undo.count, 1)
                undo.undo()
                undo.redo()
                self.assertEqual(
                    [call[1] for call in annotation_write.position_calls[1:]],
                    [
                        [("a1", annotation_type, old_position)],
                        [("a1", annotation_type, new_position)],
                    ],
                )

    def test_polygon_control_point_edits_use_sql_geometry_queue(self):
        old_position = [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0]
        new_position = [
            0.0,
            0.0,
            50.0,
            0.0,
            100.0,
            0.0,
            100.0,
            100.0,
            0.0,
            100.0,
        ]
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                data = FakeProjectData()
                data.annotations = [
                    BidAnnotation(
                        uid="a1",
                        annotation_type=annotation_type,
                        page_uid="p1",
                        position=list(new_position),
                    )
                ]
                write = FakeWriteService()
                write.sql_collaboration_mutations = True
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
                handler.on_positions_flushed(
                    [],
                    [
                        (
                            "a1",
                            annotation_type,
                            list(old_position),
                            list(new_position),
                        )
                    ],
                )
                self.assertEqual(annotation_write.position_calls, [])
                self.assertEqual(len(write.queued_geometry), 1)
                self.assertEqual(
                    write.queued_geometry[0][2]["annotation_positions"],
                    [("a1", annotation_type, new_position)],
                )
                self.assertEqual(undo.count, 0)
                write.queued_geometry[0][-1](
                    QueuedMutationResult(
                        database_id="bid.mdb",
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                    )
                )
                self.assertEqual(undo.count, 1)

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

    def test_rotated_annotation_history_after_calibration_preserves_angle(
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
                position=[0.0, 0.0, 96.0, 96.0, 0.123456789],
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
                    [0.0, 0.0, 96.0, 96.0, 0.123456789],
                    [0.0, 0.0, 120.0, 120.0, 0.123456789],
                )
            ],
        )
        data.pages["p1"].scale_factor1 = 0.1875
        data.pages["p1"].scale_factor2 = 12.0
        data.annotations[0].position = [0.0, 0.0, 80.0, 80.0, 0.123456789]
        undo.undo()
        undo.redo()
        self.assertEqual(
            ann_write.position_calls[1],
            (
                "bid.mdb",
                [("a1", ANNOTATION_TYPE_RECT, [0.0, 0.0, 64.0, 64.0, 0.123456789])],
                False,
            ),
        )
        self.assertEqual(
            ann_write.position_calls[2],
            (
                "bid.mdb",
                [("a1", ANNOTATION_TYPE_RECT, [0.0, 0.0, 80.0, 80.0, 0.123456789])],
                False,
            ),
        )

    def test_failed_annotation_position_save_rolls_back_without_history(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        write.annotation_write_service = ann_write
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
        self.assertEqual(undo.count, 0)
        self.assertEqual(
            plan_view.restored_positions,
            [(takeoff_changes, ann_changes)],
        )
        self.assertEqual(
            write.position_calls,
            [
                ("bid.mdb", [("t1", [5.0, 6.0])], False),
            ],
        )
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])


class PlanViewActionHandlerOnGeometryEditLeaseRequestedTests(
    _PlanViewActionHandlerFixture
):
    """PlanViewActionHandler.on_geometry_edit_lease_requested."""

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
        self.assertEqual(database_id, "bid.mdb")
        self.assertEqual(resources, (ResourceRef("takeoff", "t1", 7),))
        self.assertEqual(
            dependencies,
            tuple(
                sorted(
                    (
                        ResourceRef("condition", "c1", 7),
                        ResourceRef("page", "p1", 7),
                    )
                )
            ),
        )
        self.assertEqual(options["owning_surface"], "main-plan")
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
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

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
        handler.on_plan_item_selection_changed(["t1"])
        self.assertEqual(write.ended_edit_leases, [])
        self.assertEqual(plan_view.geometry_lease_granted, {"t1"})
        handler.on_plan_item_selection_changed([])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertIsNone(handler._geometry_edit_lease_handle)

    def test_sql_geometry_lease_late_grant_is_released_after_access_loss(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        access = FakeAccess(set(Feature))
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=FakeUiState(),
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=FakeAnnotationWriteService(),
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=access,
        )
        handler.on_geometry_edit_lease_requested(["t1"])
        database_id, resources, dependencies, options, lease_callback = (
            write.edit_lease_requests[0]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id="draft-late",
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
        access.allowed_features.remove(Feature.EDIT_PLAN_ITEMS)
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_sql_geometry_lease_late_grant_is_released_after_page_switch(self):
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
            draft_id="draft-late",
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
        plan_view.current_page_uid = "p2"
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_sql_geometry_lease_late_grant_rejects_same_uid_page_replacement(self):
        data = FakeProjectData()
        original_page = data.pages["p1"]
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
            draft_id="draft-replaced-page",
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
        data.pages["p1"] = SimpleNamespace(
            uid="p1",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        self.assertIsNot(data.pages["p1"], original_page)
        lease_callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def _lease_handler(self, sql_mutations=True, allowed=None):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql_mutations
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, allowed_features=allowed
        )
        return handler, plan_view, write

    def test_unrelated_edit_lease_loss_keeps_granted_geometry_lease(self):
        handler, plan_view, write = self._lease_handler()
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
        for field, value in (
            ("draft_id", "another-draft"),
            ("runtime_generation", 4),
            ("database_id", "another.mdb"),
        ):
            with self.subTest(field=field):
                loss_fields = {
                    "database_id": database_id,
                    "draft_id": handle.draft_id,
                    "runtime_generation": handle.runtime_generation,
                    "operation_id": handle.operation_id,
                    "owning_surface": handle.owning_surface,
                    "resources": handle.resources,
                    "reason": "trust-lost",
                }
                loss_fields[field] = value
                handler.on_edit_lease_lost(EditLeaseLoss(**loss_fields))
                self.assertIs(handler._geometry_edit_lease_handle, handle)
                self.assertEqual(plan_view.geometry_lease_granted, {"t1"})

    def test_geometry_lease_is_not_requested_without_sql_edit_access_or_selection(
        self,
    ):
        handler, plan_view, write = self._lease_handler(sql_mutations=False)
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(write.edit_lease_requests, [])
        self.assertEqual(plan_view.geometry_lease_pending, set())
        handler, plan_view, write = self._lease_handler(
            allowed={Feature.SELECT_PLAN_ITEMS}
        )
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(write.edit_lease_requests, [])
        handler, plan_view, write = self._lease_handler()
        handler.on_geometry_edit_lease_requested([])
        handler.on_geometry_edit_lease_requested(["not-a-plan-item"])
        self.assertEqual(write.edit_lease_requests, [])
        self.assertEqual(plan_view.geometry_lease_pending, set())

    def test_sql_geometry_lease_denial_clears_pending_state(self):
        handler, plan_view, write = self._lease_handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(plan_view.geometry_lease_pending, {"t1"})
        write.edit_lease_requests[0][-1](EditLeaseResult(False))
        self.assertEqual(plan_view.geometry_lease_pending, set())
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(write.ended_edit_leases, [])
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(len(write.edit_lease_requests), 2)

    def test_sql_geometry_lease_repeat_request_for_pending_selection_is_ignored(
        self,
    ):
        handler, plan_view, write = self._lease_handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(len(write.edit_lease_requests), 1)
        self.assertEqual(plan_view.geometry_lease_pending, {"t1"})

    def test_sql_geometry_lease_loss_requires_a_fresh_lease_for_same_selection(self):
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
            draft_id="draft-before-reconnect",
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
        handler.on_edit_lease_lost(
            EditLeaseLoss(
                database_id=database_id,
                draft_id=handle.draft_id,
                runtime_generation=handle.runtime_generation,
                operation_id=handle.operation_id,
                owning_surface=handle.owning_surface,
                resources=handle.resources,
                reason="trust-lost",
            )
        )
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(write.ended_edit_leases, [])
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(len(write.edit_lease_requests), 2)


class PlanViewActionHandlerOnGroupRotationFlushedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_group_rotation_flushed."""

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
        undo = FakeUndoService()
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
        self.assertEqual(
            write.position_calls, [("bid.mdb", [("t1", [3.0, 4.0])], False)]
        )
        self.assertEqual(write.rotation_calls, [("bid.mdb", [("t1", 45.0)], False)])
        self.assertEqual(write.reloads, [])
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 45.0)
        self.assertEqual(len(event_bus.events), 1)
        event_name, event_payload = event_bus.events[0]
        self.assertEqual(event_name, AppEvents.TAKEOFFS_CHANGED)
        self.assertEqual(event_payload["page_uid"], "p1")
        self.assertEqual(set(event_payload["takeoff_uids"]), {"t1"})
        self.assertEqual(event_payload["condition_uids"], ["c1"])
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)

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

    def test_group_rotation_failure_rolls_back_position_change(self):
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
        self.assertEqual(plan_view.restored_positions, [(position_changes, [])])
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertEqual(event_bus.events, [])

    def test_group_rotation_failure_does_not_register_partial_undo(self):
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
        self.assertEqual(undo.count, 0)
        self.assertEqual(
            write.position_calls,
            [
                ("bid.mdb", [("t1", [3.0, 4.0])], False),
            ],
        )
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 0.0)
        self.assertEqual(event_bus.events, [])

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
        write.annotation_write_service = annotation_write
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
        write.annotation_write_service = annotation_write
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
        self.assertEqual(len(write.rotation_calls), 1)
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])
        self.assertEqual(
            plan_view.restored_positions,
            [(takeoff_changes, annotation_changes)],
        )
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])
        self.assertEqual(undo.count, 0)

    def test_group_rotation_undo_rotation_failure_preserves_post_state(self):
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
        self.assertEqual(data.takeoffs["t1"].position, [3.0, 4.0])
        self.assertEqual(data.takeoffs["t1"].rotation, 45.0)
        self.assertEqual(
            [event for event, _payload in events.events],
            [AppEvents.TAKEOFFS_CHANGED],
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
        write.annotation_write_service = annotation_write
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

    def test_group_rotation_failure_stops_annotation_write_and_restores_preview(self):
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
        write.annotation_write_service = annotation_write
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
        self.assertEqual(undo.count, 0)
        self.assertEqual(len(annotation_write.position_calls), 0)
        self.assertEqual(len(write.position_calls), 1)
        self.assertEqual(data.annotations[0].position, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(handler._plan_view.restored_rotations, [rotation_changes])


class PlanViewActionHandlerOnPasteRequestedTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.on_paste_requested."""

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
            [(takeoff.uid, takeoff.parent_uid) for takeoff in data.added_takeoffs],
            [("100", "0"), ("101", "100")],
        )
        self.assertEqual(
            event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["100", "101"],
                        "condition_uids": ["c1"],
                    },
                )
            ],
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

    def test_curved_takeoff_paste_replay_preserves_length_offset_semantics(self):
        source = Takeoff(
            uid="source",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 106.0, 20.0, 58.0, 30.0, 9.0],
            curve=1,
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
        self.assertEqual(write.calls[0][2][0].position, [11, 21, 107, 21, 59, 31, 9])
        expected = [22 / 3, 14, 214 / 3, 14, 118 / 3, 62 / 3, 6]
        for actual, value in zip(write.calls[1][2][0].position, expected):
            self.assertAlmostEqual(actual, value)
        for _ in range(20):
            undo.undo()
            data.pages["p1"].scale_factor1 = 0.125
            undo.redo()
            self.assertEqual(
                write.calls[-1][2][0].position, [11, 21, 107, 21, 59, 31, 9]
            )
            undo.undo()
            data.pages["p1"].scale_factor1 = 0.1875
            undo.redo()
        self.assertEqual(source.position, [10, 20, 106, 20, 58, 30, 9])

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

    def test_cross_bid_paste_redo_reuses_remapped_condition_without_duplicating(self):
        source = self._copied_takeoff()
        data = FakeProjectData()
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(write=write, data=data, undo=undo)
        handler._clipboard_svc = FakeClipboard(
            [source], source_bid_uid="6", source_file_path="bid.mdb"
        )
        handler.on_paste_requested()
        self.assertEqual(len(write.condition_duplicate_calls), 1)
        undo.undo()
        undo.redo()
        self.assertEqual(len(write.condition_duplicate_calls), 1)
        self.assertEqual(
            [call[2][0].condition_uid for call in write.calls], ["new-c1", "new-c1"]
        )
        self.assertEqual(
            [payload.source_bid_uid for _db, payload, _options in write.local_pastes],
            ["6", "7"],
        )

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

    def test_line_paste_undo_removes_authoritative_typed_annotation(self):
        source = self._copied_annotation(annotation_type="line")
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        annotation_write = FakeAnnotationWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view,
            ann_write=annotation_write,
            data=data,
            undo=undo,
        )
        handler._clipboard_svc = FakeClipboard([], annotations=[source])
        handler.on_paste_requested()
        self.assertEqual(
            {
                (annotation.uid, annotation.annotation_type)
                for annotation in data.annotations
            },
            {("ann-1", "line")},
        )
        undo.undo()
        self.assertEqual(data.annotations, [])
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(
            handler._write_svc.local_annotation_delete_calls,
            [("bid.mdb", [("ann-1", "line")], False)],
        )

    def test_paste_history_on_another_page_preserves_current_selection(self):
        source = self._copied_annotation(annotation_type="line")
        data = FakeProjectData()
        data.pages["p2"] = SimpleNamespace(
            uid="p2",
            overlay_rect=None,
            scale_factor1=1.0,
            scale_factor2=1.0,
        )
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1_line"}
        annotation_write = FakeAnnotationWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view,
            ann_write=annotation_write,
            data=data,
            undo=undo,
        )
        handler._clipboard_svc = FakeClipboard([], annotations=[source])
        handler.on_paste_requested()
        plan_view.current_page_uid = "p2"
        plan_view.set_selected_uids({"page-2-selection"})
        undo.undo()
        self.assertEqual(data.annotations, [])
        self.assertEqual(plan_view.selected, {"page-2-selection"})
        undo.redo()
        self.assertEqual(
            [
                (annotation.uid, annotation.annotation_type)
                for annotation in data.annotations
            ],
            [("ann-1", "line")],
        )
        self.assertEqual(plan_view.selected, {"page-2-selection"})

    def test_multiple_line_paste_undo_removes_every_generated_identity(self):
        sources = [
            self._copied_annotation(uid=f"source-{index}", annotation_type="line")
            for index in range(3)
        ]
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {
            (f"ann-{index}", "line"): f"ann-{index}" for index in range(1, 4)
        }
        annotation_write = FakeAnnotationWriteService()
        annotation_write.next_uids = ["ann-1", "ann-2", "ann-3"]
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view,
            ann_write=annotation_write,
            data=data,
            undo=undo,
        )
        handler._clipboard_svc = FakeClipboard([], annotations=sources)
        handler.on_paste_requested()
        undo.undo()
        self.assertEqual(data.annotations, [])
        self.assertEqual(
            set(handler._write_svc.local_annotation_delete_calls[-1][1]),
            {("ann-1", "line"), ("ann-2", "line"), ("ann-3", "line")},
        )

    def test_mixed_line_takeoff_paste_undo_keeps_typed_membership(self):
        takeoff = self._copied_takeoff()
        line = self._copied_annotation(annotation_type="line")
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("100", "line"): "100_line"}
        write = FakeWriteService()
        write.next_annotation_uids = ["100"]
        annotation_write = FakeAnnotationWriteService()
        annotation_write.next_uids = ["100"]
        undo = UndoRedoService()
        undo.set_active_bid(FakeUiState().get_selected_bid_ref())
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            ann_write=annotation_write,
            data=data,
            undo=undo,
        )
        handler._clipboard_svc = FakeClipboard([takeoff], annotations=[line])
        handler.on_paste_requested()
        self.assertEqual(set(data.takeoffs), {"100"})
        self.assertEqual(
            {
                (annotation.uid, annotation.annotation_type)
                for annotation in data.annotations
            },
            {("100", "line")},
        )
        undo.undo()
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(data.annotations, [])
        self.assertEqual(write.local_deletes[-1][2], ["100"])
        self.assertEqual(write.local_deletes[-1][3], [("100", "line")])

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

    def test_mixed_paste_delete_undo_tracks_table_scoped_annotation_uids(self):
        takeoff = self._copied_takeoff()
        rect = self._copied_annotation(
            uid="rect-source",
            annotation_type="rect",
        )
        oval = self._copied_annotation(
            uid="oval-source",
            annotation_type="oval",
            position=[20.0, 30.0, 24.0, 34.0],
        )
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {
            ("shared-new", "rect"): "shared-new",
            ("shared-new", "oval"): "shared-new_oval",
        }
        write = FakeWriteService()
        write.next_uids = ["takeoff-new", "takeoff-restored"]
        annotation_write = FakeAnnotationWriteService()
        annotation_write.next_uids = ["shared-new", "shared-new"]
        undo = UndoRedoService()
        bid_ref = FakeUiState().get_selected_bid_ref()
        undo.set_active_bid(bid_ref)
        prior_undos = []
        undo.push_local(
            lambda: prior_undos.append("prior") or True,
            lambda: True,
        )
        write.annotation_write_service = annotation_write
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
        handler._clipboard_svc = FakeClipboard(
            [takeoff],
            annotations=[rect, oval],
        )
        handler.on_paste_requested()
        self.assertEqual(
            plan_view.selected,
            {"takeoff-new", "shared-new", "shared-new_oval"},
        )
        plan_view.annotations = {
            plan_view.annotation_key_map[
                (annotation.uid, annotation.annotation_type)
            ]: (annotation)
            for annotation in data.annotations
        }
        handler.on_elements_deleted(list(plan_view.selected))
        self.assertEqual(
            set(write.local_deletes[-1][3]),
            {("shared-new", "rect"), ("shared-new", "oval")},
        )
        self.assertEqual(data.annotations, [])
        undo.undo()
        self.assertEqual(prior_undos, [])
        self.assertEqual(
            {
                (annotation.uid, annotation.annotation_type)
                for annotation in data.annotations
            },
            {("shared-new", "rect"), ("shared-new", "oval")},
        )
        self.assertEqual(
            plan_view.selected,
            {"takeoff-restored", "shared-new", "shared-new_oval"},
        )

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
        handler._clipboard_svc = FakeClipboard(
            [hole], extras={"old-hole": {"Raw": "x"}}
        )
        handler.on_paste_requested()
        self.assertEqual(
            plan_view.paste_backout_calls,
            [([hole], {"old-hole": {"Raw": "x"}}, "7")],
        )
        self.assertEqual(write.calls, [])
        self.assertEqual(write.queued_pastes, [])
        self.assertEqual(write.local_pastes, [])

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
        handler._clipboard_svc = FakeClipboard(
            [hole], extras={"old-hole": {"Raw": "x"}}
        )
        handler.on_paste_requested()
        self.assertEqual(
            plan_view.paste_backout_calls,
            [([hole], {"old-hole": {"Raw": "x"}}, "7")],
        )
        self.assertEqual(write.calls, [])
        self.assertEqual(write.queued_pastes, [])
        self.assertEqual(write.local_pastes, [])

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

    def test_sql_paste_request_queues_translated_payload_and_selects_on_commit(self):
        source = self._copied_takeoff()
        plan_view = FakePlanView()
        plan_view.intelligent_paste_enabled = False
        plan_view.selected = {"previous"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(plan_view=plan_view, write=write, undo=undo)
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(write.calls, [])
        self.assertEqual(write.local_pastes, [])
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(len(write.queued_pastes), 1)
        database_id, payload, options, callback = write.queued_pastes[0]
        self.assertEqual(database_id, "bid.mdb")
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        self.assertEqual(payload.takeoff_source_uids, ("source",))
        self.assertEqual(payload.takeoff_specs[0].page_uid, "p1")
        self.assertEqual(payload.takeoff_specs[0].position, [11.0, 21.0, 15.0, 21.0])
        self.assertEqual(options["dependency_resources"], ())
        self.assertEqual(undo.count, 0)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_uid_maps=(("takeoffs", (("source", "new-1"),)),),
                ),
            )
        )
        self.assertEqual(plan_view.selected, {"new-1"})
        self.assertEqual(undo.count, 1)
        undo.undo()
        self.assertEqual(write.queued_deletes[0][2], ["new-1"])

    def test_sql_paste_request_failure_restores_previous_selection(self):
        source = self._copied_takeoff()
        plan_view = FakePlanView()
        data = FakeProjectData()
        data.takeoffs["previous"] = Takeoff(
            uid="previous", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view.data = data
        plan_view.selected = {"previous"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, undo=undo, data=data
        )
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(plan_view.selected, set())
        write.queued_pastes[0][3](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected, {"previous"})
        self.assertEqual(undo.count, 0)

    def test_sql_paste_failure_does_not_override_newer_selection(self):
        plan_view = FakePlanView()
        plan_view.selected = {"previous"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write)
        handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
        handler.on_paste_requested()
        plan_view.set_selected_uids({"user-choice"})
        write.queued_pastes[0][3](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.CONFLICT,
            )
        )
        self.assertEqual(plan_view.selected, {"user-choice"})

    def test_intelligent_paste_without_mouse_position_keeps_source_position(self):
        source = self._copied_takeoff()
        plan_view = FakePlanView()
        plan_view.mouse_ost_position = None
        write = FakeWriteService()
        handler = self._paste_handler(plan_view=plan_view, write=write)
        handler._clipboard_svc = FakeClipboard([source])
        handler.on_paste_requested()
        self.assertEqual(write.calls[0][2][0].position, [10.0, 20.0, 14.0, 20.0])
        self.assertEqual(plan_view.intelligent_paste_calls, [(["100"], (10.0, 20.0))])

    def test_standard_offset_paste_uses_snap_increment_or_one_when_disabled(self):
        for snap_increments, expected_offset in ((2.5, 2.5), (0.0, 1.0)):
            with self.subTest(snap_increments=snap_increments):
                plan_view = FakePlanView()
                plan_view.intelligent_paste_enabled = False
                plan_view.snap_increments = snap_increments
                write = FakeWriteService()
                handler = self._paste_handler(plan_view=plan_view, write=write)
                handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
                handler.on_paste_requested()
                self.assertEqual(
                    write.calls[0][2][0].position,
                    [
                        10.0 + expected_offset,
                        20.0 + expected_offset,
                        14.0 + expected_offset,
                        20.0 + expected_offset,
                    ],
                )

    def test_pasted_hotlink_is_dropped_when_its_named_view_is_unavailable(self):
        data = FakeProjectData()
        data.annotations = [_named_view_annotation("nv-existing", "Lobby")]
        hotlinks = [
            _hotlink_annotation("hl-missing", "nv-missing"),
            _hotlink_annotation("hl-existing", "nv-existing"),
        ]
        plan_view = FakePlanView(data)
        plan_view.intelligent_paste_enabled = False
        plan_view.annotation_key_map = {("ann-1", "hotlink"): "ann-1"}
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data
        )
        handler._clipboard_svc = FakeClipboard([], annotations=hotlinks)
        handler.on_paste_requested()
        self.assertEqual(len(ann_write.insert_calls), 1)
        specs = ann_write.insert_calls[0][2]
        self.assertEqual(
            [spec.properties["BidPageViewUID"] for spec in specs], ["nv-existing"]
        )


class PlanViewActionHandlerCanPasteToCurrentBidTests(_PlanViewActionHandlerFixture):
    """PlanViewActionHandler.can_paste_to_current_bid."""

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

    def test_paste_is_unavailable_for_empty_or_foreign_database_clipboard(self):
        source = self._copied_takeoff()
        ann_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        handler = self._paste_handler(write=write, ann_write=ann_write)
        self.assertFalse(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        handler._clipboard_svc = FakeClipboard(
            [source], source_file_path="other-database.mdb"
        )
        self.assertFalse(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(write.calls, [])
        self.assertEqual(write.local_pastes, [])
        self.assertEqual(ann_write.insert_calls, [])

    def test_annotation_only_clipboard_from_other_bid_is_not_pasteable(self):
        source = self._copied_annotation()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(ann_write=ann_write)
        handler._clipboard_svc = FakeClipboard(
            [], annotations=[source], source_bid_uid="6"
        )
        self.assertFalse(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(ann_write.insert_calls, [])

    def test_mixed_clipboard_without_edit_access_pastes_only_annotations(self):
        source = self._copied_takeoff()
        annotation = self._copied_annotation()
        plan_view = FakePlanView()
        plan_view.annotation_key_map = {("ann-1", "line"): "ann-1"}
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            ann_write=ann_write,
            allowed_features={Feature.PLACE_ANNOTATIONS},
        )
        handler._clipboard_svc = FakeClipboard(
            [source], annotations=[annotation], source_bid_uid="7"
        )
        self.assertTrue(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(write.calls, [])
        self.assertEqual(len(ann_write.insert_calls), 1)
        self.assertEqual(plan_view.selected, {"ann-1"})

    def test_clipboard_paste_accepts_equivalent_windows_database_path(self):
        source = self._copied_takeoff()
        handler = self._paste_handler()
        handler._ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("C:/Jobs/Bid.mdb", "7")
        )
        handler._clipboard_svc = FakeClipboard(
            [source], source_file_path=r"c:\jobs\bid.mdb"
        )
        self.assertTrue(handler.can_paste_to_current_bid())
        handler.on_paste_requested()
        self.assertEqual(len(handler._write_svc.calls), 1)


class TakeoffLifecycleHistoryTests(unittest.TestCase):
    def test_history_projection_rejects_destroyed_native_plan_owner(self):
        import tests.integration.history.test_property_lifetimes as fixtures
        from PySide6.QtWidgets import QApplication, QWidget
        from shiboken6 import delete

        app = QApplication.instance() or QApplication([])
        handler, _data, _write, _undo = (
            fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        plan = QWidget()
        plan._is_cleaning_up = False
        plan.current_page_uid = "p1"
        handler._plan_view = plan
        bid_ref = handler._ui_state.get_selected_bid_ref()
        self.assertTrue(handler._plan_context_is_current(bid_ref, ("p1",)))
        plan._is_cleaning_up = True
        self.assertFalse(handler._plan_context_is_current(bid_ref, ("p1",)))
        plan._is_cleaning_up = False
        delete(plan)
        self.assertFalse(handler._plan_context_is_current(bid_ref, ("p1",)))

    def test_paste_completion_does_not_project_into_cleaned_plan(self):
        import tests.integration.history.test_property_lifetimes as fixtures

        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        handler, _data, write, _undo = fixture.make_handler()
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(
            handler._ui_state.get_selected_bid_ref(), "p1", payload, ()
        )
        handler._plan_view._is_cleaning_up = True
        write.queued_pastes[-1][-1](
            fixture.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(("takeoffs", (("source", "persisted"),)),)
                )
            )
        )
        self.assertEqual(handler._plan_view.selected, set())


class PlanViewActionHandlerStaleTerminalDeliveryTests(_PlanViewActionHandlerFixture):
    """A duplicate terminal failure of operation A must not clear or restore the
    state of the newer operation B that started on the same items (D7p shape)."""

    @staticmethod
    def _failure(status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT):
        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
        )

    def _sql_handler(self, data, plan_view=None):
        plan_view = FakePlanView(data) if plan_view is None else plan_view
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        return handler, plan_view, write

    def _takeoff_data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        return data

    def test_duplicate_geometry_failure_keeps_the_newer_move_pending_and_unrestored(
        self,
    ):
        handler, plan_view, write = self._sql_handler(self._takeoff_data())
        first = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(first, [])
        callback_a = write.queued_geometry[0][-1]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertEqual(plan_view.restored_positions, [(first, [])])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        second = [("t1", [0.0, 0.0], [7.0, 8.0])]
        handler.on_positions_flushed(second, [])
        self.assertEqual(len(write.queued_geometry), 2)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        # The failure of the FIRST move is delivered a second time.
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(plan_view.restored_positions, [(first, [])])
        # The second move fails once on its own and is restored normally.
        write.queued_geometry[1][-1](self._failure())
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.restored_positions, [(first, []), (second, [])])

    def test_duplicate_delete_failure_keeps_the_newer_delete_pending(self):
        data = self._takeoff_data()
        handler, plan_view, write = self._sql_handler(data)
        plan_view.selected = {"t1"}
        handler.on_elements_deleted(["t1"])
        callback_a = write.queued_deletes[0][-1]
        failure_a = self._failure(MutationOutcomeStatus.CONFLICT)
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        plan_view.selected = {"t1"}
        handler.on_elements_deleted(["t1"])
        self.assertEqual(len(write.queued_deletes), 2)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        callback_a(failure_a)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        write.queued_deletes[1][-1](self._failure(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_duplicate_cancelled_placement_delete_failure_keeps_the_newer_move_pending(
        self,
    ):
        handler, data, plan_view, write, _undo = (
            PlanViewActionHandlerOnTakeoffCreatedTests._multi_condition_pending_handler(
                self
            )
        )
        operation_id, callback = write.queued_takeoff_callbacks[0]
        first_pending, _second_pending = list(data.takeoffs)
        handler.on_elements_deleted([first_pending])
        data.add_takeoffs(
            [
                Takeoff(
                    uid=uid,
                    condition_uid=condition_uid,
                    page_uid="9",
                    position=[1.0, 2.0],
                )
                for uid, condition_uid in (("501", "c1"), ("502", "c2"))
            ]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("501", "502"),
            )
        )
        # The follow-up delete of the cancelled preview's committed takeoff "501".
        self.assertEqual(write.queued_deletes[0][2], ["501"])
        self.assertIn("501", plan_view.pending_mutation_uids)
        callback_a = write.queued_deletes[0][-1]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertNotIn("501", plan_view.pending_mutation_uids)
        # A newer operation B (a move) starts on the surviving takeoff "501".
        handler.on_positions_flushed([("501", [1.0, 2.0], [5.0, 6.0])], [])
        self.assertIn("501", plan_view.pending_mutation_uids)
        # The failure of the cancelled-placement delete is delivered a second time.
        callback_a(failure_a)
        self.assertIn("501", plan_view.pending_mutation_uids)

    def test_duplicate_paste_failure_does_not_override_a_newer_selection(self):
        data = self._takeoff_data()
        handler, plan_view, write = self._sql_handler(data)
        plan_view.selected = {"t1"}
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(
            handler._ui_state.get_selected_bid_ref(), "p1", payload, ()
        )
        self.assertEqual(plan_view.selected, set())
        callback_a = write.queued_pastes[-1][-1]
        failure_a = self._failure()
        callback_a(failure_a)
        self.assertEqual(plan_view.selected, {"t1"})
        # The user then chooses something else; the failure is delivered again.
        plan_view.set_selected_uids({"user-choice"})
        callback_a(failure_a)
        self.assertEqual(plan_view.selected, {"user-choice"})

    def test_duplicate_placement_failure_leaves_the_other_placement_untouched(self):
        plan_view = FakePlanView()
        plan_view.current_page_uid = "9"
        data = FakeProjectData()
        handler, plan_view, write = self._sql_handler(data, plan_view)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        handler.on_takeoff_created("42", [3.0, 4.0], "9")
        previews = set(data.takeoffs)
        self.assertEqual(len(previews), 2)
        first_operation_id, first_callback = write.queued_takeoff_callbacks[0]
        first_preview = next(uid for uid in previews if first_operation_id in uid)
        failure_a = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=first_operation_id,
            outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        with self.assertLogs(handler_module.logger, level="WARNING") as logged:
            first_callback(failure_a)
            self.assertEqual(set(data.takeoffs), previews - {first_preview})
            self.assertEqual(
                plan_view.pending_mutation_uids, previews - {first_preview}
            )
            # The failure of the first placement is delivered a second time.
            first_callback(failure_a)
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(set(data.takeoffs), previews - {first_preview})
        self.assertEqual(plan_view.pending_mutation_uids, previews - {first_preview})

    def test_failure_after_interim_results_is_still_handled_exactly_once(self):
        handler, plan_view, write = self._sql_handler(self._takeoff_data())
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        callback = write.queued_geometry[0][-1]
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callback(self._failure(status))
            self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
            self.assertEqual(plan_view.restored_positions, [])
        callback(self._failure(MutationOutcomeStatus.FAILED_BEFORE_COMMIT))
        callback(self._failure(MutationOutcomeStatus.FAILED_BEFORE_COMMIT))
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.restored_positions, [(changes, [])])


class _LockedBidWriteService(FakeWriteService):
    """FakeWriteService whose SQL plan queues refuse like the real ProjectWriteService
    on a locked active Bid (ActiveBidLockedError at submission, nothing queued)."""

    def __init__(self):
        super().__init__()
        self.sql_collaboration_mutations = True
        self.locked = True
        self.refused = []

    def _refuse_when_locked(self, name):
        if self.locked:
            self.refused.append(name)
            raise ActiveBidLockedError()

    def queue_plan_geometry(self, *args, **kwargs):
        self._refuse_when_locked("geometry")
        return super().queue_plan_geometry(*args, **kwargs)

    def queue_plan_properties(self, *args, **kwargs):
        self._refuse_when_locked("properties")
        return super().queue_plan_properties(*args, **kwargs)

    def queue_plan_items_delete(self, *args, **kwargs):
        self._refuse_when_locked("delete")
        return super().queue_plan_items_delete(*args, **kwargs)

    def queue_plan_items_paste(self, *args, **kwargs):
        self._refuse_when_locked("paste")
        return super().queue_plan_items_paste(*args, **kwargs)


class PlanViewActionHandlerLockedBidRefusalTests(_PlanViewActionHandlerFixture):
    """Decision P2: a SQL plan write refused with ActiveBidLockedError at submission
    (the Bid was locked after the UI allowed the edit) is a silent refusal, like the
    Access guarded command returning a failed result: no exception out of the Qt slot,
    no dialog, the optimistic preview and selection are restored exactly as for a
    rejected write, no pending marker or forward-mutation token is left behind, one
    warning is logged and the surface stays usable (the retry reaches the service)."""

    def setUp(self):
        super().setUp()
        for name in ("show_warning", "confirm"):
            patcher = patch.object(
                handler_module,
                name,
                side_effect=AssertionError(
                    "a locked-Bid refusal must not open a dialog"
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def _data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            area_uid="5",
            position=[0.0, 0.0],
        )
        return data

    def _handler(self, data=None, undo=None):
        data = self._data() if data is None else data
        plan_view = FakePlanView(data)
        write = _LockedBidWriteService()
        undo = FakeUndoService() if undo is None else undo
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo

    def _assert_state_freed(self, plan_view, undo):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(undo.count, 0)

    def test_a_refused_geometry_write_restores_the_preview_and_frees_the_state(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            handler.on_positions_flushed(changes, [])
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL plan geometry blocked: the active bid is locked"],
        )
        self.assertEqual(write.refused, ["geometry"])
        self.assertEqual(write.queued_geometry, [])
        self.assertEqual(plan_view.restored_positions, [(changes, [])])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)
        # The surface stays usable: once unlocked the same move is queued.
        write.locked = False
        handler.on_positions_flushed(changes, [])
        self.assertEqual(len(write.queued_geometry), 1)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})

    def test_a_refused_rotation_flush_restores_the_rotation_preview(self):
        handler, plan_view, write, undo = self._handler()
        rotations = [("t1", 0.0, 90.0)]
        with self.assertLogs(handler_module.logger, "WARNING"):
            handler.on_rotations_flushed(rotations)
        self.assertEqual(write.refused, ["geometry"])
        self.assertEqual(plan_view.restored_rotations, [rotations])
        self._assert_state_freed(plan_view, undo)

    def test_a_refused_geometry_write_ends_the_unconsumed_edit_lease(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
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
        self.assertEqual(plan_view.geometry_lease_granted, {"t1"})
        with self.assertLogs(handler_module.logger, "WARNING"):
            handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        # The handle left the handler when the write was prepared, so the refusal must
        # end it (a queued write would have consumed it).
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self._assert_state_freed(plan_view, undo)

    def test_a_refused_property_write_restores_the_state_for_every_entry_point(self):
        data = self._data()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        cases = (
            ("assign to area", lambda h: h.on_assign_to_area(["t1"])),
            ("reassign condition", lambda h: h.on_reassign_condition(["t1"], "c9")),
            ("set negative", lambda h: h.on_set_negative(["t1"], True)),
            (
                "condition text",
                lambda h: h.on_condition_text_properties_flushed(
                    [("t1", "label", {"Text": "a"}, {"Text": "b"})]
                ),
            ),
        )
        for name, act in cases:
            with self.subTest(entry=name):
                handler, plan_view, write, undo = self._handler(data)
                plan_view.selected = {"t1"}
                with self.assertLogs(handler_module.logger, "WARNING") as logged:
                    act(handler)
                self.assertEqual(len(logged.records), 1)
                self.assertIn("blocked: the active bid is locked", logged.output[0])
                self.assertEqual(write.refused, ["properties"])
                self.assertEqual(write.queued_properties, [])
                self.assertEqual(plan_view.selected, {"t1"})
                self._assert_state_freed(plan_view, undo)
                write.locked = False
                act(handler)
                self.assertEqual(len(write.queued_properties), 1)

    def test_a_refused_text_property_write_restores_the_edited_text(self):
        handler, plan_view, write, undo = self._handler()
        changes = [("t1", "label", {"Text": "a"}, {"Text": "b"})]
        with self.assertLogs(handler_module.logger, "WARNING"):
            handler.on_condition_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self._assert_state_freed(plan_view, undo)

    def test_a_refused_delete_restores_the_selection_and_frees_the_state(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            handler.on_elements_deleted(["t1"])
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL plan item delete blocked: the active bid is locked"],
        )
        self.assertEqual(write.refused, ["delete"])
        self.assertEqual(write.queued_deletes, [])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)
        write.locked = False
        handler.on_elements_deleted(["t1"])
        self.assertEqual(len(write.queued_deletes), 1)

    def test_a_refused_paste_restores_the_previous_selection(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        bid_ref = handler._ui_state.get_selected_bid_ref()
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            handler._queue_sql_plan_items_paste_payload(bid_ref, "p1", payload, ())
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL plan item paste blocked: the active bid is locked"],
        )
        self.assertEqual(write.refused, ["paste"])
        self.assertEqual(write.queued_pastes, [])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)
        write.locked = False
        handler._queue_sql_plan_items_paste_payload(bid_ref, "p1", payload, ())
        self.assertEqual(len(write.queued_pastes), 1)

    def test_a_refused_annotation_placement_leaves_no_forward_mutation(self):
        handler, plan_view, write, undo = self._handler()
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            handler.on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL annotation insert blocked: the active bid is locked"],
        )
        self.assertEqual(write.refused, ["paste"])
        self.assertEqual(write.queued_pastes, [])
        self._assert_state_freed(plan_view, undo)
        write.locked = False
        handler.on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self.assertEqual(len(write.queued_pastes), 1)

    def _cancelled_placement_cleanup(self, write):
        """Place on page 9, delete the preview while the placement is queued, then
        commit the placement as row 501: the handler queues the cleanup of 501."""
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write.cancel_queued_mutation_result = False
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        (pending_uid,) = list(data.takeoffs)
        handler.on_elements_deleted([pending_uid])
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="c1", page_uid="9", position=[1.0, 2.0])]
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
        return handler, plan_view, data, undo

    def test_a_cancelled_placement_cleanup_delete_is_allowed_on_a_locked_bid_silently(
        self,
    ):
        # Decision B5: the cleanup of a cancelled placement goes through the
        # exempt entry point, so a locked active Bid no longer refuses it (the SQL
        # writer exempts it too); no dialog, no warning, the provisional takeoff
        # is deleted.
        write = _LockedBidWriteService()
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            handler, plan_view, data, undo = self._cancelled_placement_cleanup(write)
        self.assertEqual(write.refused, [])
        self.assertEqual(len(write.cleanup_delete_calls), 1)
        database_id, bid_uid, takeoff_uids, options, callback = (
            write.cleanup_delete_calls[0]
        )
        self.assertEqual(
            (database_id, bid_uid, takeoff_uids), ("bid.mdb", "7", ["501"])
        )
        self.assertEqual(options["page_uids"], ("9",))
        self.assertEqual(
            options["dependency_resources"], (ResourceRef("condition", "c1", 7),)
        )
        self.assertEqual(write.queued_deletes[0][3], [])
        self.assertIn("501", plan_view.pending_mutation_uids)
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertNotIn("501", plan_view.pending_mutation_uids)
        self.assertEqual(write.refused, [])

    def test_the_cleanup_uses_the_exempt_entry_point_on_an_unlocked_bid_too(self):
        write = _LockedBidWriteService()
        write.locked = False
        handler, plan_view, data, undo = self._cancelled_placement_cleanup(write)
        self.assertEqual(len(write.cleanup_delete_calls), 1)
        self.assertEqual(write.cleanup_delete_calls[0][2], ["501"])
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.refused, [])

    def test_a_failed_cleanup_on_a_locked_bid_still_frees_the_pending_state_once(self):
        write = _LockedBidWriteService()
        handler, plan_view, data, undo = self._cancelled_placement_cleanup(write)
        callback = write.cleanup_delete_calls[0][-1]
        failure = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        callback(failure)
        callback(failure)
        self.assertNotIn("501", plan_view.pending_mutation_uids)
        self.assertEqual(len(write.cleanup_delete_calls), 1)

    def test_other_deletes_stay_refused_on_a_locked_bid_and_never_use_the_exempt_entry(
        self,
    ):
        write = _LockedBidWriteService()
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        with self.assertLogs(handler_module.logger, "WARNING"):
            handler.on_elements_deleted(["t1"])
        self.assertEqual(write.refused, ["delete"])
        self.assertEqual(write.queued_deletes, [])
        self.assertEqual(write.cleanup_delete_calls, [])

    def test_an_unlocked_user_delete_uses_the_plain_entry_not_the_exempt_one(self):
        handler, plan_view, write, undo = self._handler()
        write.locked = False
        plan_view.selected = {"t1"}
        handler.on_elements_deleted(["t1"])
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.cleanup_delete_calls, [])

    def test_a_locked_bid_placement_rejected_by_the_guard_is_not_cleaned_up(self):
        # Redo of a placement (queue_takeoff_placement) is the only other flow that
        # touches provisional rows: its guard rejection (REJECTED/bid_locked)
        # commits nothing, so there is nothing to clean up and no delete is queued.
        write = _LockedBidWriteService()
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        callback(
            replace(
                locked_bid_refusal_result("bid.mdb"),
                operation_id=operation_id,
                runtime_generation=3,
            )
        )
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(write.queued_deletes, [])
        self.assertEqual(write.cleanup_delete_calls, [])

    def test_the_real_service_queues_the_handlers_cleanup_on_a_locked_bid(self):
        # Chain: the handler's cleanup -> the REAL ProjectWriteService on a locked
        # active Bid: queued with the exempt flag instead of ActiveBidLockedError,
        # while the generic delete of the same rows is refused.
        from tests.application.services.test_project_write_service import _Harness

        harness = _Harness()
        harness.data.locked = True
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        handler = self._paste_handler(
            plan_view=plan_view,
            write=harness.service,
            data=data,
            undo=FakeUndoService(),
        )
        spec = InsertTakeoffSpec("10", "20", "0", [1.0, 2.0])
        pending = handler_module._PendingTakeoffPlacement(
            database_id=_Harness.DATABASE,
            bid_uid="7",
            pending_uids=("pending-1",),
            specs=(spec,),
            page_identities=(),
            page_scales={},
            selection_revision=0,
            tool_revision=0,
            runtime_generation=3,
        )
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            handler._queue_cancelled_takeoff_placement_delete(pending, ["30"], [spec])
        queued, execute, _callback = harness.provider.requests[-1]
        execute()
        self.assertIs(harness.executor.requests[-1].bid_lock_exempt, True)
        self.assertEqual(queued.payload.takeoff_uids, ("30",))
        with self.assertRaises(ActiveBidLockedError):
            harness.service.queue_plan_items_delete(
                _Harness.DATABASE, "7", ["30"], [], lambda _result: None
            )

    def test_only_the_cancelled_placement_cleanup_calls_the_exempt_entry_point(self):
        import ast

        root = Path(__file__).resolve().parents[3] / "ost_visualizer"
        callers = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(function):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "queue_cancelled_placement_cleanup_delete"
                    ):
                        callers.append(
                            (path.relative_to(root.parent).as_posix(), function.name)
                        )
        self.assertEqual(
            sorted(set(callers)),
            [
                (
                    "ost_visualizer/presentation/handlers/plan_view_action_handler.py",
                    "_queue_cancelled_takeoff_placement_delete",
                )
            ],
        )

    def test_an_undo_replay_refused_by_the_lock_keeps_the_entry_replayable(self):
        history = UndoRedoService()
        history.set_active_bid(BidRef("bid.mdb", "7"))
        handler, plan_view, write, _undo = self._handler(undo=history)
        write.locked = False
        handler.on_set_negative(["t1"], True)
        callback = write.queued_properties[0][-1]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertTrue(history.can_undo())
        write.locked = True
        with self.assertLogs(history.logger, "WARNING") as logged:
            history.undo()
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["History mutation blocked: the active bid is locked"],
        )
        self.assertEqual(write.refused, ["properties"])
        self.assertEqual(len(write.queued_properties), 1)
        self.assertTrue(history.can_undo())
        write.locked = False
        history.undo()
        self.assertEqual(len(write.queued_properties), 2)


def _writer_bid_locked_rejection(operation_id=None, database_id="bid.mdb"):
    from ost_visualizer.application.dtos.collaboration_dtos import (
        BID_LOCKED_MESSAGE,
        MutationRejectionReason,
    )

    return QueuedMutationResult(
        database_id=database_id,
        runtime_generation=3,
        operation_id=operation_id or str(uuid.uuid4()),
        outcome_status=MutationOutcomeStatus.REJECTED,
        message=BID_LOCKED_MESSAGE,
        rejection_reason=MutationRejectionReason.BID_LOCKED,
    )


class PlanViewActionHandlerBidLockedRejectionTests(_PlanViewActionHandlerFixture):
    """Decision B4 at the plan-view handler: a queued SQL plan write that the SQL
    writer refused with REJECTED / bid_locked (it was queued before another client
    locked the Bid) is handled exactly like the queue-time refusal (P2), which feeds
    the very same completion with locked_bid_refusal_result: the optimistic preview,
    selection and pending marker are restored, the forward-mutation token is freed,
    no history entry is pushed, no dialog opens, the handler logs nothing itself (the
    coordinator's BID_LOCKED_REJECTION hook logs the one warning and re-resolves the
    lock) and a second delivery of the same result changes nothing. Real handler;
    the write service, plan view, project data and undo service are the fakes of this
    module (the real undo service is used for the replay test)."""

    def setUp(self):
        super().setUp()
        for name in ("show_warning", "confirm"):
            patcher = patch.object(
                handler_module,
                name,
                side_effect=AssertionError(
                    "a bid-locked rejection must not open a dialog"
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def _data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            area_uid="5",
            position=[0.0, 0.0],
        )
        return data

    def _handler(self, data=None, undo=None):
        data = self._data() if data is None else data
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService() if undo is None else undo
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo

    def _deliver_twice(self, callback):
        result = _writer_bid_locked_rejection()
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            callback(result)
            callback(result)

    def _assert_state_freed(self, plan_view, undo):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(undo.count, 0)

    def test_a_rejected_geometry_write_restores_the_preview_once(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        changes = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler.on_positions_flushed(changes, [])
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(plan_view.restored_positions, [])
        self._deliver_twice(write.queued_geometry[0][-1])
        self.assertEqual(plan_view.restored_positions, [(changes, [])])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_rotation_flush_restores_the_rotation_preview_once(self):
        handler, plan_view, write, undo = self._handler()
        rotations = [("t1", 0.0, 90.0)]
        handler.on_rotations_flushed(rotations)
        self.assertEqual(plan_view.restored_rotations, [])
        self._deliver_twice(write.queued_geometry[0][-1])
        self.assertEqual(plan_view.restored_rotations, [rotations])
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_geometry_write_does_not_end_the_already_consumed_lease(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
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
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        # the queued write took the handle over; the coordinator consumes it when it
        # rejects the write, so the handler neither keeps nor ends it again
        self.assertIs(write.queued_geometry[0][2]["edit_lease_handle"], handle)
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self._deliver_twice(write.queued_geometry[0][-1])
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_property_write_restores_the_state_for_every_entry_point(self):
        data = self._data()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        cases = (
            ("assign to area", lambda h: h.on_assign_to_area(["t1"])),
            ("reassign condition", lambda h: h.on_reassign_condition(["t1"], "c9")),
            ("set negative", lambda h: h.on_set_negative(["t1"], True)),
            (
                "condition text",
                lambda h: h.on_condition_text_properties_flushed(
                    [("t1", "label", {"Text": "a"}, {"Text": "b"})]
                ),
            ),
        )
        for name, act in cases:
            with self.subTest(entry=name):
                handler, plan_view, write, undo = self._handler(data)
                plan_view.selected = {"t1"}
                act(handler)
                self.assertEqual(len(write.queued_properties), 1)
                self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
                # the optimistic edit left the selection cleared (without a new
                # selection revision): the failure puts the prior selection back
                plan_view.selected = set()
                self._deliver_twice(write.queued_properties[0][-1])
                self.assertEqual(plan_view.selected, {"t1"})
                self._assert_state_freed(plan_view, undo)
                self.assertEqual(len(write.queued_properties), 1)

    def test_a_rejected_text_property_write_restores_the_edited_text_once(self):
        handler, plan_view, write, undo = self._handler()
        changes = [("t1", "label", {"Text": "a"}, {"Text": "b"})]
        handler.on_condition_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_condition_text_properties, [])
        self._deliver_twice(write.queued_properties[0][-1])
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_delete_restores_the_selection_and_frees_the_state(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        handler.on_elements_deleted(["t1"])
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(plan_view.selected, set())
        self._deliver_twice(write.queued_deletes[0][-1])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)
        self.assertEqual(len(write.queued_deletes), 1)

    def test_a_rejected_paste_restores_the_previous_selection(self):
        handler, plan_view, write, undo = self._handler()
        plan_view.selected = {"t1"}
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        bid_ref = handler._ui_state.get_selected_bid_ref()
        handler._queue_sql_plan_items_paste_payload(bid_ref, "p1", payload, ())
        self.assertEqual(len(write.queued_pastes), 1)
        self._deliver_twice(write.queued_pastes[0][-1])
        self.assertEqual(plan_view.selected, {"t1"})
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_annotation_placement_leaves_no_forward_mutation(self):
        handler, plan_view, write, undo = self._handler()
        handler.on_annotation_created("line", [0.0, 0.0, 5.0, 5.0], "p1")
        self.assertEqual(len(write.queued_pastes), 1)
        self._deliver_twice(write.queued_pastes[0][-1])
        self._assert_state_freed(plan_view, undo)

    def test_a_rejected_takeoff_placement_removes_the_preview_without_a_warning(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        self.assertEqual(len(data.takeoffs), 1)
        self.assertEqual(len(plan_view.pending_mutation_uids), 1)
        result = _writer_bid_locked_rejection(operation_id)
        # the placement's own failure log is replaced by the coordinator's hook
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            callback(result)
            callback(result)
        self.assertEqual(data.takeoffs, {})
        self._assert_state_freed(plan_view, undo)
        self.assertEqual(write.queued_deletes, [])
        self.assertEqual(write.cleanup_delete_calls, [])

    def test_a_placement_rejected_for_another_reason_still_logs_its_failure(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        plain = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=operation_id,
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="busy",
        )
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            callback(plain)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL takeoff placement failed: busy"],
        )
        self.assertEqual(data.takeoffs, {})

    def test_a_rejected_history_replay_keeps_the_entry_ready_and_replayable(self):
        history = UndoRedoService()
        history.set_active_bid(BidRef("bid.mdb", "7"))
        conflicts = []
        handler, plan_view, write, _undo = self._handler(undo=history)
        handler._event_bus.publish = lambda event, **payload: conflicts.append(event)
        handler.on_set_negative(["t1"], True)
        write.queued_properties[0][-1](
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertTrue(history.can_undo())
        history.undo()
        self.assertEqual(len(write.queued_properties), 2)
        self.assertFalse(history.can_undo())
        with self.assertNoLogs(history.logger, "WARNING"):
            write.queued_properties[1][-1](_writer_bid_locked_rejection())
        # READY again: the same entry can be replayed (not CONFLICTED, not consumed)
        self.assertTrue(history.can_undo())
        self.assertFalse(history.can_redo())
        entry = history._undo_stack[-1]
        self.assertEqual(entry.state.name, "READY")
        history.undo()
        self.assertEqual(len(write.queued_properties), 3)
        self.assertNotIn(AppEvents.SYNCHRONIZATION_CONFLICT, conflicts)


def _committed(
    operation_id=None, created=(), maps=None, database_id="bid.mdb", generation=1
):
    return QueuedMutationResult(
        database_id=database_id,
        runtime_generation=generation,
        operation_id=operation_id or str(uuid.uuid4()),
        outcome_status=MutationOutcomeStatus.COMMITTED,
        created_resource_ids=tuple(created),
        authoritative_result=(
            AuthoritativeMutationResult(created_uid_maps=maps)
            if maps is not None
            else None
        ),
    )


def _failed(status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT, operation_id=None):
    return QueuedMutationResult(
        database_id="bid.mdb",
        runtime_generation=1,
        operation_id=operation_id or str(uuid.uuid4()),
        outcome_status=status,
    )


class PlanViewActionHandlerToolRevisionGuardTests(_PlanViewActionHandlerFixture):
    """Stale SQL completions must never act on a newer Tool intent: the tool revision
    captured at submission is compared again at completion (the FakePlanView keeps
    tool_revision as a plain attribute that the tests bump)."""

    def _placement_handler(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, data, plan_view, write, undo

    def test_a_placement_completed_after_a_tool_change_does_not_select_its_takeoff(
        self,
    ):
        for bump, expected_selection in ((False, {"501"}), (True, set())):
            with self.subTest(tool_changed=bump):
                handler, data, plan_view, write, undo = self._placement_handler()
                handler.on_takeoff_created("42", [1.0, 2.0], "9")
                operation_id, callback = write.queued_takeoff_callbacks[0]
                if bump:
                    plan_view.tool_revision += 1
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
                self.assertEqual(plan_view.selected, expected_selection)
                self.assertEqual(undo.count, 1)
                self.assertEqual(undo.forward_mutations, [])

    def test_an_annotation_completed_after_a_tool_change_keeps_the_new_tool(self):
        for bump, expected_tools in ((False, ["text"]), (True, [])):
            with self.subTest(tool_changed=bump):
                data = FakeProjectData()
                plan_view = FakePlanView(data)
                plan_view.annotation_key_map = {
                    ("annotation-1", "text"): "annotation-1_text"
                }
                write = FakeWriteService()
                write.sql_collaboration_mutations = True
                handler = self._paste_handler(
                    plan_view=plan_view, write=write, data=data
                )
                handler.on_text_annotation_created(
                    [1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Delayed"}
                )
                payload = write.queued_pastes[0][1]
                if bump:
                    plan_view.tool_revision += 1
                write.queued_pastes[0][3](
                    _committed(
                        maps=(
                            (
                                "annotations",
                                ((payload.annotation_source_uids[0], "annotation-1"),),
                            ),
                        )
                    )
                )
                self.assertEqual(plan_view.activated_annotations, expected_tools)
                self.assertEqual(plan_view.selected, {"annotation-1_text"})

    def _cleanup_failure_handler(self):
        """A single-spec placement whose preview was deleted while it executed: the
        commit queues the cleanup delete of row 501; returns its terminal callback."""
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        (pending_uid,) = list(data.takeoffs)
        handler.on_elements_deleted([pending_uid])
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
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
        return handler, data, plan_view, write, write.cleanup_delete_calls[0][-1]

    def test_a_failed_cleanup_of_a_cancelled_placement_reselects_the_row_it_could_not_delete(
        self,
    ):
        handler, data, plan_view, write, cleanup = self._cleanup_failure_handler()
        self.assertEqual(plan_view.selected, set())
        self.assertIn("501", plan_view.pending_mutation_uids)
        cleanup(_failed())
        self.assertEqual(plan_view.selected, {"501"})
        self.assertNotIn("501", plan_view.pending_mutation_uids)

    def test_a_failed_cleanup_does_not_reselect_after_a_tool_change(self):
        handler, data, plan_view, write, cleanup = self._cleanup_failure_handler()
        plan_view.tool_revision += 1
        cleanup(_failed())
        self.assertEqual(plan_view.selected, set())
        self.assertNotIn("501", plan_view.pending_mutation_uids)

    def test_a_failed_cleanup_does_not_reselect_after_a_newer_selection(self):
        handler, data, plan_view, write, cleanup = self._cleanup_failure_handler()
        plan_view.set_selected_uids({"user-choice"})
        cleanup(_failed())
        self.assertEqual(plan_view.selected, {"user-choice"})

    def test_a_failed_cleanup_does_not_reselect_after_a_bid_switch(self):
        handler, data, plan_view, write, cleanup = self._cleanup_failure_handler()
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        cleanup(_failed())
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})


class PlanViewActionHandlerPendingStateProjectionTests(_PlanViewActionHandlerFixture):
    """Pending markers are keyed by BidRef, published with the Bid identity and only
    projected into a live plan view of the active Bid."""

    def _handler(self):
        data = FakeProjectData()
        for uid in ("t1", "t2"):
            data.takeoffs[uid] = Takeoff(
                uid=uid, condition_uid="c1", page_uid="p1", is_negative=False
            )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        return handler, plan_view, write, data

    def test_pending_changes_are_published_with_the_bid_identity_and_the_flag(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_set_negative(["t2", "t1"], True)
        pending_event = AppEvents.PENDING_PLAN_MUTATIONS_CHANGED
        self.assertEqual(
            handler._event_bus.events,
            [
                (
                    pending_event,
                    {
                        "database_id": "bid.mdb",
                        "bid_uid": "7",
                        "takeoff_uids": ["t1", "t2"],
                        "pending": True,
                    },
                )
            ],
        )
        write.queued_properties[0][-1](_failed())
        self.assertEqual(
            handler._event_bus.events[1],
            (
                pending_event,
                {
                    "database_id": "bid.mdb",
                    "bid_uid": "7",
                    "takeoff_uids": ["t1", "t2"],
                    "pending": False,
                },
            ),
        )
        self.assertEqual(len(handler._event_bus.events), 2)

    def test_an_annotation_edit_publishes_no_takeoff_uids_but_marks_the_view(self):
        data = FakeProjectData()
        annotation = BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.annotations = {"a1_rect": annotation}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_annotation_styles_flushed(
            [("a1", "rect", {"Width": 4.0}, {"Width": 7.0})]
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"a1_rect"})
        self.assertEqual(
            handler._event_bus.events,
            [
                (
                    AppEvents.PENDING_PLAN_MUTATIONS_CHANGED,
                    {
                        "database_id": "bid.mdb",
                        "bid_uid": "7",
                        "takeoff_uids": [],
                        "pending": True,
                    },
                )
            ],
        )

    def test_pending_markers_of_another_bid_never_leak_into_the_active_plan(self):
        handler, plan_view, write, _data = self._handler()
        selected = [BidRef("bid.mdb", "7")]
        handler._ui_state = SimpleNamespace(
            active_page_uid="p1", get_selected_bid_ref=lambda: selected[0]
        )
        handler.on_set_negative(["t1"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        selected[0] = BidRef("bid.mdb", "8")
        plan_view.set_pending_mutation_uids(set())
        handler.on_set_negative(["t2"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"t2"})
        self.assertEqual(
            handler._pending_plan_takeoff_uids_by_bid,
            {BidRef("bid.mdb", "7"): {"t1"}, BidRef("bid.mdb", "8"): {"t2"}},
        )
        write.queued_properties[0][-1](_failed())
        self.assertEqual(plan_view.pending_mutation_uids, {"t2"})
        self.assertEqual(
            handler._pending_plan_takeoff_uids_by_bid, {BidRef("bid.mdb", "8"): {"t2"}}
        )
        self.assertEqual(handler._pending_plan_annotations_by_bid, {})

    def test_a_plan_that_is_cleaning_up_still_gets_the_event_but_no_projection(self):
        handler, plan_view, _write, _data = self._handler()
        plan_view._is_cleaning_up = True
        handler.on_set_negative(["t1"], True)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(len(handler._event_bus.events), 1)

    def test_a_destroyed_native_plan_is_never_marked(self):
        from shiboken6 import delete

        plan = QtWidgets.QWidget()
        marked = []
        plan._is_cleaning_up = False
        plan.set_pending_mutation_uids = marked.append
        plan.find_annotation_keys_by_uid_type = lambda identities: set()
        handler, _plan_view, _write, _data = self._handler()
        handler._plan_view = plan
        bid_ref = BidRef("bid.mdb", "7")
        handler._set_plan_items_pending(bid_ref, {"t1"}, {"t1"}, True)
        self.assertEqual(marked, [{"t1"}])
        delete(plan)
        handler._set_plan_items_pending(bid_ref, {"t1"}, {"t1"}, False)
        self.assertEqual(marked, [{"t1"}])
        self.assertEqual(len(handler._event_bus.events), 2)


class PlanViewActionHandlerGeometryLeaseLifecycleTests(_PlanViewActionHandlerFixture):
    """Late, superseded and obsolete geometry edit leases; the lease follows the
    selection, the access right and authoritative refreshes."""

    def _handler(self):
        data = FakeProjectData()
        for uid, x in (("t1", 0.0), ("t2", 5.0)):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="c1" if uid == "t1" else "c2",
                page_uid="p1",
                position=[x, 0.0],
                parent_uid="t1" if uid == "t2" else "0",
            )
        annotation = BidAnnotation(
            uid="a1", annotation_type="rect", page_uid="p1", layer_uid="L1"
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_rect": annotation}
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        return handler, plan_view, write, data

    @staticmethod
    def _grant(write, index=-1, draft="draft-1"):
        database_id, resources, dependencies, options, callback = (
            write.edit_lease_requests[index]
        )
        handle = EditLeaseHandle(
            database_id=database_id,
            draft_id=draft,
            runtime_generation=3,
            operation_id=options["operation_id"],
            owning_surface="main-plan",
            resources=resources,
            dependency_resources=dependencies,
            locks=tuple(
                ResourceLock(database_id, resource, f"lock-{i}")
                for i, resource in enumerate(resources)
            ),
        )
        return handle, callback

    def test_a_selected_parent_leases_its_children_and_every_dependency_sorted(self):
        handler, plan_view, write, _data = self._handler()
        plan_view.selected = {"t1", "a1_rect"}
        handler.on_geometry_edit_lease_requested(["t1", "a1_rect"])
        _db, resources, dependencies, _options, _callback = write.edit_lease_requests[0]
        self.assertEqual(
            set(resources),
            {
                ResourceRef("takeoff", "t1", 7),
                ResourceRef("takeoff", "t2", 7),
                ResourceRef("annotation", "rect/a1", 7),
            },
        )
        self.assertEqual(
            set(dependencies),
            {
                ResourceRef("page", "p1", 7),
                ResourceRef("condition", "c1", 7),
                ResourceRef("condition", "c2", 7),
                ResourceRef("layer", "L1", 7),
            },
        )
        self.assertEqual(resources, tuple(sorted(resources)))
        self.assertEqual(dependencies, tuple(sorted(dependencies)))

    def test_a_lease_granted_after_the_handler_is_gone_is_still_ended(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        reference = weakref.ref(handler)
        del handler
        self.assertIsNone(reference())
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        callback(EditLeaseResult(False))
        self.assertEqual(write.ended_edit_leases, [handle])

    def test_a_superseded_request_ends_its_late_grant_and_keeps_the_newer_state(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        stale_handle, stale_callback = self._grant(write, 0, "stale")
        handler.on_plan_item_selection_changed([])
        self.assertEqual(plan_view.geometry_lease_pending, set())
        plan_view.selected = {"t2"}
        handler.on_geometry_edit_lease_requested(["t2"])
        self.assertEqual(len(write.edit_lease_requests), 2)
        stale_callback(EditLeaseResult(True, handle=stale_handle))
        self.assertEqual(write.ended_edit_leases, [stale_handle])
        self.assertEqual(plan_view.geometry_lease_pending, {"t2"})
        self.assertIsNone(handler._geometry_edit_lease_handle)
        fresh_handle, fresh_callback = self._grant(write, 1, "fresh")
        fresh_callback(EditLeaseResult(True, handle=fresh_handle))
        self.assertIs(handler._geometry_edit_lease_handle, fresh_handle)
        self.assertEqual(plan_view.geometry_lease_granted, {"t2"})
        self.assertEqual(write.ended_edit_leases, [stale_handle])

    def test_a_grant_for_a_selection_that_changed_meanwhile_is_ended_and_unmarked(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        plan_view.selected = {"t2"}
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(plan_view.geometry_lease_pending, set())
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertEqual(handler._geometry_edit_lease_selection, set())
        self.assertIsNone(handler._geometry_edit_lease_handle)

    def test_a_repeated_request_for_the_granted_selection_reuses_the_lease(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        plan_view.geometry_lease_granted = set()
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(len(write.edit_lease_requests), 1)
        self.assertEqual(plan_view.geometry_lease_granted, {"t1"})
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIs(handler._geometry_edit_lease_handle, handle)

    def test_a_request_for_other_resources_replaces_the_granted_lease(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        plan_view.selected = {"a1_rect"}
        handler.on_geometry_edit_lease_requested(["a1_rect"])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(len(write.edit_lease_requests), 2)
        self.assertEqual(plan_view.geometry_lease_pending, {"a1_rect"})
        self.assertIsNone(handler._geometry_edit_lease_handle)

    def test_a_geometry_write_on_other_resources_ends_the_lease_and_queues_without_it(
        self,
    ):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        handler.on_positions_flushed([("t2", [5.0, 0.0], [6.0, 0.0])], [])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(write.queued_geometry[0][2]["edit_lease_handle"])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_an_authoritative_refresh_ends_the_lease_and_prepares_the_plan(self):
        handler, plan_view, write, _data = self._handler()
        prepared = []
        plan_view.prepare_for_authoritative_refresh = lambda: prepared.append(True)
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        handler.prepare_for_authoritative_refresh()
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(prepared, [True])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertEqual(handler._geometry_edit_lease_selection, set())
        self.assertEqual(handler._geometry_edit_lease_request_id, "")

    def test_only_losing_the_edit_right_ends_the_lease(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        handler.reconcile_geometry_edit_access(True)
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIs(handler._geometry_edit_lease_handle, handle)
        handler.reconcile_geometry_edit_access(False)
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)


class PlanViewActionHandlerForwardMutationHistoryTests(_PlanViewActionHandlerFixture):
    """REAL UndoRedoService behind the handler: a forward SQL mutation records history
    only if its original history generation is still valid when it commits, history
    keeps submission order whatever the completion order, and an accepted forward
    mutation blocks undo/redo until it is terminal."""

    def _setup(self):
        data = FakeProjectData()
        for uid in ("t1", "t2"):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="c1",
                page_uid="p1",
                position=[0.0, 0.0],
                is_negative=False,
            )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = UndoRedoService()
        undo.set_active_bid(BidRef("bid.mdb", "7"))
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def _flows(self, handler, plan_view, write, data):
        def geometry():
            handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
            callback = write.queued_geometry[-1][-1]
            return lambda: callback(_committed())

        def properties():
            handler.on_set_negative(["t1"], True)
            callback = write.queued_properties[-1][-1]
            return lambda: callback(_committed())

        def delete():
            handler.on_elements_deleted(["t1"])
            callback = write.queued_deletes[-1][-1]
            return lambda: callback(_committed())

        def paste():
            handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
            handler.on_paste_requested()
            callback = write.queued_pastes[-1][-1]
            return lambda: callback(
                _committed(maps=(("takeoffs", (("source", "new-1"),)),))
            )

        def annotation():
            handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
            payload, callback = write.queued_pastes[-1][1], write.queued_pastes[-1][-1]
            return lambda: callback(
                _committed(
                    maps=(
                        (
                            "annotations",
                            ((payload.annotation_source_uids[0], "annotation-1"),),
                        ),
                    )
                )
            )

        def placement():
            handler.on_takeoff_created("42", [1.0, 2.0], "p1")
            operation_id, callback = write.queued_takeoff_callbacks[-1]

            def deliver():
                data.add_takeoffs(
                    [
                        Takeoff(
                            uid="501",
                            condition_uid="42",
                            page_uid="p1",
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

            return deliver

        return {
            "geometry": geometry,
            "properties": properties,
            "delete": delete,
            "paste": paste,
            "annotation": annotation,
            "placement": placement,
        }

    def test_a_forward_completion_records_history_only_if_its_generation_is_current(
        self,
    ):
        for name in (
            "geometry",
            "properties",
            "delete",
            "paste",
            "annotation",
            "placement",
        ):
            for cleared in (False, True):
                with self.subTest(flow=name, history_cleared_meanwhile=cleared):
                    handler, plan_view, write, data, undo = self._setup()
                    deliver = self._flows(handler, plan_view, write, data)[name]()
                    self.assertFalse(undo.can_undo())
                    if cleared:
                        undo.clear()
                    deliver()
                    self.assertEqual(undo.can_undo(), not cleared)
                    self.assertFalse(undo.can_redo())

    def test_history_keeps_submission_order_when_the_completions_arrive_reversed(self):
        handler, plan_view, write, _data, undo = self._setup()
        handler.on_set_negative(["t1"], True)
        handler.on_set_negative(["t2"], True)
        first, second = write.queued_properties[0][-1], write.queued_properties[1][-1]
        second(_committed())
        self.assertFalse(undo.can_undo())
        first(_committed())
        self.assertTrue(undo.can_undo())
        undo.undo()
        self.assertEqual(write.queued_properties[2][3], [("t2", False)])
        write.queued_properties[2][-1](_committed())
        undo.undo()
        self.assertEqual(write.queued_properties[3][3], [("t1", False)])

    def test_an_accepted_forward_mutation_blocks_redo_until_it_is_terminal(self):
        handler, plan_view, write, _data, undo = self._setup()
        handler.on_set_negative(["t1"], True)
        write.queued_properties[0][-1](_committed())
        undo.undo()
        write.queued_properties[1][-1](_committed())
        self.assertTrue(undo.can_redo())
        handler.on_set_negative(["t2"], True)
        self.assertFalse(undo.can_redo())
        undo.redo()
        self.assertEqual(len(write.queued_properties), 3)
        write.queued_properties[2][-1](_committed())
        self.assertFalse(undo.can_redo())
        self.assertTrue(undo.can_undo())


class PlanViewActionHandlerDuplicateCommittedDeliveryTests(
    _PlanViewActionHandlerFixture
):
    """A COMMITTED result delivered a second time (recovery after an uncertain commit
    repeats it) must not touch the state of a NEWER operation on the same items: the
    handler remembers the operation ids it already applied."""

    def _setup(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_a_duplicate_committed_geometry_result_keeps_the_newer_move_pending(self):
        handler, plan_view, write, _data, undo = self._setup()
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        result = _committed()
        write.queued_geometry[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 1)
        handler.on_positions_flushed([("t1", [5.0, 6.0], [7.0, 8.0])], [])
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        events_before = len(handler._event_bus.events)
        write.queued_geometry[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(len(handler._event_bus.events), events_before)
        self.assertEqual(undo.count, 1)
        self.assertEqual(len(undo.forward_mutations), 1)

    def test_a_duplicate_committed_delete_result_keeps_the_newer_delete_pending(self):
        handler, plan_view, write, _data, undo = self._setup()
        handler.on_elements_deleted(["t1"])
        result = _committed()
        write.queued_deletes[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.count, 1)
        handler.on_elements_deleted(["t1"])
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        write.queued_deletes[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(undo.count, 1)

    def test_a_duplicate_committed_paste_result_does_not_select_again(self):
        handler, plan_view, write, _data, undo = self._setup()
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(
            BidRef("bid.mdb", "7"), "p1", payload, ()
        )
        result = _committed(maps=(("takeoffs", (("source", "new-1"),)),))
        write.queued_pastes[0][-1](result)
        self.assertEqual(plan_view.selected, {"new-1"})
        self.assertEqual(undo.count, 1)
        plan_view.selected = set()
        write.queued_pastes[0][-1](result)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 1)

    def test_a_duplicate_committed_annotation_insert_does_not_reactivate_the_tool(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("annotation-1", "text"): "annotation-1_text"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Delayed"}
        )
        payload, callback = write.queued_pastes[0][1], write.queued_pastes[0][3]
        result = _committed(
            maps=(
                ("annotations", ((payload.annotation_source_uids[0], "annotation-1"),)),
            )
        )
        callback(result)
        self.assertEqual(plan_view.activated_annotations, ["text"])
        callback(result)
        self.assertEqual(plan_view.activated_annotations, ["text"])
        self.assertEqual(undo.count, 1)

    def test_a_duplicate_committed_property_result_keeps_the_newer_edit_pending(self):
        handler, plan_view, write, _data, undo = self._setup()
        handler.on_set_negative(["t1"], True)
        result = _committed()
        write.queued_properties[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        handler.on_set_negative(["t1"], False)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        write.queued_properties[0][-1](result)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(undo.count, 1)

    def test_a_duplicate_committed_cleanup_result_keeps_the_newer_move_pending(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        (pending_uid,) = list(data.takeoffs)
        handler.on_elements_deleted([pending_uid])
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
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
        cleanup = write.cleanup_delete_calls[0][-1]
        result = _committed()
        cleanup(result)
        self.assertNotIn("501", plan_view.pending_mutation_uids)
        handler.on_positions_flushed([("501", [1.0, 2.0], [5.0, 6.0])], [])
        self.assertIn("501", plan_view.pending_mutation_uids)
        cleanup(result)
        self.assertIn("501", plan_view.pending_mutation_uids)

    def test_a_duplicate_committed_placement_result_does_not_duplicate_history(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            created_resource_ids=("501",),
        )
        callback(result)
        self.assertEqual(handler._completed_sql_mutation_ids, {operation_id})
        self.assertEqual(plan_view.selected, {"501"})
        plan_view.selected = set()
        callback(result)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 1)


class PlanViewActionHandlerPageIdentityTests(_PlanViewActionHandlerFixture):
    """Typed Page-scoped lifetime: a Page is identified by its object, and a capture
    that lost a Page (unknown uid at submission) can never be continued."""

    def test_a_capture_that_lost_a_page_is_never_current(self):
        data = FakeProjectData()
        handler = self._paste_handler(data=data)
        captured = handler._capture_page_identities(("p1", "ghost", "p1"))
        self.assertEqual(captured, (("p1", data.pages["p1"]),))
        self.assertTrue(handler._page_identities_are_current(("p1",), captured))
        self.assertFalse(
            handler._page_identities_are_current(("p1", "ghost"), captured)
        )
        self.assertTrue(handler._page_identities_are_current((), ()))
        data.pages["p1"] = SimpleNamespace(uid="p1")
        self.assertFalse(handler._page_identities_are_current(("p1",), captured))

    def test_a_failed_move_on_an_unknown_page_is_not_restored_into_the_plan(self):
        data = FakeProjectData()
        data.takeoffs["t9"] = Takeoff(
            uid="t9", condition_uid="c1", page_uid="ghost", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "ghost"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_positions_flushed([("t9", [0.0, 0.0], [5.0, 6.0])], [])
        write.queued_geometry[0][-1](_failed())
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())


class _SignalRecorder:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


_PLAN_VIEW_SIGNAL_SLOTS = {
    "assign_to_area_requested": "on_assign_to_area",
    "reassign_condition_requested": "on_reassign_condition",
    "set_negative_requested": "on_set_negative",
    "set_curved_requested": "on_set_curved",
    "positions_flushed": "on_positions_flushed",
    "annotation_text_properties_flushed": "on_annotation_text_properties_flushed",
    "annotation_styles_flushed": "on_annotation_styles_flushed",
    "condition_text_properties_flushed": "on_condition_text_properties_flushed",
    "rotations_flushed": "on_rotations_flushed",
    "group_rotation_flushed": "on_group_rotation_flushed",
    "takeoff_created": "on_takeoff_created",
    "annotation_created": "on_annotation_created",
    "text_annotation_created": "on_text_annotation_created",
    "named_view_created": "on_named_view_created",
    "hotlink_placement_requested": "on_hotlink_placement_requested",
    "hole_created": "on_hole_created",
    "elements_deleted": "on_elements_deleted",
    "copy_requested": "on_copy_requested",
    "paste_requested": "on_paste_requested",
    "paste_backouts_placed": "on_paste_backouts_placed",
    "geometry_edit_lease_requested": "on_geometry_edit_lease_requested",
    "plan_item_selection_changed": "on_plan_item_selection_changed",
}


class PlanViewActionHandlerSignalWiringTests(_PlanViewActionHandlerFixture):
    """connect_signals routes each plan view signal to exactly one handler entry
    point; a dropped or crossed connection silently disables an editing gesture."""

    def test_every_plan_view_signal_is_routed_to_its_entry_point_once(self):
        signals = {name: _SignalRecorder() for name in _PLAN_VIEW_SIGNAL_SLOTS}
        signals["undo_requested"] = _SignalRecorder()
        signals["redo_requested"] = _SignalRecorder()
        plan_view = SimpleNamespace(**signals)
        saved_handlers = []
        validators = []
        plan_view.set_overlay_rect_save_handler = saved_handlers.append
        plan_view.set_named_view_name_validator = validators.append
        undo = FakeUndoService()
        undo.undo = lambda: None
        undo.redo = lambda: None
        handler = self._paste_handler(plan_view=FakePlanView(), undo=undo)
        handler._plan_view = plan_view
        handler.connect_signals()
        for name, slot_name in _PLAN_VIEW_SIGNAL_SLOTS.items():
            with self.subTest(signal=name):
                self.assertEqual(signals[name].slots, [getattr(handler, slot_name)])
        self.assertEqual(signals["undo_requested"].slots, [undo.undo])
        self.assertEqual(signals["redo_requested"].slots, [undo.redo])
        self.assertEqual(saved_handlers, [handler.save_current_page_overlay_rect])
        self.assertEqual(validators, [handler._validate_named_view_name])

    def test_the_plan_view_declares_every_signal_the_handler_connects(self):
        from ost_visualizer.presentation.components.plan_view.view import (
            TakeoffPlanView,
        )

        for name in (*_PLAN_VIEW_SIGNAL_SLOTS, "undo_requested", "redo_requested"):
            with self.subTest(signal=name):
                self.assertIsInstance(getattr(TakeoffPlanView, name), QtCore.Signal)


class PlanViewActionHandlerSelectionRestoreTests(_PlanViewActionHandlerFixture):
    """What a failed SQL write puts back into the selection, by typed identity."""

    def test_a_key_that_is_a_takeoff_is_not_also_remembered_as_an_annotation(self):
        data = FakeProjectData()
        data.takeoffs["shared"] = Takeoff(
            uid="shared", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        annotation = BidAnnotation(uid="shared", annotation_type="text", page_uid="p1")
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"shared": annotation, "shared_text": annotation}
        plan_view.annotation_key_map = {("shared", "text"): "shared_text"}
        plan_view.selected = {"shared"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(
            BidRef("bid.mdb", "7"), "p1", payload, ()
        )
        self.assertEqual(plan_view.selected, set())
        write.queued_pastes[0][-1](_failed())
        self.assertEqual(plan_view.selected, {"shared"})

    def test_a_failed_edit_does_not_clear_the_selection_when_its_items_are_gone(self):
        data = FakeProjectData()
        annotation = BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_rect": annotation}
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.selected = {"a1_rect"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_annotation_styles_flushed(
            [("a1", "rect", {"Width": 4.0}, {"Width": 7.0})]
        )
        plan_view.annotation_key_map = {}
        write.queued_properties[0][-1](_failed())
        self.assertEqual(
            plan_view.restored_annotation_styles,
            [[("a1", "rect", {"Width": 4.0}, {"Width": 7.0})]],
        )
        self.assertEqual(plan_view.selected, {"a1_rect"})
        self.assertEqual(plan_view.selection_revision, 1)


class PlanViewActionHandlerPreparedPropertyCompletionTests(
    _PlanViewActionHandlerFixture
):
    """prepare_sql_property_completion is the public entry the Condition handler uses
    for edits that are queued elsewhere: its optional parameters decide what history
    records, whether the selection is preserved and whether a stale owner is ignored."""

    BID = BidRef("bid.mdb", "7")

    def _setup(self, undo=None):
        data = FakeProjectData()
        for uid in ("t1", "t2"):
            data.takeoffs[uid] = Takeoff(
                uid=uid, condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
            )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService() if undo is None else undo
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def _prepare(self, handler, **options):
        arguments = dict(
            old_updates=[("t1", False)],
            plan_uids={"t1"},
            takeoff_uids={"t1"},
            page_uids=("p1",),
        )
        arguments.update(options)
        return handler.prepare_sql_property_completion(
            self.BID, "takeoff_negative", [("t1", True)], **arguments
        )

    def test_history_records_the_committed_updates_and_their_dependencies(self):
        handler, plan_view, write, _data, undo = self._setup()
        dependency = ResourceRef("condition", "c1", 7)
        seen = []

        def committed_updates(result):
            seen.append(result)
            return [("t1", "authoritative")], (dependency,)

        complete, _abort = self._prepare(handler, committed_updates=committed_updates)
        result = _committed()
        complete(result)
        self.assertEqual(seen, [result])
        self.assertEqual(undo.count, 1)
        undo.undo()
        undo.redo()
        self.assertEqual(write.queued_properties[0][3], [("t1", False)])
        self.assertEqual(
            write.queued_properties[0][4]["dependency_resources"], (dependency,)
        )
        self.assertEqual(write.queued_properties[1][3], [("t1", "authoritative")])
        self.assertEqual(
            write.queued_properties[1][4]["dependency_resources"], (dependency,)
        )

    def test_without_committed_updates_history_replays_the_submitted_ones(self):
        handler, plan_view, write, _data, undo = self._setup()
        dependency = ResourceRef("condition", "c1", 7)
        complete, _abort = self._prepare(handler, dependency_resources=(dependency,))
        complete(_committed())
        undo.redo()
        self.assertEqual(write.queued_properties[0][3], [("t1", True)])
        self.assertEqual(
            write.queued_properties[0][4]["dependency_resources"], (dependency,)
        )

    def test_a_stale_owner_gets_neither_selection_nor_history_nor_restore(self):
        for outcome in (
            MutationOutcomeStatus.COMMITTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        ):
            for via_abort in (False, True):
                if via_abort and outcome == MutationOutcomeStatus.COMMITTED:
                    continue
                with self.subTest(outcome=outcome.name, via_abort=via_abort):
                    handler, plan_view, write, _data, undo = self._setup()
                    restored = []
                    complete, abort = self._prepare(
                        handler,
                        restore=lambda: restored.append(True),
                        owner_is_current=lambda: False,
                    )
                    plan_view.selected = set()
                    plan_view.pending_mutation_uids = {"t1"}
                    if via_abort:
                        abort()
                    else:
                        complete(
                            QueuedMutationResult(
                                database_id="bid.mdb",
                                runtime_generation=1,
                                operation_id=str(uuid.uuid4()),
                                outcome_status=outcome,
                            )
                        )
                    self.assertEqual(restored, [])
                    self.assertEqual(plan_view.selected, set())
                    self.assertEqual(plan_view.pending_mutation_uids, set())
                    self.assertEqual(undo.count, 0)
                    self.assertEqual(undo.forward_mutations, [])

    def test_a_current_owner_is_restored_by_a_failure_and_by_an_abort(self):
        for via_abort in (False, True):
            with self.subTest(via_abort=via_abort):
                handler, plan_view, write, _data, undo = self._setup()
                restored = []
                complete, abort = self._prepare(
                    handler,
                    restore=lambda: restored.append(True),
                    owner_is_current=lambda: True,
                )
                plan_view.selected = set()
                if via_abort:
                    abort()
                    abort()
                else:
                    complete(_failed())
                    complete(_failed())
                    abort()
                self.assertEqual(restored, [True])
                self.assertEqual(plan_view.selected, {"t1"})
                self.assertEqual(undo.forward_mutations, [])

    def test_preserve_selection_restores_the_selection_the_edit_started_from(self):
        for outcome_committed in (False, True):
            with self.subTest(committed=outcome_committed):
                handler, plan_view, write, _data, undo = self._setup()
                plan_view.selected = {"t2"}
                complete, _abort = self._prepare(handler, preserve_selection=True)
                plan_view.selected = set()
                complete(_committed() if outcome_committed else _failed())
                self.assertEqual(plan_view.selected, {"t2"})

    def test_without_preserve_selection_the_edited_items_are_selected(self):
        handler, plan_view, write, _data, undo = self._setup()
        plan_view.selected = {"t2"}
        complete, _abort = self._prepare(handler)
        plan_view.selected = set()
        complete(_committed())
        self.assertEqual(plan_view.selected, {"t1"})


class PlanViewActionHandlerPlanContextTests(_PlanViewActionHandlerFixture):
    """_plan_context_is_current: the Bid, the live plan view and the Page decide whether
    a late completion may still touch the plan."""

    def _context(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        handler = self._paste_handler(plan_view=plan_view, data=data)
        bid = BidRef("bid.mdb", "7")
        state = SimpleNamespace(active_page_uid="p1", get_selected_bid_ref=lambda: bid)
        handler._ui_state = state
        return handler, plan_view, state, bid

    def test_the_page_comes_from_the_plan_view_then_the_ui_state(self):
        handler, plan_view, state, bid = self._context()
        plan_view.current_page_uid = None
        self.assertTrue(handler._plan_context_is_current(bid, ("p1",)))
        self.assertFalse(handler._plan_context_is_current(bid, ("p2",)))
        plan_view.current_page_uid = "p2"
        self.assertFalse(handler._plan_context_is_current(bid, ("p1",)))
        self.assertTrue(handler._plan_context_is_current(bid, ("p2",)))

    def test_an_unknown_page_never_matches_a_page_uid(self):
        handler, plan_view, state, bid = self._context()
        plan_view.current_page_uid = None
        state.active_page_uid = None
        self.assertFalse(handler._plan_context_is_current(bid, ("None",)))
        self.assertFalse(handler._plan_context_is_current(bid, ("p1",)))

    def test_a_context_without_pages_only_needs_the_bid_and_a_live_plan(self):
        handler, plan_view, state, bid = self._context()
        plan_view.current_page_uid = None
        state.active_page_uid = None
        self.assertIs(handler._plan_context_is_current(bid, ()), True)
        self.assertIs(
            handler._plan_context_is_current(BidRef("bid.mdb", "8"), ()), False
        )
        plan_view._is_cleaning_up = True
        self.assertIs(handler._plan_context_is_current(bid, ()), False)

    def test_a_context_with_unchanged_page_identities_is_current(self):
        handler, plan_view, state, bid = self._context()
        identities = handler._capture_page_identities(("p1",))
        self.assertIs(handler._plan_context_is_current(bid, ("p1",), identities), True)
        handler._data_svc.pages["p1"] = SimpleNamespace(uid="p1")
        self.assertIs(handler._plan_context_is_current(bid, ("p1",), identities), False)


class PlanViewActionHandlerPlacementCompletionTests(_PlanViewActionHandlerFixture):
    """The terminal branches of a queued SQL takeoff placement."""

    def _placed(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        (pending_uid,) = list(data.takeoffs)
        return (
            handler,
            data,
            plan_view,
            write,
            undo,
            operation_id,
            callback,
            pending_uid,
        )

    @staticmethod
    def _result(operation_id, status, created=(), message=""):
        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=operation_id,
            outcome_status=status,
            created_resource_ids=tuple(created),
            message=message,
        )

    @staticmethod
    def _changed_events(handler):
        return [
            payload
            for event, payload in handler._event_bus.events
            if event == AppEvents.TAKEOFFS_CHANGED
        ]

    def test_a_committed_placement_with_the_wrong_identity_count_removes_the_preview(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        with self.assertLogs(handler_module.logger, "ERROR") as logged:
            callback(
                self._result(
                    operation_id, MutationOutcomeStatus.COMMITTED, ("501", "502")
                )
            )
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL takeoff placement returned 2 identities for 1 takeoffs."],
        )
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(
            self._changed_events(handler)[-1],
            {
                "page_uid": "9",
                "takeoff_uids": [pending_uid],
                "condition_uids": ["42"],
            },
        )

    def test_a_failed_placement_logs_the_message_or_the_default_reason(self):
        for message, expected in (
            ("conflict", "SQL takeoff placement failed: conflict"),
            ("", "SQL takeoff placement failed: The database rejected the placement."),
        ):
            with self.subTest(message=message):
                (
                    handler,
                    data,
                    plan_view,
                    write,
                    undo,
                    operation_id,
                    callback,
                    pending_uid,
                ) = self._placed()
                with self.assertLogs(handler_module.logger, "WARNING") as logged:
                    callback(
                        self._result(
                            operation_id,
                            MutationOutcomeStatus.CONFLICT,
                            message=message,
                        )
                    )
                self.assertEqual(
                    [record.getMessage() for record in logged.records], [expected]
                )
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(
                    self._changed_events(handler)[-1]["takeoff_uids"], [pending_uid]
                )

    def test_a_failed_placement_of_another_bid_removes_its_preview_without_a_projection(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        events_before = len(self._changed_events(handler))
        with self.assertLogs(handler_module.logger, "WARNING"):
            callback(
                self._result(operation_id, MutationOutcomeStatus.CONFLICT, message="x")
            )
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(len(self._changed_events(handler)), events_before)
        self.assertEqual(undo.forward_mutations, [])

    def test_interim_outcomes_keep_the_placement_waiting(self):
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            with self.subTest(status=status.name):
                (
                    handler,
                    data,
                    plan_view,
                    write,
                    undo,
                    operation_id,
                    callback,
                    pending_uid,
                ) = self._placed()
                callback(self._result(operation_id, status, ("501",)))
                self.assertIn(pending_uid, data.takeoffs)
                self.assertIn(operation_id, handler._pending_takeoff_placements)
                self.assertEqual(plan_view.pending_mutation_uids, {pending_uid})
                self.assertEqual(len(undo.forward_mutations), 1)
                self.assertEqual(handler._completed_sql_mutation_ids, set())

    def test_a_committed_placement_for_another_bid_registers_nothing_and_is_remembered(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        result = self._result(operation_id, MutationOutcomeStatus.COMMITTED, ("501",))
        callback(result)
        self.assertNotIn(pending_uid, data.takeoffs)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(handler._completed_sql_mutation_ids, {operation_id})
        self.assertNotIn(operation_id, handler._pending_takeoff_placements)

    def test_a_committed_placement_on_a_replaced_page_registers_nothing_and_is_remembered(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        data.pages["9"] = SimpleNamespace(uid="9")
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        callback(self._result(operation_id, MutationOutcomeStatus.COMMITTED, ("501",)))
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(handler._completed_sql_mutation_ids, {operation_id})

    def test_a_selection_made_while_the_placement_ran_is_kept(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        plan_view.set_selected_uids({"user-choice"})
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        callback(self._result(operation_id, MutationOutcomeStatus.COMMITTED, ("501",)))
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(undo.count, 1)

    def test_a_cancelled_placement_whose_previews_were_all_deleted_ends_silently(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        handler.on_elements_deleted([pending_uid])
        events_before = len(self._changed_events(handler))
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            callback(
                self._result(operation_id, MutationOutcomeStatus.CANCELLED_BEFORE_START)
            )
        self.assertEqual(len(self._changed_events(handler)), events_before)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(undo.count, 0)
        self.assertNotIn(operation_id, handler._pending_takeoff_placements)

    def test_a_cancellation_that_did_not_cover_every_preview_is_a_failure(self):
        data = FakeProjectData()
        data.conditions["c2"] = Condition(
            uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler._ui_state.place_condition_uids = ["c1", "c2"]
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        first, second = list(data.takeoffs)
        handler.on_elements_deleted([first])
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            callback(
                self._result(
                    operation_id,
                    MutationOutcomeStatus.CANCELLED_BEFORE_START,
                    message="cancelled",
                )
            )
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL takeoff placement failed: cancelled"],
        )
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(
            self._changed_events(handler)[-1]["takeoff_uids"], [first, second]
        )

    def test_deleting_a_preview_together_with_a_real_takeoff_deletes_only_the_real_one(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        handler.on_elements_deleted([pending_uid, "t1"])
        self.assertEqual(write.cancelled_mutations, [("bid.mdb", operation_id)])
        self.assertEqual(len(write.queued_deletes), 1)
        self.assertEqual(write.queued_deletes[0][2], ["t1"])
        self.assertNotIn(pending_uid, data.takeoffs)

    def test_hiding_previews_removes_only_those_of_the_active_bid(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        handler.hide_pending_takeoff_placement_previews()
        self.assertIn(pending_uid, data.takeoffs)
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
        )
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(
            self._changed_events(handler)[-1],
            {"page_uid": "9", "takeoff_uids": [pending_uid], "condition_uids": ["42"]},
        )
        self.assertIn(operation_id, handler._pending_takeoff_placements)
        self.assertEqual(len(undo.forward_mutations), 1)
        events_after = len(handler._event_bus.events)
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(len(handler._event_bus.events), events_after)

    def test_hiding_previews_without_an_active_bid_removes_them_silently(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        handler._ui_state = SimpleNamespace(
            active_page_uid=None, get_selected_bid_ref=lambda: None
        )
        events_before = len(self._changed_events(handler))
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(len(self._changed_events(handler)), events_before)

    def test_invalidating_placements_forgets_them_and_frees_their_history_tokens(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        self.assertEqual(len(undo.forward_mutations), 1)
        handler.invalidate_pending_takeoff_placements()
        self.assertEqual(handler._pending_takeoff_placements, {})
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(data.takeoffs, {})


class PlanViewActionHandlerSqlHistoryReplayTests(_PlanViewActionHandlerFixture):
    """What the history entries of COMMITTED SQL geometry/delete/paste edits queue when
    they are replayed (the fake undo service calls the submit callbacks directly; the
    callbacks they receive are driven by hand)."""

    def _sql(self, data=None):
        data = FakeProjectData() if data is None else data
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_sql_geometry_history_replays_rescaled_positions_for_the_same_pages(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0, 96.0, 0.0]
        )
        handler, plan_view, write, _data, undo = self._sql(data)
        handler.on_positions_flushed(
            [("t1", [0.0, 0.0, 96.0, 0.0], [0.0, 0.0, 120.0, 0.0])], []
        )
        write.queued_geometry[0][-1](_committed())
        self.assertEqual(undo.count, 1)
        data.pages["p1"].scale_factor1 = 0.1875
        undo.undo()
        undo.redo()
        undo_payload, redo_payload = (
            write.queued_geometry[1][2],
            write.queued_geometry[2][2],
        )
        self.assertEqual(
            undo_payload["takeoff_positions"], [("t1", [0.0, 0.0, 64.0, 0.0])]
        )
        self.assertEqual(
            redo_payload["takeoff_positions"], [("t1", [0.0, 0.0, 80.0, 0.0])]
        )
        self.assertEqual(undo_payload["page_uids"], ("p1",))
        self.assertEqual(redo_payload["page_uids"], ("p1",))
        self.assertEqual(undo_payload["takeoff_rotations"], [])
        self.assertEqual(undo_payload["annotation_positions"], [])

    def test_sql_group_rotation_history_replays_old_and_new_rotations(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        handler, plan_view, write, _data, undo = self._sql(data)
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [3.0, 4.0])], [], [("t1", 0.0, 45.0)]
        )
        write.queued_geometry[0][-1](_committed())
        undo.undo()
        undo.redo()
        self.assertEqual(
            write.queued_geometry[1][2]["takeoff_positions"], [("t1", [0.0, 0.0])]
        )
        self.assertEqual(
            write.queued_geometry[1][2]["takeoff_rotations"], [("t1", 0.0)]
        )
        self.assertEqual(
            write.queued_geometry[2][2]["takeoff_positions"], [("t1", [3.0, 4.0])]
        )
        self.assertEqual(
            write.queued_geometry[2][2]["takeoff_rotations"], [("t1", 45.0)]
        )

    def test_a_failed_group_rotation_restores_positions_and_rotations_once(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        handler, plan_view, write, _data, undo = self._sql(data)
        position_changes = [("t1", [0.0, 0.0], [3.0, 4.0])]
        rotation_changes = [("t1", 0.0, 45.0)]
        handler.on_group_rotation_flushed(position_changes, [], rotation_changes)
        callback = write.queued_geometry[0][-1]
        callback(_failed())
        callback(_failed())
        self.assertEqual(plan_view.restored_positions, [(position_changes, [])])
        self.assertEqual(plan_view.restored_rotations, [rotation_changes])
        self.assertEqual(undo.count, 0)

    def _deleted_family(self):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["hole"] = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="parent",
            is_negative=True,
        )
        data.extras["hole"] = {"GUID": "{H}"}
        return self._sql(data)

    def test_sql_delete_history_restores_the_family_and_redeletes_the_new_identities(
        self,
    ):
        handler, plan_view, write, data, undo = self._deleted_family()
        handler.on_elements_deleted(["parent"])
        self.assertEqual(write.queued_deletes[0][2], ["parent", "hole"])
        self.assertEqual(undo.count, 0)
        write.queued_deletes[0][-1](_committed())
        self.assertEqual(undo.count, 1)
        undo.undo()
        database_id, payload, options, restored = write.queued_pastes[0]
        self.assertEqual(database_id, "bid.mdb")
        self.assertEqual(payload.takeoff_source_uids, ("parent", "hole"))
        self.assertEqual(payload.source_bid_uid, "7")
        self.assertEqual(payload.destination_bid_uid, "7")
        self.assertEqual(
            [spec.parent_uid for spec in payload.takeoff_specs], ["0", "parent"]
        )
        self.assertEqual(payload.takeoff_specs[1].raw_extras, {"GUID": "{H}"})
        self.assertEqual(payload.takeoff_specs[1].is_negative, True)
        self.assertEqual(
            payload.takeoff_specs[0].position, [0.0, 0.0, 10.0, 0.0, 10.0, 10.0]
        )
        self.assertEqual(payload.annotation_specs, ())
        self.assertFalse(any(target.available for target in undo.takeoff_targets))
        restored(
            _committed(
                maps=(
                    ("takeoffs", (("parent", "P2"), ("hole", "H2"))),
                    ("annotations", ()),
                )
            )
        )
        self.assertEqual(
            sorted((target.uid, target.available) for target in undo.takeoff_targets),
            [("H2", True), ("P2", True)],
        )
        undo.redo()
        self.assertEqual(write.queued_deletes[1][2], ["P2", "H2"])
        self.assertEqual(write.queued_deletes[1][3], [])
        self.assertEqual(write.queued_deletes[1][4]["page_uids"], ("p1",))

    def test_sql_delete_history_leaves_the_targets_suspended_when_the_restore_fails(
        self,
    ):
        handler, plan_view, write, data, undo = self._deleted_family()
        handler.on_elements_deleted(["parent"])
        write.queued_deletes[0][-1](_committed())
        undo.undo()
        write.queued_pastes[0][-1](_failed())
        self.assertFalse(any(target.available for target in undo.takeoff_targets))
        self.assertEqual(
            {target.uid for target in undo.takeoff_targets}, {"parent", "hole"}
        )

    def test_sql_paste_history_redo_replays_the_payload_and_rebinds_the_new_identity(
        self,
    ):
        handler, plan_view, write, data, undo = self._sql()
        plan_view.intelligent_paste_enabled = False
        handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
        handler.on_paste_requested()
        write.queued_pastes[0][-1](
            _committed(maps=(("takeoffs", (("source", "new-1"),)),))
        )
        self.assertEqual(undo.count, 1)
        self.assertEqual([target.uid for target in undo.takeoff_targets], ["new-1"])
        undo.undo()
        write.queued_deletes[0][-1](_committed())
        self.assertFalse(undo.takeoff_targets[0].available)
        undo.redo()
        redo_database, redo_payload, _options, completed = write.queued_pastes[1]
        self.assertEqual(redo_database, "bid.mdb")
        self.assertEqual(redo_payload.takeoff_source_uids, ("source",))
        self.assertEqual(
            redo_payload.takeoff_specs[0].position, [11.0, 21.0, 15.0, 21.0]
        )
        completed(_committed(maps=(("takeoffs", (("source", "new-2"),)),)))
        self.assertEqual(undo.takeoff_targets[0].uid, "new-2")
        self.assertTrue(undo.takeoff_targets[0].available)

    def test_a_failed_sql_paste_undo_keeps_the_targets_available(self):
        handler, plan_view, write, data, undo = self._sql()
        plan_view.intelligent_paste_enabled = False
        handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
        handler.on_paste_requested()
        write.queued_pastes[0][-1](
            _committed(maps=(("takeoffs", (("source", "new-1"),)),))
        )
        undo.undo()
        write.queued_deletes[0][-1](_failed())
        self.assertTrue(undo.takeoff_targets[0].available)
        self.assertEqual(undo.takeoff_targets[0].uid, "new-1")


class PlanViewActionHandlerGeometryLeaseRequestTests(_PlanViewActionHandlerFixture):
    """When a granted or pending geometry lease is kept, replaced or ended by a new
    request (the request path of on_geometry_edit_lease_requested)."""

    def _handler(self):
        data = FakeProjectData()
        for uid, parent, condition in (
            ("t1", "0", "c1"),
            ("t2", "t1", "c1"),
            ("t3", "0", "c1"),
        ):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid=condition,
                page_uid="p1",
                position=[0.0, 0.0],
                parent_uid=parent,
            )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        plan_view.disable_calls = []
        disable = plan_view.disable_geometry_edit_leasing

        def counting_disable():
            plan_view.disable_calls.append(True)
            disable()

        plan_view.disable_geometry_edit_leasing = counting_disable
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        return handler, plan_view, write, data

    _grant = staticmethod(PlanViewActionHandlerGeometryLeaseLifecycleTests._grant)

    def _held(self):
        handler, plan_view, write, data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        callback(EditLeaseResult(True, handle=handle))
        return handler, plan_view, write, data, handle

    def test_a_release_while_a_request_is_pending_ends_its_late_grant(self):
        handler, plan_view, write, _data = self._handler()
        plan_view.prepare_for_authoritative_refresh = lambda: None
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        handler.prepare_for_authoritative_refresh()
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_a_request_that_cannot_be_served_ends_the_current_lease(self):
        cases = {
            "access lost": lambda h: h._ui_access_manager.allowed_features.discard(
                Feature.EDIT_PLAN_ITEMS
            ),
            "no bid": lambda h: setattr(
                h, "_ui_state", SimpleNamespace(get_selected_bid_ref=lambda: None)
            ),
            "not sql": lambda h: setattr(
                h._write_svc, "sql_collaboration_mutations", False
            ),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                handler, plan_view, write, _data, handle = self._held()
                change(handler)
                handler.on_geometry_edit_lease_requested(["t1"])
                self.assertEqual(write.ended_edit_leases, [handle])
                self.assertEqual(len(write.edit_lease_requests), 1)
                self.assertIsNone(handler._geometry_edit_lease_handle)

    def test_an_empty_selection_ends_the_lease_without_looking_at_the_bid(self):
        handler, plan_view, write, _data, handle = self._held()
        handler._ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("bid.mdb", "not-a-number")
        )
        handler.on_geometry_edit_lease_requested([])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(len(write.edit_lease_requests), 1)

    def test_a_selection_without_leasable_resources_ends_the_current_lease(self):
        handler, plan_view, write, _data, handle = self._held()
        handler.on_geometry_edit_lease_requested(["unknown-item"])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(len(write.edit_lease_requests), 1)
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_a_lease_is_reused_only_for_the_same_resources_and_dependencies(self):
        handler, plan_view, write, data, handle = self._held()
        data.takeoffs["t1"].condition_uid = "c9"
        handler.on_geometry_edit_lease_requested(["t1"])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(len(write.edit_lease_requests), 2)
        handler, plan_view, write, data, handle = self._held()
        plan_view.selected = {"t3"}
        handler.on_geometry_edit_lease_requested(["t3"])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertEqual(len(write.edit_lease_requests), 2)
        self.assertEqual(
            write.edit_lease_requests[1][2], write.edit_lease_requests[0][2]
        )

    def test_a_reused_lease_follows_the_new_selection(self):
        handler, plan_view, write, _data, handle = self._held()
        plan_view.selected = {"t1", "t2"}
        handler.on_geometry_edit_lease_requested(["t1", "t2"])
        self.assertEqual(len(write.edit_lease_requests), 1)
        self.assertEqual(handler._geometry_edit_lease_selection, {"t1", "t2"})
        handler.on_plan_item_selection_changed(["t1", "t2"])
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIs(handler._geometry_edit_lease_handle, handle)

    def test_a_different_selection_supersedes_a_pending_request(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        stale_handle, stale_callback = self._grant(write, 0, "stale")
        plan_view.selected = {"t3"}
        handler.on_geometry_edit_lease_requested(["t3"])
        self.assertEqual(len(write.edit_lease_requests), 2)
        self.assertEqual(plan_view.geometry_lease_pending, {"t3"})
        stale_callback(EditLeaseResult(True, handle=stale_handle))
        self.assertEqual(write.ended_edit_leases, [stale_handle])
        self.assertEqual(plan_view.geometry_lease_pending, {"t3"})

    def test_a_lease_loss_makes_the_handler_forget_the_leased_selection(self):
        handler, plan_view, write, _data, handle = self._held()
        handler.on_edit_lease_lost(
            EditLeaseLoss(
                database_id=handle.database_id,
                draft_id=handle.draft_id,
                runtime_generation=handle.runtime_generation,
                operation_id=handle.operation_id,
                owning_surface=handle.owning_surface,
                resources=handle.resources,
                reason="trust-lost",
            )
        )
        self.assertEqual(handler._geometry_edit_lease_selection, set())
        disables = len(plan_view.disable_calls)
        handler.on_plan_item_selection_changed(["t3"])
        self.assertEqual(len(plan_view.disable_calls), disables)
        self.assertEqual(write.ended_edit_leases, [])

    def test_a_loss_without_a_held_lease_changes_nothing(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, _callback = self._grant(write)
        disables = len(plan_view.disable_calls)
        handler.on_edit_lease_lost(
            EditLeaseLoss(
                database_id=handle.database_id,
                draft_id=handle.draft_id,
                runtime_generation=handle.runtime_generation,
                operation_id=handle.operation_id,
                owning_surface=handle.owning_surface,
                resources=handle.resources,
                reason="trust-lost",
            )
        )
        self.assertEqual(len(plan_view.disable_calls), disables)
        self.assertEqual(plan_view.geometry_lease_pending, {"t1"})
        self.assertEqual(handler._geometry_edit_lease_selection, {"t1"})

    def test_a_selection_change_without_a_lease_leaves_the_plan_alone(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_plan_item_selection_changed(["t1"])
        handler.on_plan_item_selection_changed([])
        self.assertEqual(plan_view.disable_calls, [])
        self.assertEqual(write.ended_edit_leases, [])

    def test_a_child_without_a_parent_is_not_leased_with_a_takeoff_called_none(self):
        handler, plan_view, write, data = self._handler()
        data.takeoffs["None"] = Takeoff(
            uid="None", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.takeoffs["orphan"] = Takeoff(
            uid="orphan",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            parent_uid=None,
        )
        plan_view.selected = {"None"}
        handler.on_geometry_edit_lease_requested(["None"])
        self.assertEqual(
            write.edit_lease_requests[0][1], (ResourceRef("takeoff", "None", 7),)
        )


class PlanViewActionHandlerOverlayRectGuardTests(_PlanViewActionHandlerFixture):
    """save_current_page_overlay_rect answers a strict bool and only acts on a known
    Bid and Page; its deferred callbacks only act while the Bid is still the active one.
    """

    def _handler(self, deferred=None):
        data = FakeProjectData()
        deferred = FakeDeferredPersistence() if deferred is None else deferred
        return self._overlay_handler(data, deferred), data, deferred

    def test_the_answer_is_a_bool_for_every_outcome(self):
        handler, data, deferred = self._handler()
        self.assertIs(handler.save_current_page_overlay_rect((1, 2, 3, 4)), True)
        handler, data, deferred = self._handler(
            deferred=FakeDeferredPersistence(accepts_writes=False)
        )
        self.assertIs(handler.save_current_page_overlay_rect((1, 2, 3, 4)), False)
        handler, data, deferred = self._handler()
        handler._ui_access_manager.allowed_features.clear()
        self.assertIs(handler.save_current_page_overlay_rect((1, 2, 3, 4)), False)

    def test_nothing_is_scheduled_without_a_bid_a_page_or_a_known_page(self):
        cases = {
            "no bid": lambda h, d: setattr(
                h,
                "_ui_state",
                SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                ),
            ),
            "no page uid": lambda h, d: setattr(h._ui_state, "active_page_uid", ""),
            "unknown page": lambda h, d: d.pages.pop("p1"),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                handler, data, deferred = self._handler()
                change(handler, data)
                self.assertIs(
                    handler.save_current_page_overlay_rect((1, 2, 3, 4)), False
                )
                self.assertEqual(deferred.overlay_rect_calls, [])

    def test_callbacks_of_another_bid_leave_the_page_alone(self):
        handler, data, deferred = self._handler()
        data.get_page("p1").overlay_rect = (0.0, 0.0, 10.0, 10.0)
        self.assertTrue(handler.save_current_page_overlay_rect((1, 2, 3, 4)))
        handler._ui_state = SimpleNamespace(
            active_page_uid="p1", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        callbacks = deferred.overlay_rect_callbacks[0]
        callbacks["restore_authoritative"]()
        self.assertEqual(data.get_page("p1").overlay_rect, (1.0, 2.0, 3.0, 4.0))
        callbacks["project_value"]()
        self.assertEqual(data.get_page("p1").overlay_rect, (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(handler._plan_view.projected_overlay_rects, [])


class PlanViewActionHandlerPasteContentTests(_PlanViewActionHandlerFixture):
    """What the clipboard offers for the current Bid."""

    def test_the_answer_is_a_bool_without_a_bid(self):
        handler = self._paste_handler()
        handler._ui_state = SimpleNamespace(get_selected_bid_ref=lambda: None)
        handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
        self.assertIs(handler.can_paste_to_current_bid(), False)
        handler._ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
        )
        self.assertIs(handler.can_paste_to_current_bid(), True)

    def test_a_mixed_clipboard_of_another_bid_offers_takeoffs_and_annotations(self):
        handler = self._paste_handler()
        takeoff = self._copied_takeoff()
        annotation = self._copied_annotation()
        handler._clipboard_svc = FakeClipboard(
            [takeoff], annotations=[annotation], source_bid_uid="6"
        )
        items, annotations = handler._permitted_paste_content(BidRef("bid.mdb", "7"))
        self.assertEqual(items, [takeoff])
        self.assertEqual(annotations, [annotation])
        handler._clipboard_svc = FakeClipboard(
            [], annotations=[annotation], source_bid_uid="6"
        )
        self.assertEqual(
            handler._permitted_paste_content(BidRef("bid.mdb", "7")), ([], [])
        )
        handler._clipboard_svc = FakeClipboard(
            [], annotations=[annotation], source_bid_uid="7"
        )
        self.assertEqual(
            handler._permitted_paste_content(BidRef("bid.mdb", "7")), ([], [annotation])
        )


class PlanViewActionHandlerConditionTextEdgeTests(_PlanViewActionHandlerFixture):
    """on_condition_text_properties_flushed without a Bid, and the Page scope of its
    SQL write."""

    def test_without_a_bid_the_editor_state_is_restored_and_nothing_is_written(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler._ui_state = SimpleNamespace(get_selected_bid_ref=lambda: None)
        changes = [("t1", "name", {"name_font_bold": False}, {"name_font_bold": True})]
        handler.on_condition_text_properties_flushed(changes)
        self.assertEqual(plan_view.restored_condition_text_properties, [changes])
        self.assertEqual(write.queued_properties, [])
        self.assertEqual(write.text_property_calls, [])

    def test_the_sql_write_is_scoped_to_the_pages_of_the_known_takeoffs_only(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        data.takeoffs["t2"] = Takeoff(uid="t2", condition_uid="c1", page_uid="")
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_condition_text_properties_flushed(
            [
                ("t1", "name", {"name_font_bold": False}, {"name_font_bold": True}),
                ("t2", "name", {"name_font_bold": False}, {"name_font_bold": True}),
                ("gone", "name", {"name_font_bold": False}, {"name_font_bold": True}),
            ]
        )
        self.assertEqual(write.queued_properties[0][4]["page_uids"], ("p1",))


class PlanViewActionHandlerPendingPlacementImmutabilityTests(
    _PlanViewActionHandlerFixture
):
    def test_a_pending_placement_cannot_be_modified_in_place(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        (pending,) = handler._pending_takeoff_placements.values()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            pending.deleted_pending_uids = frozenset({"x"})


class _OptionRecordingWriteService(FakeWriteService):
    """FakeWriteService that also keeps the scope (pages, dependencies, publish flag)
    the handler passes to the local property executor, which the plain fake drops."""

    def __init__(self):
        super().__init__()
        self.local_property_options = []

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
        self.local_property_options.append(
            {
                "kind": property_kind,
                "page_uids": page_uids,
                "dependency_resources": dependency_resources,
                "publish": publish_database_refreshed_after_write,
            }
        )
        return super().execute_plan_properties_local(
            database_id,
            bid_uid,
            property_kind,
            updates,
            page_uids=page_uids,
            dependency_resources=dependency_resources,
            publish_database_refreshed_after_write=publish_database_refreshed_after_write,
        )


class PlanViewActionHandlerLocalGeometryRoutingTests(_PlanViewActionHandlerFixture):
    """Which write entry the local (Access) geometry paths use and how they scope it."""

    def _handler(self):
        data = FakeProjectData()
        data.pages["9"].scale_factor1 = 1.0
        for uid, page in (("t1", "p1"), ("t2", "9")):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="c1",
                page_uid=page,
                position=[0.0, 0.0],
                rotation=0.0,
            )
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="9",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_rect": annotation}
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        return handler, plan_view, write, ann_write, undo, data

    def test_pure_edits_use_their_dedicated_save_not_the_geometry_executor(self):
        handler, plan_view, write, ann_write, undo, data = self._handler()
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(len(write.position_calls), 1)
        handler.on_group_rotation_flushed([], [], [("t1", 0.0, 45.0)])
        self.assertEqual(write.rotation_calls, [("bid.mdb", [("t1", 45.0)], False)])
        handler.on_positions_flushed(
            [], [("a1", "rect", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])]
        )
        self.assertEqual(len(ann_write.position_calls), 1)
        self.assertEqual(
            ann_write.position_calls[0][1], [("a1", "rect", [3.0, 3.0, 4.0, 4.0])]
        )
        self.assertEqual(write.local_geometry, [])
        self.assertEqual(len(write.position_calls), 1)
        self.assertEqual(undo.count, 3)

    def test_mixed_edits_use_one_scoped_geometry_executor_call(self):
        handler, plan_view, write, ann_write, undo, data = self._handler()
        handler.on_positions_flushed(
            [("t1", [0.0, 0.0], [5.0, 6.0])],
            [("a1", "rect", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])],
        )
        self.assertEqual(
            write.local_geometry,
            [
                (
                    "bid.mdb",
                    "7",
                    [("t1", [5.0, 6.0])],
                    [],
                    [("a1", "rect", [3.0, 3.0, 4.0, 4.0])],
                    {
                        "page_uids": ("p1", "9"),
                        "dependency_resources": (),
                        "publish_database_refreshed_after_write": False,
                    },
                )
            ],
        )
        self.assertEqual(undo.count, 1)

    def test_a_group_edit_lists_the_positioned_then_the_rotated_takeoffs(self):
        handler, plan_view, write, ann_write, undo, data = self._handler()
        handler.on_group_rotation_flushed(
            [("t1", [0.0, 0.0], [5.0, 6.0])], [], [("t2", 0.0, 45.0)]
        )
        self.assertEqual(
            handler._event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uids": ["p1", "9"],
                        "page_uid": "",
                        "takeoff_uids": ["t1", "t2"],
                        "condition_uids": ["c1"],
                    },
                )
            ],
        )
        self.assertEqual(
            write.local_geometry[0][2:5], ([("t1", [5.0, 6.0])], [("t2", 45.0)], [])
        )

    def test_the_dedicated_saves_report_a_strict_bool(self):
        handler, plan_view, write, ann_write, undo, data = self._handler()
        before = (len(write.position_calls), len(write.rotation_calls))
        self.assertIs(handler._save_takeoff_positions_fast("bid.mdb", []), True)
        self.assertIs(handler._save_takeoff_rotations_fast("bid.mdb", []), True)
        self.assertEqual((len(write.position_calls), len(write.rotation_calls)), before)
        self.assertIs(
            handler._save_takeoff_positions_fast("bid.mdb", [("t1", [1.0, 1.0])]), True
        )
        self.assertIs(
            handler._save_takeoff_rotations_fast("bid.mdb", [("t1", 1.0)]), True
        )
        write.save_takeoff_positions = lambda *args, **options: False
        write.save_takeoff_rotations = lambda *args, **options: False
        self.assertIs(
            handler._save_takeoff_positions_fast("bid.mdb", [("t1", [1.0, 1.0])]), False
        )
        self.assertIs(
            handler._save_takeoff_rotations_fast("bid.mdb", [("t1", 1.0)]), False
        )
        self.assertIs(
            handler._execute_local_plan_geometry(
                handler._ui_state.get_selected_bid_ref(),
                takeoff_positions=[("t1", [1.0, 1.0])],
                annotation_positions=[("a1", "rect", [3.0, 3.0, 4.0, 4.0])],
            ),
            False,
        )

    def test_the_dedicated_saves_do_not_publish_when_the_write_fails(self):
        handler, plan_view, write, ann_write, undo, data = self._handler()
        write.save_takeoff_positions = lambda *args, **options: False
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(handler._event_bus.events, [])
        self.assertEqual(data.takeoffs["t1"].position, [0.0, 0.0])


class PlanViewActionHandlerLocalPropertyScopeTests(_PlanViewActionHandlerFixture):
    """The page and dependency scope of the local property executor, per entry point."""

    def _handler(self):
        data = FakeProjectData()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        for uid, page in (("t1", "p1"), ("t2", "9")):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="c1",
                page_uid=page,
                area_uid="5",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
                is_negative=uid == "t2",
            )
        plan_view = FakePlanView(data)
        write = _OptionRecordingWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler._page_settings_bar = SimpleNamespace(get_current_area_uid=lambda: "A2")
        return handler, write, data, undo

    def test_a_negative_flag_edit_is_scoped_to_the_pages_of_its_takeoffs(self):
        handler, write, data, undo = self._handler()
        handler.on_set_negative(["t1", "t2"], True)
        self.assertEqual(
            write.local_property_options,
            [
                {
                    "kind": "takeoff_negative",
                    "page_uids": ("p1", "9"),
                    "dependency_resources": (),
                    "publish": False,
                }
            ],
        )
        undo.undo()
        self.assertEqual(
            [call[1:3] for call in write.negative_calls],
            [(["t1", "t2"], True), (["t1"], False), (["t2"], True)],
        )

    def test_an_area_edit_depends_on_the_new_and_the_replaced_areas(self):
        handler, write, data, undo = self._handler()
        handler.on_assign_to_area(["t1"])
        self.assertEqual(write.local_property_options[0]["kind"], "takeoff_area")
        self.assertEqual(write.local_property_options[0]["page_uids"], ("p1",))
        self.assertEqual(
            write.local_property_options[0]["dependency_resources"],
            (ResourceRef("area", "5", 7), ResourceRef("area", "A2", 7)),
        )

    def test_a_condition_edit_depends_on_the_new_and_the_replaced_conditions(self):
        handler, write, data, undo = self._handler()
        handler.on_reassign_condition(["t1"], "c9")
        self.assertEqual(write.local_property_options[0]["kind"], "takeoff_condition")
        self.assertEqual(write.local_property_options[0]["page_uids"], ("p1",))
        self.assertEqual(
            write.local_property_options[0]["dependency_resources"],
            (ResourceRef("condition", "c1", 7), ResourceRef("condition", "c9", 7)),
        )
        undo.undo()
        self.assertEqual(
            write.local_property_options[1]["dependency_resources"],
            write.local_property_options[0]["dependency_resources"],
        )

    def test_a_curve_edit_is_scoped_to_its_pages(self):
        handler, write, data, undo = self._handler()
        handler.on_set_curved(["t1", "t2"], False)
        self.assertEqual(write.local_property_options[0]["kind"], "takeoff_curve")
        self.assertEqual(write.local_property_options[0]["page_uids"], ("p1", "9"))
        self.assertEqual(write.local_property_options[0]["publish"], False)

    def test_a_condition_text_edit_is_scoped_to_its_pages(self):
        handler, write, data, undo = self._handler()
        handler.on_condition_text_properties_flushed(
            [("t2", "name", {"name_font_bold": False}, {"name_font_bold": True})]
        )
        self.assertEqual(write.local_property_options[0]["kind"], "takeoff_text")
        self.assertEqual(write.local_property_options[0]["page_uids"], ("9",))


class _SqlFlowFixture(_PlanViewActionHandlerFixture):
    """Six SQL flows (geometry, property, delete, paste, annotation insert, placement)
    that can be started twice (operation A on t1/source-A, operation B on t2/source-B),
    delivered by hand and replayed through the REAL UndoRedoService."""

    FLOWS = ("geometry", "properties", "delete", "paste", "annotation", "placement")

    def _flow_setup(self):
        data = FakeProjectData()
        for uid in ("t1", "t2"):
            data.takeoffs[uid] = Takeoff(
                uid=uid,
                condition_uid="c1",
                page_uid="p1",
                position=[0.0, 0.0],
                is_negative=False,
            )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = UndoRedoService()
        undo.set_active_bid(BidRef("bid.mdb", "7"))
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def _start(self, name, which, handler, plan_view, write, data):
        """Start operation A or B of a flow; returns (deliver, undo_signature)."""
        index = 0 if which == "A" else 1
        uid = ("t1", "t2")[index]
        if name == "geometry":
            handler.on_positions_flushed([(uid, [0.0, 0.0], [5.0, 6.0])], [])
            callback = write.queued_geometry[-1][-1]
            return (
                lambda: callback(_committed()),
                lambda: write.queued_geometry[-1][2]["takeoff_positions"][0][0],
            )
        if name == "properties":
            handler.on_set_negative([uid], True)
            callback = write.queued_properties[-1][-1]
            return (
                lambda: callback(_committed()),
                lambda: write.queued_properties[-1][3][0][0],
            )
        if name == "delete":
            handler.on_elements_deleted([uid])
            callback = write.queued_deletes[-1][-1]
            return (
                lambda: callback(_committed()),
                lambda: write.queued_pastes[-1][1].takeoff_source_uids[0],
            )
        if name == "paste":
            source = Takeoff(
                uid=f"source-{which}",
                condition_uid="c1",
                page_uid="source-page",
                position=[10.0, 20.0],
            )
            handler._clipboard_svc = FakeClipboard([source])
            handler.on_paste_requested()
            callback = write.queued_pastes[-1][-1]
            return (
                lambda: callback(
                    _committed(
                        maps=(("takeoffs", ((f"source-{which}", f"new-{which}"),)),)
                    )
                ),
                lambda: write.queued_deletes[-1][2][0],
            )
        if name == "annotation":
            handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
            payload, callback = write.queued_pastes[-1][1], write.queued_pastes[-1][-1]

            def deliver():
                data.annotations.append(
                    BidAnnotation(
                        uid=f"annotation-{which}", annotation_type="rect", page_uid="p1"
                    )
                )
                callback(
                    _committed(
                        maps=(
                            (
                                "annotations",
                                (
                                    (
                                        payload.annotation_source_uids[0],
                                        f"annotation-{which}",
                                    ),
                                ),
                            ),
                        )
                    )
                )

            return deliver, lambda: write.queued_deletes[-1][3][0][0]
        handler.on_takeoff_created("42", [1.0, 2.0], "p1")
        operation_id, callback = write.queued_takeoff_callbacks[-1]

        def deliver():
            data.add_takeoffs(
                [
                    Takeoff(
                        uid=f"row-{which}",
                        condition_uid="42",
                        page_uid="p1",
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
                    created_resource_ids=(f"row-{which}",),
                )
            )

        return deliver, lambda: write.queued_deletes[-1][2][0]


class PlanViewActionHandlerForwardOrderingTests(_SqlFlowFixture):
    """History keeps submission order for every flow, and a forward mutation whose
    Page was replaced before it committed records nothing."""

    EXPECTED_UNDO_OF_B = {
        "geometry": "t2",
        "properties": "t2",
        "delete": "t2",
        "paste": "new-B",
        "annotation": "annotation-B",
        "placement": "row-B",
    }

    def test_the_last_submitted_operation_is_undone_first_whatever_the_completion_order(
        self,
    ):
        for name in self.FLOWS:
            with self.subTest(flow=name):
                handler, plan_view, write, data, undo = self._flow_setup()
                _deliver_a, _ = self._start(name, "A", handler, plan_view, write, data)
                deliver_b, signature = self._start(
                    name, "B", handler, plan_view, write, data
                )
                self.assertFalse(undo.can_undo())
                deliver_b()
                self.assertFalse(undo.can_undo())
                _deliver_a()
                self.assertTrue(undo.can_undo())
                undo.undo()
                self.assertEqual(signature(), self.EXPECTED_UNDO_OF_B[name])

    def test_a_commit_on_a_replaced_page_records_no_history(self):
        for name in ("geometry", "properties", "delete", "paste", "annotation"):
            with self.subTest(flow=name):
                handler, plan_view, write, data, undo = self._flow_setup()
                deliver, _signature = self._start(
                    name, "A", handler, plan_view, write, data
                )
                data.pages["p1"] = SimpleNamespace(
                    uid="p1", overlay_rect=None, scale_factor1=1.0, scale_factor2=1.0
                )
                deliver()
                self.assertFalse(undo.can_undo())
                self.assertEqual(undo._forward_mutations, {})


class PlanViewActionHandlerLateCompletionTests(_SqlFlowFixture):
    """A completion delivered after the handler is gone does nothing, and a queue that
    fails for another reason than the Bid lock frees the forward-mutation token."""

    def test_a_completion_after_the_handler_is_gone_is_ignored(self):
        for name in self.FLOWS:
            for status in (
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.CONFLICT,
            ):
                with self.subTest(flow=name, status=status.name):
                    handler, plan_view, write, data, undo = self._flow_setup()
                    self._start(name, "A", handler, plan_view, write, data)
                    pending = set(plan_view.pending_mutation_uids)
                    callback = {
                        "geometry": lambda: write.queued_geometry[-1][-1],
                        "properties": lambda: write.queued_properties[-1][-1],
                        "delete": lambda: write.queued_deletes[-1][-1],
                        "paste": lambda: write.queued_pastes[-1][-1],
                        "annotation": lambda: write.queued_pastes[-1][-1],
                        "placement": lambda: write.queued_takeoff_callbacks[-1][1],
                    }[name]()
                    operation_id = (
                        write.queued_takeoff_callbacks[-1][0]
                        if name == "placement"
                        else str(uuid.uuid4())
                    )
                    reference = weakref.ref(handler)
                    del handler
                    self.assertIsNone(reference())
                    callback(
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=3,
                            operation_id=operation_id,
                            outcome_status=status,
                            created_resource_ids=(
                                ("1",)
                                if status == MutationOutcomeStatus.COMMITTED
                                else ()
                            ),
                        )
                    )
                    self.assertEqual(plan_view.pending_mutation_uids, pending)
                    self.assertFalse(undo.can_undo())

    def test_a_queue_failure_other_than_the_lock_frees_the_forward_token(self):
        cases = {
            "geometry": (
                "queue_plan_geometry",
                lambda h: h.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], []),
            ),
            "delete": (
                "queue_plan_items_delete",
                lambda h: h.on_elements_deleted(["t1"]),
            ),
            "annotation": (
                "queue_plan_items_paste",
                lambda h: h.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1"),
            ),
            "paste": (
                "queue_plan_items_paste",
                lambda h: (
                    setattr(
                        h, "_clipboard_svc", FakeClipboard([self._copied_takeoff()])
                    ),
                    h.on_paste_requested(),
                ),
            ),
        }
        for name, (method, act) in cases.items():
            with self.subTest(flow=name):
                handler, plan_view, write, data, undo = self._flow_setup()

                def broken(*args, **kwargs):
                    raise RuntimeError("queue unavailable")

                setattr(write, method, broken)
                with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                    act(handler)
                self.assertEqual(undo._forward_mutations, {})
                self.assertTrue(undo.can_undo() is False)

    def test_a_property_queue_failure_other_than_the_lock_restores_the_edit(self):
        handler, plan_view, write, data, undo = self._flow_setup()
        plan_view.selected = {"t1"}

        def broken(*args, **kwargs):
            raise RuntimeError("queue unavailable")

        write.queue_plan_properties = broken
        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            handler.on_set_negative(["t1"], True)
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo._forward_mutations, {})
        self.assertEqual(plan_view.selected, {"t1"})

    def test_a_property_edit_ends_a_held_geometry_lease(self):
        handler, plan_view, write, data, undo = self._flow_setup()
        plan_view.selected = {"t1"}
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = PlanViewActionHandlerGeometryLeaseLifecycleTests._grant(
            write
        )
        callback(EditLeaseResult(True, handle=handle))
        handler.on_set_negative(["t2"], True)
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())


class PlanViewActionHandlerSqlGeometrySelectionTests(_PlanViewActionHandlerFixture):
    """The selection and preview a SQL geometry write hands back at its terminal result
    (the optimistic edit leaves the selection cleared; the completion restores it by
    typed identity)."""

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_rect": annotation}
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.selected = {"t1", "a1_rect"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo

    @staticmethod
    def _changes():
        return (
            [("t1", [0.0, 0.0], [5.0, 6.0])],
            [("a1", "rect", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])],
        )

    def test_a_failed_move_restores_the_preview_and_the_selection_by_identity(self):
        handler, plan_view, write, undo = self._handler()
        takeoff_changes, annotation_changes = self._changes()
        handler.on_positions_flushed(takeoff_changes, annotation_changes)
        plan_view.selected = set()
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect_rekeyed"}
        write.queued_geometry[0][-1](_failed())
        self.assertEqual(
            plan_view.restored_positions, [(takeoff_changes, annotation_changes)]
        )
        self.assertEqual(plan_view.selected, {"t1", "a1_rect_rekeyed"})
        self.assertEqual(undo.count, 0)

    def test_a_committed_move_restores_the_selection_and_records_history_once(self):
        handler, plan_view, write, undo = self._handler()
        takeoff_changes, annotation_changes = self._changes()
        handler.on_positions_flushed(takeoff_changes, annotation_changes)
        plan_view.selected = set()
        write.queued_geometry[0][-1](_committed())
        self.assertEqual(plan_view.selected, {"t1", "a1_rect"})
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(undo.count, 1)

    def test_a_failed_annotation_only_move_restores_the_annotation_preview(self):
        handler, plan_view, write, undo = self._handler()
        _takeoff_changes, annotation_changes = self._changes()
        handler.on_positions_flushed([], annotation_changes)
        write.queued_geometry[0][-1](_failed())
        self.assertEqual(plan_view.restored_positions, [([], annotation_changes)])
        self.assertEqual(plan_view.restored_rotations, [])

    def test_a_failed_rotation_only_move_restores_only_the_rotation_preview(self):
        handler, plan_view, write, undo = self._handler()
        handler.on_rotations_flushed([("t1", 0.0, 90.0)])
        write.queued_geometry[0][-1](_failed())
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.restored_rotations, [[("t1", 0.0, 90.0)]])

    def test_a_failed_move_without_edit_access_restores_the_selection_only(self):
        handler, plan_view, write, undo = self._handler()
        takeoff_changes, annotation_changes = self._changes()
        handler.on_positions_flushed(takeoff_changes, annotation_changes)
        plan_view.selected = set()
        handler._ui_access_manager.allowed_features.discard(Feature.EDIT_PLAN_ITEMS)
        write.queued_geometry[0][-1](_failed())
        self.assertEqual(plan_view.restored_positions, [])
        self.assertEqual(plan_view.selected, {"t1", "a1_rect"})


class PlanViewActionHandlerGeometryWriteLeaseTests(_PlanViewActionHandlerFixture):
    """A geometry write consumes the held lease only if it covers exactly the leased
    resources and dependencies; otherwise the lease is ended and the write is queued
    without it."""

    def _handler(self):
        data = FakeProjectData()
        for uid in ("t1", "t3"):
            data.takeoffs[uid] = Takeoff(
                uid=uid, condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
            )
        plan_view = FakePlanView(data)
        plan_view.selected = {"t1"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = PlanViewActionHandlerGeometryLeaseLifecycleTests._grant(
            write
        )
        callback(EditLeaseResult(True, handle=handle))
        return handler, plan_view, write, data, handle

    def test_the_lease_is_consumed_by_a_write_on_exactly_its_resources(self):
        handler, plan_view, write, data, handle = self._handler()
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertIs(write.queued_geometry[0][2]["edit_lease_handle"], handle)
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(handler._geometry_edit_lease_selection, set())
        self.assertEqual(handler._geometry_edit_lease_request_id, "")
        self.assertEqual(plan_view.geometry_lease_granted, set())

    def test_other_resources_with_the_same_dependencies_do_not_reuse_the_lease(self):
        handler, plan_view, write, data, handle = self._handler()
        handler.on_positions_flushed([("t3", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(write.queued_geometry[0][2]["edit_lease_handle"])

    def test_the_same_resources_with_other_dependencies_do_not_reuse_the_lease(self):
        handler, plan_view, write, data, handle = self._handler()
        data.takeoffs["t1"].condition_uid = "c9"
        handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(write.queued_geometry[0][2]["edit_lease_handle"])


class PlanViewActionHandlerPageScopeTests(_PlanViewActionHandlerFixture):
    """Items that cannot name a Page (unknown takeoff, empty page uid) never put a
    page into the scope of a write."""

    def _data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.takeoffs["nopage"] = Takeoff(
            uid="nopage", condition_uid="c1", page_uid="", position=[0.0, 0.0]
        )
        return data

    def test_the_sql_geometry_scope_skips_unknown_and_pageless_takeoffs(self):
        data = self._data()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data
        )
        handler.on_positions_flushed(
            [
                ("t1", [0.0, 0.0], [5.0, 6.0]),
                ("ghost", [0.0, 0.0], [5.0, 6.0]),
                ("nopage", [0.0, 0.0], [5.0, 6.0]),
            ],
            [],
        )
        self.assertEqual(write.queued_geometry[0][2]["page_uids"], ("p1",))

    def test_the_local_geometry_scope_skips_pageless_takeoffs_and_unlisted_annotations(
        self,
    ):
        data = self._data()
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        ]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        write = FakeWriteService()
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_positions_flushed(
            [("nopage", [0.0, 0.0], [5.0, 6.0])],
            [("a1", "rect", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])],
        )
        self.assertEqual(write.local_geometry[0][5]["page_uids"], ())

    def test_the_local_property_scope_skips_pageless_takeoffs(self):
        data = self._data()
        write = _OptionRecordingWriteService()
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data
        )
        handler.on_set_negative(["t1", "nopage"], True)
        self.assertEqual(write.local_property_options[0]["page_uids"], ("p1",))


class PlanViewActionHandlerCommandTakeoffTests(_PlanViewActionHandlerFixture):
    """_command_takeoff: the Takeoff a command works on."""

    def test_the_plan_view_object_wins_then_the_data_service_answers(self):
        data = FakeProjectData()
        persisted = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        shown = Takeoff(uid="t1", condition_uid="c1", page_uid="p1")
        data.takeoffs["t1"] = persisted
        data.takeoffs["t2"] = Takeoff(uid="t2", condition_uid="c1", page_uid="p1")
        plan_view = FakePlanView()
        plan_view.get_takeoff = lambda uid: shown if uid == "t1" else None
        handler = self._paste_handler(plan_view=plan_view, data=data)
        self.assertIs(handler._command_takeoff("t1"), shown)
        self.assertIs(handler._command_takeoff("t2"), data.takeoffs["t2"])
        self.assertIsNone(handler._command_takeoff("missing"))

    def test_a_queued_preview_is_never_a_command_target(self):
        data = FakeProjectData()
        preview_uid = "pending:takeoff-placement:" + str(uuid.uuid4()) + ":0"
        preview = Takeoff(uid=preview_uid, condition_uid="c1", page_uid="p1")
        data.takeoffs[preview_uid] = preview
        plan_view = FakePlanView(data)
        handler = self._paste_handler(plan_view=plan_view, data=data)
        self.assertIsNone(handler._command_takeoff(preview_uid))
        self.assertEqual(handler._takeoff_uids_only([preview_uid, "nothing"]), [])


class _PayloadValidatingWriteService(FakeWriteService):
    """FakeWriteService whose SQL queue entries build the REAL payload DTOs first, like
    ProjectWriteService does (non-empty payloads, valid identities, a numeric Bid uid,
    JSON-serialisable property updates, known property kinds), so a handler call the
    real service would reject fails here as well."""

    def __init__(self):
        super().__init__()
        self.sql_collaboration_mutations = True
        self.validated = []
        self.callbacks = []

    def queue_plan_geometry(self, database_id, bid_uid, callback, **options):
        int(bid_uid)
        self.callbacks.append(callback)
        PlanGeometryPayload(
            takeoff_positions=tuple(
                (str(uid), tuple(float(v) for v in position))
                for uid, position in options.get("takeoff_positions", ())
            ),
            takeoff_rotations=tuple(
                (str(uid), float(rotation))
                for uid, rotation in options.get("takeoff_rotations", ())
            ),
            annotation_positions=tuple(
                (str(uid), str(kind), tuple(float(v) for v in position))
                for uid, kind, position in options.get("annotation_positions", ())
            ),
        )
        self.validated.append("geometry")
        return super().queue_plan_geometry(database_id, bid_uid, callback, **options)

    def queue_plan_properties(
        self, database_id, bid_uid, kind, updates, callback, **options
    ):
        int(bid_uid)
        self.callbacks.append(callback)
        PlanPropertyPayload.from_updates(kind, updates)
        self.validated.append(kind)
        return super().queue_plan_properties(
            database_id, bid_uid, kind, updates, callback, **options
        )

    def queue_plan_items_delete(
        self, database_id, bid_uid, takeoff_uids, annotations, callback, **options
    ):
        int(bid_uid)
        self.callbacks.append(callback)
        PlanItemsDeletePayload(
            takeoff_uids=tuple(takeoff_uids), annotations=tuple(annotations)
        )
        self.validated.append("delete")
        return super().queue_plan_items_delete(
            database_id, bid_uid, takeoff_uids, annotations, callback, **options
        )

    def queue_plan_items_paste(self, database_id, payload, callback, **options):
        self.callbacks.append(callback)
        PlanItemsPastePayload(
            **{
                field.name: getattr(payload, field.name)
                for field in dataclasses.fields(payload)
            }
        )
        self.validated.append("paste")
        return super().queue_plan_items_paste(database_id, payload, callback, **options)

    def queue_takeoff_placement(
        self, database_id, bid_uid, specs, operation_id, callback
    ):
        int(bid_uid)
        self.callbacks.append(callback)
        if not specs:
            raise ValueError("A queued takeoff placement requires at least one takeoff")
        self.validated.append("placement")
        return super().queue_takeoff_placement(
            database_id, bid_uid, specs, operation_id, callback
        )


class PlanViewActionHandlerRealPayloadContractTests(_PlanViewActionHandlerFixture):
    """Every SQL entry point of the handler (and every history replay it registers)
    feeds the write service payloads the real DTOs accept."""

    def _handler(self):
        data = FakeProjectData()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            area_uid="5",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            rotation=0.0,
        )
        data.takeoffs["t2"] = Takeoff(
            uid="t2",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0],
            parent_uid="0",
        )
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            position=[1.0, 1.0, 20.0, 5.0],
            properties={"Text": "x"},
            layer_uid="L1",
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_text": annotation}
        plan_view.annotation_key_map = {("a1", "text"): "a1_text"}
        write = _PayloadValidatingWriteService()
        undo = UndoRedoService()
        undo.set_active_bid(BidRef("bid.mdb", "7"))
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler._page_settings_bar = SimpleNamespace(get_current_area_uid=lambda: "A2")
        return handler, plan_view, write, data, undo

    def test_every_geometry_and_property_entry_point_passes_the_real_dtos(self):
        handler, plan_view, write, data, undo = self._handler()
        steps = (
            lambda: handler.on_positions_flushed(
                [
                    (
                        "t1",
                        [0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
                        [1.0, 1.0, 11.0, 1.0, 11.0, 11.0],
                    )
                ],
                [("a1", "text", [1.0, 1.0, 20.0, 5.0], [2.0, 2.0, 20.0, 5.0])],
            ),
            lambda: handler.on_rotations_flushed([("t1", 0.0, 90.0)]),
            lambda: handler.on_group_rotation_flushed(
                [("t2", [0.0, 0.0, 10.0, 0.0], [1.0, 0.0, 11.0, 0.0])],
                [],
                [("t2", 0.0, 45.0)],
            ),
            lambda: handler.on_assign_to_area(["t1"]),
            lambda: handler.on_reassign_condition(["t1"], "c9"),
            lambda: handler.on_set_negative(["t1"], True),
            lambda: handler.on_set_curved(["t2"], True),
            lambda: handler.on_condition_text_properties_flushed(
                [("t1", "name", {"name_font_bold": False}, {"name_font_bold": True})]
            ),
            lambda: handler.on_annotation_text_properties_flushed(
                [("a1", "text", {"Text": "x"}, {"Text": "y"})]
            ),
            lambda: handler.on_annotation_styles_flushed(
                [
                    (
                        "a1",
                        "text",
                        {"Color": "#000000", "Width": 1.0},
                        {"Color": "#112233", "Width": 2.0},
                    )
                ]
            ),
        )
        for step in steps:
            step()
            write.callbacks[-1](_committed())
        self.assertEqual(
            write.validated,
            [
                "geometry",
                "geometry",
                "geometry",
                "takeoff_area",
                "takeoff_condition",
                "takeoff_negative",
                "takeoff_curve",
                "takeoff_text",
                "annotation_text",
                "annotation_style",
            ],
        )
        for _ in steps:
            self.assertTrue(undo.can_undo())
            undo.undo()
            write.callbacks[-1](_committed())
        for _ in steps:
            self.assertTrue(undo.can_redo())
            undo.redo()
            write.callbacks[-1](_committed())
        self.assertEqual(len(write.validated), 30)

    def test_deletes_pastes_and_placements_pass_the_real_dtos_and_replay(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["t1", "a1_text"])
        write.callbacks[-1](_committed())
        handler._clipboard_svc = FakeClipboard(
            [
                Takeoff(
                    uid="src",
                    condition_uid="c1",
                    page_uid="source-page",
                    position=[1.0, 2.0],
                )
            ],
            annotations=[
                BidAnnotation(
                    uid="srca",
                    annotation_type="rect",
                    page_uid="source-page",
                    position=[1.0, 2.0, 3.0, 4.0],
                )
            ],
        )
        handler.on_paste_requested()
        write.queued_pastes[-1][-1](
            _committed(
                maps=(
                    ("takeoffs", (("src", "n1"),)),
                    ("annotations", (("rect/srca", "na1"),)),
                )
            )
        )
        handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
        handler.on_takeoff_created("42", [1.0, 2.0], "p1")
        handler.on_hole_created("c1", [1.0, 1.0, 2.0, 2.0], "p1", "t2")
        self.assertEqual(
            write.validated, ["delete", "paste", "paste", "placement", "placement"]
        )


def _write_count(write):
    """Every write or queue call a FakeWriteService recorded (any entry point)."""
    names = (
        "calls",
        "position_calls",
        "rotation_calls",
        "text_property_calls",
        "area_calls",
        "condition_calls",
        "negative_calls",
        "delete_calls",
        "curve_calls",
        "local_geometry",
        "local_properties",
        "local_deletes",
        "local_pastes",
        "queued_geometry",
        "queued_properties",
        "queued_deletes",
        "queued_pastes",
        "queued_takeoff_callbacks",
    )
    return sum(len(getattr(write, name)) for name in names)


class PlanViewActionHandlerCommandGuardTests(_PlanViewActionHandlerFixture):
    """The preconditions of the property commands (area, condition, negative, curve):
    each missing precondition makes the command a silent no-op, in the Access (local)
    and in the SQL (queued) mode, and a positive control proves the command writes."""

    PREVIEW = "pending:takeoff-placement:00000000-0000-4000-8000-000000000000:0"
    COMMANDS = {
        "assign to area": lambda h, uid: h.on_assign_to_area([uid]),
        "reassign condition": lambda h, uid: h.on_reassign_condition([uid], "c9"),
        "set negative": lambda h, uid: h.on_set_negative([uid], True),
        "set curved": lambda h, uid: h.on_set_curved([uid], True),
    }

    def _handler(self, sql):
        data = FakeProjectData()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            area_uid="5",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        data.takeoffs[self.PREVIEW] = Takeoff(
            uid=self.PREVIEW,
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, write, data, undo

    def test_every_missing_precondition_makes_the_command_a_no_op(self):
        breakers = {
            "no access": lambda h, d: h._ui_access_manager.allowed_features.discard(
                Feature.EDIT_PLAN_ITEMS
            ),
            "no database": lambda h, d: setattr(
                d, "get_current_bid_file_path", lambda: ""
            ),
            "no bid": lambda h, d: setattr(
                h,
                "_ui_state",
                SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                ),
            ),
        }
        for sql in (False, True):
            for command_name, command in self.COMMANDS.items():
                handler, write, data, undo = self._handler(sql)
                command(handler, "t1")
                self.assertEqual(
                    len(write.queued_properties if sql else write.local_properties),
                    1,
                    (command_name, sql, "control"),
                )
                self.assertEqual(
                    len(write.queued_properties) + len(write.local_properties), 1
                )
                for breaker_name, breaker in breakers.items():
                    with self.subTest(
                        command=command_name, sql=sql, missing=breaker_name
                    ):
                        handler, write, data, undo = self._handler(sql)
                        breaker(handler, data)
                        command(handler, "t1")
                        self.assertEqual(_write_count(write), 0)
                        self.assertEqual(undo.count, 0)
                for uid in ("missing", self.PREVIEW):
                    with self.subTest(command=command_name, sql=sql, uid=uid[:7]):
                        handler, write, data, undo = self._handler(sql)
                        command(handler, uid)
                        self.assertEqual(_write_count(write), 0)
                        self.assertEqual(undo.count, 0)

    def test_the_page_scope_lists_each_known_page_once(self):
        for command_name, command in self.COMMANDS.items():
            with self.subTest(command=command_name):
                handler, write, data, undo = self._handler(True)
                data.takeoffs["t2"] = Takeoff(
                    uid="t2",
                    condition_uid="c1",
                    page_uid="p1",
                    area_uid="5",
                    position=[1.0, 1.0, 5.0, 1.0],
                )
                data.takeoffs["t3"] = Takeoff(
                    uid="t3",
                    condition_uid="c1",
                    page_uid="9",
                    area_uid="5",
                    position=[1.0, 1.0, 5.0, 1.0],
                )
                command_uids = ["t1", "t2", "t3"]
                {
                    "assign to area": lambda: handler.on_assign_to_area(command_uids),
                    "reassign condition": lambda: handler.on_reassign_condition(
                        command_uids, "c9"
                    ),
                    "set negative": lambda: handler.on_set_negative(command_uids, True),
                    "set curved": lambda: handler.on_set_curved(command_uids, True),
                }[command_name]()
                self.assertEqual(
                    write.queued_properties[0][4]["page_uids"], ("p1", "9")
                )

    def test_commands_do_not_scope_a_write_to_an_empty_page_uid(self):
        for command_name in ("assign to area", "reassign condition", "set negative"):
            with self.subTest(command=command_name):
                handler, write, data, undo = self._handler(True)
                data.takeoffs["t4"] = Takeoff(
                    uid="t4",
                    condition_uid="c1",
                    page_uid="",
                    area_uid="5",
                    position=[1.0, 1.0, 5.0, 1.0],
                )
                uids = ["t1", "t4"]
                {
                    "assign to area": lambda: handler.on_assign_to_area(uids),
                    "reassign condition": lambda: handler.on_reassign_condition(
                        uids, "c9"
                    ),
                    "set negative": lambda: handler.on_set_negative(uids, True),
                }[command_name]()
                self.assertEqual(write.queued_properties[0][4]["page_uids"], ("p1",))

    def test_a_takeoff_without_an_area_replays_as_the_empty_area(self):
        handler, write, data, undo = self._handler(True)
        data.takeoffs["t1"].area_uid = None
        handler._page_settings_bar = SimpleNamespace(get_current_area_uid=lambda: "A2")
        handler.on_assign_to_area(["t1"])
        write.queued_properties[0][-1](_committed())
        undo.undo()
        self.assertEqual(write.queued_properties[0][3], [("t1", "A2")])
        self.assertEqual(write.queued_properties[1][3], [("t1", "")])

    def test_curving_skips_takeoffs_without_a_segment_and_keeps_only_its_end_points(
        self,
    ):
        handler, write, data, undo = self._handler(True)
        data.takeoffs["short"] = Takeoff(
            uid="short", condition_uid="c1", page_uid="9", position=[1.0, 2.0, 3.0]
        )
        data.takeoffs["empty"] = Takeoff(
            uid="empty", condition_uid="c1", page_uid="9", position=[]
        )
        data.takeoffs["curved"] = Takeoff(
            uid="curved",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 5.0, 5.0, 3.0],
            curve=Takeoff.CURVE_ENABLED,
        )
        handler.on_set_curved(["short", "empty", "curved"], True)
        _db, _bid, kind, updates, options, _callback = write.queued_properties[0]
        self.assertEqual(kind, "takeoff_curve")
        self.assertEqual(
            updates,
            [("curved", [0.0, 0.0, 10.0, 0.0, 5.0, 0.0, 0.0], Takeoff.CURVE_ENABLED)],
        )
        self.assertEqual(options["page_uids"], ("p1",))

    def test_nothing_is_queued_when_no_takeoff_can_be_curved(self):
        handler, write, data, undo = self._handler(True)
        data.takeoffs["short"] = Takeoff(
            uid="short", condition_uid="c1", page_uid="9", position=[1.0, 2.0, 3.0]
        )
        handler.on_set_curved(["short"], True)
        self.assertEqual(_write_count(write), 0)
        handler, write, data, undo = self._handler(False)
        data.takeoffs["short"] = Takeoff(
            uid="short", condition_uid="c1", page_uid="9", position=[1.0, 2.0, 3.0]
        )
        handler.on_set_curved(["short"], True)
        self.assertEqual(_write_count(write), 0)
        self.assertEqual(undo.count, 0)

    def test_reassigning_ignores_takeoffs_whose_condition_is_unknown_when_expanding_areas(
        self,
    ):
        handler, write, data, undo = self._handler(True)
        data.takeoffs["orphan"] = Takeoff(
            uid="orphan",
            condition_uid="no-such-condition",
            page_uid="p1",
            parent_uid="t1",
            position=[1.0, 1.0, 5.0, 1.0],
        )
        handler.on_reassign_condition(["t1"], "c9")
        self.assertEqual(write.queued_properties[0][3], [("t1", "c9")])


class PlanViewActionHandlerInterimOutcomeTests(_SqlFlowFixture):
    """Uncertain-commit recovery: COMMIT_STATUS_UNKNOWN and COMMITTED_PROJECTION_FAILED
    never end a forward mutation; the terminal result that follows does."""

    CALLBACKS = {
        "geometry": lambda w: w.queued_geometry[-1][-1],
        "properties": lambda w: w.queued_properties[-1][-1],
        "delete": lambda w: w.queued_deletes[-1][-1],
        "paste": lambda w: w.queued_pastes[-1][-1],
        "annotation": lambda w: w.queued_pastes[-1][-1],
        "placement": lambda w: w.queued_takeoff_callbacks[-1][1],
    }

    def test_interim_outcomes_leave_every_flow_pending_and_blocking_history(self):
        for name in self.FLOWS:
            for status in (
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            ):
                with self.subTest(flow=name, status=status.name):
                    handler, plan_view, write, data, undo = self._flow_setup()
                    deliver, _signature = self._start(
                        name, "A", handler, plan_view, write, data
                    )
                    pending = set(plan_view.pending_mutation_uids)
                    operation_id = (
                        write.queued_takeoff_callbacks[-1][0]
                        if name == "placement"
                        else str(uuid.uuid4())
                    )
                    self.CALLBACKS[name](write)(
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=3,
                            operation_id=operation_id,
                            outcome_status=status,
                            commit_attempted=True,
                        )
                    )
                    self.assertEqual(plan_view.pending_mutation_uids, pending)
                    self.assertEqual(plan_view.restored_positions, [])
                    self.assertEqual(plan_view.restored_rotations, [])
                    self.assertEqual(len(undo._forward_mutations), 1)
                    self.assertFalse(undo.can_undo())
                    deliver()
                    self.assertEqual(undo._forward_mutations, {})
                    self.assertTrue(undo.can_undo())

    def test_a_property_edit_without_a_restore_callback_still_restores_the_selection(
        self,
    ):
        handler, plan_view, write, data, undo = self._flow_setup()
        plan_view.selected = {"t1"}
        complete, _abort = handler.prepare_sql_property_completion(
            BidRef("bid.mdb", "7"),
            "takeoff_negative",
            [("t1", True)],
            old_updates=[("t1", False)],
            plan_uids={"t1"},
            takeoff_uids={"t1"},
            page_uids=("p1",),
        )
        plan_view.selected = set()
        complete(_failed())
        self.assertEqual(plan_view.selected, {"t1"})

    def test_a_failed_property_edit_does_not_restore_the_editor_without_edit_access(
        self,
    ):
        handler, plan_view, write, data, undo = self._flow_setup()
        restored = []
        complete, _abort = handler.prepare_sql_property_completion(
            BidRef("bid.mdb", "7"),
            "takeoff_negative",
            [("t1", True)],
            old_updates=[("t1", False)],
            plan_uids={"t1"},
            takeoff_uids={"t1"},
            page_uids=("p1",),
            restore=lambda: restored.append(True),
        )
        handler._ui_access_manager.allowed_features.discard(Feature.EDIT_PLAN_ITEMS)
        complete(_failed())
        self.assertEqual(restored, [])
        self.assertEqual(plan_view.pending_mutation_uids, set())

    def test_a_property_completion_without_history_updates_records_nothing(self):
        handler, plan_view, write, data, undo = self._flow_setup()
        complete, _abort = handler.prepare_sql_property_completion(
            BidRef("bid.mdb", "7"),
            "takeoff_negative",
            [("t1", True)],
            plan_uids={"t1"},
            takeoff_uids={"t1"},
            page_uids=("p1",),
        )
        complete(_committed())
        self.assertFalse(undo.can_undo())
        self.assertEqual(undo._forward_mutations, {})


class PlanViewActionHandlerHistoryParentTests(_PlanViewActionHandlerFixture):
    """A history entry that restores or re-pastes a Backout whose parent lives outside
    the entry follows that parent's CURRENT identity and refuses to run when the
    parent is no longer what the entry captured."""

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["H"] = Takeoff(
            uid="H",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="P",
            is_negative=True,
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    @staticmethod
    def _replace_parent(data, undo, new_uid):
        parent_targets = [t for t in undo.takeoff_targets if t.uid == "P"]
        assert len(parent_targets) == 1
        data.takeoffs[new_uid] = replace(data.takeoffs.pop("P"), uid=new_uid)
        parent_targets[0].uid = new_uid

    def _deleted_hole(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["H"])
        write.queued_deletes[0][-1](_committed())
        return handler, plan_view, write, data, undo

    def test_a_restored_backout_follows_the_current_identity_of_its_surviving_parent(
        self,
    ):
        handler, plan_view, write, data, undo = self._deleted_hole()
        self.assertEqual(write.queued_deletes[0][2], ["H"])
        self._replace_parent(data, undo, "P2")
        undo.undo()
        payload = write.queued_pastes[0][1]
        self.assertEqual(payload.takeoff_source_uids, ("H",))
        self.assertEqual(payload.takeoff_specs[0].parent_uid, "P2")
        self.assertEqual(payload.takeoff_external_parent_sources, ("H",))

    def test_a_restored_backout_with_an_unchanged_parent_keeps_the_parent_uid(self):
        handler, plan_view, write, data, undo = self._deleted_hole()
        undo.undo()
        payload = write.queued_pastes[0][1]
        self.assertEqual(payload.takeoff_specs[0].parent_uid, "P")
        self.assertEqual(payload.takeoff_external_parent_sources, ("H",))

    def test_the_restore_refuses_to_run_when_the_parent_target_is_unavailable(self):
        handler, plan_view, write, data, undo = self._deleted_hole()
        for target in undo.takeoff_targets:
            if target.uid == "P":
                target.available = False
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()
        self.assertEqual(write.queued_pastes, [])

    def test_a_parent_that_moved_to_another_page_refuses_the_restore(self):
        handler, plan_view, write, data, undo = self._deleted_hole()
        data.takeoffs["P"].page_uid = "9"
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()

    def test_a_deleted_family_needs_no_parent_target(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["P"])
        write.queued_deletes[0][-1](_committed())
        self.assertEqual({t.uid for t in undo.takeoff_targets}, {"P", "H"})
        undo.undo()
        payload = write.queued_pastes[0][1]
        self.assertEqual(payload.takeoff_source_uids, ("P", "H"))
        self.assertEqual(payload.takeoff_external_parent_sources, ())
        self.assertEqual(
            [spec.parent_uid for spec in payload.takeoff_specs], ["0", "P"]
        )

    def _pasted_backout(self, internal):
        handler, plan_view, write, data, undo = self._handler()
        handler._clipboard_svc = FakeClipboard([], source_bid_uid="7")
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "c1",
                    "page_uid": "p1",
                    "position": [2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
                    "parent_uid": "P",
                    "rotation": 0.0,
                    "is_negative": True,
                    "extras": {},
                    "source_uid": "src-hole",
                    "parent_is_internal": internal,
                }
            ],
            "7",
        )
        write.queued_pastes[0][-1](
            _committed(maps=(("takeoffs", (("src-hole", "H2"),)), ("annotations", ())))
        )
        return handler, plan_view, write, data, undo

    def test_a_pasted_backout_replays_against_the_current_identity_of_its_existing_parent(
        self,
    ):
        handler, plan_view, write, data, undo = self._pasted_backout(False)
        self.assertEqual(
            write.queued_pastes[0][1].takeoff_external_parent_sources, ("src-hole",)
        )
        self._replace_parent(data, undo, "P2")
        undo.undo()
        write.queued_deletes[0][-1](_committed())
        undo.redo()
        redo_payload = write.queued_pastes[1][1]
        self.assertEqual(redo_payload.takeoff_specs[0].parent_uid, "P2")
        self.assertEqual(redo_payload.takeoff_external_parent_sources, ("src-hole",))


class PlanViewActionHandlerPlacementGuardTests(_PlanViewActionHandlerFixture):
    """The placement gestures (takeoff, Backout, annotation, text, Named View) do
    nothing without their right, a Bid, a page or valid arguments, in the Access and
    in the SQL mode; the positive control proves each one writes."""

    NAMED_VIEW = [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]

    def _handler(self, sql):
        data = FakeProjectData()
        data.takeoffs["parent"] = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        return handler, write, ann_write, undo

    def _writes(self, write, ann_write):
        return _write_count(write) + len(ann_write.insert_calls)

    def _commands(self):
        return {
            "takeoff": (
                lambda h, *a: h.on_takeoff_created(*a),
                ("42", [1.0, 2.0], "9"),
                {Feature.PLACE_PLAN_ITEMS},
                [
                    ("", [1.0, 2.0], "9"),
                    ("42", [1.0, 2.0], ""),
                    ("hidden-or-unknown", [1.0, 2.0], "9"),
                ],
            ),
            "hole": (
                lambda h, *a: h.on_hole_created(*a),
                ("c1", [2.0, 2.0, 4.0, 4.0], "p1", "parent"),
                {Feature.PLACE_PLAN_ITEMS},
                [
                    ("", [2.0, 2.0], "p1", "parent"),
                    ("c1", [2.0, 2.0], "", "parent"),
                    ("c1", [2.0, 2.0], "p1", ""),
                    ("unknown", [2.0, 2.0], "p1", "parent"),
                ],
            ),
            "annotation": (
                lambda h, *a: h.on_annotation_created(*a),
                ("rect", [1.0, 2.0, 5.0, 6.0], "p1"),
                {Feature.PLACE_ANNOTATIONS},
                [
                    ("", [1.0, 2.0, 5.0, 6.0], "p1"),
                    ("rect", [1.0, 2.0, 5.0, 6.0], ""),
                    ("not-an-annotation-type", [1.0, 2.0, 5.0, 6.0], "p1"),
                ],
            ),
            "text": (
                lambda h, *a: h.on_text_annotation_created(*a),
                ([1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Note"}),
                {Feature.PLACE_ANNOTATIONS},
                [
                    ([1.0, 2.0, 5.0, 6.0], "", {"Text": "Note"}),
                    ([1.0, 2.0, 5.0, 6.0], "p1", {"Text": "  "}),
                    ([1.0, 2.0, 5.0, 6.0], "p1", {}),
                ],
            ),
            "named view": (
                lambda h, *a: h.on_named_view_created(*a),
                (self.NAMED_VIEW, "p1", {"Text": "Lobby"}),
                {Feature.PLACE_ANNOTATIONS},
                [
                    (self.NAMED_VIEW, "", {"Text": "Lobby"}),
                    (self.NAMED_VIEW, "p1", {"Text": " "}),
                    (self.NAMED_VIEW, "p1", {}),
                ],
            ),
        }

    def test_each_gesture_writes_and_ignores_every_invalid_call(self):
        for sql in (False, True):
            for name, (
                command,
                valid,
                right,
                invalid_calls,
            ) in self._commands().items():
                handler, write, ann_write, undo = self._handler(sql)
                command(handler, *valid)
                self.assertGreaterEqual(
                    self._writes(write, ann_write), 1, (name, sql, "control")
                )
                no_bid = {"get_selected_bid_ref": lambda: None, "active_page_uid": "p1"}
                breakers = {
                    "no right": lambda h: h._ui_access_manager.allowed_features.difference_update(
                        right
                    ),
                    "no bid": lambda h: setattr(
                        h, "_ui_state", SimpleNamespace(**no_bid)
                    ),
                }
                for breaker_name, breaker in breakers.items():
                    with self.subTest(gesture=name, sql=sql, missing=breaker_name):
                        handler, write, ann_write, undo = self._handler(sql)
                        breaker(handler)
                        command(handler, *valid)
                        self.assertEqual(self._writes(write, ann_write), 0)
                        self.assertEqual(undo.count, 0)
                for index, arguments in enumerate(invalid_calls):
                    with self.subTest(gesture=name, sql=sql, invalid=index):
                        handler, write, ann_write, undo = self._handler(sql)
                        command(handler, *arguments)
                        self.assertEqual(self._writes(write, ann_write), 0)
                        self.assertEqual(undo.count, 0)

    def test_a_text_annotation_takes_its_colour_from_an_integer_font_colour_only(self):
        for font_color, expected in ((0x336699, "#996633"), ("#112233", None)):
            with self.subTest(font_color=font_color):
                handler, write, ann_write, undo = self._handler(False)
                default = build_placed_annotation_spec(
                    "text", "p1", [1.0, 2.0, 5.0, 6.0]
                ).color
                handler.on_text_annotation_created(
                    [1.0, 2.0, 5.0, 6.0],
                    "p1",
                    {"Text": "Note", "FontColor": font_color},
                )
                spec = ann_write.insert_calls[0][2][0]
                self.assertEqual(spec.color, expected or default)
                self.assertEqual(spec.properties["FontColor"], font_color)


class PlanViewActionHandlerDeleteScopeTests(_PlanViewActionHandlerFixture):
    """What a plan-item delete writes: guards, the delete family, fast versus generic
    local path, and the page/dependency scope of the write."""

    def _handler(self, sql=False, undo=None):
        data = FakeProjectData()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["H"] = Takeoff(
            uid="H",
            condition_uid="c2",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="P",
            is_negative=True,
        )
        data.takeoffs["S"] = Takeoff(
            uid="S", condition_uid="c1", page_uid="9", position=[1.0, 1.0]
        )
        rect = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="9",
            layer_uid="L1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        loose = BidAnnotation(uid="n1", annotation_type="annotation", page_uid="9")
        data.annotations = [rect, loose]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1_rect": rect, "n1_note": loose}
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        ann_write = FakeAnnotationWriteService()
        write.annotation_write_service = ann_write
        undo = FakeUndoService() if undo is None else undo
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_a_delete_without_its_preconditions_or_items_does_nothing(self):
        cases = {
            "no access": lambda h, d: h._ui_access_manager.allowed_features.discard(
                Feature.EDIT_PLAN_ITEMS
            ),
            "no bid": lambda h, d: setattr(
                h,
                "_ui_state",
                SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                ),
            ),
        }
        for sql in (False, True):
            for name, change in cases.items():
                with self.subTest(sql=sql, missing=name):
                    handler, plan_view, write, data, undo = self._handler(sql)
                    change(handler, data)
                    handler.on_elements_deleted(["S"])
                    self.assertEqual(_write_count(write), 0)
            with self.subTest(sql=sql, items="none"):
                handler, plan_view, write, data, undo = self._handler(sql)
                handler.on_elements_deleted([])
                handler.on_elements_deleted(["nothing"])
                handler.on_elements_deleted(["n1_note"])
                self.assertEqual(_write_count(write), 0)
                self.assertEqual(undo.count, 0)

    def test_a_sql_delete_queues_the_family_the_annotations_and_every_dependency(self):
        handler, plan_view, write, data, undo = self._handler(sql=True)
        plan_view.selected = {"P", "a1_rect"}
        handler.on_elements_deleted(["P", "a1_rect"])
        database_id, bid_uid, takeoff_uids, annotations, options, _callback = (
            write.queued_deletes[0]
        )
        self.assertEqual((database_id, bid_uid), ("bid.mdb", "7"))
        self.assertEqual(takeoff_uids, ["P", "H"])
        self.assertEqual(annotations, [("a1", "rect")])
        self.assertEqual(options["page_uids"], ("p1", "9"))
        self.assertEqual(
            options["dependency_resources"],
            tuple(
                sorted(
                    {
                        ResourceRef("condition", "c1", 7),
                        ResourceRef("condition", "c2", 7),
                        ResourceRef("layer", "L1", 7),
                    }
                )
            ),
        )
        self.assertEqual(plan_view.pending_mutation_uids, {"P", "a1_rect"})
        self.assertEqual(plan_view.selected, set())

    def test_the_local_mixed_delete_is_scoped_to_its_pages_and_dependencies(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["P", "a1_rect"])
        (record,) = write.local_deletes
        self.assertEqual(
            (record[0], record[1], sorted(record[2]), record[3]),
            ("bid.mdb", "7", ["H", "P"], [("a1", "rect")]),
        )
        self.assertEqual(record[4]["page_uids"], ("p1", "9"))
        self.assertEqual(
            record[4]["dependency_resources"],
            tuple(
                sorted(
                    {
                        ResourceRef("condition", "c1", 7),
                        ResourceRef("condition", "c2", 7),
                        ResourceRef("layer", "L1", 7),
                    }
                )
            ),
        )
        self.assertEqual(record[4]["publish_database_refreshed_after_write"], False)

    def test_only_a_lone_takeoff_with_supported_extras_takes_the_fast_local_path(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["S"])
        self.assertEqual(write.local_deletes, [])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["S"], False)])
        handler, plan_view, write, data, undo = self._handler()
        data.extras["S"] = {"UnsupportedColumn": "x"}
        handler.on_elements_deleted(["S"])
        self.assertEqual(len(write.local_deletes), 1)
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["P"])
        self.assertEqual(len(write.local_deletes), 1)
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["H"])
        self.assertEqual(write.local_deletes, [])
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["S", "H"])
        self.assertEqual(write.local_deletes, [])

    def test_a_child_with_no_parent_uid_is_deleted_alone_on_the_fast_path(self):
        handler, plan_view, write, data, undo = self._handler()
        data.takeoffs["H"].parent_uid = None
        handler.on_elements_deleted(["H"])
        self.assertEqual(write.local_deletes, [])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["H"], False)])

    def test_the_insert_fast_path_reports_nothing_when_no_identity_comes_back(self):
        handler, plan_view, write, data, undo = self._handler()
        spec = InsertTakeoffSpec(
            condition_uid="c1", page_uid="p1", area_uid="0", position=[1.0, 2.0]
        )
        write.uid_batches = [[]]
        self.assertEqual(
            handler._insert_takeoffs_fast(
                handler._ui_state.get_selected_bid_ref(), [spec]
            ),
            [],
        )
        self.assertEqual(handler._event_bus.events, [])
        self.assertEqual(data.added_takeoffs, [])
        write.uid_batches = [["new-1"]]
        self.assertEqual(
            handler._insert_takeoffs_fast(
                handler._ui_state.get_selected_bid_ref(), [spec]
            ),
            ["new-1"],
        )
        self.assertEqual(
            handler._event_bus.events,
            [
                (
                    AppEvents.TAKEOFFS_CHANGED,
                    {
                        "page_uid": "p1",
                        "takeoff_uids": ["new-1"],
                        "condition_uids": ["c1"],
                    },
                )
            ],
        )

    def test_a_mixed_batch_of_supported_and_unsupported_extras_needs_a_full_refresh(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        supported = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={"GUID": "{A}"},
        )
        unsupported = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[3.0, 4.0],
            raw_extras={"Other": 1},
        )
        bid = handler._ui_state.get_selected_bid_ref()
        handler._insert_takeoffs_with_undo(
            bid, [supported, supported], fast_refresh=True
        )
        self.assertEqual(write.calls[-1][3], False)
        handler._insert_takeoffs_with_undo(
            bid, [supported, unsupported], fast_refresh=True
        )
        self.assertEqual(write.calls[-1][3], True)

    def test_redoing_a_local_takeoff_insert_publishes_the_inserted_identities(self):
        handler, plan_view, write, data, undo = self._handler()
        write.next_uids = ["n1", "n2"]
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        undo.undo()
        undo.redo()
        self.assertEqual(
            handler._event_bus.events[-1],
            (
                AppEvents.TAKEOFFS_CHANGED,
                {"page_uid": "9", "takeoff_uids": ["n2"], "condition_uids": ["42"]},
            ),
        )


class PlanViewActionHandlerCopyTests(_PlanViewActionHandlerFixture):
    """on_copy_requested fills the clipboard from the plan view's live items."""

    def _handler(self):
        data = FakeProjectData()
        parent = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        hole = Takeoff(
            uid="H",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="P",
            is_negative=True,
        )
        data.takeoffs = {"P": parent, "H": hole}
        data.extras["P"] = {"GUID": "{P}"}
        rect = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        view = BidAnnotation(
            uid="nv",
            annotation_type="namedview",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        note = BidAnnotation(uid="n1", annotation_type="annotation", page_uid="p1")
        plan_view = FakePlanView(data)
        plan_view.annotations = {"a1": rect, "nv": view, "n1": note}
        emitted = []
        plan_view.clipboard_changed = SimpleNamespace(emit=lambda: emitted.append(True))
        handler = self._paste_handler(plan_view=plan_view, data=data)
        return handler, emitted

    def test_copy_takes_the_children_but_only_copyable_annotations(self):
        handler, emitted = self._handler()
        handler.on_copy_requested(["P", "a1", "nv", "n1", "unknown"])
        clipboard = handler._clipboard_svc
        self.assertEqual([t.uid for t in clipboard.items], ["P", "H"])
        self.assertEqual([a.uid for a in clipboard.annotations], ["a1"])
        self.assertEqual(clipboard.source_bid_uid, "7")
        self.assertTrue(clipboard.source_matches_database("bid.mdb"))
        self.assertEqual(clipboard.get_extras("P")["GUID"], "{P}")
        self.assertEqual(set(clipboard.conditions), {"42", "c1"})
        self.assertEqual(emitted, [True])

    def test_copy_without_access_or_items_leaves_the_clipboard_alone(self):
        handler, emitted = self._handler()
        handler._ui_access_manager.allowed_features.discard(Feature.SELECT_PLAN_ITEMS)
        handler.on_copy_requested(["P"])
        self.assertFalse(handler._clipboard_svc.has_content())
        handler._ui_access_manager.allowed_features.add(Feature.SELECT_PLAN_ITEMS)
        handler.on_copy_requested(["unknown", "nv", "n1"])
        self.assertFalse(handler._clipboard_svc.has_content())
        self.assertEqual(emitted, [])

    def test_copy_without_a_bid_still_copies_but_remembers_no_source(self):
        handler, emitted = self._handler()
        handler._ui_state = SimpleNamespace(get_selected_bid_ref=lambda: None)
        handler.on_copy_requested(["P"])
        self.assertTrue(handler._clipboard_svc.has_content())
        self.assertIsNone(handler._clipboard_svc.source_bid_uid)
        self.assertFalse(handler._clipboard_svc.source_matches_database("bid.mdb"))


class PlanViewActionHandlerFlushGuardTests(_PlanViewActionHandlerFixture):
    """The refusal rules of the three geometry flush entry points (positions,
    rotations, group rotation): what is restored, and that nothing is written."""

    PREVIEW = "pending:takeoff-placement:00000000-0000-4000-8000-000000000001:0"

    def _handler(self, sql):
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
        write.sql_collaboration_mutations = sql
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo, data

    TAKEOFF = [("t1", [0.0, 0.0], [5.0, 6.0])]
    ANNOTATION = [("a1", "rect", [1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 4.0, 4.0])]
    ROTATION = [("t1", 0.0, 45.0)]

    def _refused(self, handler, plan_view, write, undo):
        self.assertEqual(_write_count(write), 0)
        self.assertEqual(undo.count, 0)

    def test_positions_are_restored_and_not_written_when_they_cannot_be_applied(self):
        preview = [(self.PREVIEW, [0.0, 0.0], [5.0, 6.0])]
        cases = {
            "denied takeoff": (
                lambda h, d: h._ui_access_manager.allowed_features.clear(),
                self.TAKEOFF,
                [],
            ),
            "denied annotation": (
                lambda h, d: h._ui_access_manager.allowed_features.clear(),
                [],
                self.ANNOTATION,
            ),
            "preview": (lambda h, d: None, preview, []),
            "no bid": (
                lambda h, d: setattr(
                    h,
                    "_ui_state",
                    SimpleNamespace(
                        active_page_uid="p1", get_selected_bid_ref=lambda: None
                    ),
                ),
                self.TAKEOFF,
                self.ANNOTATION,
            ),
        }
        for sql in (False, True):
            for name, (change, takeoffs, annotations) in cases.items():
                with self.subTest(sql=sql, case=name):
                    handler, plan_view, write, undo, data = self._handler(sql)
                    change(handler, data)
                    handler.on_positions_flushed(takeoffs, annotations)
                    self.assertEqual(
                        plan_view.restored_positions, [(takeoffs, annotations)]
                    )
                    self.assertEqual(plan_view.restored_rotations, [])
                    self._refused(handler, plan_view, write, undo)

    def test_positions_without_changes_or_a_database_do_nothing_at_all(self):
        for sql in (False, True):
            with self.subTest(sql=sql, case="no changes"):
                handler, plan_view, write, undo, data = self._handler(sql)
                handler.on_positions_flushed([], [])
                handler._ui_access_manager.allowed_features.clear()
                handler.on_positions_flushed([], [])
                self.assertEqual(plan_view.restored_positions, [])
                self._refused(handler, plan_view, write, undo)
            with self.subTest(sql=sql, case="no database"):
                handler, plan_view, write, undo, data = self._handler(sql)
                data.get_current_bid_file_path = lambda: ""
                handler.on_positions_flushed(self.TAKEOFF, [])
                self.assertEqual(plan_view.restored_positions, [])
                self._refused(handler, plan_view, write, undo)

    def test_rotations_are_restored_or_ignored_before_any_write(self):
        preview = [(self.PREVIEW, 0.0, 45.0)]
        for sql in (False, True):
            with self.subTest(sql=sql, case="denied"):
                handler, plan_view, write, undo, data = self._handler(sql)
                handler._ui_access_manager.allowed_features.clear()
                handler.on_rotations_flushed(self.ROTATION)
                handler.on_rotations_flushed([])
                self.assertEqual(plan_view.restored_rotations, [self.ROTATION])
                self._refused(handler, plan_view, write, undo)
            with self.subTest(sql=sql, case="preview"):
                handler, plan_view, write, undo, data = self._handler(sql)
                handler.on_rotations_flushed(preview)
                self.assertEqual(plan_view.restored_rotations, [preview])
                self._refused(handler, plan_view, write, undo)
            with self.subTest(sql=sql, case="no database or no changes"):
                handler, plan_view, write, undo, data = self._handler(sql)
                handler.on_rotations_flushed([])
                data.get_current_bid_file_path = lambda: ""
                handler.on_rotations_flushed(self.ROTATION)
                self.assertEqual(plan_view.restored_rotations, [])
                self._refused(handler, plan_view, write, undo)

    def test_group_rotations_restore_positions_and_rotations_together_when_refused(
        self,
    ):
        preview_positions = [(self.PREVIEW, [0.0, 0.0], [5.0, 6.0])]
        preview_rotations = [(self.PREVIEW, 0.0, 45.0)]
        combos = {
            "takeoff only": (self.TAKEOFF, [], []),
            "annotation only": ([], self.ANNOTATION, []),
            "rotation only": ([], [], self.ROTATION),
        }
        for sql in (False, True):
            for name, (takeoffs, annotations, rotations) in combos.items():
                with self.subTest(sql=sql, case="denied " + name):
                    handler, plan_view, write, undo, data = self._handler(sql)
                    handler._ui_access_manager.allowed_features.clear()
                    handler.on_group_rotation_flushed(takeoffs, annotations, rotations)
                    self.assertEqual(
                        plan_view.restored_positions, [(takeoffs, annotations)]
                    )
                    self.assertEqual(plan_view.restored_rotations, [rotations])
                    self._refused(handler, plan_view, write, undo)
            for name, (takeoffs, rotations) in {
                "preview position": (preview_positions, self.ROTATION),
                "preview rotation": (self.TAKEOFF, preview_rotations),
            }.items():
                with self.subTest(sql=sql, case=name):
                    handler, plan_view, write, undo, data = self._handler(sql)
                    handler.on_group_rotation_flushed(
                        takeoffs, self.ANNOTATION, rotations
                    )
                    self.assertEqual(
                        plan_view.restored_positions, [(takeoffs, self.ANNOTATION)]
                    )
                    self.assertEqual(plan_view.restored_rotations, [rotations])
                    self._refused(handler, plan_view, write, undo)
            with self.subTest(sql=sql, case="no bid"):
                handler, plan_view, write, undo, data = self._handler(sql)
                handler._ui_state = SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                )
                handler.on_group_rotation_flushed(
                    self.TAKEOFF, self.ANNOTATION, self.ROTATION
                )
                self.assertEqual(
                    plan_view.restored_positions, [(self.TAKEOFF, self.ANNOTATION)]
                )
                self.assertEqual(plan_view.restored_rotations, [self.ROTATION])
                self._refused(handler, plan_view, write, undo)
            with self.subTest(sql=sql, case="no database"):
                handler, plan_view, write, undo, data = self._handler(sql)
                data.get_current_bid_file_path = lambda: ""
                handler.on_group_rotation_flushed(self.TAKEOFF, [], self.ROTATION)
                self.assertEqual(plan_view.restored_positions, [])
                self.assertEqual(plan_view.restored_rotations, [])
                self._refused(handler, plan_view, write, undo)

    def test_a_group_with_a_rotation_and_an_annotation_move_saves_both(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 2.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.annotations = {"a1_rect": annotation}
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data
        )
        handler.on_group_rotation_flushed([], self.ANNOTATION, self.ROTATION)
        self.assertEqual(write.rotation_calls, [("bid.mdb", [("t1", 45.0)], False)])
        self.assertEqual(
            ann_write.position_calls[0][1], [("a1", "rect", [3.0, 3.0, 4.0, 4.0])]
        )
        self.assertEqual(len(write.local_geometry), 1)


class PlanViewActionHandlerAnnotationFlushEdgeTests(_PlanViewActionHandlerFixture):
    """Edge cases shared by the annotation text and style flush entry points."""

    KINDS = {
        "text": (
            "on_annotation_text_properties_flushed",
            "text_property_calls",
            "annotation_text",
        ),
        "style": ("on_annotation_styles_flushed", "style_calls", "annotation_style"),
    }

    def _handler(self, sql):
        data = FakeProjectData()
        first = BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        second = BidAnnotation(uid="a2", annotation_type="rect", page_uid="p1")
        third = BidAnnotation(uid="a3", annotation_type="rect", page_uid="9")
        pageless = BidAnnotation(uid="a4", annotation_type="rect", page_uid="")
        data.annotations = [first, second, third, pageless]
        plan_view = FakePlanView(data)
        plan_view.annotations = {
            "a1_rect": first,
            "a2_rect": second,
            "a3_rect": third,
            "a4_rect": pageless,
        }
        plan_view.annotation_key_map = {
            (uid, "rect"): f"{uid}_rect" for uid in ("a1", "a2", "a3", "a4", "ghost")
        }
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        return handler, plan_view, write, ann_write, undo

    @staticmethod
    def _changes(kind, uid="a1", old=None):
        key = "Text" if kind == "text" else "Width"
        return [(uid, "rect", old, {key: "new" if kind == "text" else 7.0})]

    def test_nothing_happens_without_a_database_or_changes(self):
        for kind, (method, calls, _property_kind) in self.KINDS.items():
            for sql in (False, True):
                with self.subTest(kind=kind, sql=sql):
                    handler, plan_view, write, ann_write, undo = self._handler(sql)
                    getattr(handler, method)([])
                    handler._data_svc.get_current_bid_file_path = lambda: ""
                    getattr(handler, method)(
                        self._changes(kind, old={"Text": "o", "Width": 1.0})
                    )
                    self.assertEqual(getattr(ann_write, calls), [])
                    self.assertEqual(write.queued_properties, [])
                    self.assertEqual(plan_view.restored_text_properties, [])
                    self.assertEqual(plan_view.restored_annotation_styles, [])

    def test_local_history_needs_a_non_empty_previous_state(self):
        for kind, (method, calls, _property_kind) in self.KINDS.items():
            for old, expected_undo in (
                (None, 0),
                ({}, 0),
                ({"Text": "o", "Width": 1.0}, 1),
            ):
                with self.subTest(kind=kind, old=old):
                    handler, plan_view, write, ann_write, undo = self._handler(False)
                    getattr(handler, method)(self._changes(kind, old=old))
                    self.assertEqual(len(getattr(ann_write, calls)), 1)
                    self.assertEqual(undo.count, expected_undo)

    def test_sql_history_needs_a_previous_state_that_is_not_none(self):
        for kind, (method, _calls, property_kind) in self.KINDS.items():
            for old, expected_undo in (
                (None, 0),
                ({}, 1),
                ({"Text": "o", "Width": 1.0}, 1),
            ):
                with self.subTest(kind=kind, old=old):
                    handler, plan_view, write, ann_write, undo = self._handler(True)
                    getattr(handler, method)(self._changes(kind, old=old))
                    self.assertEqual(write.queued_properties[0][2], property_kind)
                    write.queued_properties[0][-1](_committed())
                    self.assertEqual(undo.count, expected_undo)

    def test_the_sql_page_scope_lists_each_known_page_once(self):
        for kind, (method, _calls, _property_kind) in self.KINDS.items():
            with self.subTest(kind=kind):
                handler, plan_view, write, ann_write, undo = self._handler(True)
                key = "Text" if kind == "text" else "Width"
                value = "x" if kind == "text" else 1.0
                changes = [
                    (uid, "rect", {key: value}, {key: value})
                    for uid in ("a1", "a2", "a3", "a4", "ghost")
                ]
                getattr(handler, method)(changes)
                self.assertEqual(
                    write.queued_properties[0][4]["page_uids"], ("p1", "9")
                )
                self.assertEqual(
                    plan_view.pending_mutation_uids,
                    {"a1_rect", "a2_rect", "a3_rect", "a4_rect", "ghost_rect"},
                )

    def test_a_sql_edit_without_a_bid_falls_back_to_the_local_writer(self):
        for kind, (method, calls, _property_kind) in self.KINDS.items():
            with self.subTest(kind=kind):
                handler, plan_view, write, ann_write, undo = self._handler(True)
                handler._ui_state = SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                )
                getattr(handler, method)(self._changes(kind, old=None))
                self.assertEqual(write.queued_properties, [])
                self.assertEqual(len(getattr(ann_write, calls)), 1)


class _ParentResolvingPlanView(FakePlanView):
    """FakePlanView with the Backout parent resolution of the real plan view."""

    def __init__(self, data=None):
        super().__init__(data)
        self.resolution_requests = []
        self.resolution = ([("existing-parent", True)], True)

    def resolve_pasted_child_parents(self, children, positions, conditions):
        self.resolution_requests.append((children, positions, conditions))
        return self.resolution


class PlanViewActionHandlerBackoutPasteTests(_PlanViewActionHandlerFixture):
    """Pasting Backouts: the placements the plan view hands over, and the parents of
    pasted Backouts whose own parent is not part of the clipboard."""

    def _placement(self, **overrides):
        placement = {
            "condition_uid": "c1",
            "page_uid": "p1",
            "position": [2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            "parent_uid": "existing-parent",
            "rotation": 0.5,
            "is_negative": True,
            "extras": {"GUID": "{H}"},
            "source_uid": "src-hole",
            "parent_is_internal": False,
        }
        placement.update(overrides)
        return placement

    def _handler(self, sql):
        data = FakeProjectData()
        data.takeoffs["existing-parent"] = Takeoff(
            uid="existing-parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data
        )
        handler._clipboard_svc = FakeClipboard([], source_bid_uid="6")
        return handler, write, data

    def test_placements_become_a_payload_for_the_active_bid(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, write, data = self._handler(sql)
                handler.on_paste_backouts_placed(
                    [self._placement(), self._placement(source_uid="", curve=1)],
                    "6",
                )
                database_id, payload = (
                    (write.queued_pastes[0][0], write.queued_pastes[0][1])
                    if sql
                    else (write.local_pastes[0][0], write.local_pastes[0][1])
                )
                self.assertEqual(database_id, "bid.mdb")
                self.assertEqual(
                    (payload.source_bid_uid, payload.destination_bid_uid), ("6", "7")
                )
                first, second = payload.takeoff_specs
                self.assertEqual(
                    (
                        first.condition_uid,
                        first.page_uid,
                        first.parent_uid,
                        first.curve,
                    ),
                    ("c1", "p1", "existing-parent", -1),
                )
                self.assertEqual(
                    (first.rotation, first.is_negative, first.source_bid_uid),
                    (0.5, True, "6"),
                )
                self.assertEqual(first.raw_extras, {"GUID": "{H}"})
                self.assertEqual(first.area_uid, "0")
                self.assertEqual(second.curve, 1)
                self.assertEqual(payload.takeoff_source_uids[0], "src-hole")
                self.assertNotEqual(payload.takeoff_source_uids[1], "")
                self.assertEqual(payload.takeoff_external_parent_sources, ("src-hole",))
                self.assertEqual(
                    {
                        (r.resource_type, r.resource_id, r.bid_uid)
                        for r in (
                            write.queued_pastes[0][2]["dependency_resources"]
                            if sql
                            else write.local_pastes[0][2]["dependency_resources"]
                        )
                    },
                    {("condition", "c1", 6)},
                )

    def test_internal_parents_bind_nothing_and_a_missing_source_bid_means_the_active_bid(
        self,
    ):
        handler, write, data = self._handler(True)
        handler.on_paste_backouts_placed(
            [
                self._placement(
                    source_uid="src-a", parent_uid="src-b", parent_is_internal=True
                ),
                self._placement(source_uid="src-b", parent_uid="existing-parent"),
            ],
            None,
        )
        payload = write.queued_pastes[0][1]
        self.assertEqual(payload.source_bid_uid, "7")
        self.assertEqual(payload.takeoff_external_parent_sources, ("src-b",))
        self.assertEqual(write.queued_pastes[0][2]["dependency_resources"], ())

    def test_a_backout_paste_needs_the_right_a_bid_and_placements(self):
        for sql in (False, True):
            with self.subTest(sql=sql, case="no right"):
                handler, write, data = self._handler(sql)
                handler._ui_access_manager.allowed_features.discard(
                    Feature.PLACE_PLAN_ITEMS
                )
                handler.on_paste_backouts_placed([self._placement()], "6")
                self.assertEqual(_write_count(write), 0)
            with self.subTest(sql=sql, case="no bid"):
                handler, write, data = self._handler(sql)
                handler._ui_state = SimpleNamespace(
                    active_page_uid="p1", get_selected_bid_ref=lambda: None
                )
                handler.on_paste_backouts_placed([self._placement()], "6")
                self.assertEqual(_write_count(write), 0)
            with self.subTest(sql=sql, case="no placements"):
                handler, write, data = self._handler(sql)
                handler.on_paste_backouts_placed([], "6")
                self.assertEqual(_write_count(write), 0)

    def _external_hole_handler(self, sql):
        data = FakeProjectData()
        data.takeoffs["existing-parent"] = Takeoff(
            uid="existing-parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        plan_view = _ParentResolvingPlanView(data)
        plan_view.intelligent_paste_enabled = False
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        regular = Takeoff(
            uid="reg",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 14.0, 20.0],
        )
        hole = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="source-page",
            position=[11.0, 21.0, 12.0, 21.0, 12.0, 22.0],
            parent_uid="not-copied",
            is_negative=True,
        )
        handler._clipboard_svc = FakeClipboard([regular, hole])
        return handler, plan_view, write, data, hole

    def test_a_hole_whose_parent_was_not_copied_is_pasted_under_the_resolved_parent(
        self,
    ):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, plan_view, write, data, hole = self._external_hole_handler(sql)
                handler.on_paste_requested()
                self.assertEqual(len(plan_view.resolution_requests), 1)
                children, positions, conditions = plan_view.resolution_requests[0]
                self.assertEqual(children, [hole])
                self.assertEqual(positions, [[12.0, 22.0, 13.0, 22.0, 13.0, 23.0]])
                self.assertEqual(set(conditions), {"42", "c1"})
                payload = write.queued_pastes[0][1] if sql else write.local_pastes[0][1]
                self.assertEqual(
                    [s.parent_uid for s in payload.takeoff_specs],
                    ["0", "existing-parent"],
                )
                self.assertEqual(payload.takeoff_external_parent_sources, ("hole",))

    def test_an_unresolvable_parent_cancels_the_paste(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, plan_view, write, data, hole = self._external_hole_handler(sql)
                plan_view.resolution = ([], False)
                handler.on_paste_requested()
                self.assertEqual(_write_count(write), 0)
                self.assertEqual(plan_view.selected, set())

    def test_the_conditions_for_the_parent_search_follow_the_source_bid(self):
        handler, plan_view, write, data, hole = self._external_hole_handler(True)
        handler._clipboard_svc = FakeClipboard(
            handler._clipboard_svc.items, source_bid_uid="6"
        )
        handler._clipboard_svc.conditions = {"foreign": "condition"}
        handler.on_paste_requested()
        self.assertEqual(plan_view.resolution_requests[0][2], {"foreign": "condition"})


class PlanViewActionHandlerHotlinkHistoryTests(_PlanViewActionHandlerFixture):
    """Hot Link history follows the Named View it points to and refuses to replay
    against a different Named View (decision A: a Hot Link follows the restored view).
    """

    def _handler(self):
        data = FakeProjectData()
        view = _named_view_annotation("nv1", "Lobby")
        data.annotations = [view]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("ann-1", "hotlink"): "ann-1_hotlink"}
        plan_view.annotations = {"nv1": view}
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data, undo=undo
        )
        return handler, plan_view, ann_write, data, undo, view

    def _place_hotlink(self, handler):
        class AcceptingDialog:
            def __init__(self, _named_views, parent=None):
                pass

            def exec(self):
                return handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid="nv1")

            def deleteLater(self):
                pass

        with patch.object(handler_module, "SelectNamedViewDialog", AcceptingDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")

    def test_a_placed_hot_link_keeps_its_named_view_as_a_history_target(self):
        handler, plan_view, ann_write, data, undo, view = self._handler()
        self._place_hotlink(handler)
        targets = {(t.annotation_type, t.uid) for t in undo.annotation_targets}
        self.assertEqual(targets, {("hotlink", "ann-1"), ("namedview", "nv1")})

    def test_redoing_a_hot_link_whose_named_view_is_gone_warns_and_inserts_nothing(
        self,
    ):
        handler, plan_view, ann_write, data, undo, view = self._handler()
        self._place_hotlink(handler)
        undo.undo()
        for target in undo.annotation_targets:
            if target.annotation_type == "namedview":
                target.available = False
        inserts = len(ann_write.insert_calls)
        with patch.object(handler_module, "show_warning") as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                undo.redo()
        warning.assert_called_once_with(
            plan_view, "Hot Link History", HOTLINK_VIEW_UNAVAILABLE_MESSAGE
        )
        self.assertEqual(len(ann_write.insert_calls), inserts)

    def test_redoing_a_hot_link_whose_named_view_is_intact_points_it_at_the_view(self):
        handler, plan_view, ann_write, data, undo, view = self._handler()
        self._place_hotlink(handler)
        undo.undo()
        ann_write.next_uids = ["ann-2"]
        undo.redo()
        redone = ann_write.insert_calls[-1][2][0]
        self.assertEqual(redone.properties, {"BidPageViewUID": "nv1"})

    def test_undoing_a_hot_link_delete_after_its_view_was_replaced_refuses_the_restore(
        self,
    ):
        handler, plan_view, ann_write, data, undo, view = self._handler()
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view.annotations = {"hl1": hotlink, "nv1": view}
        handler._write_svc.annotation_write_service = ann_write
        handler.on_elements_deleted(["hl1"])
        data.annotations = [_named_view_annotation("nv1", "Other")]
        data.annotations[0].page_uid = "9"
        with patch.object(handler_module, "show_warning") as warning:
            with self.assertRaises(AnnotationHistoryDependencyError):
                undo.undo()
        warning.assert_called_once_with(
            plan_view, "Hot Link History", HOTLINK_VIEW_UNAVAILABLE_MESSAGE
        )
        self.assertEqual(ann_write.insert_calls, [])

    def test_undoing_a_hot_link_delete_with_its_view_in_place_restores_the_link(self):
        handler, plan_view, ann_write, data, undo, view = self._handler()
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view.annotations = {"hl1": hotlink, "nv1": view}
        handler._write_svc.annotation_write_service = ann_write
        ann_write.next_uids = ["hl-new"]
        handler.on_elements_deleted(["hl1"])
        undo.undo()
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in data.annotations if a.is_hotlink],
            [("hl-new", "hotlink")],
        )
        restored = [a for a in data.annotations if a.is_hotlink][0]
        self.assertEqual(restored.properties["BidPageViewUID"], "nv1")


class PlanViewActionHandlerSqlAnnotationCompletionTests(_PlanViewActionHandlerFixture):
    """The completion of a queued annotation insert and the replay of its history."""

    def _handler(self):
        data = FakeProjectData()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12.0
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {("annotation-1", "text"): "annotation-1_text"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    @staticmethod
    def _result(payload, uid="annotation-1"):
        return _committed(
            maps=(("annotations", ((payload.annotation_source_uids[0], uid),)),)
        )

    def test_a_selection_made_meanwhile_keeps_the_user_choice_but_history_is_recorded(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Delayed"}
        )
        payload, callback = write.queued_pastes[0][1], write.queued_pastes[0][3]
        plan_view.set_selected_uids({"user-choice"})
        callback(self._result(payload))
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(plan_view.activated_annotations, [])
        self.assertEqual(undo.count, 1)

    def test_the_inserted_annotation_is_selected_and_the_tool_reactivated_once(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_text_annotation_created(
            [1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Delayed"}
        )
        payload, callback = write.queued_pastes[0][1], write.queued_pastes[0][3]
        callback(self._result(payload))
        self.assertEqual(plan_view.selected, {"annotation-1_text"})
        self.assertEqual(plan_view.activated_annotations, ["text"])

    def test_a_committed_result_without_maps_is_refused_loudly(self):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_annotation_created("text", [1.0, 2.0, 5.0, 6.0], "p1")
        callback = write.queued_pastes[0][3]
        with self.assertRaisesRegex(RuntimeError, "missing authoritative UID maps"):
            callback(_committed())
        self.assertEqual(undo.count, 0)

    def test_redoing_a_queued_annotation_insert_rescales_it_to_the_current_page_scale(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_annotation_created("rect", [0.0, 0.0, 96.0, 96.0], "p1")
        payload, callback = write.queued_pastes[0][1], write.queued_pastes[0][3]
        data.annotations.append(
            BidAnnotation(uid="annotation-1", annotation_type="rect", page_uid="p1")
        )
        callback(
            _committed(
                maps=(
                    (
                        "annotations",
                        ((payload.annotation_source_uids[0], "annotation-1"),),
                    ),
                )
            )
        )
        data.pages["p1"].scale_factor1 = 0.1875
        undo.undo()
        self.assertEqual(write.queued_deletes[0][3], [("annotation-1", "rect")])
        undo.redo()
        redo_payload = write.queued_pastes[1][1]
        self.assertEqual(
            redo_payload.annotation_specs[0].position, [0.0, 0.0, 64.0, 64.0]
        )

    def test_redoing_a_queued_takeoff_paste_rescales_it_and_keeps_the_page_scope(self):
        handler, plan_view, write, data, undo = self._handler()
        plan_view.intelligent_paste_enabled = False
        handler._clipboard_svc = FakeClipboard(
            [
                Takeoff(
                    uid="source",
                    condition_uid="c1",
                    page_uid="source-page",
                    position=[10.0, 20.0, 106.0, 20.0],
                )
            ]
        )
        handler.on_paste_requested()
        write.queued_pastes[0][-1](
            _committed(maps=(("takeoffs", (("source", "new-1"),)),))
        )
        data.pages["p1"].scale_factor1 = 0.1875
        undo.undo()
        self.assertEqual(write.queued_deletes[0][4]["page_uids"], ("p1",))
        undo.redo()
        self.assertEqual(
            write.queued_pastes[1][1].takeoff_specs[0].position,
            [7.333333333333333, 14.0, 71.33333333333333, 14.0],
        )


class _TransientRecordingData(FakeProjectData):
    """FakeProjectData that tells transient preview inserts from authoritative ones
    (the plain fake routes both to the same list)."""

    def __init__(self):
        super().__init__()
        self.transient_batches = []
        self.authoritative_batches = []

    def add_transient_takeoffs(self, takeoffs):
        self.transient_batches.append([t.uid for t in takeoffs])
        for takeoff in takeoffs:
            self.takeoffs[takeoff.uid] = takeoff

    def add_takeoffs(self, takeoffs):
        self.authoritative_batches.append([t.uid for t in takeoffs])
        super().add_takeoffs(takeoffs)


class PlanViewActionHandlerPlacementPreviewTests(_PlanViewActionHandlerFixture):
    """The provisional takeoffs of a queued placement and the curve rule of placed
    segments."""

    def _handler(self, data=None, sql=True):
        data = FakeProjectData() if data is None else data
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_previews_are_transient_and_named_after_the_operation_and_their_index(self):
        data = _TransientRecordingData()
        data.conditions["c2"] = Condition(
            uid="c2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        handler, plan_view, write, data, undo = self._handler(data)
        handler._ui_state.place_condition_uids = ["c1", "c2"]
        handler.on_takeoff_created("c1", [1.0, 2.0], "9")
        operation_id, _callback = write.queued_takeoff_callbacks[0]
        expected = [
            queued_takeoff_preview_uid(operation_id, 0),
            queued_takeoff_preview_uid(operation_id, 1),
        ]
        self.assertEqual(data.transient_batches, [expected])
        self.assertEqual(data.authoritative_batches, [])
        self.assertEqual(plan_view.pending_mutation_uids, set(expected))
        self.assertEqual(
            [data.takeoffs[uid].condition_uid for uid in expected], ["c1", "c2"]
        )

    def test_a_queue_failure_removes_every_trace_of_the_placement(self):
        handler, plan_view, write, data, undo = self._handler()

        def broken(*args, **kwargs):
            raise RuntimeError("queue unavailable")

        write.queue_takeoff_placement = broken
        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(handler._pending_takeoff_placements, {})
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})

    def test_only_a_curved_segment_with_a_control_point_is_placed_curved(self):
        cases = (
            (
                "linear curved six coordinates",
                Condition.TYPE_LINEAR,
                True,
                [0.0, 0.0, 10.0, 0.0, 5.0, 5.0],
                Takeoff.CURVE_ENABLED,
            ),
            (
                "linear curved five coordinates",
                Condition.TYPE_LINEAR,
                True,
                [0.0, 0.0, 10.0, 0.0, 5.0],
                Takeoff.CURVE_DISABLED,
            ),
            (
                "linear curved four coordinates",
                Condition.TYPE_LINEAR,
                True,
                [0.0, 0.0, 10.0, 0.0],
                Takeoff.CURVE_DISABLED,
            ),
            (
                "linear straight six coordinates",
                Condition.TYPE_LINEAR,
                False,
                [0.0, 0.0, 10.0, 0.0, 5.0, 5.0],
                Takeoff.CURVE_DISABLED,
            ),
            (
                "area curved six coordinates",
                Condition.TYPE_AREA,
                True,
                [0.0, 0.0, 10.0, 0.0, 5.0, 5.0],
                Takeoff.CURVE_DISABLED,
            ),
        )
        for name, condition_type, curved, position, expected in cases:
            with self.subTest(case=name):
                data = FakeProjectData()
                data.conditions["x"] = Condition(
                    uid="x",
                    layer_visible=True,
                    condition_type=condition_type,
                    is_curved_segment=curved,
                )
                handler, plan_view, write, data, undo = self._handler(data, sql=False)
                handler.on_takeoff_created("x", position, "9")
                self.assertEqual(write.calls[0][2][0].curve, expected)

    def test_a_failed_placement_publishes_only_while_its_bid_and_page_are_still_current(
        self,
    ):
        cases = {
            "same": (BidRef("bid.mdb", "7"), None, True),
            "other bid uid": (BidRef("bid.mdb", "8"), None, False),
            "other database": (BidRef("other.mdb", "7"), None, False),
            "no bid": (None, None, False),
            "replaced page": (BidRef("bid.mdb", "7"), "replace", False),
        }
        for name, (bid, page_change, publishes) in cases.items():
            with self.subTest(case=name):
                handler, plan_view, write, data, undo = self._handler()
                handler.on_takeoff_created("42", [1.0, 2.0], "9")
                operation_id, callback = write.queued_takeoff_callbacks[0]
                handler._ui_state = SimpleNamespace(
                    active_page_uid="9", get_selected_bid_ref=lambda bid=bid: bid
                )
                if page_change:
                    data.pages["9"] = SimpleNamespace(uid="9")
                before = len(
                    [
                        e
                        for e in handler._event_bus.events
                        if e[0] == AppEvents.TAKEOFFS_CHANGED
                    ]
                )
                with self.assertLogs(handler_module.logger, "WARNING"):
                    callback(
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=3,
                            operation_id=operation_id,
                            outcome_status=MutationOutcomeStatus.CONFLICT,
                            message="m",
                        )
                    )
                after = len(
                    [
                        e
                        for e in handler._event_bus.events
                        if e[0] == AppEvents.TAKEOFFS_CHANGED
                    ]
                )
                self.assertEqual(after - before, 1 if publishes else 0)
                self.assertEqual(data.takeoffs, {})


class _SynchronousRejectionWriteService(FakeWriteService):
    """The real SQL coordinator rejects a submission it cannot queue (SQL collaboration
    not ready for editing, queue full, runtime stopped) through the Qt callback bridge,
    which calls the completion synchronously on the UI thread, BEFORE queue_* returns
    (the runtime generation is only known after the return)."""

    def __init__(self, generation=0, bid_locked=False):
        super().__init__()
        self.sql_collaboration_mutations = True
        self.rejection_generation = generation
        self.bid_locked = bid_locked

    def queue_takeoff_placement(
        self, database_id, bid_uid, specs, operation_id, callback
    ):
        if self.bid_locked:
            result = replace(
                locked_bid_refusal_result(database_id),
                operation_id=operation_id,
                runtime_generation=self.rejection_generation,
            )
        else:
            result = QueuedMutationResult(
                database_id=database_id,
                runtime_generation=self.rejection_generation,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.REJECTED,
                message="SQL collaboration is not ready for editing.",
            )
        callback(result)
        return -1


class PlanViewActionHandlerSynchronousRejectionTests(_PlanViewActionHandlerFixture):
    """A placement whose submission is rejected before queue_takeoff_placement returns
    is a rejected persistence like any other: the preview is removed, the pending
    marker and the forward-mutation token are freed and no history is added."""

    def _place(self, write, history=None):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        undo = FakeUndoService() if history is None else history
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        return handler, data, plan_view, undo

    def test_a_synchronously_rejected_placement_leaves_no_preview_marker_or_token(self):
        for generation in (0, 3):
            with self.subTest(runtime_generation=generation):
                write = _SynchronousRejectionWriteService(generation=generation)
                with self.assertLogs(handler_module.logger, "WARNING") as logged:
                    handler, data, plan_view, undo = self._place(write)
                self.assertEqual(
                    [record.getMessage() for record in logged.records],
                    [
                        "SQL takeoff placement failed: SQL collaboration is not ready for editing."
                    ],
                )
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(plan_view.pending_mutation_uids, set())
                self.assertEqual(handler._pending_takeoff_placements, {})
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(undo.count, 0)

    def test_a_synchronous_rejection_does_not_block_the_real_history(self):
        history = UndoRedoService()
        history.set_active_bid(BidRef("bid.mdb", "7"))
        history.push_local(lambda: True, lambda: True)
        write = _SynchronousRejectionWriteService()
        with self.assertLogs(handler_module.logger, "WARNING"):
            self._place(write, history)
        self.assertTrue(history.can_undo())

    def test_a_synchronous_bid_locked_rejection_is_silent(self):
        write = _SynchronousRejectionWriteService(bid_locked=True)
        with self.assertNoLogs(handler_module.logger, "WARNING"):
            handler, data, plan_view, undo = self._place(write)
        self.assertEqual(data.takeoffs, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.forward_mutations, [])

    def test_a_stale_generation_is_still_ignored_once_the_submission_returned(self):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=write.queued_runtime_generation + 1,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.REJECTED,
            )
        )
        self.assertEqual(len(data.takeoffs), 1)
        self.assertIn(operation_id, handler._pending_takeoff_placements)
        self.assertEqual(
            handler._pending_takeoff_placements[operation_id].runtime_generation,
            write.queued_runtime_generation,
        )


class PlanViewActionHandlerTakeoffLabelExtrasTests(_PlanViewActionHandlerFixture):
    """The label font extras of a placed takeoff and how raw extras reach the model."""

    def _handler(
        self, area_font, style_font, area_color="#112233", style_color="#445566"
    ):
        data = FakeProjectData()
        write = FakeWriteService()
        handler = self._paste_handler(write=write, data=data)
        handler._ui_state.config_model = _FakeConfigModel(
            Config(
                default_area_label_font=area_font,
                default_style_label_font=style_font,
                default_area_label_color=area_color,
                default_style_label_color=style_color,
            )
        )
        return handler, write, data

    def test_label_extras_follow_the_configured_fonts_and_colours(self):
        bold_italic = FontDefinition("Arial", "Bold Italic", 24, 700, True, True)
        regular = FontDefinition("Arial", "Regular", 18, 400, False, False)
        bold = FontDefinition("Arial", "Bold", 30, 700, False, False)
        handler, _write, _data = self._handler(bold_italic, regular)
        self.assertEqual(
            handler._default_takeoff_label_extras(),
            {
                "FontName": "Arial",
                "FontColor": hex_color_to_int("#112233"),
                "FontSize": 24,
                "FontBold": True,
                "FontItalic": True,
                "FontUnderline": True,
                "NameFontName": "Arial",
                "NameFontColor": hex_color_to_int("#445566"),
                "NameFontSize": 18,
                "NameFontBold": False,
                "NameFontItalic": False,
                "NameFontUnderline": False,
            },
        )
        handler, _write, _data = self._handler(regular, bold)
        extras = handler._default_takeoff_label_extras()
        self.assertEqual((extras["FontBold"], extras["NameFontBold"]), (False, True))
        self.assertEqual((extras["FontSize"], extras["NameFontSize"]), (18, 30))
        self.assertEqual(
            (
                extras["FontItalic"],
                extras["FontUnderline"],
                extras["NameFontItalic"],
                extras["NameFontUnderline"],
            ),
            (False, False, False, False),
        )

    def test_raw_extras_reach_the_model_takeoff_field_by_field(self):
        handler, _write, data = self._handler(
            FontDefinition("Arial", "Regular", 18, 400, False, False),
            FontDefinition("Arial", "Regular", 18, 400, False, False),
        )
        spec = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            parent_uid=None,
            raw_extras={
                "FontName": "Dim",
                "FontColor": "255",
                "FontSize": -12,
                "FontBold": 1,
                "FontItalic": True,
                "FontUnderline": 1,
                "NameFontName": "Nm",
                "NameFontColor": 65280,
                "NameFontSize": "-9",
                "NameFontBold": True,
                "NameFontItalic": 1,
                "NameFontUnderline": True,
            },
        )
        handler._add_inserted_takeoffs_to_model(["n1"], [spec])
        takeoff = data.takeoffs["n1"]
        self.assertEqual(
            (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.dimension_font_bold,
                takeoff.dimension_font_italic,
                takeoff.dimension_font_underline,
            ),
            ("Dim", 255, 12, True, True, True),
        )
        self.assertEqual(
            (
                takeoff.name_font_name,
                takeoff.name_font_color,
                takeoff.name_font_size,
                takeoff.name_font_bold,
                takeoff.name_font_italic,
                takeoff.name_font_underline,
            ),
            ("Nm", 65280, 9, True, True, True),
        )
        self.assertEqual(takeoff.parent_uid, "0")

    def test_missing_or_blank_raw_extras_leave_the_defaults(self):
        handler, _write, data = self._handler(
            FontDefinition("Arial", "Regular", 18, 400, False, False),
            FontDefinition("Arial", "Regular", 18, 400, False, False),
        )
        blank = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={"FontName": "", "FontColor": "", "FontSize": None},
        )
        empty = InsertTakeoffSpec(
            condition_uid="c1", page_uid="p1", area_uid="0", position=[1.0, 2.0]
        )
        handler._add_inserted_takeoffs_to_model(["blank", "empty"], [blank, empty])
        for uid in ("blank", "empty"):
            takeoff = data.takeoffs[uid]
            self.assertEqual(
                (
                    takeoff.dimension_font_name,
                    takeoff.dimension_font_color,
                    takeoff.dimension_font_size,
                ),
                (None, None, None),
            )
            self.assertEqual(
                (
                    takeoff.dimension_font_bold,
                    takeoff.name_font_bold,
                    takeoff.name_font_name,
                ),
                (False, False, None),
            )

    def test_unique_ordered_keeps_the_first_of_each_truthy_value(self):
        self.assertEqual(
            PlanViewActionHandler._unique_ordered(
                ["b", "", None, "a", "b", 0, "a", "c"]
            ),
            ["b", "a", "c"],
        )


class PlanViewActionHandlerInsertResultTests(_PlanViewActionHandlerFixture):
    """_insert_takeoffs_with_undo and _insert_annotations_fast report their outcome."""

    def _handler(self):
        data = FakeProjectData()
        write = FakeWriteService()
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            write=write, ann_write=ann_write, data=data, undo=undo
        )
        return handler, write, ann_write, data, undo

    def _spec(self, **extras):
        return InsertTakeoffSpec(
            condition_uid="42",
            page_uid="9",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras=extras,
        )

    def test_a_takeoff_insert_reports_a_strict_bool(self):
        handler, write, ann_write, data, undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        self.assertIs(
            handler._insert_takeoffs_with_undo(bid, [self._spec()], fast_refresh=True),
            True,
        )
        write.uid_batches = [[]]
        self.assertIs(
            handler._insert_takeoffs_with_undo(bid, [self._spec()], fast_refresh=True),
            False,
        )
        write.insert_takeoffs_failure_reason = "refused"
        with patch.object(handler_module, "show_warning") as warning:
            self.assertIs(
                handler._insert_takeoffs_with_undo(bid, [self._spec()]), False
            )
        warning.assert_called_once_with(handler._plan_view, "Database Write", "refused")
        self.assertEqual(undo.count, 1)

    def test_a_reload_failure_without_a_reason_is_a_failed_insert(self):
        handler, write, ann_write, data, undo = self._handler()
        write.insert_takeoffs_result = lambda *args, **options: WriteReloadResult(
            ["new-1"], write_success=True, reload_success=False
        )
        bid = handler._ui_state.get_selected_bid_ref()
        self.assertIs(handler._insert_takeoffs_with_undo(bid, [self._spec()]), False)
        self.assertEqual(undo.count, 0)
        self.assertEqual(handler._plan_view.selected, set())

    def test_a_full_refresh_insert_replays_through_the_plain_write_entries(self):
        handler, write, ann_write, data, undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        handler._plan_view.current_page_uid = "9"
        write.next_uids = ["n1", "n2"]
        self.assertTrue(
            handler._insert_takeoffs_with_undo(
                bid, [self._spec(Other=1)], fast_refresh=True
            )
        )
        self.assertEqual(handler._plan_view.selected, {"n1"})
        self.assertEqual(data.added_takeoffs, [])
        undo.undo()
        self.assertEqual(write.delete_calls, [("bid.mdb", ["n1"], True)])
        self.assertEqual(handler._plan_view.clears, 1)
        undo.redo()
        self.assertEqual(write.calls[-1][3], True)
        self.assertEqual(write.calls[-1][0:2], ("bid.mdb", "7"))
        self.assertEqual(handler._plan_view.selected, {"n2"})
        self.assertEqual(data.added_takeoffs, [])

    def test_a_refused_redo_insert_returns_false_and_selects_nothing(self):
        handler, write, ann_write, data, undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        handler._insert_takeoffs_with_undo(bid, [self._spec()], fast_refresh=True)
        undo.undo()
        write.uid_batches = [[]]
        selected = set(handler._plan_view.selected)
        self.assertIs(undo.redo(), False)
        self.assertEqual(handler._plan_view.selected, selected)

    def test_a_failed_annotation_insert_logs_what_could_not_be_saved(self):
        handler, write, ann_write, data, undo = self._handler()
        ann_write.next_uids = []
        spec = InsertAnnotationSpec(
            page_uid="p1",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
            layer_uid="L1",
        )
        bid = handler._ui_state.get_selected_bid_ref()
        with patch.object(handler_module, "show_warning") as warning:
            with self.assertLogs(handler_module.logger, "WARNING") as logged:
                self.assertEqual(handler._insert_annotations_fast(bid, [spec]), [])
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            [
                "Annotation insertion failed: database=bid.mdb bid=7 count=1 "
                "first_targets=[('p1', 'rect', 'L1')]"
            ],
        )
        warning.assert_called_once()
        self.assertEqual(handler._insert_annotations_fast(bid, []), [])


class PlanViewActionHandlerNamedViewChoiceTests(_PlanViewActionHandlerFixture):
    """The Named View picker choices and the colours of placed Named Views."""

    def test_choices_list_named_views_only_and_fall_back_to_the_uid_for_a_blank_name(
        self,
    ):
        data = FakeProjectData()
        data.page_names["p2"] = "A101"
        data.annotations = [
            _named_view_annotation("nv1", "Lobby"),
            _named_view_annotation("nv2", ""),
            _rect_annotation("r1"),
        ]
        data.annotations[1].page_uid = "p2"
        handler = self._paste_handler(plan_view=FakePlanView(data), data=data)
        self.assertEqual(
            handler._collect_named_view_choices(),
            [("nv1", "p1", "Page 1", "Lobby"), ("nv2", "p2", "A101", "nv2")],
        )

    def test_a_named_view_gets_the_colour_it_is_given_only_when_it_is_a_non_empty_text(
        self,
    ):
        for color, expected in (
            ("#112233", "#112233"),
            ("", None),
            (5, None),
            (None, None),
        ):
            with self.subTest(color=color):
                ann_write = FakeAnnotationWriteService()
                handler = self._paste_handler(ann_write=ann_write)
                default = build_placed_annotation_spec(
                    "namedview", "p1", [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
                ).color
                self.assertNotEqual(default, "#112233")
                properties = {"Text": "Lobby"}
                if color is not None:
                    properties["Color"] = color
                handler.on_named_view_created(
                    [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0], "p1", properties
                )
                self.assertEqual(
                    ann_write.insert_calls[0][2][0].color, expected or default
                )

    def test_a_named_view_name_may_be_none_but_not_a_blank(self):
        ann_write = FakeAnnotationWriteService()
        handler = self._paste_handler(ann_write=ann_write)
        handler.on_named_view_created(list(range(9)), "p1", {"Text": None})
        handler.on_named_view_created(list(range(9)), "p1", {"Text": "\t "})
        self.assertEqual(ann_write.insert_calls, [])


class PlanViewActionHandlerLeaseReleaseAndOverlayGuardTests(
    _PlanViewActionHandlerFixture
):
    """Gaps found by the sp4 whole-module mutation sweep: the request id that fences a
    late lease grant, and the empty-Page guard in front of the data service."""

    _handler = PlanViewActionHandlerGeometryLeaseRequestTests._handler
    _grant = staticmethod(PlanViewActionHandlerGeometryLeaseLifecycleTests._grant)

    def test_a_release_forgets_the_pending_request_so_a_grant_for_a_cleared_selection_is_ended(
        self,
    ):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        self.assertNotEqual(handler._geometry_edit_lease_request_id, "")
        plan_view.selected = set()
        handler.on_plan_item_selection_changed([])
        self.assertEqual(handler._geometry_edit_lease_request_id, "")
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self.assertEqual(plan_view.geometry_lease_granted, set())
        self.assertEqual(plan_view.geometry_lease_pending, set())

    def test_an_unreleased_request_adopts_its_grant_for_the_unchanged_selection(self):
        handler, plan_view, write, _data = self._handler()
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = self._grant(write)
        handler.on_plan_item_selection_changed(["t1"])
        callback(EditLeaseResult(True, handle=handle))
        self.assertEqual(write.ended_edit_leases, [])
        self.assertIs(handler._geometry_edit_lease_handle, handle)
        self.assertEqual(plan_view.geometry_lease_granted, {"t1"})
        self.assertEqual(handler._geometry_edit_lease_request_id, "")

    def test_an_empty_active_page_uid_is_refused_before_the_data_service_is_asked(self):
        for empty in ("", None):
            with self.subTest(active_page_uid=empty):
                data = FakeProjectData()
                data.pages[empty] = SimpleNamespace(
                    uid=empty, overlay_rect=None, scale_factor1=1.0, scale_factor2=1.0
                )
                deferred = FakeDeferredPersistence()
                handler = self._overlay_handler(data, deferred)
                handler._ui_state = SimpleNamespace(
                    active_page_uid=empty,
                    get_selected_bid_ref=lambda: BidRef("bid.mdb", "7"),
                )
                self.assertIs(
                    handler.save_current_page_overlay_rect((1, 2, 3, 4)), False
                )
                self.assertEqual(deferred.overlay_rect_calls, [])
                self.assertIsNone(data.pages[empty].overlay_rect)


class PlanViewActionHandlerHistoryParentIdentityTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the helpers that keep a
    Backout's parent (and a Hot Link's Named View) a lifetime dependency of a history
    entry."""

    @staticmethod
    def _spec(parent_uid=None, **extras):
        return InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0, 3.0, 4.0],
            parent_uid=parent_uid,
            **extras,
        )

    def _handler(self, sql=False):
        data = FakeProjectData()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        data.takeoffs["H"] = Takeoff(
            uid="H",
            condition_uid="c1",
            page_uid="p1",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
            parent_uid="P",
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_a_local_delete_undo_refuses_to_restore_under_a_parent_that_moved_pages(
        self,
    ):
        handler, _plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["H"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["H"], False)])
        self.assertEqual([t.uid for t in undo.takeoff_targets if t.uid == "P"], ["P"])
        data.takeoffs["P"].page_uid = "9"
        with self.assertRaisesRegex(ValueError, "no longer owns its Page"):
            undo.undo()
        self.assertEqual(write.calls, [])

    def test_a_local_delete_undo_restores_under_the_surviving_parent(self):
        handler, _plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["H"])
        write.next_uids = ["H2"]
        self.assertIs(undo.undo(), True)
        self.assertEqual([spec.parent_uid for spec in write.calls[0][2]], ["P"])
        self.assertEqual(set(data.takeoffs), {"P", "H2"})

    def test_an_external_parent_sharing_the_uid_of_a_source_still_gets_a_lifetime_target(
        self,
    ):
        handler, _plan_view, _write, _data, _undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        specs = (self._spec(), self._spec(parent_uid="P"))
        self.assertEqual(handler._history_parent_targets(bid, ("P", "S"), specs), {})
        targets = handler._history_parent_targets(
            bid, ("P", "S"), specs, external_parent_sources=("S",)
        )
        self.assertEqual(set(targets), {"P"})
        self.assertEqual((targets["P"].page_uid, targets["P"].uid), ("p1", "P"))

    def test_only_the_external_children_follow_a_replaced_parent_that_shares_a_source_uid(
        self,
    ):
        handler, _plan_view, _write, data, _undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        specs = (self._spec(), self._spec(parent_uid="P"), self._spec(parent_uid="P"))
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("P", "A", "B"),
            takeoff_specs=specs,
            takeoff_external_parent_sources=("B",),
        )
        parents = handler._history_parent_targets(
            bid,
            payload.takeoff_source_uids,
            payload.takeoff_specs,
            external_parent_sources=payload.takeoff_external_parent_sources,
        )
        self.assertEqual(set(parents), {"P"})
        data.takeoffs["P2"] = replace(data.takeoffs["P"], uid="P2")
        parents["P"].uid = "P2"
        replaced = handler._paste_payload_with_history_parents(payload, parents)
        self.assertEqual(
            [spec.parent_uid for spec in replaced.takeoff_specs], [None, "P", "P2"]
        )
        self.assertEqual(replaced.takeoff_external_parent_sources, ("B",))

    def test_a_deleted_named_view_and_its_hot_link_leave_no_extra_view_dependency(self):
        data = FakeProjectData()
        view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"nv1": view, "hl1": hotlink}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        with patch.object(handler_module, "confirm", return_value=True):
            handler.on_elements_deleted(["nv1"])
        self.assertEqual(len(write.queued_deletes), 1)
        write.queued_deletes[0][-1](_committed())
        self.assertEqual(
            sorted((t.annotation_type, t.uid) for t in undo.annotation_targets),
            [("hotlink", "hl1"), ("namedview", "nv1")],
        )

    def test_a_hot_link_on_a_view_outside_the_batch_keeps_that_view_as_a_dependency(
        self,
    ):
        data = FakeProjectData()
        view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view = FakePlanView(data)
        plan_view.annotations = {"nv1": view, "hl1": hotlink}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler.on_elements_deleted(["hl1"])
        write.queued_deletes[0][-1](_committed())
        self.assertEqual(
            sorted((t.annotation_type, t.uid) for t in undo.annotation_targets),
            [("hotlink", "hl1"), ("namedview", "nv1")],
        )


class PlanViewActionHandlerHelperContractTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep: the small helpers whose
    documented fallbacks and strict results the end-to-end tests never observed."""

    def _handler(self):
        data = FakeProjectData()
        data.pages["zero"] = SimpleNamespace(
            uid="zero", overlay_rect=None, scale_factor1=0, scale_factor2=0
        )
        data.pages["blank"] = SimpleNamespace(
            uid="blank", overlay_rect=None, scale_factor1=None, scale_factor2=None
        )
        data.pages["half"] = SimpleNamespace(
            uid="half", overlay_rect=None, scale_factor1=2, scale_factor2=0
        )
        data.pages["scaled"] = SimpleNamespace(
            uid="scaled", overlay_rect=None, scale_factor1=0.125, scale_factor2=12
        )
        write = FakeWriteService()
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data
        )
        return handler, write, data

    def test_the_page_scale_falls_back_to_unity_per_factor_and_for_an_unknown_page(
        self,
    ):
        handler, _write, _data = self._handler()
        self.assertEqual(handler._page_scale_for_page_uid("missing"), (1.0, 1.0))
        self.assertEqual(handler._page_scale_for_page_uid("zero"), (1.0, 1.0))
        self.assertEqual(handler._page_scale_for_page_uid("blank"), (1.0, 1.0))
        self.assertEqual(handler._page_scale_for_page_uid("half"), (2.0, 1.0))
        scaled = handler._page_scale_for_page_uid("scaled")
        self.assertEqual(scaled, (0.125, 12.0))
        self.assertEqual({type(value) for value in scaled}, {float})

    def test_a_takeoff_or_annotation_takes_the_scale_of_its_page_and_unity_when_unknown(
        self,
    ):
        handler, _write, data = self._handler()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="scaled", position=[0.0, 0.0]
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="rect",
                page_uid="half",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        self.assertEqual(handler._takeoff_scale_for_uid("t1"), (0.125, 12.0))
        self.assertEqual(handler._takeoff_scale_for_uid("gone"), (1.0, 1.0))
        self.assertEqual(handler._annotation_scale_for_key("a1", "rect"), (2.0, 1.0))
        self.assertEqual(handler._annotation_scale_for_key("a1", "oval"), (1.0, 1.0))
        self.assertEqual(handler._annotation_scale_for_key("gone", "rect"), (1.0, 1.0))
        self.assertEqual(
            handler._capture_takeoff_scales([("t1", [0.0]), ("gone", [0.0])]),
            {"t1": (0.125, 12.0), "gone": (1.0, 1.0)},
        )

    def test_deleting_takeoffs_fast_reports_a_strict_bool_and_touches_nothing_when_empty(
        self,
    ):
        handler, write, data = self._handler()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        self.assertIs(handler._delete_takeoffs_fast("bid.mdb", []), True)
        self.assertEqual(write.delete_calls, [])
        self.assertEqual(handler._event_bus.events, [])
        write.delete_takeoffs = lambda *args, **options: False
        self.assertIs(handler._delete_takeoffs_fast("bid.mdb", ["t1"]), False)
        self.assertIn("t1", data.takeoffs)
        self.assertEqual(handler._event_bus.events, [])
        del write.delete_takeoffs
        self.assertIs(handler._delete_takeoffs_fast("bid.mdb", ["t1"]), True)
        self.assertNotIn("t1", data.takeoffs)
        self.assertEqual(
            handler._event_bus.events,
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

    def test_fast_delete_eligibility_is_a_strict_bool(self):
        handler, _write, _data = self._handler()
        parent = Takeoff(
            uid="P", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        child = Takeoff(
            uid="H",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0],
            parent_uid="P",
        )
        self.assertIs(handler._takeoffs_allow_fast_delete([child], {}), True)
        self.assertIs(handler._takeoffs_allow_fast_delete([parent, child], {}), False)
        self.assertIs(
            handler._takeoffs_allow_fast_delete([child], {"H": {"FontName": "Arial"}}),
            True,
        )
        self.assertIs(
            handler._takeoffs_allow_fast_delete([child], {"H": {"Unlisted": 1}}), False
        )

    def test_a_refused_local_property_write_returns_false_and_projects_nothing(self):
        handler, write, data = self._handler()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        bid = handler._ui_state.get_selected_bid_ref()
        write.save_takeoffs_area = lambda *args, **options: False
        self.assertIs(
            handler._execute_local_plan_properties(bid, "takeoff_area", [("t1", "a2")]),
            False,
        )
        self.assertEqual(data.takeoffs["t1"].area_uid, "0")
        self.assertEqual(handler._event_bus.events, [])
        del write.save_takeoffs_area
        self.assertIs(
            handler._execute_local_plan_properties(bid, "takeoff_area", [("t1", "a2")]),
            True,
        )
        self.assertEqual(data.takeoffs["t1"].area_uid, "a2")


class PlanViewActionHandlerLocalCommandFailureTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the local (MDB) command
    paths: a refused write leaves no history, and degenerate flushes register none."""

    def _handler(self, position=None):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=(
                [0.0, 0.0, 10.0, 0.0, 10.0, 10.0] if position is None else position
            ),
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_a_refused_local_property_save_registers_no_history_and_publishes_nothing(
        self,
    ):
        commands = (
            ("area", lambda h: h.on_assign_to_area(["t1"]), "save_takeoffs_area"),
            (
                "condition",
                lambda h: h.on_reassign_condition(["t1"], "42"),
                "save_takeoffs_condition",
            ),
            (
                "negative",
                lambda h: h.on_set_negative(["t1"], True),
                "set_takeoffs_negative",
            ),
            ("curve", lambda h: h.on_set_curved(["t1"], True), "set_takeoff_curve"),
        )
        for name, command, saver in commands:
            with self.subTest(command=name, write="refused"):
                handler, _plan_view, write, data, undo = self._handler()
                before = replace(data.takeoffs["t1"])
                setattr(write, saver, lambda *args, **options: False)
                command(handler)
                self.assertEqual(undo.count, 0)
                self.assertEqual(handler._event_bus.events, [])
                self.assertEqual(data.takeoffs["t1"], before)
            with self.subTest(command=name, write="accepted"):
                handler, _plan_view, write, data, undo = self._handler()
                command(handler)
                self.assertEqual(undo.count, 1)
                self.assertEqual(len(handler._event_bus.events), 1)

    def test_curving_skips_a_takeoff_whose_position_cannot_be_parsed(self):
        handler, plan_view, write, data, undo = self._handler()
        data.takeoffs["bad"] = Takeoff(
            uid="bad", condition_uid="c1", page_uid="p1", position=[7.0]
        )
        plan_view.get_coordinate_system = lambda: SimpleNamespace(
            parse_position=lambda position: (
                None if list(position) == [7.0] else list(position)
            )
        )
        handler.on_set_curved(["bad", "t1"], True)
        self.assertEqual([call[1] for call in write.curve_calls], ["t1"])
        self.assertEqual(undo.count, 1)

    def test_a_queued_curve_marks_exactly_the_curved_takeoffs_pending(self):
        handler, plan_view, write, _data, _undo = self._handler()
        write.sql_collaboration_mutations = True
        handler.on_set_curved(["t1"], True)
        self.assertEqual(plan_view.pending_mutation_uids, {"t1"})
        self.assertEqual(
            [
                event
                for event in handler._event_bus.events
                if event[0] == AppEvents.PENDING_PLAN_MUTATIONS_CHANGED
            ],
            [
                (
                    AppEvents.PENDING_PLAN_MUTATIONS_CHANGED,
                    {
                        "database_id": "bid.mdb",
                        "bid_uid": "7",
                        "takeoff_uids": ["t1"],
                        "pending": True,
                    },
                )
            ],
        )

    def test_a_position_flush_without_any_previous_position_is_saved_but_not_undoable(
        self,
    ):
        handler, _plan_view, write, _data, undo = self._handler()
        handler.on_positions_flushed([("t1", [], [1.0, 1.0, 2.0, 2.0])], [])
        self.assertEqual(
            [call[1] for call in write.position_calls], [[("t1", [1.0, 1.0, 2.0, 2.0])]]
        )
        self.assertEqual(undo.count, 0)

    def test_a_rotation_flush_without_any_previous_rotation_is_saved_but_not_undoable(
        self,
    ):
        handler, _plan_view, write, _data, undo = self._handler()
        handler.on_rotations_flushed([("t1", None, 45.0)])
        self.assertEqual([call[1] for call in write.rotation_calls], [[("t1", 45.0)]])
        self.assertEqual(undo.count, 0)

    def test_one_queued_preview_in_a_rotation_flush_restores_the_whole_flush(self):
        preview = queued_takeoff_preview_uid(str(uuid.uuid4()), 0)
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, plan_view, write, _data, undo = self._handler()
                write.sql_collaboration_mutations = sql
                changes = [("t1", 0.0, 45.0), (preview, 0.0, 90.0)]
                handler.on_rotations_flushed(changes)
                self.assertEqual(plan_view.restored_rotations, [changes])
                self.assertEqual(write.rotation_calls, [])
                self.assertEqual(write.queued_geometry, [])
                self.assertEqual(undo.count, 0)

    def test_a_denied_empty_group_rotation_has_nothing_to_restore(self):
        handler, plan_view, write, _data, undo = self._handler()
        handler._ui_access_manager.allowed_features.clear()
        handler.on_group_rotation_flushed([], [], [])
        self.assertEqual(
            (plan_view.restored_positions, plan_view.restored_rotations), ([], [])
        )

    def test_a_group_rotation_of_annotations_alone_is_undoable(self):
        handler, plan_view, write, data, undo = self._handler()
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="rect",
                page_uid="p1",
                position=[1.0, 1.0, 5.0, 1.0],
            )
        ]
        plan_view.annotation_key_map = {("a1", "rect"): "a1_rect"}
        plan_view.annotations = {"a1_rect": data.annotations[0]}
        handler.on_group_rotation_flushed(
            [], [("a1", "rect", [1.0, 1.0, 5.0, 1.0], [2.0, 2.0, 6.0, 2.0])], []
        )
        self.assertEqual(undo.count, 1)
        self.assertEqual(data.annotations[0].position, [2.0, 2.0, 6.0, 2.0])
        undo.undo()
        self.assertEqual(data.annotations[0].position, [1.0, 1.0, 5.0, 1.0])
        undo.redo()
        self.assertEqual(data.annotations[0].position, [2.0, 2.0, 6.0, 2.0])


class PlanViewActionHandlerPlacementCompletionGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the terminal branches of a
    queued takeoff placement."""

    _placed = PlanViewActionHandlerPlacementCompletionTests._placed
    _result = staticmethod(PlanViewActionHandlerPlacementCompletionTests._result)
    _changed_events = staticmethod(
        PlanViewActionHandlerPlacementCompletionTests._changed_events
    )

    def test_a_wrong_identity_count_republishes_the_removed_preview_only_for_the_current_model(
        self,
    ):
        for name, bid, publishes in (
            ("same bid", BidRef("bid.mdb", "7"), 1),
            ("another bid in the same database", BidRef("bid.mdb", "8"), 0),
            ("another database", BidRef("other.mdb", "7"), 0),
        ):
            with self.subTest(case=name):
                (
                    handler,
                    data,
                    plan_view,
                    write,
                    undo,
                    operation_id,
                    callback,
                    pending_uid,
                ) = self._placed()
                handler._ui_state = SimpleNamespace(
                    active_page_uid="9", get_selected_bid_ref=lambda: bid
                )
                before = len(self._changed_events(handler))
                with self.assertLogs(handler_module.logger, "ERROR"):
                    callback(
                        self._result(
                            operation_id,
                            MutationOutcomeStatus.COMMITTED,
                            ("501", "502"),
                        )
                    )
                self.assertEqual(len(self._changed_events(handler)) - before, publishes)
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(undo.forward_mutations, [])

    def test_a_committed_placement_is_ignored_unless_its_bid_and_page_are_still_active(
        self,
    ):
        replaced = SimpleNamespace(
            uid="9", overlay_rect=None, scale_factor1=1.0, scale_factor2=1.0
        )
        cases = (
            ("another bid of the same database", BidRef("bid.mdb", "8"), None),
            ("the same bid uid in another database", BidRef("other.mdb", "7"), None),
            ("no active bid", None, None),
            ("the page was replaced", BidRef("bid.mdb", "7"), replaced),
        )
        for name, bid, replacement in cases:
            with self.subTest(case=name):
                (
                    handler,
                    data,
                    plan_view,
                    write,
                    undo,
                    operation_id,
                    callback,
                    pending_uid,
                ) = self._placed()
                handler._ui_state = SimpleNamespace(
                    active_page_uid="9", get_selected_bid_ref=lambda: bid
                )
                if replacement is not None:
                    data.pages["9"] = replacement
                callback(
                    self._result(
                        operation_id, MutationOutcomeStatus.COMMITTED, ("501",)
                    )
                )
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(plan_view.selected, set())
                self.assertEqual(undo.count, 0)
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(handler._completed_sql_mutation_ids, {operation_id})
                self.assertEqual(handler._pending_takeoff_placements, {})

    def test_the_committed_takeoffs_are_selected_on_the_page_the_view_or_the_ui_shows(
        self,
    ):
        for view_page, ui_page, expected in (
            ("", "9", {"501"}),
            ("9", "p1", {"501"}),
            ("p1", "9", set()),
            ("", "", set()),
        ):
            with self.subTest(view_page=view_page, ui_page=ui_page):
                (
                    handler,
                    data,
                    plan_view,
                    write,
                    undo,
                    operation_id,
                    callback,
                    pending_uid,
                ) = self._placed()
                plan_view.current_page_uid = view_page
                handler._ui_state = SimpleNamespace(
                    active_page_uid=ui_page,
                    get_selected_bid_ref=lambda: BidRef("bid.mdb", "7"),
                )
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
                    self._result(
                        operation_id, MutationOutcomeStatus.COMMITTED, ("501",)
                    )
                )
                self.assertEqual(plan_view.selected, expected)
                self.assertEqual(undo.count, 1)

    def test_a_committed_placement_does_not_select_into_a_plan_that_is_cleaning_up(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        plan_view._is_cleaning_up = True
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        callback(self._result(operation_id, MutationOutcomeStatus.COMMITTED, ("501",)))
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(undo.count, 1)

    def test_a_committed_placement_whose_previews_were_all_deleted_leaves_the_selection_alone(
        self,
    ):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        plan_view.selected = {"user-choice"}
        handler.on_elements_deleted([pending_uid])
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        callback(self._result(operation_id, MutationOutcomeStatus.COMMITTED, ("501",)))
        self.assertEqual(len(write.cleanup_delete_calls), 1)
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(undo.count, 0)

    def test_a_rejection_after_every_preview_was_deleted_is_still_a_failure(self):
        handler, data, plan_view, write, undo, operation_id, callback, pending_uid = (
            self._placed()
        )
        handler.on_elements_deleted([pending_uid])
        self.assertEqual(write.cancelled_mutations, [("bid.mdb", operation_id)])
        before = len(self._changed_events(handler))
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            callback(
                self._result(
                    operation_id, MutationOutcomeStatus.CONFLICT, message="conflict"
                )
            )
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL takeoff placement failed: conflict"],
        )
        self.assertEqual(len(self._changed_events(handler)) - before, 1)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(handler._pending_takeoff_placements, {})

    def test_a_failing_rollback_projection_is_logged_and_the_queue_error_still_surfaces(
        self,
    ):
        data = FakeProjectData()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(write=write, data=data)
        failures = []

        def broken_queue(*args, **kwargs):
            raise RuntimeError("queue unavailable")

        def broken_publish(event, **payload):
            if (
                event == AppEvents.PENDING_PLAN_MUTATIONS_CHANGED
                and payload["pending"] is False
            ):
                failures.append(payload)
                raise OSError("bus unavailable")

        write.queue_takeoff_placement = broken_queue
        handler._event_bus.publish = broken_publish
        with self.assertLogs(handler_module.logger, "ERROR") as logged:
            with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                handler.on_takeoff_created("42", [3.0, 4.0], "9")
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["Failed to publish queued-placement pending-state rollback"],
        )
        self.assertEqual(handler._pending_takeoff_placements, {})


class PlanViewActionHandlerAnnotationDeleteHistoryGapTests(
    _PlanViewActionHandlerFixture
):
    """Gaps found by the sp4 whole-module mutation sweep in the local fast delete of
    annotations alone and in the results its undo and redo report."""

    def _handler(self):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        plan_view.annotation_key_map[("a2", "rect")] = "rect-item-2"
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = ["a2"]
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data, undo=undo
        )
        handler.on_elements_deleted(["rect-item"])
        return handler, plan_view, ann_write, data, undo

    def test_undoing_an_annotation_delete_that_cannot_reinsert_reports_false_and_stays_suspended(
        self,
    ):
        handler, plan_view, ann_write, data, undo = self._handler()
        self.assertEqual(data.annotations, [])
        self.assertEqual([t.available for t in undo.annotation_targets], [False])
        ann_write.next_uids = []
        self.assertIs(undo.undo(), False)
        self.assertEqual([t.available for t in undo.annotation_targets], [False])
        self.assertEqual(plan_view.selected, set())

    def test_undoing_and_redoing_an_annotation_delete_follow_the_restored_identity(
        self,
    ):
        handler, plan_view, ann_write, data, undo = self._handler()
        self.assertIs(undo.undo(), True)
        self.assertEqual(
            [(t.uid, t.available) for t in undo.annotation_targets], [("a2", True)]
        )
        self.assertEqual(plan_view.selected, {"rect-item-2"})
        self.assertIs(undo.redo(), True)
        self.assertEqual([t.available for t in undo.annotation_targets], [False])
        self.assertEqual(plan_view.selected, set())

    def test_an_annotation_redo_the_database_refuses_reports_false(self):
        handler, plan_view, ann_write, data, undo = self._handler()
        undo.undo()
        ann_write.delete_annotations = lambda *args, **options: False
        self.assertIs(undo.redo(), False)
        self.assertEqual([t.available for t in undo.annotation_targets], [True])
        self.assertEqual(plan_view.selected, {"rect-item-2"})


class PlanViewActionHandlerPartialPreviousPositionTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep. The plan view reports `[]` as
    the previous position of an item whose position before the edit was not captured
    (finding F4). The local history of such a flush keeps the annotations it knows and
    must stay undoable for the rest."""

    ANNOTATION_OLD = [1.0, 1.0, 5.0, 1.0]
    ANNOTATION_NEW = [2.0, 2.0, 6.0, 2.0]

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[3.0, 3.0, 4.0, 4.0]
        )
        data.annotations = [
            BidAnnotation(
                uid="a1",
                annotation_type="rect",
                page_uid="p1",
                position=list(self.ANNOTATION_NEW),
            ),
            BidAnnotation(
                uid="a2",
                annotation_type="rect",
                page_uid="p1",
                position=list(self.ANNOTATION_NEW),
            ),
        ]
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {
            ("a1", "rect"): "a1_rect",
            ("a2", "rect"): "a2_rect",
        }
        plan_view.annotations = {
            "a1_rect": data.annotations[0],
            "a2_rect": data.annotations[1],
        }
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    @staticmethod
    def _flush(handler, entry_point, takeoff_changes, annotation_changes):
        if entry_point == "positions":
            handler.on_positions_flushed(takeoff_changes, annotation_changes)
        else:
            handler.on_group_rotation_flushed(takeoff_changes, annotation_changes, [])

    def test_an_annotation_without_a_previous_position_does_not_stop_the_undo_of_the_takeoff(
        self,
    ):
        for entry_point in ("positions", "group rotation"):
            with self.subTest(entry_point=entry_point):
                handler, plan_view, write, data, undo = self._handler()
                self._flush(
                    handler,
                    entry_point,
                    [("t1", [3.0, 3.0, 4.0, 4.0], [5.0, 5.0, 6.0, 6.0])],
                    [("a1", "rect", [], list(self.ANNOTATION_NEW))],
                )
                self.assertEqual(undo.count, 1)
                self.assertEqual(
                    [(t.annotation_type, t.uid) for t in undo.annotation_targets],
                    [("rect", "a1")],
                )
                self.assertIs(undo.undo(), True)
                self.assertEqual(data.takeoffs["t1"].position, [3.0, 3.0, 4.0, 4.0])
                self.assertEqual(data.annotations[0].position, self.ANNOTATION_NEW)

    def test_an_annotation_with_a_previous_position_is_restored_next_to_one_without(
        self,
    ):
        for entry_point in ("positions", "group rotation"):
            with self.subTest(entry_point=entry_point):
                handler, plan_view, write, data, undo = self._handler()
                self._flush(
                    handler,
                    entry_point,
                    [("t1", [3.0, 3.0, 4.0, 4.0], [5.0, 5.0, 6.0, 6.0])],
                    [
                        (
                            "a1",
                            "rect",
                            list(self.ANNOTATION_OLD),
                            list(self.ANNOTATION_NEW),
                        ),
                        ("a2", "rect", [], list(self.ANNOTATION_NEW)),
                    ],
                )
                self.assertEqual(
                    [(t.annotation_type, t.uid) for t in undo.annotation_targets],
                    [("rect", "a1")],
                )
                self.assertIs(undo.undo(), True)
                self.assertEqual(data.takeoffs["t1"].position, [3.0, 3.0, 4.0, 4.0])
                self.assertEqual(data.annotations[0].position, self.ANNOTATION_OLD)
                self.assertEqual(data.annotations[1].position, self.ANNOTATION_NEW)


class PlanViewActionHandlerCommandTargetGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the multi-condition placement
    targets, the reassignment pool, the paste anchor and the delete selection."""

    def _handler(self, sql=False, history=None):
        data = FakeProjectData()
        data.conditions["area2"] = Condition(
            uid="area2", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        data.conditions["hidden"] = Condition(
            uid="hidden", layer_visible=False, condition_type=Condition.TYPE_AREA
        )
        data.conditions["linear"] = Condition(
            uid="linear", layer_visible=True, condition_type=Condition.TYPE_LINEAR
        )
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        undo = FakeUndoService() if history is None else history
        plan_view = FakePlanView(data)
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_placement_targets_keep_the_visible_conditions_of_the_active_type_once_in_order(
        self,
    ):
        handler, _plan_view, _write, _data, _undo = self._handler()
        places = ["area2", "hidden", "linear", "unknown", "", None, "42", "area2"]
        self.assertEqual(
            handler._target_place_condition_uids("42", places), ["area2", "42"]
        )
        self.assertEqual(handler._target_place_condition_uids("42", None), ["42"])
        self.assertEqual(
            handler._target_place_condition_uids("42", ["linear", "hidden"]), ["42"]
        )
        self.assertEqual(
            handler._target_place_condition_uids("linear", places), ["linear"]
        )

    def test_placement_targets_of_a_hidden_or_unknown_active_condition_are_that_condition_only(
        self,
    ):
        handler, _plan_view, _write, _data, _undo = self._handler()
        self.assertEqual(
            handler._target_place_condition_uids("hidden", ["42", "area2"]), ["hidden"]
        )
        self.assertEqual(
            handler._target_place_condition_uids("unknown", ["42", "area2"]),
            ["unknown"],
        )

    def test_a_takeoff_placed_with_several_selected_conditions_places_one_takeoff_per_visible_one(
        self,
    ):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, plan_view, write, data, undo = self._handler(sql=sql)
                plan_view.current_page_uid = "9"
                handler._ui_state = SimpleNamespace(
                    place_condition_uids=["area2", "hidden", "linear"],
                    active_page_uid="9",
                    get_selected_bid_ref=lambda: BidRef("bid.mdb", "7"),
                    config_model=FakeUiState.config_model,
                )
                handler.on_takeoff_created("42", [1.0, 2.0], "9")
                specs = write.calls[0][2]
                self.assertEqual(
                    [spec.condition_uid for spec in specs], ["area2", "42"]
                )

    def test_a_reassignment_carries_only_the_area_children_of_the_selection(self):
        handler, _plan_view, write, data, _undo = self._handler()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        data.takeoffs["H"] = Takeoff(
            uid="H",
            condition_uid="c1",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
            parent_uid="P",
        )
        data.takeoffs["odd"] = Takeoff(
            uid="odd",
            condition_uid="linear",
            page_uid="p1",
            position=[1.0, 1.0, 2.0, 1.0],
            parent_uid="P",
        )
        handler.on_reassign_condition(["P"], "42")
        self.assertEqual(write.condition_calls, [("bid.mdb", ["P", "H"], "42", False)])

    def test_the_paste_anchor_is_the_first_takeoff_with_a_position_else_the_first_annotation(
        self,
    ):
        handler, _plan_view, _write, _data, _undo = self._handler()
        short = Takeoff(uid="short", condition_uid="c1", page_uid="p1", position=[7.0])
        exact = Takeoff(
            uid="exact", condition_uid="c1", page_uid="p1", position=[3.0, 4.0]
        )
        annotation = self._copied_annotation(position=[10.0, 20.0, 14.0, 20.0])
        self.assertEqual(
            handler._paste_source_anchor([short, exact], [annotation]), (3.0, 4.0)
        )
        self.assertEqual(
            handler._paste_source_anchor([short], [annotation]),
            annotation_paste_anchor(annotation),
        )
        self.assertIsNone(handler._paste_source_anchor([short], []))

    def test_a_refused_annotation_only_delete_reselects_the_request_and_registers_no_history(
        self,
    ):
        data = FakeProjectData()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        ann_write = FakeAnnotationWriteService()
        ann_write.delete_annotations = lambda *args, **options: False
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data, undo=undo
        )
        handler.on_elements_deleted(["rect-item"])
        self.assertEqual(plan_view.selected, {"rect-item"})
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.annotation_targets, [])
        self.assertEqual(data.annotations, [annotation])

    def test_a_local_mixed_delete_selects_the_named_view_the_user_kept(self):
        handler, plan_view, write, data, undo = self._handler()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        rect = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [rect, view, hotlink]
        plan_view.annotations = {"rect-item": rect, "nv1": view, "hl1": hotlink}
        with patch.object(handler_module, "confirm", return_value=False):
            handler.on_elements_deleted(["t1", "rect-item", "nv1"])
        self.assertEqual(len(write.local_deletes), 1)
        self.assertEqual(write.local_deletes[0][2], ["t1"])
        self.assertEqual(plan_view.selected, {"nv1"})
        self.assertEqual(undo.count, 1)

    def test_the_queued_paste_history_completes_rebinds_and_suspends_through_its_callbacks(
        self,
    ):
        history = _RecordingHistory()
        handler, plan_view, write, data, undo = self._handler(sql=True, history=history)
        plan_view.annotation_key_map = {
            ("new-ann", "line"): "new-ann_line",
            ("new-ann-2", "line"): "new-ann_line-2",
        }
        handler._clipboard_svc = FakeClipboard(
            [self._copied_takeoff()],
            annotations=[self._copied_annotation()],
            source_bid_uid="7",
        )
        handler.on_paste_requested()
        payload = write.queued_pastes[0][1]
        write.queued_pastes[0][3](
            _committed(
                maps=(
                    ("takeoffs", (("source", "new-1"),)),
                    ("annotations", ((payload.annotation_source_uids[0], "new-ann"),)),
                )
            )
        )
        self.assertEqual(undo.count, 1)
        data.takeoffs["new-1"] = Takeoff(
            uid="new-1",
            condition_uid="c1",
            page_uid="p1",
            position=[11.0, 21.0, 15.0, 21.0],
        )
        data.annotations = [
            BidAnnotation(
                uid="new-ann",
                annotation_type="line",
                page_uid="p1",
                position=[11.0, 21.0, 15.0, 21.0],
            )
        ]
        undo_submit, redo_submit = history.submits
        completed = []
        undo_submit(completed.append)
        deleted = _committed()
        write.queued_deletes[-1][-1](deleted)
        self.assertEqual(completed, [deleted])
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual({t.available for t in undo.annotation_targets}, {False})
        redo_submit(completed.append)
        restored = _committed(
            maps=(
                ("takeoffs", (("source", "new-2"),)),
                ("annotations", ((payload.annotation_source_uids[0], "new-ann-2"),)),
            )
        )
        write.queued_pastes[-1][-1](restored)
        self.assertEqual(completed, [deleted, restored])
        self.assertEqual(
            {(t.uid, t.available) for t in undo.takeoff_targets}, {("new-2", True)}
        )
        self.assertEqual(
            {(t.uid, t.available) for t in undo.annotation_targets},
            {("new-ann-2", True)},
        )


class PlanViewActionHandlerCompletionMemoryTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep: a committed queued property
    edit is remembered by its operation id (also for an owner that is gone), a failed
    one is not."""

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", is_negative=False
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo

    def test_a_committed_property_edit_is_remembered_and_a_failed_one_is_not(self):
        for committed in (True, False):
            with self.subTest(committed=committed):
                handler, plan_view, write, undo = self._handler()
                handler.on_set_negative(["t1"], True)
                result = _committed() if committed else _failed()
                write.queued_properties[0][5](result)
                self.assertEqual(
                    handler._completed_sql_mutation_ids,
                    {result.operation_id} if committed else set(),
                )
                self.assertEqual(undo.count, 1 if committed else 0)
                self.assertEqual(undo.forward_mutations, [])

    def test_a_committed_property_edit_whose_owner_is_gone_is_remembered_without_history_or_selection(
        self,
    ):
        handler, plan_view, write, undo = self._handler()
        complete, _abort = handler.prepare_sql_property_completion(
            handler._ui_state.get_selected_bid_ref(),
            "takeoff_negative",
            [("t1", True)],
            old_updates=[("t1", False)],
            plan_uids={"t1"},
            takeoff_uids={"t1"},
            page_uids=("p1",),
            owner_is_current=lambda: False,
        )
        self.assertEqual(len(undo.forward_mutations), 1)
        plan_view.selected = {"user-choice"}
        result = _committed()
        complete(result)
        self.assertEqual(handler._completed_sql_mutation_ids, {result.operation_id})
        self.assertEqual(undo.count, 0)
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})


class PlanViewActionHandlerCleanupAndPreviewGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep: the cleanup delete of a
    cancelled placement, hiding previews, and the history of a queued placement."""

    def _cleanup(self, bid_at_commit=None):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        write.cancel_queued_mutation_result = False
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        (pending_uid,) = list(data.takeoffs)
        handler.on_elements_deleted([pending_uid])
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
        )
        if bid_at_commit is not None:
            handler._ui_state = SimpleNamespace(
                active_page_uid="9", get_selected_bid_ref=lambda: bid_at_commit[0]
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
        return handler, data, plan_view, write, write.cleanup_delete_calls[0][-1]

    def test_the_cleanup_of_a_cancelled_placement_is_marked_pending_only_for_the_active_bid(
        self,
    ):
        for name, bid, marked in (
            ("same bid", BidRef("bid.mdb", "7"), True),
            ("another bid of the database", BidRef("bid.mdb", "8"), False),
            ("another database", BidRef("other.mdb", "7"), False),
            ("no bid", None, False),
        ):
            with self.subTest(case=name):
                handler, data, plan_view, write, cleanup = self._cleanup((bid,))
                expected = {BidRef("bid.mdb", "7"): {"501"}} if marked else {}
                self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, expected)
                self.assertEqual(
                    plan_view.pending_mutation_uids, {"501"} if marked else set()
                )

    def test_a_failed_cleanup_reselects_only_for_the_bid_it_was_queued_for(self):
        for name, bid, reselected in (
            ("same bid", BidRef("bid.mdb", "7"), True),
            ("another bid of the database", BidRef("bid.mdb", "8"), False),
            ("another database", BidRef("other.mdb", "7"), False),
            ("no bid", None, False),
        ):
            with self.subTest(case=name):
                handler, data, plan_view, write, cleanup = self._cleanup()
                handler._ui_state = SimpleNamespace(
                    active_page_uid="9", get_selected_bid_ref=lambda: bid
                )
                cleanup(_failed())
                self.assertEqual(plan_view.selected, {"501"} if reselected else set())

    def test_a_committed_cleanup_does_not_reselect_the_rows_it_deleted(self):
        handler, data, plan_view, write, cleanup = self._cleanup()
        self.assertIn("501", plan_view.pending_mutation_uids)
        result = _committed()
        cleanup(result)
        self.assertEqual(plan_view.selected, set())
        self.assertNotIn("501", plan_view.pending_mutation_uids)
        self.assertIn(result.operation_id, handler._completed_sql_mutation_ids)

    def test_an_interim_cleanup_outcome_keeps_the_rows_pending_and_the_selection_alone(
        self,
    ):
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            with self.subTest(status=status.name):
                handler, data, plan_view, write, cleanup = self._cleanup()
                cleanup(_failed(status))
                self.assertEqual(plan_view.selected, set())
                self.assertIn("501", plan_view.pending_mutation_uids)
                cleanup(_failed())
                self.assertEqual(plan_view.selected, {"501"})
                self.assertNotIn("501", plan_view.pending_mutation_uids)

    def test_a_cleanup_completion_after_the_handler_is_gone_is_ignored(self):
        handler, data, plan_view, write, cleanup = self._cleanup()
        del handler
        gc.collect()
        cleanup(_failed())
        cleanup(_committed())
        self.assertEqual(plan_view.selected, set())

    def test_previews_of_other_bids_and_databases_survive_hiding_while_stale_markers_are_cleared(
        self,
    ):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        (mine,) = list(data.takeoffs)
        for other in (BidRef("bid.mdb", "8"), BidRef("other.mdb", "7")):
            handler._ui_state = SimpleNamespace(
                active_page_uid="9", get_selected_bid_ref=lambda other=other: other
            )
            handler.hide_pending_takeoff_placement_previews()
            self.assertIn(mine, data.takeoffs)
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
        )
        del data.takeoffs[mine]
        self.assertIn(
            mine, handler._pending_plan_takeoff_uids_by_bid[BidRef("bid.mdb", "7")]
        )
        before = len(handler._event_bus.events)
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertGreater(len(handler._event_bus.events), before)

    def test_hiding_removes_a_preview_that_is_in_the_model_even_without_a_pending_marker(
        self,
    ):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        handler._pending_plan_takeoff_uids_by_bid.clear()
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(data.takeoffs, {})

    def test_hiding_with_neither_a_model_row_nor_a_marker_changes_nothing(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        (mine,) = list(data.takeoffs)
        del data.takeoffs[mine]
        handler._pending_plan_takeoff_uids_by_bid.clear()
        before = list(handler._event_bus.events)
        handler.hide_pending_takeoff_placement_previews()
        self.assertEqual(handler._event_bus.events, before)

    def test_the_history_of_a_queued_placement_completes_its_undo_and_redo_in_the_real_service(
        self,
    ):
        history = UndoRedoService()
        history.set_active_bid(BidRef("bid.mdb", "7"))
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=history
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        operation_id, callback = write.queued_takeoff_callbacks[0]
        data.add_takeoffs(
            [Takeoff(uid="501", condition_uid="42", page_uid="9", position=[1.0, 2.0])]
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
        self.assertTrue(history.can_undo())
        history.undo()
        self.assertFalse(history.can_undo())
        self.assertFalse(history.can_redo())
        write.queued_deletes[0][-1](_committed())
        self.assertTrue(history.can_redo())
        history.redo()
        self.assertFalse(history.can_redo())
        redo_id, redo_callback = write.queued_takeoff_callbacks[1]
        redo_callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=redo_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("502",),
            )
        )
        self.assertTrue(history.can_undo())
        self.assertFalse(history.can_redo())


class PlanViewActionHandlerLocalInsertHistoryGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the local (MDB) insert paths
    and their undo/redo: a failed step reports False and leaves selection and lifetime
    targets alone, an owner that is no longer current never has its selection cleared.
    """

    ANNOTATION = [1.0, 2.0, 3.0, 4.0]

    def _annotation_handler(self):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.annotation_key_map = {
            ("ann-1", "rect"): "ann-1_rect",
            ("ann-2", "rect"): "ann-2_rect",
        }
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, ann_write=ann_write, data=data, undo=undo
        )
        return handler, plan_view, ann_write, data, undo

    def _takeoff_handler(self, data=None):
        data = FakeProjectData() if data is None else data
        plan_view = FakePlanView(data)
        plan_view.current_page_uid = "9"
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    @staticmethod
    def _spec(**options):
        return InsertTakeoffSpec(
            condition_uid="42",
            page_uid="9",
            area_uid="0",
            position=[1.0, 2.0],
            **options,
        )

    def test_a_failed_local_annotation_insert_returns_an_empty_list_and_registers_no_history(
        self,
    ):
        handler, plan_view, ann_write, data, undo = self._annotation_handler()
        ann_write.next_uids = []
        bid = handler._ui_state.get_selected_bid_ref()
        spec = InsertAnnotationSpec(
            page_uid="p1",
            annotation_type="rect",
            position=self.ANNOTATION,
            color="#ff0000",
            width=1.0,
            layer_uid="L1",
        )
        with patch.object(handler_module, "show_warning"):
            with self.assertLogs(handler_module.logger, "WARNING"):
                self.assertEqual(handler._insert_annotations_with_undo(bid, [spec]), [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan_view.selected, set())

    def test_undoing_a_local_annotation_insert_clears_the_selection_only_after_a_successful_delete(
        self,
    ):
        for deletes, current, cleared in (
            (True, True, 1),
            (False, True, 0),
            (True, False, 0),
        ):
            with self.subTest(delete_succeeds=deletes, owner_current=current):
                handler, plan_view, ann_write, data, undo = self._annotation_handler()
                handler.on_annotation_created("rect", self.ANNOTATION, "p1")
                self.assertEqual(plan_view.selected, {"ann-1_rect"})
                ann_write.delete_annotations = lambda *args, **options: deletes
                if not current:
                    handler._ui_state = SimpleNamespace(
                        active_page_uid="p1",
                        get_selected_bid_ref=lambda: BidRef("other.mdb", "8"),
                    )
                self.assertIs(undo.undo(), deletes)
                self.assertEqual(plan_view.clears, cleared)
                self.assertEqual(
                    plan_view.selected, set() if cleared else {"ann-1_rect"}
                )
                self.assertEqual(
                    [t.available for t in undo.annotation_targets], [not deletes]
                )

    def test_redoing_a_local_annotation_insert_reports_its_outcome_and_rebinds_the_target(
        self,
    ):
        handler, plan_view, ann_write, data, undo = self._annotation_handler()
        handler.on_annotation_created("rect", self.ANNOTATION, "p1")
        self.assertIs(undo.undo(), True)
        ann_write.next_uids = []
        with patch.object(handler_module, "show_warning"):
            with self.assertLogs(handler_module.logger, "WARNING"):
                self.assertIs(undo.redo(), False)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual([t.available for t in undo.annotation_targets], [False])
        ann_write.next_uids = ["ann-2"]
        self.assertIs(undo.redo(), True)
        self.assertEqual(plan_view.selected, {"ann-2_rect"})
        self.assertEqual(
            [(t.uid, t.available) for t in undo.annotation_targets], [("ann-2", True)]
        )

    def test_a_backout_placement_without_the_internal_flag_has_an_external_parent(self):
        for placement_flags, external in (
            ({}, ("src-hole",)),
            ({"parent_is_internal": True}, ()),
            ({"parent_is_internal": False}, ("src-hole",)),
        ):
            with self.subTest(flags=placement_flags):
                handler, plan_view, write, data, undo = self._takeoff_handler()
                data.takeoffs["P"] = Takeoff(
                    uid="P",
                    condition_uid="c1",
                    page_uid="p1",
                    position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
                )
                handler.on_paste_backouts_placed(
                    [
                        {
                            "condition_uid": "c1",
                            "page_uid": "p1",
                            "position": [2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
                            "parent_uid": "P",
                            "rotation": 0.0,
                            "is_negative": True,
                            "extras": {},
                            "source_uid": "src-hole",
                            **placement_flags,
                        }
                    ],
                    "7",
                )
                (_database, payload, _options) = write.local_pastes[0]
                self.assertEqual(payload.takeoff_external_parent_sources, external)

    def test_a_local_backout_placement_is_not_also_queued_as_an_sql_paste(self):
        handler, plan_view, write, data, undo = self._takeoff_handler()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "c1",
                    "page_uid": "p1",
                    "position": [2.0, 2.0, 4.0, 2.0, 4.0, 4.0],
                    "parent_uid": "P",
                    "rotation": 0.0,
                    "is_negative": True,
                    "extras": {},
                    "source_uid": "src-hole",
                    "parent_is_internal": False,
                }
            ],
            "7",
        )
        self.assertEqual(len(write.local_pastes), 1)
        self.assertEqual(write.queued_pastes, [])

    def test_a_takeoff_insert_without_the_fast_refresh_flag_reloads_the_database(self):
        handler, plan_view, write, data, undo = self._takeoff_handler()
        bid = handler._ui_state.get_selected_bid_ref()
        self.assertIs(handler._insert_takeoffs_with_undo(bid, [self._spec()]), True)
        self.assertIs(write.calls[0][3], True)
        self.assertEqual(data.added_takeoffs, [])
        self.assertEqual(handler._event_bus.events, [])
        self.assertIs(
            handler._insert_takeoffs_with_undo(bid, [self._spec()], fast_refresh=True),
            True,
        )
        self.assertIs(write.calls[1][3], False)
        self.assertEqual(len(data.added_takeoffs), 1)

    def test_a_successful_insert_without_any_identity_is_a_failed_insert(self):
        handler, plan_view, write, data, undo = self._takeoff_handler()
        bid = handler._ui_state.get_selected_bid_ref()
        write.insert_takeoffs_result = lambda *args, **options: WriteReloadResult(
            None, write_success=True, reload_success=True
        )
        self.assertIs(handler._insert_takeoffs_with_undo(bid, [self._spec()]), False)
        self.assertEqual(undo.count, 0)

    def test_a_local_takeoff_placement_is_added_to_the_authoritative_model_not_as_a_preview(
        self,
    ):
        data = _TransientRecordingData()
        handler, plan_view, write, data, undo = self._takeoff_handler(data)
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertEqual(data.authoritative_batches, [["100"]])
        self.assertEqual(data.transient_batches, [])

    def test_undoing_a_local_takeoff_insert_clears_the_selection_only_after_a_successful_delete(
        self,
    ):
        for deletes, current, cleared in (
            (True, True, 1),
            (False, True, 0),
            (True, False, 0),
        ):
            with self.subTest(delete_succeeds=deletes, owner_current=current):
                handler, plan_view, write, data, undo = self._takeoff_handler()
                handler.on_takeoff_created("42", [1.0, 2.0], "9")
                self.assertEqual(plan_view.selected, {"100"})
                write.delete_takeoffs = lambda *args, **options: deletes
                if not current:
                    handler._ui_state = SimpleNamespace(
                        active_page_uid="9",
                        get_selected_bid_ref=lambda: BidRef("other.mdb", "8"),
                    )
                self.assertIs(undo.undo(), deletes)
                self.assertEqual(plan_view.clears, cleared)
                self.assertEqual(
                    [t.available for t in undo.takeoff_targets], [not deletes]
                )

    def test_redoing_a_local_takeoff_insert_rebinds_the_target_and_reports_success(
        self,
    ):
        handler, plan_view, write, data, undo = self._takeoff_handler()
        handler.on_takeoff_created("42", [1.0, 2.0], "9")
        self.assertIs(undo.undo(), True)
        write.uid_batches = [["200"]]
        self.assertIs(undo.redo(), True)
        self.assertEqual(
            [(t.uid, t.available) for t in undo.takeoff_targets], [("200", True)]
        )
        self.assertEqual(plan_view.selected, {"200"})
        handler._ui_state = SimpleNamespace(
            active_page_uid="9", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        self.assertIs(undo.undo(), True)
        write.uid_batches = [["300"]]
        plan_view.selected = {"user-choice"}
        self.assertIs(undo.redo(), True)
        self.assertEqual(plan_view.selected, {"user-choice"})


class PlanViewActionHandlerAnnotationPlacementGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the annotation, Hot Link
    and Backout placement gestures and in the raw extras of a placed takeoff."""

    ACCEPTED = QtWidgets.QDialog.DialogCode.Accepted

    def _hotlink_handler(self, sql=False):
        data = FakeProjectData()
        data.annotations = [_named_view_annotation("nv1", "Lobby")]
        plan_view = FakePlanView(data)
        ann_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data
        )
        return handler, plan_view, ann_write, write

    @staticmethod
    def _dialog(result, built=None):
        class Dialog:
            def __init__(self, named_views, parent=None):
                if built is not None:
                    built.append(True)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return result

            def deleteLater(self):
                pass

        return Dialog

    def test_a_hot_link_request_without_an_active_bid_does_not_even_open_the_picker(
        self,
    ):
        handler, plan_view, ann_write, _write = self._hotlink_handler()
        handler._ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: None, active_page_uid="p1"
        )
        built = []
        with patch.object(
            handler_module,
            "SelectNamedViewDialog",
            self._dialog(
                SimpleNamespace(create_new=False, named_view_uid="nv1"), built
            ),
        ):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(built, [])
        self.assertEqual(plan_view.cancel_place_mode_calls, 0)
        self.assertEqual(ann_write.insert_calls, [])

    def test_a_picker_result_without_a_named_view_places_no_hot_link(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, plan_view, ann_write, write = self._hotlink_handler(sql)
                with patch.object(
                    handler_module,
                    "SelectNamedViewDialog",
                    self._dialog(SimpleNamespace(create_new=False, named_view_uid="")),
                ):
                    handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
                self.assertEqual(ann_write.insert_calls, [])
                self.assertEqual(write.queued_pastes, [])
                self.assertEqual(plan_view.activated_annotations, [])

    def test_choosing_to_create_a_new_view_only_arms_the_named_view_tool(self):
        handler, plan_view, ann_write, write = self._hotlink_handler()
        with patch.object(
            handler_module,
            "SelectNamedViewDialog",
            self._dialog(SimpleNamespace(create_new=True, named_view_uid="")),
        ):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(plan_view.activated_annotations, ["namedview"])
        self.assertEqual(ann_write.insert_calls, [])

    def test_a_picker_destroyed_while_it_ran_places_nothing(self):
        from shiboken6 import delete

        handler, plan_view, ann_write, _write = self._hotlink_handler()
        result = SimpleNamespace(create_new=False, named_view_uid="nv1")

        class DestroyedDialog(QtWidgets.QDialog):
            def __init__(self, named_views, parent=None):
                super().__init__()

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return result

        with patch.object(handler_module, "SelectNamedViewDialog", DestroyedDialog):
            handler.on_hotlink_placement_requested([9.0, 11.0], "p1")
        self.assertEqual(ann_write.insert_calls, [])
        self.assertEqual(plan_view.activated_annotations, [])

    def test_a_hole_in_sql_mode_is_only_queued_never_inserted_locally_as_well(self):
        data = FakeProjectData()
        data.takeoffs["P"] = Takeoff(
            uid="P",
            condition_uid="c1",
            page_uid="9",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(
            plan_view=FakePlanView(data), write=write, data=data
        )
        handler.on_hole_created("42", [1.0, 1.0, 2.0, 1.0, 2.0, 2.0], "9", "P")
        self.assertEqual(len(write.queued_takeoff_callbacks), 1)
        self.assertEqual([call[3] for call in write.calls], ["queued"])

    def test_a_named_view_in_sql_mode_is_only_queued_never_inserted_locally_as_well(
        self,
    ):
        ann_write = FakeAnnotationWriteService()
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(ann_write=ann_write, write=write)
        handler.on_named_view_created(
            [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0], "p1", {"Text": "Lobby"}
        )
        self.assertEqual(len(write.queued_pastes), 1)
        self.assertEqual(ann_write.insert_calls, [])

    def test_the_named_view_name_check_answers_a_strict_bool(self):
        handler, plan_view, ann_write, write = self._hotlink_handler()
        with patch.object(
            handler_module, "show_duplicate_named_view_name"
        ) as duplicate:
            self.assertIs(handler._validate_named_view_name("Lobby"), False)
            duplicate.assert_called_once_with(plan_view)
            self.assertIs(handler._validate_named_view_name("Lobby", "nv1"), True)
            self.assertIs(handler._validate_named_view_name("Elsewhere"), True)
            duplicate.assert_called_once()

    def test_a_duplicate_committed_annotation_insert_without_a_selection_acts_once(
        self,
    ):
        data = FakeProjectData()
        plan_view = FakePlanView(data)
        plan_view.selected = {"user-choice"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        handler = self._paste_handler(plan_view=plan_view, write=write, data=data)
        handler.on_text_annotation_created([1.0, 2.0, 5.0, 6.0], "p1", {"Text": "Once"})
        payload = write.queued_pastes[0][1]
        callback = write.queued_pastes[0][3]
        result = _committed(
            maps=(
                ("annotations", ((payload.annotation_source_uids[0], "annotation-1"),)),
            )
        )
        callback(result)
        callback(result)
        self.assertEqual(plan_view.activated_annotations, ["text"])
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertIn(result.operation_id, handler._completed_sql_mutation_ids)

    def test_a_raw_extra_flag_is_false_unless_it_is_set_and_a_colour_keeps_its_sign(
        self,
    ):
        data = FakeProjectData()
        handler = self._paste_handler(data=data)
        unset = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={"FontName": "Dim"},
        )
        cleared = InsertTakeoffSpec(
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            raw_extras={
                "FontColor": -5,
                "NameFontColor": -7,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "NameFontBold": False,
                "NameFontItalic": False,
                "NameFontUnderline": False,
            },
        )
        handler._add_inserted_takeoffs_to_model(["unset", "cleared"], [unset, cleared])
        flags = (
            "dimension_font_bold",
            "dimension_font_italic",
            "dimension_font_underline",
            "name_font_bold",
            "name_font_italic",
            "name_font_underline",
        )
        for uid in ("unset", "cleared"):
            self.assertEqual(
                [getattr(data.takeoffs[uid], flag) for flag in flags], [False] * 6
            )
        self.assertEqual(data.takeoffs["unset"].dimension_font_name, "Dim")
        self.assertEqual(
            (
                data.takeoffs["cleared"].dimension_font_color,
                data.takeoffs["cleared"].name_font_color,
            ),
            (-5, -7),
        )


class PlanViewActionHandlerFastDeleteHistoryGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the local (MDB) fast delete
    of takeoffs and in the selection it leaves behind."""

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, data, undo

    def test_undoing_a_fast_delete_that_cannot_reinsert_reports_false_and_keeps_the_target_suspended(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["t1"])
        self.assertEqual(data.takeoffs, {})
        self.assertEqual([t.available for t in undo.takeoff_targets], [False])
        write.uid_batches = [[]]
        self.assertIs(undo.undo(), False)
        self.assertEqual([t.available for t in undo.takeoff_targets], [False])
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(data.takeoffs, {})

    def test_undoing_and_redoing_a_fast_delete_report_true_and_follow_the_restored_identity(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["t1"])
        write.next_uids = ["t2"]
        self.assertIs(undo.undo(), True)
        self.assertEqual(
            [(t.uid, t.available) for t in undo.takeoff_targets], [("t2", True)]
        )
        self.assertEqual(plan_view.selected, {"t2"})
        self.assertIs(undo.redo(), True)
        self.assertEqual([t.available for t in undo.takeoff_targets], [False])
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(write.delete_calls[-1], ("bid.mdb", ["t2"], False))

    def test_redoing_a_fast_delete_that_the_database_refuses_keeps_the_restored_target_available(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        handler.on_elements_deleted(["t1"])
        write.next_uids = ["t2"]
        undo.undo()
        write.delete_takeoffs = lambda *args, **options: False
        self.assertIs(undo.redo(), False)
        self.assertEqual(
            [(t.uid, t.available) for t in undo.takeoff_targets], [("t2", True)]
        )
        self.assertEqual(plan_view.selected, {"t2"})
        self.assertIn("t2", data.takeoffs)

    def test_a_local_delete_of_a_takeoff_and_a_kept_named_view_selects_the_kept_view(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler()
        view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view.annotations = {"nv1": view, "hl1": hotlink}
        with patch.object(handler_module, "confirm", return_value=False):
            handler.on_elements_deleted(["t1", "nv1"])
        self.assertEqual(write.delete_calls, [("bid.mdb", ["t1"], False)])
        self.assertEqual(plan_view.selected, {"nv1"})
        self.assertEqual(undo.count, 1)
        self.assertEqual([a.uid for a in data.annotations], ["nv1", "hl1"])


class _RecordingHistory(FakeUndoService):
    """FakeUndoService that keeps the submit callables of the latest queued history
    entry, so a test can drive them with its own completion callback, and records the
    annotation deletions that no history entry covers."""

    def __init__(self):
        super().__init__()
        self.submits = None
        self.notified = []

    def push_for_bid(
        self,
        bid_ref,
        undo_submit,
        redo_submit,
        *,
        takeoff_targets=(),
        annotation_targets=(),
    ):
        self.submits = (undo_submit, redo_submit)
        super().push_for_bid(
            bid_ref,
            undo_submit,
            redo_submit,
            takeoff_targets=takeoff_targets,
            annotation_targets=annotation_targets,
        )

    def notify_annotation_deletion(self, bid_ref, identities):
        self.notified.append((bid_ref, set(identities)))


class PlanViewActionHandlerDeleteHistoryGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the delete history of mixed
    selections (local and queued), in the lifetime targets it keeps and in the results
    its undo and redo report."""

    def _handler(self, sql, extras=None, history=None):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        if extras:
            data.extras["t1"] = dict(extras)
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            page_uid="p1",
            position=[1.0, 2.0, 3.0, 4.0],
        )
        data.annotations = [annotation]
        plan_view = FakePlanView(data)
        plan_view.annotations["rect-item"] = annotation
        plan_view.annotation_key_map[("a2", "rect")] = "rect-item"
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        write.next_uids = ["t2"]
        ann_write = FakeAnnotationWriteService()
        ann_write.next_uids = ["a2"]
        undo = FakeUndoService() if history is None else history
        handler = self._paste_handler(
            plan_view=plan_view, write=write, ann_write=ann_write, data=data, undo=undo
        )
        handler.on_elements_deleted(["t1", "rect-item"])
        return handler, plan_view, write, data, undo

    @staticmethod
    def _restored(takeoff="t2", annotation="a2"):
        return _committed(
            maps=(
                ("takeoffs", (("t1", takeoff),)),
                ("annotations", ((annotation_resource_id("rect", "a1"), annotation),)),
            )
        )

    @staticmethod
    def _refuse_delete(write):
        write.execute_plan_items_delete_local = (
            lambda *args, **options: MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )

    def test_a_local_mixed_restore_that_the_database_refuses_reports_false_and_stays_suspended(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler(sql=False)
        write.uid_batches = [[]]
        self.assertIs(undo.undo(), False)
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual({t.available for t in undo.annotation_targets}, {False})
        self.assertEqual(plan_view.selected, set())

    def test_a_local_mixed_restore_whose_projection_fails_reports_false(self):
        handler, plan_view, write, data, undo = self._handler(
            sql=False, extras={"CustomColumn": "keep"}
        )
        write.reload_and_notify = lambda database: False
        self.assertIs(undo.undo(), False)
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual(plan_view.selected, set())

    def test_a_local_mixed_delete_reports_true_follows_the_restored_identities_and_clears_the_selection(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler(sql=False)
        write.next_annotation_uids = ["a2"]
        self.assertIs(undo.undo(), True)
        self.assertEqual(
            {(t.uid, t.available) for t in undo.takeoff_targets}, {("t2", True)}
        )
        self.assertEqual(
            {(t.uid, t.available) for t in undo.annotation_targets}, {("a2", True)}
        )
        self.assertEqual(plan_view.selected, {"t2", "rect-item"})
        before = plan_view.clears
        self.assertIs(undo.redo(), True)
        self.assertEqual(plan_view.clears, before + 1)
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual({t.available for t in undo.annotation_targets}, {False})
        self.assertEqual(
            write.local_deletes[-1][4]["publish_database_refreshed_after_write"], False
        )
        self.assertEqual(write.local_deletes[-1][2], ["t2"])
        self.assertEqual(write.local_deletes[-1][3], [("a2", "rect")])

    def test_a_refused_local_mixed_redo_reports_false_and_keeps_the_restored_targets(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler(sql=False)
        write.next_annotation_uids = ["a2"]
        undo.undo()
        self._refuse_delete(write)
        self.assertIs(undo.redo(), False)
        self.assertEqual({t.available for t in undo.takeoff_targets}, {True})
        self.assertEqual({t.available for t in undo.annotation_targets}, {True})
        self.assertEqual(plan_view.selected, {"t2", "rect-item"})

    def test_a_local_mixed_redo_for_a_bid_that_is_no_longer_active_leaves_the_selection_alone(
        self,
    ):
        handler, plan_view, write, data, undo = self._handler(sql=False)
        write.next_annotation_uids = ["a2"]
        undo.undo()
        handler._ui_state = SimpleNamespace(
            active_page_uid="p1", get_selected_bid_ref=lambda: BidRef("other.mdb", "8")
        )
        before = plan_view.clears
        self.assertIs(undo.redo(), True)
        self.assertEqual(plan_view.clears, before)
        self.assertEqual(plan_view.selected, {"t2", "rect-item"})

    def test_a_refused_queued_delete_keeps_no_history_and_a_committed_one_does(self):
        for committed in (False, True):
            with self.subTest(committed=committed):
                history = _RecordingHistory()
                handler, plan_view, write, data, undo = self._handler(
                    sql=True, history=history
                )
                result = _committed() if committed else _failed()
                write.queued_deletes[0][-1](result)
                self.assertEqual(undo.count, 1 if committed else 0)
                self.assertEqual(undo.notified, [])
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})

    def test_a_committed_queued_delete_reselects_the_kept_named_views_the_view_lost(
        self,
    ):
        history = _RecordingHistory()
        handler, plan_view, write, data, undo = self._handler(sql=True, history=history)
        view = _named_view_annotation("nv1", "Lobby")
        hotlink = _hotlink_annotation("hl1", "nv1")
        data.annotations = [view, hotlink]
        plan_view.annotations = {"nv1": view, "hl1": hotlink}
        plan_view.annotation_key_map = {
            ("nv1", "namedview"): "nv1",
            ("hl1", "hotlink"): "hl1",
        }
        with patch.object(handler_module, "confirm", return_value=False):
            handler.on_elements_deleted(["nv1", "hl1"])
        self.assertEqual(plan_view.selected, {"nv1"})
        plan_view.selected = set()
        write.queued_deletes[-1][-1](_committed())
        self.assertEqual(plan_view.selected, {"nv1"})

    def test_an_annotation_deletion_no_history_entry_covers_is_announced_to_the_history(
        self,
    ):
        for replaced, announced in ((False, []), (True, [{("p1", "rect", "a1")}])):
            with self.subTest(page_replaced=replaced):
                history = _RecordingHistory()
                handler, plan_view, write, data, undo = self._handler(
                    sql=True, history=history
                )
                if replaced:
                    data.pages["p1"] = SimpleNamespace(
                        uid="p1",
                        overlay_rect=None,
                        scale_factor1=1.0,
                        scale_factor2=1.0,
                    )
                write.queued_deletes[0][-1](_committed())
                self.assertEqual(
                    [identities for _bid, identities in undo.notified], announced
                )
                self.assertEqual(undo.count, 0 if replaced else 1)

    def test_the_queued_delete_history_rebinds_completes_and_suspends_through_its_callbacks(
        self,
    ):
        history = _RecordingHistory()
        handler, plan_view, write, data, undo = self._handler(sql=True, history=history)
        write.queued_deletes[0][-1](_committed())
        undo_submit, redo_submit = history.submits
        completed = []
        undo_submit(completed.append)
        restore = _committed(
            maps=self._restored().authoritative_result.created_uid_maps
        )
        write.queued_pastes[-1][3](restore)
        self.assertEqual(completed, [restore])
        self.assertEqual(
            {(t.uid, t.available) for t in undo.takeoff_targets}, {("t2", True)}
        )
        self.assertEqual(
            {(t.uid, t.available) for t in undo.annotation_targets}, {("a2", True)}
        )
        completed.clear()
        data.takeoffs["t2"] = Takeoff(
            uid="t2", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.annotations = [
            BidAnnotation(
                uid="a2",
                annotation_type="rect",
                page_uid="p1",
                position=[1.0, 2.0, 3.0, 4.0],
            )
        ]
        redo_submit(completed.append)
        failed = _failed()
        write.queued_deletes[-1][-1](failed)
        self.assertEqual(completed, [failed])
        self.assertEqual({t.available for t in undo.takeoff_targets}, {True})
        self.assertEqual({t.available for t in undo.annotation_targets}, {True})
        deleted = _committed()
        write.queued_deletes[-1][-1](deleted)
        self.assertEqual(completed, [failed, deleted])
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual({t.available for t in undo.annotation_targets}, {False})


class _BackoutRecordingPlanView(_ParentResolvingPlanView):
    """_ParentResolvingPlanView that also remembers the conditions handed to a Backout paste."""

    def begin_paste_backout(
        self, holes, extras_by_uid, source_bid_uid, *, conditions=None
    ):
        super().begin_paste_backout(
            holes, extras_by_uid, source_bid_uid, conditions=conditions
        )
        self.backout_conditions = conditions


class PlanViewActionHandlerPasteGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in copy and paste: the guards in
    front of a paste, the clipboard defaults, and the local paste history."""

    def _handler(self, sql=False, plan_view=None, allowed=None):
        data = FakeProjectData()
        data.takeoffs["existing-parent"] = Takeoff(
            uid="existing-parent",
            condition_uid="c1",
            page_uid="p1",
            position=[0.0, 0.0, 9.0, 0.0, 9.0, 9.0],
        )
        plan_view = _BackoutRecordingPlanView(data) if plan_view is None else plan_view
        plan_view.intelligent_paste_enabled = False
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        ann_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view,
            write=write,
            ann_write=ann_write,
            data=data,
            undo=undo,
            allowed_features=allowed,
        )
        return handler, plan_view, write, ann_write, data, undo

    def _regular(self):
        return Takeoff(
            uid="reg",
            condition_uid="c1",
            page_uid="source-page",
            position=[10.0, 20.0, 14.0, 20.0],
        )

    def _hole(self, parent="reg"):
        return Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="source-page",
            position=[11.0, 21.0, 12.0, 21.0, 12.0, 22.0],
            parent_uid=parent,
        )

    def test_a_paste_without_a_bid_or_a_current_page_writes_nothing(self):
        for name, change in (
            (
                "no bid",
                lambda h, pv: setattr(
                    h,
                    "_ui_state",
                    SimpleNamespace(
                        get_selected_bid_ref=lambda: None, active_page_uid="p1"
                    ),
                ),
            ),
            ("no page", lambda h, pv: setattr(pv, "current_page_uid", "")),
            ("page is none", lambda h, pv: setattr(pv, "current_page_uid", None)),
        ):
            with self.subTest(case=name):
                handler, plan_view, write, ann_write, data, undo = self._handler()
                handler._clipboard_svc = FakeClipboard([self._regular()])
                change(handler, plan_view)
                handler.on_paste_requested()
                self.assertEqual(_write_count(write), 0)
                self.assertEqual(write.local_pastes, [])
                self.assertEqual(undo.count, 0)

    def test_a_regular_takeoff_pasted_with_a_hole_does_not_need_the_place_right(self):
        allowed = set(Feature) - {Feature.PLACE_PLAN_ITEMS}
        handler, plan_view, write, ann_write, data, undo = self._handler(
            allowed=allowed
        )
        handler._clipboard_svc = FakeClipboard([self._regular(), self._hole()])
        handler.on_paste_requested()
        (_database, payload, _options) = write.local_pastes[0]
        self.assertEqual(payload.takeoff_source_uids, ("reg", "hole"))
        self.assertEqual(plan_view.paste_backout_calls, [])

    def test_a_clipboard_with_holes_and_annotations_is_pasted_directly_not_through_a_backout(
        self,
    ):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        handler._clipboard_svc = FakeClipboard(
            [self._hole(parent="not-copied")], annotations=[self._copied_annotation()]
        )
        handler.on_paste_requested()
        self.assertEqual(plan_view.paste_backout_calls, [])
        (_database, payload, _options) = write.local_pastes[0]
        self.assertEqual(payload.takeoff_source_uids, ("hole",))
        self.assertEqual(len(payload.annotation_specs), 1)

    def test_the_backout_conditions_come_from_the_active_bid_for_a_same_bid_clipboard(
        self,
    ):
        for source_bid, expected in (("7", {"42", "c1"}), ("6", {"foreign"})):
            with self.subTest(source_bid=source_bid):
                handler, plan_view, write, ann_write, data, undo = self._handler()
                clipboard = FakeClipboard(
                    [self._hole(parent="not-copied")], source_bid_uid=source_bid
                )
                clipboard.conditions = {"foreign": "condition"}
                handler._clipboard_svc = clipboard
                handler.on_paste_requested()
                self.assertEqual(set(plan_view.backout_conditions), expected)

    def test_an_annotation_only_selection_is_copied(self):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        annotation = self._copied_annotation(uid="a1")
        plan_view.annotations["rect-item"] = annotation
        handler.on_copy_requested(["rect-item"])
        self.assertTrue(handler._clipboard_svc.has_content())
        self.assertEqual(handler._clipboard_svc.items, [])
        self.assertEqual([a.uid for a in handler._clipboard_svc.annotations], ["a1"])

    def test_a_clipboard_without_a_source_bid_is_pasted_as_a_same_bid_paste(self):
        handler, plan_view, write, ann_write, data, undo = self._handler(sql=True)
        handler._clipboard_svc = FakeClipboard([self._regular()], source_bid_uid=None)
        handler.on_paste_requested()
        (_database, payload, options, _callback) = write.queued_pastes[0]
        self.assertEqual(
            (payload.source_bid_uid, payload.destination_bid_uid), ("7", "7")
        )
        self.assertEqual(options["dependency_resources"], ())

    def test_a_pasted_annotation_gets_the_default_layer_of_the_bid(self):
        handler, plan_view, write, ann_write, data, undo = self._handler(sql=True)
        data.annotation_layer_uid = "default-layer"
        handler._clipboard_svc = FakeClipboard(
            [], annotations=[self._copied_annotation()], source_bid_uid="7"
        )
        handler.on_paste_requested()
        (_database, payload, options, _callback) = write.queued_pastes[0]
        self.assertEqual(
            [spec.layer_uid for spec in payload.annotation_specs], ["default-layer"]
        )
        self.assertEqual(
            [r.resource_type for r in options["dependency_resources"]], ["layer"]
        )

    def test_the_paste_offset_is_the_snap_increment_when_it_is_positive(self):
        for snap, expected in ((0.5, 0.5), (1.0, 1.0), (3.0, 3.0), (-1.0, 1.0)):
            with self.subTest(snap_increments=snap):
                handler, plan_view, write, ann_write, data, undo = self._handler()
                plan_view.snap_increments = snap
                handler._clipboard_svc = FakeClipboard([self._regular()])
                handler.on_paste_requested()
                position = write.local_pastes[0][1].takeoff_specs[0].position
                self.assertEqual(
                    position,
                    [
                        10.0 + expected,
                        20.0 + expected,
                        14.0 + expected,
                        20.0 + expected,
                    ],
                )

    def test_a_refused_local_paste_leaves_the_selection_and_history_alone(self):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        plan_view.selected = {"user-choice"}
        write.uid_batches = [[]]
        handler._clipboard_svc = FakeClipboard([self._regular()])
        handler.on_paste_requested()
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(undo.count, 0)
        self.assertEqual(data.takeoffs.keys(), {"existing-parent"})

    def test_a_local_paste_whose_projection_fails_is_neither_selected_nor_undoable(
        self,
    ):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        plan_view.selected = {"user-choice"}
        write.reload_and_notify = lambda database: False
        handler._clipboard_svc = FakeClipboard(
            [self._regular()], extras={"reg": {"Unlisted": 1}}
        )
        handler.on_paste_requested()
        self.assertEqual(len(write.local_pastes), 1)
        self.assertEqual(plan_view.selected, {"user-choice"})
        self.assertEqual(undo.count, 0)

    def test_an_intelligent_paste_that_selects_nothing_starts_no_drag(self):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        plan_view.intelligent_paste_enabled = True
        handler._clipboard_svc = FakeClipboard(
            [], annotations=[self._copied_annotation()], source_bid_uid="7"
        )
        handler.on_paste_requested()
        self.assertEqual(len(write.local_pastes), 1)
        self.assertEqual(plan_view.selected, set())
        self.assertEqual(plan_view.intelligent_paste_calls, [])

    def _pasted(self, sql=False):
        handler, plan_view, write, ann_write, data, undo = self._handler(sql=sql)
        plan_view.annotation_key_map[("ann-1", "line")] = "ann-1_line"
        plan_view.annotation_key_map[("ann-2", "line")] = "ann-2_line"
        handler._clipboard_svc = FakeClipboard(
            [self._regular()],
            annotations=[self._copied_annotation()],
            source_bid_uid="6",
        )
        handler.on_paste_requested()
        return handler, plan_view, write, ann_write, data, undo

    def test_a_cross_bid_paste_keeps_only_its_own_bid_dependencies_in_the_history(self):
        handler, plan_view, write, ann_write, data, undo = self._pasted()
        (_database, _payload, first) = write.local_pastes[0]
        self.assertEqual(
            sorted((r.resource_type, r.bid_uid) for r in first["dependency_resources"]),
            [("condition", 6), ("layer", 7)],
        )
        data.annotations = [
            BidAnnotation(
                uid="ann-1",
                annotation_type="line",
                page_uid="p1",
                position=[10.0, 20.0, 14.0, 20.0],
            )
        ]
        self.assertIs(undo.undo(), True)
        self.assertEqual(
            write.local_deletes[-1][4]["publish_database_refreshed_after_write"], False
        )
        ann_write.next_uids = ["ann-2"]
        write.uid_batches = [["new-100"]]
        self.assertIs(undo.redo(), True)
        (_database, _payload, redo_options) = write.local_pastes[-1]
        self.assertEqual(
            sorted(
                (r.resource_type, r.bid_uid)
                for r in redo_options["dependency_resources"]
            ),
            [("layer", 7)],
        )
        self.assertEqual(redo_options["publish_database_refreshed_after_write"], False)

    def test_redoing_a_local_paste_rebinds_every_target_to_the_new_identity(self):
        handler, plan_view, write, ann_write, data, undo = self._pasted()
        data.annotations = [
            BidAnnotation(
                uid="ann-1",
                annotation_type="line",
                page_uid="p1",
                position=[10.0, 20.0, 14.0, 20.0],
            )
        ]
        undo.undo()
        self.assertEqual({t.available for t in undo.takeoff_targets}, {False})
        self.assertEqual({t.available for t in undo.annotation_targets}, {False})
        ann_write.next_uids = ["ann-2"]
        write.uid_batches = [["new-100"]]
        self.assertIs(undo.redo(), True)
        self.assertEqual(
            {(t.uid, t.available) for t in undo.takeoff_targets}, {("new-100", True)}
        )
        self.assertEqual(
            {(t.uid, t.available) for t in undo.annotation_targets}, {("ann-2", True)}
        )
        self.assertEqual(plan_view.selected, {"new-100", "ann-2_line"})

    def test_a_refused_local_paste_undo_or_redo_reports_false(self):
        handler, plan_view, write, ann_write, data, undo = self._pasted()
        data.annotations = [
            BidAnnotation(
                uid="ann-1",
                annotation_type="line",
                page_uid="p1",
                position=[10.0, 20.0, 14.0, 20.0],
            )
        ]
        refused = MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        write.execute_plan_items_delete_local = lambda *args, **options: refused
        self.assertIs(undo.undo(), False)
        self.assertEqual({t.available for t in undo.takeoff_targets}, {True})
        del write.execute_plan_items_delete_local
        undo.undo()
        write.uid_batches = [[]]
        self.assertIs(undo.redo(), False)
        write.reload_and_notify = lambda database: False
        write.uid_batches = [["new-100"]]
        ann_write.next_uids = ["ann-2"]
        refused_projection = write.execute_plan_items_paste_local

        def mixed(database_id, payload, **options):
            result = refused_projection(database_id, payload, **options)
            return replace(
                result,
                authoritative_result=replace(
                    result.authoritative_result,
                    created_uid_maps=result.authoritative_result.created_uid_maps
                    + (("conditions", (("c1", "c-new"),)),),
                ),
            )

        write.execute_plan_items_paste_local = mixed
        self.assertIs(undo.redo(), False)

    def test_projecting_a_paste_keeps_an_external_parent_and_remaps_a_pasted_view_for_its_hot_link(
        self,
    ):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        spec = lambda parent: InsertTakeoffSpec(  # noqa: E731
            condition_uid="c1",
            page_uid="p1",
            area_uid="0",
            position=[1.0, 2.0],
            parent_uid=parent,
        )
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("P", "B", "C"),
            takeoff_specs=(spec("0"), spec("P"), spec("P")),
            takeoff_external_parent_sources=("C",),
        )
        result = MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=AuthoritativeMutationResult(
                created_uid_maps=(
                    ("takeoffs", (("P", "P-new"), ("B", "B-new"), ("C", "C-new"))),
                    ("annotations", ()),
                )
            ),
        )
        self.assertIs(handler._project_mdb_plan_items_paste(bid, payload, result), True)
        self.assertEqual(
            {uid: data.takeoffs[uid].parent_uid for uid in ("P-new", "B-new", "C-new")},
            {"P-new": "0", "B-new": "P-new", "C-new": "P"},
        )

    def test_projecting_a_pasted_named_view_remaps_its_hot_link_target(self):
        handler, plan_view, write, ann_write, data, undo = self._handler()
        bid = handler._ui_state.get_selected_bid_ref()
        view_spec = InsertAnnotationSpec(
            page_uid="p1",
            annotation_type="namedview",
            position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
            color="#008000",
            width=1.0,
            properties={"Text": "Lobby"},
        )
        link_spec = InsertAnnotationSpec(
            page_uid="p1",
            annotation_type="hotlink",
            position=[5.0, 6.0],
            color="#0000ff",
            width=1.0,
            properties={"BidPageViewUID": "nv-old"},
        )
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(
                annotation_resource_id("namedview", "nv-old"),
                annotation_resource_id("hotlink", "hl-old"),
            ),
            annotation_specs=(view_spec, link_spec),
        )
        result = MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=AuthoritativeMutationResult(
                created_uid_maps=(
                    ("takeoffs", ()),
                    (
                        "annotations",
                        (
                            (annotation_resource_id("namedview", "nv-old"), "nv-new"),
                            (annotation_resource_id("hotlink", "hl-old"), "hl-new"),
                        ),
                    ),
                )
            ),
        )
        self.assertIs(handler._project_mdb_plan_items_paste(bid, payload, result), True)
        links = [a for a in data.annotations if a.annotation_type == "hotlink"]
        self.assertEqual(
            [(a.uid, a.properties["BidPageViewUID"]) for a in links],
            [("hl-new", "nv-new")],
        )


class PlanViewActionHandlerQueuedPasteGapTests(_PlanViewActionHandlerFixture):
    """Gaps found by the sp4 whole-module mutation sweep in the completion of a queued paste."""

    def _handler(self):
        data = FakeProjectData()
        data.takeoffs["previous"] = Takeoff(
            uid="previous", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        plan_view = FakePlanView(data)
        plan_view.selected = {"previous"}
        write = FakeWriteService()
        write.sql_collaboration_mutations = True
        undo = FakeUndoService()
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        handler._clipboard_svc = FakeClipboard([self._copied_takeoff()])
        handler.on_paste_requested()
        callback = write.queued_pastes[0][3]
        return handler, plan_view, write, data, undo, callback

    @staticmethod
    def _committed():
        return _committed(
            maps=(("takeoffs", (("source", "new-1"),)), ("annotations", ()))
        )

    def test_a_failed_paste_restores_the_previous_selection_only_for_the_context_it_was_started_in(
        self,
    ):
        for replace_page, restored in ((False, {"previous"}), (True, set())):
            with self.subTest(page_replaced=replace_page):
                handler, plan_view, write, data, undo, callback = self._handler()
                self.assertEqual(plan_view.selected, set())
                if replace_page:
                    data.pages["p1"] = SimpleNamespace(
                        uid="p1",
                        overlay_rect=None,
                        scale_factor1=1.0,
                        scale_factor2=1.0,
                    )
                callback(_failed())
                self.assertEqual(plan_view.selected, restored)
                self.assertEqual(undo.forward_mutations, [])

    def test_a_committed_paste_selects_its_takeoffs_unless_the_user_chose_something_meanwhile(
        self,
    ):
        for user_choice, expected in (
            (None, {"new-1"}),
            ({"user-choice"}, {"user-choice"}),
        ):
            with self.subTest(user_choice=user_choice):
                handler, plan_view, write, data, undo, callback = self._handler()
                if user_choice is not None:
                    plan_view.set_selected_uids(user_choice)
                result = self._committed()
                callback(result)
                self.assertEqual(plan_view.selected, expected)
                self.assertEqual(undo.count, 1)
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(
                    handler._completed_sql_mutation_ids, {result.operation_id}
                )


class _DeselectingPlanView(FakePlanView):
    """FakePlanView that drops the pending uids from the selection like the real
    SelectionManager.set_pending_mutation_uids does, so a restored selection is
    observable (the plain fake keeps the selection and hides a missing restore)."""

    def set_pending_mutation_uids(self, uids):
        super().set_pending_mutation_uids(uids)
        self.selected = self.selected.difference(self.pending_mutation_uids)


class _FinishCountingUndo(FakeUndoService):
    """FakeUndoService that records every finish_forward_mutation call (the plain fake
    is idempotent, so a token finished twice would go unnoticed)."""

    def __init__(self):
        super().__init__()
        self.finished = []

    def finish_forward_mutation(self, token):
        self.finished.append(token)
        super().finish_forward_mutation(token)


class _RaisingWriteService(FakeWriteService):
    """FakeWriteService whose queue entry points named in raise_in raise `error` at
    submission (nothing is queued), like a provider that is missing or a payload the
    service refuses with a RuntimeError/ValueError/KeyError (anything but the lock)."""

    def __init__(self, error, raise_in):
        super().__init__()
        self.sql_collaboration_mutations = True
        self.error = error
        self.raise_in = set(raise_in)
        self.attempts = []

    def _maybe_raise(self, name):
        self.attempts.append(name)
        if name in self.raise_in:
            raise self.error

    def queue_plan_geometry(self, *args, **kwargs):
        self._maybe_raise("queue_plan_geometry")
        return super().queue_plan_geometry(*args, **kwargs)

    def queue_plan_properties(self, *args, **kwargs):
        self._maybe_raise("queue_plan_properties")
        return super().queue_plan_properties(*args, **kwargs)

    def queue_plan_items_delete(self, *args, **kwargs):
        self._maybe_raise("queue_plan_items_delete")
        return super().queue_plan_items_delete(*args, **kwargs)

    def queue_plan_items_paste(self, *args, **kwargs):
        self._maybe_raise("queue_plan_items_paste")
        return super().queue_plan_items_paste(*args, **kwargs)

    def queue_takeoff_placement(self, *args, **kwargs):
        self._maybe_raise("queue_takeoff_placement")
        return super().queue_takeoff_placement(*args, **kwargs)

    def queue_cancelled_placement_cleanup_delete(self, *args, **kwargs):
        self._maybe_raise("queue_cancelled_placement_cleanup_delete")
        return super().queue_cancelled_placement_cleanup_delete(*args, **kwargs)


_QUEUE_ERRORS = (
    ("RuntimeError", lambda: RuntimeError("queue unavailable")),
    ("ValueError", lambda: ValueError("payload refused")),
    ("KeyError", lambda: KeyError("provider")),
)


class PlanViewActionHandlerQueueExceptionCleanupTests(_PlanViewActionHandlerFixture):
    """Decision R4: ANY exception a queue_* entry point raises at submission other than
    ActiveBidLockedError (RuntimeError, ValueError, KeyError, ...) first frees what the
    optimistic edit took (pending marks, the deferred selection, the consumed edit
    lease, the forward-mutation token) and restores the preview exactly as a rejected
    write does, THEN re-raises the same exception object. ActiveBidLockedError keeps
    its silent refusal (PlanViewActionHandlerLockedBidRefusalTests). History replay
    submissions hold no handler state; UndoRedoService turns the error into a logged,
    replayable entry. Fakes: _RaisingWriteService (no provider or server involved)."""

    def setUp(self):
        super().setUp()
        for name in ("show_warning", "confirm", "show_critical"):
            if hasattr(handler_module, name):
                patcher = patch.object(
                    handler_module,
                    name,
                    side_effect=AssertionError("a queue error must not open a dialog"),
                )
                patcher.start()
                self.addCleanup(patcher.stop)

    def _data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            area_uid="5",
            position=[0.0, 0.0],
        )
        return data

    def _handler(self, error, raise_in, data=None, undo=None):
        data = self._data() if data is None else data
        plan_view = _DeselectingPlanView(data)
        write = _RaisingWriteService(error, raise_in)
        undo = _FinishCountingUndo() if undo is None else undo
        handler = self._paste_handler(
            plan_view=plan_view, write=write, data=data, undo=undo
        )
        return handler, plan_view, write, undo

    def _assert_freed(self, handler, plan_view, undo, selected):
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})
        self.assertEqual(handler._pending_plan_annotations_by_bid, {})
        self.assertEqual(undo.forward_mutations, [])
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan_view.selected, selected)
        self.assertEqual(len(undo.finished), 1)

    def _assert_pending_was_set_then_cleared(self, handler):
        pending_events = [
            payload["pending"]
            for name, payload in handler._event_bus.events
            if name == AppEvents.PENDING_PLAN_MUTATIONS_CHANGED
        ]
        self.assertEqual(pending_events, [True, False])

    def _grant_lease(self, handler, write, plan_view):
        plan_view.selected = {"t1"}
        handler.on_geometry_edit_lease_requested(["t1"])
        handle, callback = PlanViewActionHandlerGeometryLeaseLifecycleTests._grant(
            write
        )
        callback(EditLeaseResult(True, handle=handle))
        self.assertIs(handler._geometry_edit_lease_handle, handle)
        return handle

    def test_a_geometry_queue_error_frees_marks_preview_selection_and_lease(self):
        move = [("t1", [0.0, 0.0], [5.0, 6.0])]
        turn = [("t1", 0.0, 90.0)]
        entries = (
            (
                "positions",
                lambda h: h.on_positions_flushed(move, []),
                [(move, [])],
                [],
            ),
            (
                "rotations",
                lambda h: h.on_rotations_flushed(turn),
                [],
                [turn],
            ),
            (
                "group rotation",
                lambda h: h.on_group_rotation_flushed(move, [], turn),
                [(move, [])],
                [turn],
            ),
        )
        for error_name, make_error in _QUEUE_ERRORS:
            for name, act, positions, rotations in entries:
                with self.subTest(error=error_name, entry=name):
                    error = make_error()
                    handler, plan_view, write, undo = self._handler(
                        error, {"queue_plan_geometry"}
                    )
                    handle = self._grant_lease(handler, write, plan_view)
                    with self.assertRaises(type(error)) as raised:
                        act(handler)
                    self.assertIs(raised.exception, error)
                    self.assertEqual(write.attempts, ["queue_plan_geometry"])
                    self.assertEqual(write.queued_geometry, [])
                    self.assertEqual(plan_view.restored_positions, positions)
                    self.assertEqual(plan_view.restored_rotations, rotations)
                    self.assertEqual(write.ended_edit_leases, [handle])
                    self.assertIsNone(handler._geometry_edit_lease_handle)
                    self.assertEqual(plan_view.geometry_lease_granted, set())
                    self._assert_freed(handler, plan_view, undo, {"t1"})
                    self._assert_pending_was_set_then_cleared(handler)

    def test_a_geometry_queue_error_ends_a_mismatched_lease_exactly_once(self):
        error = RuntimeError("queue unavailable")
        handler, plan_view, write, undo = self._handler(error, {"queue_plan_geometry"})
        handler._data_svc.takeoffs["t2"] = Takeoff(
            uid="t2", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        handle = self._grant_lease(handler, write, plan_view)
        with self.assertRaises(RuntimeError):
            handler.on_positions_flushed([("t2", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self._assert_freed(handler, plan_view, undo, {"t2"})

    def test_a_geometry_queue_error_without_a_lease_ends_nothing(self):
        error = ValueError("payload refused")
        handler, plan_view, write, undo = self._handler(error, {"queue_plan_geometry"})
        plan_view.selected = {"t1"}
        with self.assertRaises(ValueError):
            handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertEqual(write.ended_edit_leases, [])
        self._assert_freed(handler, plan_view, undo, {"t1"})

    def test_a_geometry_queue_error_survives_a_failing_cleanup_and_frees_the_rest(self):
        error = RuntimeError("queue unavailable")
        handler, plan_view, write, undo = self._handler(error, {"queue_plan_geometry"})
        handle = self._grant_lease(handler, write, plan_view)

        def broken(*_args, **_kwargs):
            raise OSError("cleanup step failed")

        plan_view.restore_flushed_positions = broken
        ended = []
        write.end_plan_edit_lease = lambda lease: (ended.append(lease), broken())
        with self.assertLogs(handler_module.logger, "ERROR") as logged:
            with self.assertRaises(RuntimeError) as raised:
                handler.on_positions_flushed([("t1", [0.0, 0.0], [5.0, 6.0])], [])
        self.assertIs(raised.exception, error)
        self.assertEqual(len(logged.records), 2)
        self.assertEqual(ended, [handle])
        self.assertEqual(plan_view.pending_mutation_uids, set())
        self.assertEqual(undo.forward_mutations, [])

    def test_a_delete_queue_error_frees_marks_selection_and_token(self):
        for error_name, make_error in _QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                handler, plan_view, write, undo = self._handler(
                    error, {"queue_plan_items_delete"}
                )
                plan_view.selected = {"t1"}
                with self.assertRaises(type(error)) as raised:
                    handler.on_elements_deleted(["t1"])
                self.assertIs(raised.exception, error)
                self.assertEqual(write.queued_deletes, [])
                self._assert_freed(handler, plan_view, undo, {"t1"})
                self._assert_pending_was_set_then_cleared(handler)

    def test_a_paste_queue_error_restores_the_previous_selection_and_frees_the_token(
        self,
    ):
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        for error_name, make_error in _QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                handler, plan_view, write, undo = self._handler(
                    error, {"queue_plan_items_paste"}
                )
                plan_view.selected = {"t1"}
                bid_ref = handler._ui_state.get_selected_bid_ref()
                with self.assertRaises(type(error)) as raised:
                    handler._queue_sql_plan_items_paste_payload(
                        bid_ref, "p1", payload, ()
                    )
                self.assertIs(raised.exception, error)
                self.assertEqual(write.queued_pastes, [])
                self.assertEqual(plan_view.clears, 1)
                self._assert_freed(handler, plan_view, undo, {"t1"})

    def test_a_property_queue_error_restores_the_edit_for_every_entry_point(self):
        data = self._data()
        data.conditions["c9"] = Condition(
            uid="c9", layer_visible=True, condition_type=Condition.TYPE_AREA
        )
        text_change = [("t1", "label", {"Text": "a"}, {"Text": "b"})]
        cases = (
            ("assign to area", lambda h: h.on_assign_to_area(["t1"]), []),
            (
                "reassign condition",
                lambda h: h.on_reassign_condition(["t1"], "c9"),
                [],
            ),
            ("set negative", lambda h: h.on_set_negative(["t1"], True), []),
            (
                "condition text",
                lambda h: h.on_condition_text_properties_flushed(text_change),
                [text_change],
            ),
        )
        for error_name, make_error in _QUEUE_ERRORS:
            for name, act, restored_text in cases:
                with self.subTest(error=error_name, entry=name):
                    error = make_error()
                    handler, plan_view, write, undo = self._handler(
                        error, {"queue_plan_properties"}, data=data
                    )
                    plan_view.selected = {"t1"}
                    with self.assertRaises(type(error)) as raised:
                        act(handler)
                    self.assertIs(raised.exception, error)
                    self.assertEqual(write.queued_properties, [])
                    self.assertEqual(
                        plan_view.restored_condition_text_properties, restored_text
                    )
                    self._assert_freed(handler, plan_view, undo, {"t1"})
                    self._assert_pending_was_set_then_cleared(handler)

    def test_a_property_queue_error_ends_a_held_geometry_lease_before_raising(self):
        error = RuntimeError("queue unavailable")
        handler, plan_view, write, undo = self._handler(
            error, {"queue_plan_properties"}
        )
        handle = self._grant_lease(handler, write, plan_view)
        with self.assertRaises(RuntimeError):
            handler.on_set_negative(["t1"], True)
        self.assertEqual(write.ended_edit_leases, [handle])
        self.assertIsNone(handler._geometry_edit_lease_handle)
        self._assert_freed(handler, plan_view, undo, {"t1"})

    def test_an_annotation_insert_queue_error_frees_the_token_and_adds_no_history(self):
        for error_name, make_error in _QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                handler, plan_view, write, undo = self._handler(
                    error, {"queue_plan_items_paste"}
                )
                with self.assertRaises(type(error)) as raised:
                    handler.on_annotation_created("rect", [1.0, 2.0, 5.0, 6.0], "p1")
                self.assertIs(raised.exception, error)
                self.assertEqual(write.queued_pastes, [])
                self._assert_freed(handler, plan_view, undo, set())

    def test_a_placement_queue_error_rolls_the_preview_back_and_frees_the_token(self):
        for error_name, make_error in _QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                data = FakeProjectData()
                handler, plan_view, write, undo = self._handler(
                    error, {"queue_takeoff_placement"}, data=data
                )
                with self.assertRaises(type(error)) as raised:
                    handler.on_takeoff_created("c1", [1.0, 2.0], "p1")
                self.assertIs(raised.exception, error)
                self.assertEqual(handler._pending_takeoff_placements, {})
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(write.queued_takeoff_callbacks, [])
                self._assert_freed(handler, plan_view, undo, set())
                self._assert_pending_was_set_then_cleared(handler)

    def test_a_cleanup_delete_queue_error_frees_the_marks_selection_and_token(self):
        for error_name, make_error in _QUEUE_ERRORS:
            with self.subTest(error=error_name):
                error = make_error()
                data = FakeProjectData()
                handler, plan_view, write, undo = self._handler(
                    error, {"queue_cancelled_placement_cleanup_delete"}, data=data
                )
                plan_view.current_page_uid = "9"
                write.cancel_queued_mutation_result = False
                handler.on_takeoff_created("c1", [1.0, 2.0], "9")
                operation_id, callback = write.queued_takeoff_callbacks[0]
                (pending_uid,) = list(data.takeoffs)
                handler.on_elements_deleted([pending_uid])
                data.add_takeoffs(
                    [
                        Takeoff(
                            uid="501",
                            condition_uid="c1",
                            page_uid="9",
                            position=[1.0, 2.0],
                        )
                    ]
                )
                self.assertEqual(len(undo.forward_mutations), 1)
                with self.assertRaises(type(error)) as raised:
                    callback(
                        QueuedMutationResult(
                            database_id="bid.mdb",
                            runtime_generation=3,
                            operation_id=operation_id,
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                            created_resource_ids=("501",),
                        )
                    )
                self.assertIs(raised.exception, error)
                self.assertEqual(write.cleanup_delete_calls, [])
                self.assertEqual(plan_view.pending_mutation_uids, set())
                self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})
                self.assertEqual(undo.forward_mutations, [])
                self.assertEqual(undo.count, 0)
                self.assertEqual(len(undo.finished), 1)

    def test_a_queue_error_during_history_replay_leaves_the_entry_replayable(self):
        replays = (
            ("geometry", "queue_plan_geometry", "queue_plan_geometry"),
            ("properties", "queue_plan_properties", "queue_plan_properties"),
            ("delete", "queue_plan_items_paste", "queue_plan_items_delete"),
            ("paste", "queue_plan_items_delete", "queue_plan_items_paste"),
            ("annotation", "queue_plan_items_delete", "queue_plan_items_paste"),
            ("placement", "queue_plan_items_delete", "queue_takeoff_placement"),
        )
        counters = (
            "queued_geometry",
            "queued_properties",
            "queued_deletes",
            "queued_pastes",
            "queued_takeoff_callbacks",
        )
        for flow, undo_method, redo_method in replays:
            for direction, method in (("undo", undo_method), ("redo", redo_method)):
                with self.subTest(flow=flow, direction=direction):
                    fixture = _SqlFlowFixture()
                    handler, plan_view, write, data, undo = fixture._flow_setup()
                    deliver, _signature = fixture._start(
                        flow, "A", handler, plan_view, write, data
                    )
                    deliver()
                    self.assertTrue(undo.can_undo())
                    if direction == "redo":
                        undo._redo_stack.append(undo._undo_stack.pop())
                    error = RuntimeError("queue unavailable")
                    original = getattr(write, method)

                    def broken(*_args, **_kwargs):
                        raise error

                    setattr(write, method, broken)
                    replay = undo.undo if direction == "undo" else undo.redo
                    with self.assertLogs(undo.logger, "ERROR") as logged:
                        replay()
                    self.assertEqual(
                        [record.getMessage() for record in logged.records],
                        ["Error while submitting history mutation"],
                    )
                    self.assertFalse(undo._history_transition_pending)
                    stack = (
                        undo._undo_stack if direction == "undo" else undo._redo_stack
                    )
                    self.assertEqual(len(stack), 1)
                    self.assertEqual(stack[-1].state.value, "ready")
                    setattr(write, method, original)
                    before = sum(len(getattr(write, name)) for name in counters)
                    replay()
                    after = sum(len(getattr(write, name)) for name in counters)
                    self.assertEqual(after - before, 1)

    def test_the_failure_result_handed_to_the_completion_is_a_failure_before_commit(
        self,
    ):
        from ost_visualizer.application.dtos.queue_submission_failure import (
            queue_submission_failure_result,
        )

        result = queue_submission_failure_result("bid.mdb", ValueError("payload"))
        self.assertEqual(result.database_id, "bid.mdb")
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(result.message, "payload")
        self.assertFalse(result.commit_attempted)
        self.assertIsNone(result.rejection_reason)
        self.assertEqual(result.created_resource_ids, ())
        self.assertEqual(
            queue_submission_failure_result("bid.mdb", RuntimeError()).message,
            "RuntimeError",
        )
        self.assertNotEqual(
            result.operation_id,
            queue_submission_failure_result(
                "bid.mdb", ValueError("payload")
            ).operation_id,
        )

    def test_the_locked_bid_refusal_stays_silent_and_does_not_reraise(self):
        move = [("t1", [0.0, 0.0], [5.0, 6.0])]
        handler, plan_view, write, undo = self._handler(
            ActiveBidLockedError(), {"queue_plan_geometry"}
        )
        plan_view.selected = {"t1"}
        with self.assertLogs(handler_module.logger, "WARNING") as logged:
            handler.on_positions_flushed(move, [])
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL plan geometry blocked: the active bid is locked"],
        )
        self.assertEqual(plan_view.restored_positions, [(move, [])])
        self._assert_freed(handler, plan_view, undo, {"t1"})


class PlanViewActionHandlerNoSelectedBidFlushTests(_PlanViewActionHandlerFixture):
    """Decision R1 (reachability check, outcome: UNREACHABLE, pinned, not changed).
    A plan-view flush slot can see "no selected Bid" while the model still reports a
    current Bid database (get_current_bid_file_path() set, get_selected_bid_ref()
    None) only through the bid_ref None branch of the handler. The branch is not
    reachable in the application: (1) every flush slot starts with
    UIAccessManager.is_allowed(EDIT_PLAN_ITEMS / EDIT_ANNOTATION_TEXT / EDIT_CONDITION),
    all three in _REQUIRES_BID and evaluated on the same UIStateManager.
    get_selected_bid_ref() the handler reads, so with no selected Bid the first guard
    already restores the preview and returns; (2) the signals are emitted
    synchronously from plan-view input handlers and from PlanView.clear(), and every
    coordinator path that clears the Bid selection while the plan is shown first
    calls prepare_for_authoritative_refresh (which discards unflushed geometry edits
    and cancels inline text edits uncommitted) or clears the model Bid in the same
    step. The first test uses the REAL UIAccessManager and UIStateManager to prove
    the guard; the second pins the defensive fallthrough (local save, history with
    bid_ref None) that a permissive access double exposes, so a future change that
    makes it reachable must decide that behaviour on purpose."""

    def setUp(self):
        super().setUp()
        for name in ("show_warning", "confirm", "show_critical"):
            if hasattr(handler_module, name):
                patcher = patch.object(
                    handler_module,
                    name,
                    side_effect=AssertionError(
                        "a bid-less flush must not open a dialog"
                    ),
                )
                patcher.start()
                self.addCleanup(patcher.stop)

    @staticmethod
    def _real_access(selected):
        from ost_visualizer.presentation.managers.ui_access_manager import (
            UIAccessManager,
        )
        from ost_visualizer.presentation.managers.ui_state_manager import (
            UIStateManager,
        )
        from tests.application.services.write_permission_support import (
            _DatabaseCapability,
            _EventBus,
            _ProjectData,
            _TransactionMonitor,
        )
        from tests.presentation.managers.permission_support import _License

        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=False,
                display_mode_3d="condition",
                display_mode_2d="condition",
                grayscale_enabled=False,
            )
        )
        if selected:
            ui_state.set_bid_selection(BidRef("bid.mdb", "7"))
        else:
            ui_state.set_database_selected(True, "bid.mdb")
        project_data = _ProjectData()
        project_data.bid_ref = BidRef("bid.mdb", "7")
        access = UIAccessManager(
            _EventBus(),
            _License(),
            _TransactionMonitor(),
            project_data,
            ui_state,
            _DatabaseCapability(editable=True),
        )
        return ui_state, access

    def _data(self):
        data = FakeProjectData()
        data.takeoffs["t1"] = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[0.0, 0.0]
        )
        data.annotations = [
            BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1")
        ]
        return data

    def _handler(self, access, ui_state, sql=False):
        data = self._data()
        plan_view = FakePlanView(data)
        write = FakeWriteService()
        write.sql_collaboration_mutations = sql
        annotation_write = FakeAnnotationWriteService()
        undo = FakeUndoService()
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=annotation_write,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=undo,
            event_bus=FakeEventBus(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=access,
        )
        return handler, plan_view, write, annotation_write, undo

    def test_the_real_access_manager_forbids_every_bid_less_plan_edit(self):
        features = (
            Feature.EDIT_PLAN_ITEMS,
            Feature.EDIT_ANNOTATION_TEXT,
            Feature.EDIT_CONDITION,
        )
        ui_state, access = self._real_access(selected=False)
        self.assertIsNone(ui_state.get_selected_bid_ref())
        for feature in features:
            with self.subTest(feature=feature.name, selected=False):
                self.assertFalse(access.is_allowed(feature))
        ui_state, access = self._real_access(selected=True)
        for feature in features:
            with self.subTest(feature=feature.name, selected=True):
                self.assertTrue(access.is_allowed(feature))

    def test_every_flush_restores_and_writes_nothing_when_no_bid_is_selected(self):
        move = [("t1", [0.0, 0.0], [5.0, 6.0])]
        turn = [("t1", 0.0, 90.0)]
        text = [("a1", "rect", {"Text": "a"}, {"Text": "b"})]
        style = [("a1", "rect", {"Color": "#000000"}, {"Color": "#ffffff"})]
        condition_text = [("t1", "label", {"Text": "a"}, {"Text": "b"})]
        for sql in (False, True):
            ui_state, access = self._real_access(selected=False)
            handler, plan_view, write, annotation_write, undo = self._handler(
                access, ui_state, sql=sql
            )
            self.assertEqual(handler._data_svc.get_current_bid_file_path(), "bid.mdb")
            handler.on_positions_flushed(move, [])
            handler.on_rotations_flushed(turn)
            handler.on_group_rotation_flushed(move, [], turn)
            handler.on_annotation_text_properties_flushed(text)
            handler.on_annotation_styles_flushed(style)
            handler.on_condition_text_properties_flushed(condition_text)
            with self.subTest(sql=sql):
                self.assertEqual(plan_view.restored_positions, [(move, []), (move, [])])
                self.assertEqual(plan_view.restored_rotations, [turn, turn])
                self.assertEqual(plan_view.restored_text_properties, [text])
                self.assertEqual(plan_view.restored_annotation_styles, [style])
                self.assertEqual(
                    plan_view.restored_condition_text_properties, [condition_text]
                )
                self.assertEqual(write.position_calls, [])
                self.assertEqual(write.rotation_calls, [])
                self.assertEqual(write.text_property_calls, [])
                self.assertEqual(write.local_geometry, [])
                self.assertEqual(write.local_properties, [])
                self.assertEqual(annotation_write.text_property_calls, [])
                self.assertEqual(annotation_write.style_calls, [])
                self.assertEqual(write.queued_geometry, [])
                self.assertEqual(write.queued_properties, [])
                self.assertEqual(undo.count, 0)
                self.assertEqual(undo.forward_mutations, [])

    def test_the_defensive_fallthrough_saves_locally_and_registers_history_without_a_bid(
        self,
    ):
        turn = [("t1", 0.0, 90.0)]
        text = [("a1", "rect", {"Text": "a"}, {"Text": "b"})]
        style = [("a1", "rect", {"Color": "#000000"}, {"Color": "#ffffff"})]
        for sql in (False, True):
            ui_state, _access = self._real_access(selected=False)
            handler, plan_view, write, annotation_write, undo = self._handler(
                FakeAccess(set(Feature)), ui_state, sql=sql
            )
            handler.on_rotations_flushed(turn)
            handler.on_annotation_text_properties_flushed(text)
            handler.on_annotation_styles_flushed(style)
            with self.subTest(sql=sql):
                self.assertEqual(
                    write.rotation_calls, [("bid.mdb", [("t1", 90.0)], False)]
                )
                self.assertEqual(
                    annotation_write.text_property_calls,
                    [("bid.mdb", [("a1", "rect", {"Text": "b"})], False)],
                )
                self.assertEqual(
                    annotation_write.style_calls,
                    [("bid.mdb", [("a1", "rect", {"Color": "#ffffff"})], False)],
                )
                self.assertEqual(plan_view.restored_rotations, [])
                self.assertEqual(plan_view.restored_text_properties, [])
                self.assertEqual(plan_view.restored_annotation_styles, [])
                self.assertEqual(write.queued_geometry, [])
                self.assertEqual(write.queued_properties, [])
                self.assertEqual(undo.count, 3)
                self.assertEqual(
                    [target.bid_ref for target in undo.takeoff_targets], [None]
                )
                self.assertEqual(
                    [target.bid_ref for target in undo.annotation_targets],
                    [None, None],
                )
                self.assertEqual(undo.forward_mutations, [])
