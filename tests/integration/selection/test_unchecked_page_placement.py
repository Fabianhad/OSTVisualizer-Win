import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
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
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


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


class FakeAccess:
    def __init__(self, allowed_features):
        self.allowed_features = set(allowed_features)

    def is_allowed(self, feature):
        return feature in self.allowed_features


class UncheckedPagePlacementWorkflowTests(unittest.TestCase):
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

        data = FakeProjectData()
        data.selected_page_uids = []
        plan_view = ValidatingPlanView(data)
        visualization = VisualizationService()
        opengl_viewer = OpenGLViewer()
        published = []

        def on_takeoffs_changed(page_uid, **call_options):
            published.append((page_uid, call_options["takeoff_uids"]))
            plan_view.current_page_uid = page_uid
            plan_view._current_takeoffs = {
                uid: takeoff
                for uid, takeoff in data.takeoffs.items()
                if takeoff.page_uid == page_uid
            }
            opengl_viewer.clear_scene()
            visualization.refresh_mesh_view([])

        # The production bus builds a TakeoffsChangedEvent from the published
        # payload, so a payload the event type rejects fails the test.
        event_bus = EventBus()
        event_bus.subscribe(AppEvents.TAKEOFFS_CHANGED, on_takeoffs_changed)
        handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ActiveUncheckedPageUiState(),
            project_data_svc=data,
            project_write_svc=FakeWriteService(),
            annotation_write_svc=None,
            page_settings_bar=FakePageSettingsBar(),
            undo_svc=FakeUndoService(),
            event_bus=event_bus,
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(set(Feature)),
        )
        handler.on_takeoff_created("42", [1.0, 2.0], "p2")
        self.assertEqual(published, [("p2", ["100"])])
        self.assertEqual(plan_view.selected, {"100"})
        self.assertEqual(plan_view.current_page_uid, "p2")
        self.assertEqual(plan_view.clear_calls, 0)
        self.assertEqual(opengl_viewer.clears, 1)
        self.assertEqual(visualization.mesh_pages, [[]])
