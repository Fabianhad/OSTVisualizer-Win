from ...application.dtos.plan_items_paste import prepare_plan_items_paste_payload
from ..services.annotation_history import (
    capture_annotation_targets,
    resolve_annotation_updates,
)
import logging
import uuid
import weakref
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional
from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseLoss,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    QueuedMutationResult,
    ResourceRef,
    is_queued_takeoff_preview_uid,
    queued_takeoff_preview_uid,
)
from ...application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
    parse_annotation_resource_id,
)
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...application.events.app_events import AppEvents
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    hex_color_to_int,
    int_color_to_hex,
)
from ...domain.entities.area import normalize_area_uid
from ...domain.entities.named_view import build_named_view_from_annotation
from ...domain.entities.takeoff import Takeoff
from ...domain.services.page_scale_transform import (
    PageScale,
    rescale_annotation_position_between_page_scales,
    rescale_position_between_page_scales,
)
from ...domain.services.takeoff_domain_service import (
    expand_takeoff_uids_with_descendants,
    takeoffs_can_reassign_to_condition,
)
from ..dialogs.select_named_view_dialog import SelectNamedViewDialog
from ..managers.ui_access_manager import Feature
from ..services.annotation_write_coordinator import AnnotationWriteCoordinator
from ..services.selection_clipboard_service import SelectionClipboardService
from ..services.undo_redo_service import AnnotationHistoryTarget, TakeoffHistoryTarget
from ..utils.annotation_defaults import build_placed_annotation_spec
from ..utils.annotation_delete import (
    NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
    plan_named_view_hotlink_delete,
    skipped_named_view_selection_keys,
)
from ..utils.annotation_paste import (
    annotation_paste_anchor,
    translate_annotation_position,
)
from ..utils.dialog import delete_later_if_valid
from ..utils.font_catalog import resolve_font_definition
from ..utils.messagebox import confirm, show_warning
from ..utils.named_view_validation import (
    named_view_name_exists,
    show_duplicate_named_view_name,
)

logger = logging.getLogger(__name__)
_SAME_BID_FAST_TAKEOFF_EXTRA_COLUMNS = frozenset(
    {
        "BidZoneUID",
        "BidTypAreaUID",
        "No",
        "Quantity",
        "Count",
        "GridOffsetX",
        "GridOffsetY",
        "GridRotation",
        "FontName",
        "FontColor",
        "FontSize",
        "FontBold",
        "FontItalic",
        "FontUnderline",
        "TypGroupTakeoffUID",
        "TypPageTakeoffUID",
        "TakeoffModified",
        "TypGroupUID",
        "TypGroupMarkerUID",
        "FlipX",
        "FlipY",
        "GUID",
        "NameFontName",
        "NameFontColor",
        "NameFontSize",
        "NameFontBold",
        "NameFontItalic",
        "NameFontUnderline",
    }
)


@dataclass(frozen=True)
class _PendingTakeoffPlacement:
    database_id: str
    bid_uid: str
    pending_uids: tuple[str, ...]
    specs: tuple[InsertTakeoffSpec, ...]
    page_identities: tuple[tuple[str, object], ...]
    runtime_generation: Optional[int]
    history_token: object = None
    deleted_pending_uids: frozenset[str] = frozenset()


class PlanViewActionHandler:
    def __init__(
        self,
        plan_view,
        ui_state_manager,
        project_data_svc,
        project_write_svc,
        annotation_write_svc,
        page_settings_bar,
        undo_svc,
        event_bus,
        deferred_persistence_manager,
        ui_access_manager,
    ):
        self._plan_view = plan_view
        self._ui_state = ui_state_manager
        self._data_svc = project_data_svc
        self._write_svc = project_write_svc
        self._page_settings_bar = page_settings_bar
        self._undo_svc = undo_svc
        self._event_bus = event_bus
        self._ui_access_manager = ui_access_manager
        self._deferred_persistence = deferred_persistence_manager
        self._clipboard_svc = SelectionClipboardService()
        self._annotation_writes = AnnotationWriteCoordinator(
            annotation_write_svc, project_data_svc, event_bus
        )
        self._pending_takeoff_placements: dict[str, _PendingTakeoffPlacement] = {}
        self._pending_plan_takeoff_uids_by_database: dict[str, set[str]] = {}
        self._pending_plan_annotations_by_database: dict[str, set[tuple[str, str]]] = {}
        self._completed_sql_mutation_ids: set[str] = set()
        self._geometry_edit_lease_handle: Optional[EditLeaseHandle] = None
        self._geometry_edit_lease_request_id = ""
        self._geometry_edit_lease_selection: set[str] = set()

    def _is_allowed(self, feature: Feature) -> bool:
        return self._ui_access_manager.is_allowed(feature)

    def _uses_sql_mutation_queue(self, database_id: str) -> bool:
        return bool(self._write_svc.uses_sql_collaboration_mutations(database_id))

    def _sql_completion_was_applied(self, result: QueuedMutationResult) -> bool:
        return bool(
            result.outcome_status == MutationOutcomeStatus.COMMITTED
            and result.operation_id in self._completed_sql_mutation_ids
        )

    def _mark_sql_completion_applied(self, result: QueuedMutationResult) -> None:
        if result.outcome_status == MutationOutcomeStatus.COMMITTED:
            self._completed_sql_mutation_ids.add(result.operation_id)

    def _set_plan_items_pending(
        self,
        database_id: str,
        plan_uids: set[str],
        takeoff_uids: set[str],
        pending: bool,
        annotation_identities: set[tuple[str, str]] = frozenset(),
    ) -> None:
        database_key = str(database_id)
        pending_takeoffs = self._pending_plan_takeoff_uids_by_database.setdefault(
            database_key, set()
        )
        pending_annotations = self._pending_plan_annotations_by_database.setdefault(
            database_key, set()
        )
        pending_takeoff_uids = set(plan_uids).intersection(takeoff_uids)
        if pending:
            pending_takeoffs.update(pending_takeoff_uids)
            pending_annotations.update(annotation_identities)
        else:
            pending_takeoffs.difference_update(pending_takeoff_uids)
            pending_annotations.difference_update(annotation_identities)
        if not pending_takeoffs:
            self._pending_plan_takeoff_uids_by_database.pop(database_key, None)
        if not pending_annotations:
            self._pending_plan_annotations_by_database.pop(database_key, None)
        active_bid = self._ui_state.get_selected_bid_ref()
        active_database = str(active_bid.file_path) if active_bid is not None else ""
        self._plan_view.set_pending_mutation_uids(
            self._current_plan_keys_for_identities(
                self._pending_plan_takeoff_uids_by_database.get(active_database, set()),
                self._pending_plan_annotations_by_database.get(active_database, set()),
            )
        )
        self._event_bus.publish(
            AppEvents.PENDING_PLAN_MUTATIONS_CHANGED,
            database_id=database_id,
            takeoff_uids=sorted(takeoff_uids),
            pending=pending,
        )

    def _restore_plan_selection_if_current(
        self,
        bid_ref,
        page_uids: tuple[str, ...],
        plan_uids: set[str],
        page_identities: Optional[tuple[tuple[str, object], ...]] = None,
        *,
        selection_revision: Optional[int] = None,
    ) -> None:
        if (
            selection_revision is not None
            and self._plan_view.selection_revision != selection_revision
        ):
            return
        if not plan_uids or not self._plan_context_is_current(
            bid_ref,
            page_uids,
            page_identities,
        ):
            return
        self._plan_view.set_selected_uids(set(plan_uids))

    def _current_plan_keys_for_identities(
        self,
        takeoff_uids: set[str],
        annotation_identities: set[tuple[str, str]],
    ) -> set[str]:
        return set(takeoff_uids).union(
            self._plan_view.find_annotation_keys_by_uid_type(annotation_identities)
        )

    def _plan_identities_for_keys(
        self, plan_uids: set[str]
    ) -> tuple[set[str], set[tuple[str, str]]]:
        takeoff_uids: set[str] = set()
        annotation_identities: set[tuple[str, str]] = set()
        for uid in plan_uids:
            if self._current_plan_takeoff(uid) is not None:
                takeoff_uids.add(uid)
                continue
            annotation = self._plan_view.get_annotation(uid)
            if annotation is not None:
                annotation_identities.add(
                    (str(annotation.uid), str(annotation.annotation_type))
                )
        return takeoff_uids, annotation_identities

    def _capture_page_identities(
        self,
        page_uids: tuple[str, ...],
    ) -> tuple[tuple[str, object], ...]:
        identities = []
        for page_uid in dict.fromkeys(str(uid) for uid in page_uids):
            page = self._data_svc.get_page(page_uid)
            if page is not None:
                identities.append((page_uid, page))
        return tuple(identities)

    def _page_identities_are_current(
        self,
        page_uids: tuple[str, ...],
        page_identities: tuple[tuple[str, object], ...],
    ) -> bool:
        expected_uids = tuple(dict.fromkeys(str(uid) for uid in page_uids))
        return bool(
            len(page_identities) == len(expected_uids)
            and all(
                self._data_svc.get_page(page_uid) is page
                for page_uid, page in page_identities
            )
        )

    def _plan_context_is_current(
        self,
        bid_ref,
        page_uids: tuple[str, ...],
        page_identities: Optional[tuple[tuple[str, object], ...]] = None,
    ) -> bool:
        if not isValid(self._plan_view) or getattr(
            self._plan_view, "_is_cleaning_up", False
        ):
            return False
        if self._ui_state.get_selected_bid_ref() != bid_ref:
            return False
        if page_identities is not None and not self._page_identities_are_current(
            page_uids,
            page_identities,
        ):
            return False
        current_page_uid = str(
            self._plan_view.current_page_uid or self._ui_state.active_page_uid or ""
        )
        return not page_uids or current_page_uid in page_uids

    def _history_selection_owner(
        self, bid_ref, page_uids: tuple[str, ...]
    ) -> Callable[[], bool]:
        page_uids = tuple(dict.fromkeys(str(uid) for uid in page_uids))
        page_identities = self._capture_page_identities(page_uids)
        return lambda: self._plan_context_is_current(
            bid_ref,
            page_uids,
            page_identities,
        )

    def connect_signals(self) -> None:
        pv = self._plan_view
        pv.set_overlay_rect_save_handler(self.save_current_page_overlay_rect)
        pv.assign_to_area_requested.connect(self.on_assign_to_area)
        pv.reassign_condition_requested.connect(self.on_reassign_condition)
        pv.set_negative_requested.connect(self.on_set_negative)
        pv.set_curved_requested.connect(self.on_set_curved)
        pv.positions_flushed.connect(self.on_positions_flushed)
        pv.annotation_text_properties_flushed.connect(
            self.on_annotation_text_properties_flushed
        )
        pv.annotation_styles_flushed.connect(self.on_annotation_styles_flushed)
        pv.condition_text_properties_flushed.connect(
            self.on_condition_text_properties_flushed
        )
        pv.rotations_flushed.connect(self.on_rotations_flushed)
        pv.group_rotation_flushed.connect(self.on_group_rotation_flushed)
        pv.takeoff_created.connect(self.on_takeoff_created)
        pv.annotation_created.connect(self.on_annotation_created)
        pv.text_annotation_created.connect(self.on_text_annotation_created)
        pv.named_view_created.connect(self.on_named_view_created)
        pv.hotlink_placement_requested.connect(self.on_hotlink_placement_requested)
        pv.set_named_view_name_validator(self._validate_named_view_name)
        pv.hole_created.connect(self.on_hole_created)
        pv.elements_deleted.connect(self.on_elements_deleted)
        pv.undo_requested.connect(self._undo_svc.undo)
        pv.redo_requested.connect(self._undo_svc.redo)
        pv.copy_requested.connect(self.on_copy_requested)
        pv.paste_requested.connect(self.on_paste_requested)
        pv.paste_backouts_placed.connect(self.on_paste_backouts_placed)
        pv.geometry_edit_lease_requested.connect(self.on_geometry_edit_lease_requested)
        pv.plan_item_selection_changed.connect(self.on_plan_item_selection_changed)

    def _release_geometry_edit_lease(self) -> None:
        handle = self._geometry_edit_lease_handle
        self._geometry_edit_lease_handle = None
        self._geometry_edit_lease_selection.clear()
        self._geometry_edit_lease_request_id = ""
        self._plan_view.disable_geometry_edit_leasing()
        if handle is not None:
            self._write_svc.end_plan_edit_lease(handle)

    def on_edit_lease_lost(self, loss: EditLeaseLoss) -> None:
        handle = self._geometry_edit_lease_handle
        if (
            handle is None
            or loss.database_id != handle.database_id
            or loss.runtime_generation != handle.runtime_generation
            or loss.draft_id != handle.draft_id
        ):
            return
        self._geometry_edit_lease_handle = None
        self._geometry_edit_lease_selection.clear()
        self._geometry_edit_lease_request_id = ""
        self._plan_view.disable_geometry_edit_leasing()

    def prepare_for_authoritative_refresh(self) -> None:
        self._release_geometry_edit_lease()
        self._plan_view.prepare_for_authoritative_refresh()

    def reconcile_geometry_edit_access(self, allowed: bool) -> None:
        if not allowed:
            self._release_geometry_edit_lease()

    def on_plan_item_selection_changed(self, selected_uids: list) -> None:
        selection = {str(uid) for uid in selected_uids if uid}
        if (
            self._geometry_edit_lease_selection
            and selection != self._geometry_edit_lease_selection
        ):
            self._release_geometry_edit_lease()

    def _geometry_resources_for_selection(
        self,
        bid_ref,
        selected_uids: set[str],
    ) -> tuple[tuple[ResourceRef, ...], tuple[ResourceRef, ...]]:
        bid_value = int(bid_ref.bid_uid)
        selected_takeoffs = {
            str(uid): self._command_takeoff(str(uid)) for uid in selected_uids
        }
        selected_takeoffs = {
            uid: takeoff
            for uid, takeoff in selected_takeoffs.items()
            if takeoff is not None
        }
        selected_parent_uids = set(selected_takeoffs)
        for takeoff in self._data_svc.get_all_takeoffs():
            if str(takeoff.parent_uid or "") in selected_parent_uids:
                selected_takeoffs.setdefault(str(takeoff.uid), takeoff)
        annotations = []
        for key in sorted(selected_uids):
            annotation = self._plan_view.get_annotation(key)
            if annotation is not None:
                annotations.append(annotation)
        resources = {
            *(
                ResourceRef("takeoff", str(takeoff.uid), bid_value)
                for takeoff in selected_takeoffs.values()
            ),
            *(
                ResourceRef(
                    "annotation",
                    f"{annotation.annotation_type}/{annotation.uid}",
                    bid_value,
                )
                for annotation in annotations
            ),
        }
        dependencies = {
            *(
                ResourceRef("page", str(item.page_uid), bid_value)
                for item in (*selected_takeoffs.values(), *annotations)
                if item.page_uid
            ),
            *(
                ResourceRef("condition", str(item.condition_uid), bid_value)
                for item in selected_takeoffs.values()
                if item.condition_uid
            ),
            *(
                ResourceRef("layer", str(item.layer_uid), bid_value)
                for item in annotations
                if item.layer_uid
            ),
        }
        return tuple(sorted(resources)), tuple(sorted(dependencies))

    def on_geometry_edit_lease_requested(self, selected_uids: list) -> None:
        selection = {str(uid) for uid in selected_uids if uid}
        bid_ref = self._ui_state.get_selected_bid_ref()
        if (
            not selection
            or bid_ref is None
            or not self._is_allowed(Feature.EDIT_PLAN_ITEMS)
            or not self._uses_sql_mutation_queue(bid_ref.file_path)
        ):
            self._release_geometry_edit_lease()
            return
        resources, dependencies = self._geometry_resources_for_selection(
            bid_ref,
            selection,
        )
        if not resources:
            self._release_geometry_edit_lease()
            return
        handle = self._geometry_edit_lease_handle
        if (
            handle is not None
            and handle.resources == resources
            and handle.dependency_resources == dependencies
        ):
            self._geometry_edit_lease_selection = selection
            self._plan_view.set_geometry_edit_lease_granted(selection)
            return
        if (
            self._geometry_edit_lease_request_id
            and self._geometry_edit_lease_selection == selection
        ):
            return
        self._release_geometry_edit_lease()
        request_id = str(uuid.uuid4())
        self._geometry_edit_lease_request_id = request_id
        self._geometry_edit_lease_selection = selection
        self._plan_view.set_geometry_edit_lease_pending(selection)
        page_uids = tuple(
            resource.resource_id
            for resource in dependencies
            if resource.resource_type == "page"
        )
        page_identities = self._capture_page_identities(page_uids)
        handler_ref = weakref.ref(self)
        write_service = self._write_svc

        def resolved(result) -> None:
            handler = handler_ref()
            if handler is None:
                if result.handle is not None:
                    write_service.end_plan_edit_lease(result.handle)
                return
            if handler._geometry_edit_lease_request_id != request_id:
                if result.handle is not None:
                    handler._write_svc.end_plan_edit_lease(result.handle)
                return
            handler._geometry_edit_lease_request_id = ""
            current_selection = set(handler._plan_view.get_selected_uids())
            if (
                not result.granted
                or current_selection != selection
                or not handler._is_allowed(Feature.EDIT_PLAN_ITEMS)
                or not handler._plan_context_is_current(
                    bid_ref,
                    page_uids,
                    page_identities,
                )
            ):
                if result.handle is not None:
                    handler._write_svc.end_plan_edit_lease(result.handle)
                handler._geometry_edit_lease_selection.clear()
                handler._plan_view.set_geometry_edit_lease_pending(set())
                return
            handler._geometry_edit_lease_handle = result.handle
            handler._plan_view.set_geometry_edit_lease_granted(selection)

        self._write_svc.request_plan_edit_lease(
            bid_ref.file_path,
            resources,
            dependencies,
            resolved,
            operation_id=request_id,
            owning_surface="main-plan",
        )

    def save_current_page_overlay_rect(
        self, overlay_rect: tuple[float, float, float, float]
    ) -> bool:
        if not self._is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        bid_ref = self._ui_state.get_selected_bid_ref()
        page_uid = self._ui_state.active_page_uid
        if not bid_ref or not page_uid:
            return False
        rect = tuple(float(value) for value in overlay_rect)
        page = self._data_svc.get_page(page_uid)
        if page is None:
            return False
        original_rect = page.overlay_rect
        accepted = self._deferred_persistence.schedule_page_overlay_rect(
            bid_ref.file_path,
            page_uid,
            rect,
            restore_authoritative=lambda: self._project_overlay_rect_if_current(
                bid_ref,
                page_uid,
                original_rect,
            ),
            project_value=lambda: self._project_overlay_rect_if_current(
                bid_ref,
                page_uid,
                rect,
            ),
        )
        if accepted:
            page.overlay_rect = rect
        return accepted

    def _project_overlay_rect_if_current(
        self,
        bid_ref,
        page_uid: str,
        overlay_rect,
    ) -> None:
        if not self._plan_context_is_current(bid_ref, (page_uid,)):
            return
        page = self._data_svc.get_page(page_uid)
        if page is None:
            return
        page.overlay_rect = overlay_rect
        self._plan_view.project_overlay_rect(page_uid, overlay_rect)

    def can_paste_to_current_bid(self) -> bool:
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return False
        items, annotations = self._permitted_paste_content(bid_ref)
        return bool(items or annotations)

    def _permitted_paste_content(self, bid_ref) -> tuple[list, list]:
        if (
            not self._clipboard_svc.has_content()
            or not self._clipboard_svc.source_matches_database(bid_ref.file_path)
        ):
            return [], []
        items = (
            list(self._clipboard_svc.items)
            if self._is_allowed(Feature.EDIT_PLAN_ITEMS)
            else []
        )
        annotations = (
            list(self._clipboard_svc.annotations)
            if self._is_allowed(Feature.PLACE_ANNOTATIONS)
            else []
        )
        if not items and self._clipboard_svc.source_bid_uid != bid_ref.bid_uid:
            annotations = []
        return items, annotations

    def on_condition_text_properties_flushed(self, changes: list) -> None:
        if not changes:
            return
        if not self._is_allowed(Feature.EDIT_CONDITION):
            self._plan_view.restore_condition_text_properties(changes)
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self._plan_view.restore_condition_text_properties(changes)
            return
        new_updates = [
            (takeoff_uid, dict(new_props))
            for takeoff_uid, _label_kind, _old_props, new_props in changes
        ]
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            old_updates = [
                (takeoff_uid, dict(old_props))
                for takeoff_uid, _label_kind, old_props, _new_props in changes
            ]
            takeoff_uids = {str(uid) for uid, _properties in new_updates}
            page_uids = tuple(
                dict.fromkeys(
                    str(takeoff.page_uid)
                    for takeoff in (self._command_takeoff(uid) for uid in takeoff_uids)
                    if takeoff is not None and takeoff.page_uid
                )
            )
            self._queue_sql_plan_properties(
                bid_ref,
                "takeoff_text",
                new_updates,
                old_updates=old_updates,
                plan_uids=set(takeoff_uids),
                takeoff_uids=set(takeoff_uids),
                page_uids=page_uids,
                restore=lambda: self._plan_view.restore_condition_text_properties(
                    changes
                ),
            )
            return
        old_updates = [
            (takeoff_uid, dict(old_props))
            for takeoff_uid, _label_kind, old_props, _new_props in changes
            if old_props is not None
        ]
        if not self._execute_local_plan_properties(
            bid_ref,
            "takeoff_text",
            new_updates,
        ):
            self._plan_view.restore_condition_text_properties(changes)
            return
        if old_updates:
            self._push_local_property_history(
                bid_ref, "takeoff_text", old_updates, new_updates, ()
            )

    def _takeoff_uids_only(self, uids: list) -> list:
        return [u for u in uids if self._command_takeoff(u)]

    def _current_plan_takeoff(self, uid: str):
        return self._plan_view.get_takeoff(uid) if self._plan_view else None

    def _command_takeoff(self, uid: str):
        if is_queued_takeoff_preview_uid(str(uid)):
            return None
        takeoff = self._current_plan_takeoff(uid)
        return takeoff or self._data_svc.get_takeoff(uid)

    def _publish_takeoffs_changed_for_pages(
        self,
        page_uids: List[str],
        takeoff_uids: List[str],
        condition_uids: Optional[List[str]] = None,
    ) -> None:
        affected_condition_uids = condition_uids
        if affected_condition_uids is None:
            affected_condition_uids = self._data_svc.get_condition_uids_for_takeoffs(
                takeoff_uids
            )
        affected_page_uids = list(dict.fromkeys(str(uid) for uid in page_uids if uid))
        if not affected_page_uids:
            return
        payload = {
            "page_uid": affected_page_uids[0] if len(affected_page_uids) == 1 else "",
            "takeoff_uids": takeoff_uids,
            "condition_uids": list(affected_condition_uids),
        }
        if len(affected_page_uids) > 1:
            payload["page_uids"] = affected_page_uids
        self._event_bus.publish(AppEvents.TAKEOFFS_CHANGED, **payload)

    def _save_takeoff_positions_fast(
        self, db_path: str, positions: List[tuple]
    ) -> bool:
        if not positions:
            return True
        if not self._write_svc.save_takeoff_positions(
            db_path, positions, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.update_takeoff_positions(positions)
        self._publish_takeoffs_changed_for_pages(
            page_uids, [uid for uid, _position in positions]
        )
        return True

    def _save_takeoff_rotations_fast(
        self, db_path: str, rotations: List[tuple]
    ) -> bool:
        if not rotations:
            return True
        if not self._write_svc.save_takeoff_rotations(
            db_path, rotations, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.update_takeoff_rotations(rotations)
        self._publish_takeoffs_changed_for_pages(
            page_uids, [uid for uid, _rotation in rotations]
        )
        return True

    def _publish_saved_takeoff_position_rotation_changes(
        self, positions: List[tuple], rotations: List[tuple]
    ) -> None:
        page_uids = []
        if positions:
            page_uids.extend(self._data_svc.update_takeoff_positions(positions))
        if rotations:
            page_uids.extend(self._data_svc.update_takeoff_rotations(rotations))
        changed_uids = [uid for uid, _position in positions]
        changed_uids.extend(uid for uid, _rotation in rotations)
        self._publish_takeoffs_changed_for_pages(page_uids, changed_uids)

    def _save_annotation_positions_fast(
        self, db_path: str, positions: List[tuple]
    ) -> bool:
        return self._annotation_writes.save_positions(db_path, positions)

    def _save_annotation_text_properties_fast(
        self, db_path: str, updates: List[tuple]
    ) -> bool:
        return self._annotation_writes.save_text_properties(db_path, updates)

    def _save_annotation_styles_fast(self, db_path: str, updates: List[tuple]) -> bool:
        return self._annotation_writes.save_styles(db_path, updates)

    def _execute_local_plan_geometry(
        self,
        bid_ref,
        *,
        takeoff_positions: List[tuple] = (),
        takeoff_rotations: List[tuple] = (),
        annotation_positions: List[tuple] = (),
    ) -> bool:
        if takeoff_positions and not takeoff_rotations and not annotation_positions:
            return self._save_takeoff_positions_fast(
                bid_ref.file_path,
                takeoff_positions,
            )
        if takeoff_rotations and not takeoff_positions and not annotation_positions:
            return self._save_takeoff_rotations_fast(
                bid_ref.file_path,
                takeoff_rotations,
            )
        if annotation_positions and not takeoff_positions and not takeoff_rotations:
            return self._save_annotation_positions_fast(
                bid_ref.file_path,
                annotation_positions,
            )
        page_uids = tuple(
            dict.fromkeys(
                str(item.page_uid)
                for item in (
                    *(
                        self._command_takeoff(uid)
                        for uid, _position in takeoff_positions
                    ),
                    *(
                        self._command_takeoff(uid)
                        for uid, _rotation in takeoff_rotations
                    ),
                    *(
                        self._plan_view.get_annotation(key)
                        for key in self._plan_view.find_annotation_keys_by_uid_type(
                            {
                                (str(uid), str(annotation_type))
                                for uid, annotation_type, _position in (
                                    annotation_positions
                                )
                            }
                        )
                    ),
                )
                if item is not None and item.page_uid
            )
        )
        result = self._write_svc.execute_plan_geometry_local(
            bid_ref.file_path,
            bid_ref.bid_uid,
            takeoff_positions=takeoff_positions,
            takeoff_rotations=takeoff_rotations,
            annotation_positions=annotation_positions,
            page_uids=page_uids,
            publish_database_refreshed_after_write=False,
        )
        if result.outcome_status != MutationOutcomeStatus.COMMITTED:
            return False
        self._publish_saved_takeoff_position_rotation_changes(
            takeoff_positions,
            takeoff_rotations,
        )
        if annotation_positions:
            affected_pages = self._data_svc.update_annotation_positions(
                annotation_positions
            )
            self._annotation_writes.publish_annotations_changed_for_pages(
                affected_pages,
                [str(uid) for uid, _annotation_type, _position in annotation_positions],
                [
                    str(annotation_type)
                    for _uid, annotation_type, _position in annotation_positions
                ],
            )
        return True

    def _execute_local_plan_properties(
        self,
        bid_ref,
        property_kind: str,
        updates: List[tuple],
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
    ) -> bool:
        is_annotation = property_kind.startswith("annotation_")
        takeoff_uids = [str(update[0]) for update in updates]
        prior_condition_uids = (
            []
            if is_annotation
            else self._data_svc.get_condition_uids_for_takeoffs(takeoff_uids)
        )
        page_uids = tuple(
            dict.fromkeys(
                str(item.page_uid)
                for item in (
                    (
                        self._plan_view.get_annotation(key)
                        for key in self._plan_view.find_annotation_keys_by_uid_type(
                            {(str(update[0]), str(update[1])) for update in updates}
                        )
                    )
                    if is_annotation
                    else (self._command_takeoff(str(update[0])) for update in updates)
                )
                if item is not None and item.page_uid
            )
        )
        result = self._write_svc.execute_plan_properties_local(
            bid_ref.file_path,
            bid_ref.bid_uid,
            property_kind,
            updates,
            page_uids=page_uids,
            dependency_resources=dependency_resources,
            publish_database_refreshed_after_write=False,
        )
        if result.outcome_status != MutationOutcomeStatus.COMMITTED:
            return False
        affected_pages: List[str] = []
        if property_kind == "takeoff_text":
            affected_pages.extend(
                self._data_svc.update_takeoff_text_properties(updates)
            )
        elif property_kind == "takeoff_area":
            assignments: dict[str, list[str]] = {}
            for takeoff_uid, target_uid in updates:
                assignments.setdefault(str(target_uid), []).append(str(takeoff_uid))
            for target_uid, assigned_uids in assignments.items():
                affected_pages.extend(
                    self._data_svc.update_takeoffs_area(assigned_uids, target_uid)
                )
        elif property_kind == "takeoff_condition":
            assignments = {}
            for takeoff_uid, target_uid in updates:
                assignments.setdefault(str(target_uid), []).append(str(takeoff_uid))
            for target_uid, assigned_uids in assignments.items():
                affected_pages.extend(
                    self._data_svc.update_takeoffs_condition(
                        assigned_uids,
                        target_uid,
                    )
                )
        elif property_kind == "takeoff_negative":
            assignments: dict[bool, list[str]] = {}
            for takeoff_uid, value in updates:
                assignments.setdefault(bool(value), []).append(str(takeoff_uid))
            for value, assigned_uids in assignments.items():
                affected_pages.extend(
                    self._data_svc.update_takeoffs_negative(assigned_uids, value)
                )
        elif property_kind == "takeoff_curve":
            for takeoff_uid, position, curve in updates:
                affected_pages.extend(
                    self._data_svc.update_takeoff_curve(
                        str(takeoff_uid),
                        list(position),
                        int(curve),
                    )
                )
        elif property_kind == "annotation_text":
            affected_pages.extend(
                self._data_svc.update_annotation_text_properties(updates)
            )
        elif property_kind == "annotation_style":
            affected_pages.extend(self._data_svc.update_annotation_styles(updates))
        if is_annotation:
            self._annotation_writes.publish_annotations_changed_for_pages(
                self._unique_ordered(affected_pages),
                takeoff_uids,
                [str(update[1]) for update in updates],
            )
        else:
            condition_uids = prior_condition_uids
            if property_kind == "takeoff_area":
                condition_uids = []
            elif property_kind == "takeoff_condition":
                condition_uids = self._unique_ordered(
                    prior_condition_uids
                    + [str(target_uid) for _takeoff_uid, target_uid in updates]
                )
            self._publish_takeoffs_changed_for_pages(
                self._unique_ordered(affected_pages),
                takeoff_uids,
                condition_uids=condition_uids,
            )
        return True

    def _queue_sql_plan_geometry(
        self,
        bid_ref,
        *,
        takeoff_changes: list = (),
        annotation_changes: list = (),
        rotation_changes: list = (),
    ) -> None:
        takeoff_old = [
            (str(uid), list(old))
            for uid, old, _new in takeoff_changes
            if old is not None
        ]
        takeoff_new = [(str(uid), list(new)) for uid, _old, new in takeoff_changes]
        annotation_old = [
            (str(uid), str(annotation_type), list(old))
            for uid, annotation_type, old, _new in annotation_changes
            if old is not None
        ]
        annotation_new = [
            (str(uid), str(annotation_type), list(new))
            for uid, annotation_type, _old, new in annotation_changes
        ]
        rotation_old = [
            (str(uid), float(old))
            for uid, old, _new in rotation_changes
            if old is not None
        ]
        rotation_new = [(str(uid), float(new)) for uid, _old, new in rotation_changes]
        takeoff_scales = self._capture_takeoff_scales(takeoff_old or takeoff_new)
        takeoff_uids = {uid for uid, _position in takeoff_new}.union(
            uid for uid, _rotation in rotation_new
        )
        annotation_identities = {
            (uid, annotation_type) for uid, annotation_type, _position in annotation_new
        }
        annotation_keys = set(
            self._plan_view.find_annotation_keys_by_uid_type(annotation_identities)
        )
        plan_uids = set(takeoff_uids).union(annotation_keys)
        page_uids = tuple(
            dict.fromkeys(
                str(item.page_uid)
                for item in (
                    *(self._command_takeoff(uid) for uid in sorted(takeoff_uids)),
                    *(
                        self._plan_view.get_annotation(key)
                        for key in sorted(annotation_keys)
                    ),
                )
                if item is not None and item.page_uid
            )
        )
        page_identities = self._capture_page_identities(page_uids)
        resources, dependencies = self._geometry_resources_for_selection(
            bid_ref,
            plan_uids,
        )
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        edit_lease_handle = self._geometry_edit_lease_handle
        if edit_lease_handle is not None and (
            edit_lease_handle.resources != resources
            or edit_lease_handle.dependency_resources != dependencies
        ):
            self._release_geometry_edit_lease()
            edit_lease_handle = None
        elif edit_lease_handle is not None:
            self._geometry_edit_lease_handle = None
            self._geometry_edit_lease_selection.clear()
            self._geometry_edit_lease_request_id = ""
            self._plan_view.disable_geometry_edit_leasing()
        self._set_plan_items_pending(
            bid_ref.file_path,
            plan_uids,
            takeoff_uids,
            True,
            annotation_identities,
        )
        selection_revision = self._plan_view.begin_deferred_selection()
        handler_ref = weakref.ref(self)

        def restore_preview(handler) -> None:
            if takeoff_changes or annotation_changes:
                handler._plan_view.restore_flushed_positions(
                    takeoff_changes,
                    annotation_changes,
                )
            if rotation_changes:
                handler._plan_view.restore_flushed_rotations(rotation_changes)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None:
                return
            if handler._sql_completion_was_applied(result):
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            handler._set_plan_items_pending(
                bid_ref.file_path,
                plan_uids,
                takeoff_uids,
                False,
                annotation_identities,
            )
            current_plan_uids = handler._current_plan_keys_for_identities(
                takeoff_uids,
                annotation_identities,
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                if handler._plan_context_is_current(
                    bid_ref,
                    page_uids,
                    page_identities,
                ) and handler._is_allowed(Feature.EDIT_PLAN_ITEMS):
                    restore_preview(handler)
                handler._restore_plan_selection_if_current(
                    bid_ref,
                    page_uids,
                    current_plan_uids,
                    page_identities,
                    selection_revision=selection_revision,
                )
                handler._undo_svc.finish_forward_mutation(history_token)
                return
            handler._restore_plan_selection_if_current(
                bid_ref,
                page_uids,
                current_plan_uids,
                page_identities,
                selection_revision=selection_revision,
            )
            if handler._undo_svc.is_forward_mutation_current(
                history_token
            ) and handler._page_identities_are_current(page_uids, page_identities):
                handler._push_sql_geometry_history(
                    bid_ref,
                    takeoff_old,
                    takeoff_new,
                    annotation_old,
                    annotation_new,
                    rotation_old,
                    rotation_new,
                    page_uids,
                    takeoff_scales=takeoff_scales,
                )
                handler._undo_svc.bind_latest_history_to_forward_mutation(history_token)
            handler._mark_sql_completion_applied(result)
            handler._undo_svc.finish_forward_mutation(history_token)

        try:
            self._write_svc.queue_plan_geometry(
                bid_ref.file_path,
                bid_ref.bid_uid,
                complete,
                takeoff_positions=takeoff_new,
                takeoff_rotations=rotation_new,
                annotation_positions=annotation_new,
                page_uids=page_uids,
                dependency_resources=dependencies,
                edit_lease_handle=edit_lease_handle,
            )
        except Exception:
            self._undo_svc.finish_forward_mutation(history_token)
            raise

    def _push_sql_geometry_history(
        self,
        bid_ref,
        takeoff_old: list,
        takeoff_new: list,
        annotation_old: list,
        annotation_new: list,
        rotation_old: list,
        rotation_new: list,
        page_uids: tuple[str, ...],
        *,
        takeoff_scales=None,
    ) -> None:
        takeoff_targets = self._property_history_targets(
            bid_ref, "takeoff_geometry", takeoff_old + rotation_old
        )
        if takeoff_scales is None:
            takeoff_scales = self._capture_takeoff_scales(takeoff_old)
        annotation_targets = self._annotation_history_targets(bid_ref, annotation_old)
        annotation_scales = self._capture_annotation_scales(annotation_old)

        def submit(
            done,
            takeoff_positions: list,
            annotation_positions: list,
            takeoff_rotations: list,
        ) -> None:
            self._write_svc.queue_plan_geometry(
                bid_ref.file_path,
                bid_ref.bid_uid,
                lambda result: done(result),
                takeoff_positions=self._takeoff_history_positions(
                    takeoff_positions, takeoff_targets, takeoff_scales
                ),
                annotation_positions=self._annotation_history_positions(
                    annotation_positions, annotation_targets, annotation_scales
                ),
                takeoff_rotations=self._property_history_updates(
                    takeoff_rotations, takeoff_targets
                ),
                page_uids=page_uids,
            )

        self._undo_svc.push_for_bid(
            bid_ref,
            lambda done: submit(
                done,
                takeoff_old,
                annotation_old,
                rotation_old,
            ),
            lambda done: submit(
                done,
                takeoff_new,
                annotation_new,
                rotation_new,
            ),
            takeoff_targets=tuple(takeoff_targets.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    def _queue_sql_plan_properties(
        self,
        bid_ref,
        property_kind: str,
        new_updates: list,
        *,
        old_updates: list = (),
        plan_uids: set[str],
        takeoff_uids: set[str] = frozenset(),
        annotation_identities: set[tuple[str, str]] = frozenset(),
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        restore=None,
    ) -> None:
        complete, abort = self.prepare_sql_property_completion(
            bid_ref,
            property_kind,
            new_updates,
            old_updates=old_updates,
            plan_uids=plan_uids,
            takeoff_uids=takeoff_uids,
            annotation_identities=annotation_identities,
            page_uids=page_uids,
            dependency_resources=dependency_resources,
            restore=restore,
        )
        try:
            self._write_svc.queue_plan_properties(
                bid_ref.file_path,
                bid_ref.bid_uid,
                property_kind,
                list(new_updates),
                complete,
                page_uids=page_uids,
                dependency_resources=dependency_resources,
            )
        except Exception:
            abort()
            raise

    def prepare_sql_property_completion(
        self,
        bid_ref,
        property_kind: str,
        new_updates: list,
        *,
        old_updates: list = (),
        plan_uids: set[str],
        takeoff_uids: set[str] = frozenset(),
        annotation_identities: set[tuple[str, str]] = frozenset(),
        page_uids: tuple[str, ...] = (),
        dependency_resources: tuple[ResourceRef, ...] = (),
        restore=None,
        committed_updates=None,
        preserve_selection: bool = False,
        owner_is_current=None,
    ):
        self._release_geometry_edit_lease()
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        page_identities = self._capture_page_identities(page_uids)
        prior_selection = (
            self._plan_identities_for_keys(set(self._plan_view.get_selected_uids()))
            if preserve_selection
            else None
        )
        self._set_plan_items_pending(
            bid_ref.file_path,
            plan_uids,
            takeoff_uids,
            True,
            annotation_identities,
        )
        selection_revision = self._plan_view.begin_deferred_selection()
        handler_ref = weakref.ref(self)
        terminal_delivered = False

        def current_selection(handler) -> set[str]:
            if prior_selection is not None:
                return handler._current_plan_keys_for_identities(*prior_selection)
            if annotation_identities:
                return handler._current_plan_keys_for_identities(
                    takeoff_uids, annotation_identities
                )
            return plan_uids

        def restore_failed_selection(handler) -> None:
            if (
                restore is not None
                and handler._is_allowed(Feature.EDIT_PLAN_ITEMS)
                and handler._plan_context_is_current(
                    bid_ref, page_uids, page_identities
                )
            ):
                restore()
            handler._restore_plan_selection_if_current(
                bid_ref,
                page_uids,
                current_selection(handler),
                page_identities,
                selection_revision=selection_revision,
            )

        def complete(result: QueuedMutationResult) -> None:
            nonlocal terminal_delivered
            handler = handler_ref()
            if handler is None or terminal_delivered:
                return
            if handler._sql_completion_was_applied(result):
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            terminal_delivered = True
            handler._set_plan_items_pending(
                bid_ref.file_path,
                plan_uids,
                takeoff_uids,
                False,
                annotation_identities,
            )
            if owner_is_current is not None and not owner_is_current():
                handler._mark_sql_completion_applied(result)
                handler._undo_svc.finish_forward_mutation(history_token)
                return
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                restore_failed_selection(handler)
                handler._undo_svc.finish_forward_mutation(history_token)
                return
            handler._restore_plan_selection_if_current(
                bid_ref,
                page_uids,
                current_selection(handler),
                page_identities,
                selection_revision=selection_revision,
            )
            if (
                old_updates
                and handler._undo_svc.is_forward_mutation_current(history_token)
                and handler._page_identities_are_current(page_uids, page_identities)
            ):
                history_updates, history_dependencies = (
                    committed_updates(result)
                    if committed_updates is not None
                    else (list(new_updates), dependency_resources)
                )
                handler._push_sql_property_history(
                    bid_ref,
                    property_kind,
                    list(old_updates),
                    history_updates,
                    page_uids,
                    history_dependencies,
                )
                handler._undo_svc.bind_latest_history_to_forward_mutation(history_token)
            handler._mark_sql_completion_applied(result)
            handler._undo_svc.finish_forward_mutation(history_token)

        def abort() -> None:
            nonlocal terminal_delivered
            if terminal_delivered:
                return
            terminal_delivered = True
            self._set_plan_items_pending(
                bid_ref.file_path, plan_uids, takeoff_uids, False, annotation_identities
            )
            if owner_is_current is None or owner_is_current():
                restore_failed_selection(self)
            self._undo_svc.finish_forward_mutation(history_token)

        return complete, abort

    def _push_sql_property_history(
        self,
        bid_ref,
        property_kind: str,
        old_updates: list,
        new_updates: list,
        page_uids: tuple[str, ...],
        dependency_resources: tuple[ResourceRef, ...],
    ) -> None:
        targets = self._property_history_targets(bid_ref, property_kind, old_updates)
        annotation_targets = (
            self._annotation_history_targets(bid_ref, old_updates)
            if property_kind.startswith("annotation_")
            else {}
        )

        def submit(done, updates: list) -> None:
            self._write_svc.queue_plan_properties(
                bid_ref.file_path,
                bid_ref.bid_uid,
                property_kind,
                self._annotation_history_updates(
                    self._property_history_updates(updates, targets), annotation_targets
                ),
                lambda result: done(result),
                page_uids=page_uids,
                dependency_resources=dependency_resources,
            )

        self._undo_svc.push_for_bid(
            bid_ref,
            lambda done: submit(done, old_updates),
            lambda done: submit(done, new_updates),
            takeoff_targets=tuple(targets.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    def _annotation_history_targets(self, bid_ref, updates):
        return capture_annotation_targets(self._data_svc, bid_ref, updates)

    def _annotation_history_updates(self, updates, targets):
        return resolve_annotation_updates(self._data_svc, updates, targets)

    def _annotation_history_keys(self, targets):
        by_identity = {
            (target.uid, target.annotation_type): target for target in targets.values()
        }
        return self._annotation_history_updates(list(by_identity), by_identity)

    def _annotation_history_positions(self, positions, targets, scales):
        return self._positions_for_current_annotation_scales(
            self._annotation_history_updates(positions, targets),
            {
                (target.uid, target.annotation_type): scales[key]
                for key, target in targets.items()
            },
        )

    @staticmethod
    def _annotation_restore_history_targets(bid_ref, payload, uid_map):
        return {
            source: AnnotationHistoryTarget(
                bid_ref, str(spec.page_uid), spec.annotation_type, uid_map[source]
            )
            for source, spec in zip(
                payload.annotation_source_uids, payload.annotation_specs
            )
        }

    def _rebind_restored_annotation_history(self, bid_ref, targets, uid_map, suspended):
        self._undo_svc.rebind_restored_annotations(
            bid_ref,
            {target.identity: uid_map[source] for source, target in targets.items()},
            suspended,
        )

    def _property_history_targets(self, bid_ref, property_kind, updates):
        if property_kind.startswith("annotation_"):
            return {}
        targets = {}
        for uid, *_values in updates:
            takeoff = self._data_svc.get_takeoff(str(uid))
            if takeoff is None:
                raise ValueError(
                    "The property history Takeoff is no longer authoritative."
                )
            targets[str(uid)] = TakeoffHistoryTarget(
                bid_ref, str(takeoff.page_uid), str(uid)
            )
        return targets

    def _property_history_updates(self, updates, targets):
        if not targets:
            return updates
        for target in targets.values():
            takeoff = self._data_svc.get_takeoff(target.uid)
            if (
                not target.available
                or takeoff is None
                or str(takeoff.page_uid) != target.page_uid
            ):
                raise ValueError(
                    "The property history Takeoff no longer owns its Page."
                )
        return [(targets[str(uid)].uid, *values) for uid, *values in updates]

    def _history_parent_targets(
        self, bid_ref, source_uids, specs, *, external_parent_sources=()
    ):
        sources = tuple(source_uids)
        source_uids = set(sources)
        return self._property_history_targets(
            bid_ref,
            "takeoff_parent",
            [
                (str(spec.parent_uid),)
                for source_uid, spec in zip(sources, specs)
                if str(spec.parent_uid or "0") not in {"", "0", "None"}
                and (
                    str(spec.parent_uid) not in source_uids
                    or source_uid in external_parent_sources
                )
            ],
        )

    def _specs_with_history_parents(self, specs, parents):
        self._property_history_updates([(uid,) for uid in parents], parents)
        return [
            (
                replace(spec, parent_uid=parents[str(spec.parent_uid)].uid)
                if str(spec.parent_uid) in parents
                else spec
            )
            for spec in specs
        ]

    def _paste_payload_with_history_parents(self, payload, parents):
        self._property_history_updates([(uid,) for uid in parents], parents)
        external = set(payload.takeoff_external_parent_sources)
        specs = []
        for source_uid, spec in zip(payload.takeoff_source_uids, payload.takeoff_specs):
            parent_uid = str(spec.parent_uid)
            if parent_uid in parents and (
                parent_uid not in payload.takeoff_source_uids or source_uid in external
            ):
                spec = replace(spec, parent_uid=parents[parent_uid].uid)
                external.add(source_uid)
            specs.append(spec)
        return replace(
            payload,
            takeoff_specs=tuple(specs),
            takeoff_external_parent_sources=tuple(
                source_uid
                for source_uid in payload.takeoff_source_uids
                if source_uid in external
            ),
        )

    def _push_local_property_history(
        self, bid_ref, property_kind, old_updates, new_updates, dependencies
    ) -> None:
        targets = self._property_history_targets(bid_ref, property_kind, old_updates)

        def submit(updates):
            return self._execute_local_plan_properties(
                bid_ref,
                property_kind,
                self._property_history_updates(updates, targets),
                dependency_resources=dependencies,
            )

        self._undo_svc.push_local(
            lambda: submit(old_updates),
            lambda: submit(new_updates),
            takeoff_targets=tuple(targets.values()),
        )

    def _page_scale_for_page_uid(self, page_uid: str) -> PageScale:
        page = self._data_svc.get_page(str(page_uid))
        if page is None:
            return (1.0, 1.0)
        return (
            float(page.scale_factor1 or 1.0),
            float(page.scale_factor2 or 1.0),
        )

    def _takeoff_scale_for_uid(self, uid: str) -> PageScale:
        takeoff = self._command_takeoff(str(uid))
        if takeoff is None:
            return (1.0, 1.0)
        return self._page_scale_for_page_uid(takeoff.page_uid)

    def _annotation_scale_for_key(self, uid: str, annotation_type: str) -> PageScale:
        target_key = (str(uid), str(annotation_type))
        for annotation in self._data_svc.get_all_annotations():
            key = (str(annotation.uid), str(annotation.annotation_type))
            if key == target_key:
                return self._page_scale_for_page_uid(annotation.page_uid)
        return (1.0, 1.0)

    def _capture_takeoff_scales(self, positions: List[tuple]) -> dict[str, PageScale]:
        return {
            str(uid): self._takeoff_scale_for_uid(str(uid))
            for uid, _position in positions
        }

    def _capture_annotation_scales(
        self, positions: List[tuple]
    ) -> dict[tuple[str, str], PageScale]:
        return {
            (str(uid), str(annotation_type)): self._annotation_scale_for_key(
                str(uid), str(annotation_type)
            )
            for uid, annotation_type, _position in positions
        }

    def _capture_item_page_scales(self, items: list) -> dict[str, PageScale]:
        return {
            str(item.page_uid): self._page_scale_for_page_uid(item.page_uid)
            for item in items
        }

    def _capture_takeoff_spec_scales(
        self, specs: List[InsertTakeoffSpec]
    ) -> dict[str, PageScale]:
        return self._capture_item_page_scales(specs)

    def _capture_annotation_spec_scales(
        self, specs: List[InsertAnnotationSpec]
    ) -> dict[str, PageScale]:
        return self._capture_item_page_scales(specs)

    def _capture_saved_annotation_scales(
        self, annotations: list
    ) -> dict[str, PageScale]:
        return self._capture_item_page_scales(annotations)

    def _positions_for_current_takeoff_scales(
        self, positions: List[tuple], captured_scales: dict[str, PageScale]
    ) -> List[tuple]:
        scaled = []
        for uid, position in positions:
            uid_key = str(uid)
            scaled.append(
                (
                    uid,
                    rescale_position_between_page_scales(
                        position,
                        captured_scales.get(uid_key),
                        self._takeoff_scale_for_uid(uid_key),
                    ),
                )
            )
        return scaled

    def _takeoff_history_positions(self, positions, targets, scales):
        return self._positions_for_current_takeoff_scales(
            self._property_history_updates(positions, targets),
            {
                target.uid: scales[key]
                for key, target in targets.items()
                if key in scales
            },
        )

    def _positions_for_current_annotation_scales(
        self,
        positions: List[tuple],
        captured_scales: dict[tuple[str, str], PageScale],
    ) -> List[tuple]:
        scaled = []
        for uid, annotation_type, position in positions:
            key = (str(uid), str(annotation_type))
            scaled.append(
                (
                    uid,
                    annotation_type,
                    rescale_annotation_position_between_page_scales(
                        annotation_type,
                        position,
                        captured_scales.get(key),
                        self._annotation_scale_for_key(*key),
                    ),
                )
            )
        return scaled

    def _takeoff_specs_for_current_scales(
        self,
        specs: List[InsertTakeoffSpec],
        captured_scales: dict[str, PageScale],
    ) -> List[InsertTakeoffSpec]:
        return [
            replace(
                spec,
                position=rescale_position_between_page_scales(
                    spec.position,
                    captured_scales.get(str(spec.page_uid)),
                    self._page_scale_for_page_uid(spec.page_uid),
                ),
            )
            for spec in specs
        ]

    def _annotation_specs_for_current_scales(
        self,
        specs: List[InsertAnnotationSpec],
        captured_scales: dict[str, PageScale],
    ) -> List[InsertAnnotationSpec]:
        return [
            replace(
                spec,
                position=rescale_annotation_position_between_page_scales(
                    spec.annotation_type,
                    spec.position,
                    captured_scales.get(str(spec.page_uid)),
                    self._page_scale_for_page_uid(spec.page_uid),
                ),
            )
            for spec in specs
        ]

    def _saved_annotations_for_current_scales(
        self,
        annotations: list,
        captured_scales: dict[str, PageScale],
    ) -> list:
        return [
            replace(
                annotation,
                position=rescale_annotation_position_between_page_scales(
                    annotation.annotation_type,
                    annotation.position,
                    captured_scales.get(str(annotation.page_uid)),
                    self._page_scale_for_page_uid(annotation.page_uid),
                ),
            )
            for annotation in annotations
        ]

    def _delete_takeoffs_fast(self, db_path: str, takeoff_uids: List[str]) -> bool:
        if not takeoff_uids:
            return True
        condition_uids = self._data_svc.get_condition_uids_for_takeoffs(takeoff_uids)
        if not self._write_svc.delete_takeoffs(
            db_path, takeoff_uids, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.remove_takeoffs(takeoff_uids)
        self._publish_takeoffs_changed_for_pages(
            page_uids, list(takeoff_uids), condition_uids=condition_uids
        )
        return True

    def _insert_takeoffs_fast(
        self, bid_ref, specs: List[InsertTakeoffSpec]
    ) -> List[str]:
        new_uids = self._write_svc.insert_takeoffs(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            publish_database_refreshed_after_write=False,
        )
        if not new_uids:
            return []
        self._add_inserted_takeoffs_to_model(new_uids, specs)
        page_uids = []
        for spec in specs:
            if spec.page_uid not in page_uids:
                page_uids.append(spec.page_uid)
        self._publish_takeoffs_changed_for_pages(page_uids, list(new_uids))
        return new_uids

    def _same_bid_takeoff_extras_allow_fast_refresh(self, extras: dict) -> bool:
        return set(extras).issubset(_SAME_BID_FAST_TAKEOFF_EXTRA_COLUMNS)

    def _takeoff_specs_allow_fast_refresh(self, specs: List[InsertTakeoffSpec]) -> bool:
        return all(
            self._same_bid_takeoff_extras_allow_fast_refresh(spec.raw_extras)
            for spec in specs
        )

    def _default_takeoff_label_extras(self) -> dict:
        config = self._ui_state.config_model.snapshot()
        area = resolve_font_definition(config.default_area_label_font)
        style = resolve_font_definition(config.default_style_label_font)
        return {
            "FontName": area.family,
            "FontColor": hex_color_to_int(config.default_area_label_color),
            "FontSize": area.point_size,
            "FontBold": area.weight == 700,
            "FontItalic": area.italic,
            "FontUnderline": area.underline,
            "NameFontName": style.family,
            "NameFontColor": hex_color_to_int(config.default_style_label_color),
            "NameFontSize": style.point_size,
            "NameFontBold": style.weight == 700,
            "NameFontItalic": style.italic,
            "NameFontUnderline": style.underline,
        }

    def _takeoffs_allow_fast_delete(
        self, takeoffs: List[Takeoff], saved_takeoff_extras: dict
    ) -> bool:
        deleting_uids = {str(takeoff.uid) for takeoff in takeoffs}
        for takeoff in takeoffs:
            parent_uid = str(takeoff.parent_uid or "0")
            if parent_uid not in ("0", "") and parent_uid in deleting_uids:
                return False
            extras = saved_takeoff_extras.get(takeoff.uid, {})
            if not self._same_bid_takeoff_extras_allow_fast_refresh(extras):
                return False
        return True

    def on_assign_to_area(self, uids: list) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        takeoffs = [self._command_takeoff(uid) for uid in takeoff_uids]
        page_uids = tuple(
            dict.fromkeys(
                str(takeoff.page_uid)
                for takeoff in takeoffs
                if takeoff is not None and takeoff.page_uid
            )
        )
        old_updates = [
            (str(takeoff.uid), str(takeoff.area_uid or ""))
            for takeoff in takeoffs
            if takeoff is not None
        ]
        new_updates = [(uid, area_uid) for uid in takeoff_uids]
        dependencies = tuple(
            sorted(
                {
                    ResourceRef("area", str(value), int(bid_ref.bid_uid))
                    for value in {
                        area_uid,
                        *(
                            takeoff.area_uid
                            for takeoff in takeoffs
                            if takeoff is not None
                        ),
                    }
                    if value
                }
            )
        )
        if self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_properties(
                bid_ref,
                "takeoff_area",
                new_updates,
                old_updates=old_updates,
                plan_uids=set(takeoff_uids),
                takeoff_uids=set(takeoff_uids),
                page_uids=page_uids,
                dependency_resources=dependencies,
            )
            return
        if not self._execute_local_plan_properties(
            bid_ref,
            "takeoff_area",
            new_updates,
            dependency_resources=dependencies,
        ):
            return
        if old_updates:
            self._push_local_property_history(
                bid_ref, "takeoff_area", old_updates, new_updates, dependencies
            )

    def on_reassign_condition(self, uids: list, condition_uid: str) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = []
        takeoffs = []
        for uid in dict.fromkeys(str(uid) for uid in uids):
            takeoff = self._command_takeoff(uid)
            if takeoff is None:
                continue
            takeoff_uids.append(uid)
            takeoffs.append(takeoff)
        all_takeoffs = self._data_svc.get_all_takeoffs()
        conditions = self._data_svc.get_bid_conditions()
        descendants = expand_takeoff_uids_with_descendants(
            (
                takeoff
                for takeoff in all_takeoffs
                if (condition := conditions.get(takeoff.condition_uid)) is not None
                and condition.is_area
            ),
            takeoff_uids,
        ) - set(takeoff_uids)
        for takeoff in all_takeoffs:
            if str(takeoff.uid) in descendants:
                takeoff_uids.append(str(takeoff.uid))
                takeoffs.append(takeoff)
        if (
            not db_path
            or not takeoff_uids
            or not takeoffs_can_reassign_to_condition(
                takeoffs, conditions, str(condition_uid)
            )
        ):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        page_uids = tuple(
            dict.fromkeys(
                str(takeoff.page_uid) for takeoff in takeoffs if takeoff.page_uid
            )
        )
        old_updates = [
            (str(takeoff.uid), str(takeoff.condition_uid)) for takeoff in takeoffs
        ]
        new_updates = [(uid, str(condition_uid)) for uid in takeoff_uids]
        condition_dependencies = tuple(
            sorted(
                {
                    self._condition_resource(bid_ref, value)
                    for value in {
                        str(condition_uid),
                        *(str(takeoff.condition_uid) for takeoff in takeoffs),
                    }
                    if value
                }
            )
        )
        if self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_properties(
                bid_ref,
                "takeoff_condition",
                new_updates,
                old_updates=old_updates,
                plan_uids=set(takeoff_uids),
                takeoff_uids=set(takeoff_uids),
                page_uids=page_uids,
                dependency_resources=condition_dependencies,
            )
            return
        if not self._execute_local_plan_properties(
            bid_ref,
            "takeoff_condition",
            new_updates,
            dependency_resources=condition_dependencies,
        ):
            return
        self.record_local_condition_reassignment(bid_ref, old_updates, new_updates)

    def can_reassign_takeoffs(self, uids: set[str]) -> bool:
        return bool(
            self._is_allowed(Feature.EDIT_PLAN_ITEMS)
            and not uids.intersection(self._plan_view.get_pending_mutation_uids())
            and all(self._command_takeoff(uid) is not None for uid in uids)
        )

    def record_local_condition_reassignment(
        self, bid_ref, old_updates, new_updates
    ) -> None:
        dependencies = tuple(
            sorted(
                {
                    self._condition_resource(bid_ref, str(condition_uid))
                    for _uid, condition_uid in (*old_updates, *new_updates)
                }
            )
        )
        if old_updates:
            self._push_local_property_history(
                bid_ref, "takeoff_condition", old_updates, new_updates, dependencies
            )

    def on_set_negative(self, uids: list, is_negative: bool) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        takeoffs = [self._command_takeoff(uid) for uid in takeoff_uids]
        page_uids = tuple(
            dict.fromkeys(
                str(takeoff.page_uid)
                for takeoff in takeoffs
                if takeoff is not None and takeoff.page_uid
            )
        )
        old_updates = [
            (str(takeoff.uid), bool(takeoff.is_negative))
            for takeoff in takeoffs
            if takeoff is not None
        ]
        new_updates = [(uid, bool(is_negative)) for uid in takeoff_uids]
        if self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_properties(
                bid_ref,
                "takeoff_negative",
                new_updates,
                old_updates=old_updates,
                plan_uids=set(takeoff_uids),
                takeoff_uids=set(takeoff_uids),
                page_uids=page_uids,
            )
            return
        if not self._execute_local_plan_properties(
            bid_ref,
            "takeoff_negative",
            new_updates,
        ):
            return
        if old_updates:
            self._push_local_property_history(
                bid_ref, "takeoff_negative", old_updates, new_updates, ()
            )

    def on_set_curved(self, uids: list, make_curved: bool) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            return
        db_path = self._data_svc.get_current_bid_file_path()
        takeoff_uids = self._takeoff_uids_only(uids)
        if not db_path or not takeoff_uids:
            return
        cs = self._plan_view.get_coordinate_system()
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        new_updates = []
        old_updates = []
        page_uids = []
        for uid in takeoff_uids:
            takeoff = self._command_takeoff(uid)
            if not takeoff:
                continue
            pos = cs.parse_position(takeoff.position)
            if not pos or len(pos) < 4:
                continue
            old_updates.append((str(uid), list(pos), int(takeoff.curve)))
            if make_curved:
                x1, y1, x2, y2 = pos[:4]
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                next_position = [x1, y1, x2, y2, cx, cy, 0.0]
                next_curve = Takeoff.CURVE_ENABLED
            else:
                next_position = list(pos[:4])
                next_curve = Takeoff.CURVE_DISABLED
            new_updates.append((str(uid), next_position, next_curve))
            if takeoff.page_uid not in page_uids:
                page_uids.append(str(takeoff.page_uid))
        if self._uses_sql_mutation_queue(db_path):
            if new_updates:
                self._queue_sql_plan_properties(
                    bid_ref,
                    "takeoff_curve",
                    new_updates,
                    old_updates=old_updates,
                    plan_uids={str(update[0]) for update in new_updates},
                    takeoff_uids={str(update[0]) for update in new_updates},
                    page_uids=tuple(page_uids),
                )
            return
        if not new_updates or not self._execute_local_plan_properties(
            bid_ref,
            "takeoff_curve",
            new_updates,
        ):
            return
        self._push_local_property_history(
            bid_ref, "takeoff_curve", old_updates, new_updates, ()
        )

    def on_positions_flushed(self, takeoff_changes: list, ann_changes: list) -> None:
        if (takeoff_changes or ann_changes) and not self._is_allowed(
            Feature.EDIT_PLAN_ITEMS
        ):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or (not takeoff_changes and not ann_changes):
            return
        if any(
            is_queued_takeoff_preview_uid(str(uid))
            for uid, _old, _new in takeoff_changes
        ):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            return
        if self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_geometry(
                bid_ref,
                takeoff_changes=takeoff_changes,
                annotation_changes=ann_changes,
            )
            return
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        takeoff_scales = self._capture_takeoff_scales(t_old or t_new)
        annotation_scales = self._capture_annotation_scales(a_old or a_new)
        if not self._execute_local_plan_geometry(
            bid_ref,
            takeoff_positions=t_new,
            annotation_positions=a_new,
        ):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            return
        if not (t_old or a_old):
            return
        annotation_targets = self._annotation_history_targets(bid_ref, a_old or a_new)
        takeoff_targets = self._property_history_targets(
            bid_ref, "takeoff_geometry", t_old
        )

        def _undo_move():
            return self._execute_local_plan_geometry(
                bid_ref,
                takeoff_positions=self._takeoff_history_positions(
                    t_old, takeoff_targets, takeoff_scales
                ),
                annotation_positions=self._annotation_history_positions(
                    a_old,
                    annotation_targets,
                    annotation_scales,
                ),
            )

        def _redo_move():
            return self._execute_local_plan_geometry(
                bid_ref,
                takeoff_positions=self._takeoff_history_positions(
                    t_new, takeoff_targets, takeoff_scales
                ),
                annotation_positions=self._annotation_history_positions(
                    a_new,
                    annotation_targets,
                    annotation_scales,
                ),
            )

        self._undo_svc.push_local(
            _undo_move,
            _redo_move,
            takeoff_targets=tuple(takeoff_targets.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    def on_annotation_text_properties_flushed(self, changes: list) -> None:
        if not self._is_allowed(Feature.EDIT_ANNOTATION_TEXT):
            if changes:
                self._plan_view.restore_annotation_text_properties(changes)
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not changes:
            return
        new_updates = [
            (uid, ann_type, dict(new_props))
            for uid, ann_type, _old_props, new_props in changes
        ]
        bid_ref = self._ui_state.get_selected_bid_ref()
        if bid_ref and self._uses_sql_mutation_queue(db_path):
            identities = {
                (str(uid), str(annotation_type))
                for uid, annotation_type, _properties in new_updates
            }
            plan_uids = set(
                self._plan_view.find_annotation_keys_by_uid_type(identities)
            )
            annotations = [
                self._plan_view.get_annotation(uid) for uid in sorted(plan_uids)
            ]
            page_uids = tuple(
                dict.fromkeys(
                    str(annotation.page_uid)
                    for annotation in annotations
                    if annotation is not None and annotation.page_uid
                )
            )
            self._queue_sql_plan_properties(
                bid_ref,
                "annotation_text",
                new_updates,
                old_updates=[
                    (uid, ann_type, dict(old_props))
                    for uid, ann_type, old_props, _new_props in changes
                    if old_props is not None
                ],
                plan_uids=plan_uids,
                annotation_identities=identities,
                page_uids=page_uids,
                restore=lambda: self._plan_view.restore_annotation_text_properties(
                    changes
                ),
            )
            return
        success = self._save_annotation_text_properties_fast(db_path, new_updates)
        if not success:
            self._plan_view.restore_annotation_text_properties(changes)
            return
        old_updates = [
            (uid, ann_type, dict(old_props))
            for uid, ann_type, old_props, _new_props in changes
            if old_props
        ]
        if not old_updates:
            return

        def _undo_text_properties():
            return self._save_annotation_text_properties_fast(
                db_path, self._annotation_history_updates(old_updates, targets)
            )

        def _redo_text_properties():
            return self._save_annotation_text_properties_fast(
                db_path, self._annotation_history_updates(new_updates, targets)
            )

        targets = self._annotation_history_targets(bid_ref, old_updates)
        self._undo_svc.push_local(
            _undo_text_properties,
            _redo_text_properties,
            annotation_targets=tuple(targets.values()),
        )

    def on_annotation_styles_flushed(self, changes: list) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            if changes:
                self._plan_view.restore_annotation_styles(changes)
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not changes:
            return
        new_updates = [
            (uid, ann_type, dict(new_style))
            for uid, ann_type, _old_style, new_style in changes
        ]
        bid_ref = self._ui_state.get_selected_bid_ref()
        if bid_ref and self._uses_sql_mutation_queue(db_path):
            identities = {
                (str(uid), str(annotation_type))
                for uid, annotation_type, _properties in new_updates
            }
            plan_uids = set(
                self._plan_view.find_annotation_keys_by_uid_type(identities)
            )
            annotations = [
                self._plan_view.get_annotation(uid) for uid in sorted(plan_uids)
            ]
            page_uids = tuple(
                dict.fromkeys(
                    str(annotation.page_uid)
                    for annotation in annotations
                    if annotation is not None and annotation.page_uid
                )
            )
            self._queue_sql_plan_properties(
                bid_ref,
                "annotation_style",
                new_updates,
                old_updates=[
                    (uid, ann_type, dict(old_style))
                    for uid, ann_type, old_style, _new_style in changes
                    if old_style is not None
                ],
                plan_uids=plan_uids,
                annotation_identities=identities,
                page_uids=page_uids,
                restore=lambda: self._plan_view.restore_annotation_styles(changes),
            )
            return
        success = self._save_annotation_styles_fast(db_path, new_updates)
        if not success:
            self._plan_view.restore_annotation_styles(changes)
            return
        old_updates = [
            (uid, ann_type, dict(old_style))
            for uid, ann_type, old_style, _new_style in changes
            if old_style
        ]
        if not old_updates:
            return

        def _undo_styles():
            return self._save_annotation_styles_fast(
                db_path, self._annotation_history_updates(old_updates, targets)
            )

        def _redo_styles():
            return self._save_annotation_styles_fast(
                db_path, self._annotation_history_updates(new_updates, targets)
            )

        targets = self._annotation_history_targets(bid_ref, old_updates)
        self._undo_svc.push_local(
            _undo_styles, _redo_styles, annotation_targets=tuple(targets.values())
        )

    def on_rotations_flushed(self, rotation_changes: list) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            if rotation_changes:
                self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path or not rotation_changes:
            return
        if any(
            is_queued_takeoff_preview_uid(str(uid))
            for uid, _old, _new in rotation_changes
        ):
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if bid_ref and self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_geometry(
                bid_ref,
                rotation_changes=rotation_changes,
            )
            return
        new_rotations = [(uid, new_rot) for uid, _old, new_rot in rotation_changes]
        if not self._save_takeoff_rotations_fast(db_path, new_rotations):
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        r_old = [(uid, old) for uid, old, _ in rotation_changes if old is not None]
        r_new = [(uid, new) for uid, _, new in rotation_changes]
        if not r_old:
            return
        takeoff_targets = self._property_history_targets(
            bid_ref, "takeoff_rotation", r_old
        )

        def _undo_rotate():
            return self._save_takeoff_rotations_fast(
                db_path, self._property_history_updates(r_old, takeoff_targets)
            )

        def _redo_rotate():
            return self._save_takeoff_rotations_fast(
                db_path, self._property_history_updates(r_new, takeoff_targets)
            )

        self._undo_svc.push_local(
            _undo_rotate, _redo_rotate, takeoff_targets=tuple(takeoff_targets.values())
        )

    def on_group_rotation_flushed(
        self, takeoff_changes: list, ann_changes: list, rotation_changes: list
    ) -> None:
        if (
            takeoff_changes or ann_changes or rotation_changes
        ) and not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        db_path = self._data_svc.get_current_bid_file_path()
        if not db_path:
            return
        if any(
            is_queued_takeoff_preview_uid(str(uid))
            for uid, _old, _new in takeoff_changes
        ) or any(
            is_queued_takeoff_preview_uid(str(uid))
            for uid, _old, _new in rotation_changes
        ):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        if self._uses_sql_mutation_queue(db_path):
            self._queue_sql_plan_geometry(
                bid_ref,
                takeoff_changes=takeoff_changes,
                annotation_changes=ann_changes,
                rotation_changes=rotation_changes,
            )
            return
        t_new = [(uid, list(new)) for uid, _, new in takeoff_changes]
        r_new = [(uid, new) for uid, _, new in rotation_changes]
        t_old = [(uid, list(old)) for uid, old, _ in takeoff_changes if old]
        a_old = [(uid, t, list(old)) for uid, t, old, _ in ann_changes if old]
        a_new = [(uid, t, list(new)) for uid, t, _, new in ann_changes]
        r_old = [(uid, old) for uid, old, _ in rotation_changes if old is not None]
        takeoff_scales = self._capture_takeoff_scales(t_old or t_new)
        annotation_scales = self._capture_annotation_scales(a_old or a_new)
        if not self._execute_local_plan_geometry(
            bid_ref,
            takeoff_positions=t_new,
            takeoff_rotations=r_new,
            annotation_positions=a_new,
        ):
            self._plan_view.restore_flushed_positions(takeoff_changes, ann_changes)
            self._plan_view.restore_flushed_rotations(rotation_changes)
            return
        annotation_targets = self._annotation_history_targets(bid_ref, a_old or a_new)
        takeoff_targets = self._property_history_targets(
            bid_ref, "takeoff_geometry", t_old + r_old
        )

        def _undo_group():
            return self._execute_local_plan_geometry(
                bid_ref,
                takeoff_positions=self._takeoff_history_positions(
                    t_old, takeoff_targets, takeoff_scales
                ),
                takeoff_rotations=self._property_history_updates(
                    r_old, takeoff_targets
                ),
                annotation_positions=self._annotation_history_positions(
                    a_old, annotation_targets, annotation_scales
                ),
            )

        def _redo_group():
            return self._execute_local_plan_geometry(
                bid_ref,
                takeoff_positions=self._takeoff_history_positions(
                    t_new, takeoff_targets, takeoff_scales
                ),
                takeoff_rotations=self._property_history_updates(
                    r_new, takeoff_targets
                ),
                annotation_positions=self._annotation_history_positions(
                    a_new, annotation_targets, annotation_scales
                ),
            )

        if t_old or a_old or r_old:
            self._undo_svc.push_local(
                _undo_group,
                _redo_group,
                takeoff_targets=tuple(takeoff_targets.values()),
                annotation_targets=tuple(annotation_targets.values()),
            )

    def on_takeoff_created(
        self, condition_uid: str, position: list, page_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not condition_uid or not page_uid:
            return
        if not self._is_condition_placeable(condition_uid):
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        place_uids = self._ui_state.place_condition_uids
        target_uids = self._target_place_condition_uids(condition_uid, place_uids)
        label_extras = self._default_takeoff_label_extras()
        if len(target_uids) > 1:
            specs = [
                InsertTakeoffSpec(
                    condition_uid=cuid,
                    page_uid=page_uid,
                    area_uid=area_uid,
                    position=position,
                    raw_extras=dict(label_extras),
                )
                for cuid in target_uids
            ]
        else:
            condition = self._data_svc.get_bid_conditions().get(condition_uid)
            curve = Takeoff.CURVE_DISABLED
            if (
                condition is not None
                and condition.is_linear
                and condition.is_curved_segment
                and len(position) >= 6
            ):
                curve = Takeoff.CURVE_ENABLED
            specs = [
                InsertTakeoffSpec(
                    condition_uid=condition_uid,
                    page_uid=page_uid,
                    area_uid=area_uid,
                    position=position,
                    curve=curve,
                    raw_extras=label_extras,
                )
            ]
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_takeoff_placement(bid_ref, specs)
            return
        self._insert_takeoffs_with_undo(bid_ref, specs, fast_refresh=True)

    def _queue_takeoff_placement(self, bid_ref, specs: List[InsertTakeoffSpec]) -> None:
        operation_id = str(uuid.uuid4())
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        pending_uids = tuple(
            queued_takeoff_preview_uid(operation_id, index)
            for index in range(len(specs))
        )
        pending = _PendingTakeoffPlacement(
            database_id=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            pending_uids=pending_uids,
            specs=tuple(specs),
            page_identities=self._capture_page_identities(
                tuple(self._takeoff_spec_page_uids(specs))
            ),
            runtime_generation=None,
            history_token=history_token,
        )
        self._pending_takeoff_placements[operation_id] = pending
        handler_reference = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_reference()
            if handler is not None:
                handler._complete_queued_takeoff_placement(result)

        try:
            self._add_inserted_takeoffs_to_model(
                list(pending_uids), specs, transient=True
            )
            self._set_plan_items_pending(
                bid_ref.file_path,
                set(pending_uids),
                set(pending_uids),
                True,
            )
            self._publish_takeoffs_changed_for_pages(
                self._takeoff_spec_page_uids(specs),
                list(pending_uids),
                [str(spec.condition_uid) for spec in specs],
            )
            runtime_generation = self._write_svc.queue_takeoff_placement(
                bid_ref.file_path,
                bid_ref.bid_uid,
                specs,
                operation_id,
                complete,
            )
        except Exception:
            self._pending_takeoff_placements.pop(operation_id, None)
            self._undo_svc.finish_forward_mutation(history_token)
            self._data_svc.remove_takeoffs(pending_uids)
            try:
                self._set_plan_items_pending(
                    bid_ref.file_path,
                    set(pending_uids),
                    set(pending_uids),
                    False,
                )
            except Exception:
                logger.exception(
                    "Failed to publish queued-placement pending-state rollback"
                )
            raise
        if operation_id in self._pending_takeoff_placements:
            self._pending_takeoff_placements[operation_id] = replace(
                self._pending_takeoff_placements[operation_id],
                runtime_generation=runtime_generation,
            )

    def _complete_queued_takeoff_placement(self, result: QueuedMutationResult) -> None:
        if self._sql_completion_was_applied(result):
            return
        pending = self._pending_takeoff_placements.get(result.operation_id)
        if pending is None:
            return
        if result.outcome_status in {
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        }:
            return
        completion_matches = (
            result.database_id == pending.database_id
            and result.runtime_generation == pending.runtime_generation
        )
        if not completion_matches:
            return
        self._pending_takeoff_placements.pop(result.operation_id, None)
        self._data_svc.remove_takeoffs(pending.pending_uids)
        self._set_plan_items_pending(
            pending.database_id,
            set(pending.pending_uids),
            set(pending.pending_uids),
            False,
        )
        page_uids = self._takeoff_spec_page_uids(list(pending.specs))
        condition_uids = [str(spec.condition_uid) for spec in pending.specs]
        if result.outcome_status != MutationOutcomeStatus.COMMITTED:
            if (
                result.outcome_status == MutationOutcomeStatus.CANCELLED_BEFORE_START
                and pending.deleted_pending_uids == frozenset(pending.pending_uids)
            ):
                self._undo_svc.finish_forward_mutation(pending.history_token)
                return
            self._publish_takeoffs_changed_for_pages(
                page_uids,
                list(pending.pending_uids),
                condition_uids,
            )
            logger.warning(
                "SQL takeoff placement failed: %s",
                result.message or "The database rejected the placement.",
            )
            self._undo_svc.finish_forward_mutation(pending.history_token)
            return
        new_uids = list(result.created_resource_ids)
        if len(new_uids) != len(pending.specs):
            self._publish_takeoffs_changed_for_pages(
                page_uids,
                list(pending.pending_uids),
                condition_uids,
            )
            logger.error(
                "SQL takeoff placement returned %d identities for %d takeoffs.",
                len(new_uids),
                len(pending.specs),
            )
            self._undo_svc.finish_forward_mutation(pending.history_token)
            return
        deleted_created_uids = [
            uid
            for uid, pending_uid in zip(new_uids, pending.pending_uids)
            if pending_uid in pending.deleted_pending_uids
        ]
        deleted_specs = [
            spec
            for spec, pending_uid in zip(pending.specs, pending.pending_uids)
            if pending_uid in pending.deleted_pending_uids
        ]
        if deleted_created_uids:
            self._queue_cancelled_takeoff_placement_delete(
                pending,
                deleted_created_uids,
                deleted_specs,
            )
        retained = [
            (uid, spec)
            for uid, spec, pending_uid in zip(
                new_uids,
                pending.specs,
                pending.pending_uids,
            )
            if pending_uid not in pending.deleted_pending_uids
        ]
        bid_ref = self._ui_state.get_selected_bid_ref()
        if (
            bid_ref is None
            or bid_ref.file_path != pending.database_id
            or bid_ref.bid_uid != pending.bid_uid
        ):
            self._mark_sql_completion_applied(result)
            self._undo_svc.finish_forward_mutation(pending.history_token)
            return
        if not self._page_identities_are_current(
            tuple(page_uids),
            pending.page_identities,
        ):
            self._mark_sql_completion_applied(result)
            self._undo_svc.finish_forward_mutation(pending.history_token)
            return
        missing_uids = [
            uid for uid in new_uids if self._data_svc.get_takeoff(uid) is None
        ]
        if missing_uids:
            self._undo_svc.finish_forward_mutation(pending.history_token)
            raise RuntimeError(
                "Committed takeoff placement completed before authoritative "
                "takeoff projection"
            )
        current_page_uid = str(
            self._plan_view.current_page_uid or self._ui_state.active_page_uid or ""
        )
        selected_uids = {
            uid for uid, spec in retained if str(spec.page_uid) == current_page_uid
        }
        if selected_uids:
            self._plan_view.set_selected_uids(selected_uids)
        if retained and self._undo_svc.is_forward_mutation_current(
            pending.history_token
        ):
            self._push_sql_takeoff_placement_history(
                bid_ref,
                [spec for _uid, spec in retained],
                [uid for uid, _spec in retained],
            )
            self._undo_svc.bind_latest_history_to_forward_mutation(
                pending.history_token
            )
        self._mark_sql_completion_applied(result)
        self._undo_svc.finish_forward_mutation(pending.history_token)

    def _request_pending_takeoff_deletions(self, uids: list) -> list:
        requested = {str(uid) for uid in uids}
        consumed: set[str] = set()
        for operation_id, pending in tuple(self._pending_takeoff_placements.items()):
            matched = requested.intersection(pending.pending_uids)
            if not matched:
                continue
            consumed.update(matched)
            newly_deleted = matched.difference(pending.deleted_pending_uids)
            if not newly_deleted:
                continue
            deleted = pending.deleted_pending_uids.union(newly_deleted)
            self._pending_takeoff_placements[operation_id] = replace(
                pending,
                deleted_pending_uids=frozenset(deleted),
            )
            self._data_svc.remove_takeoffs(newly_deleted)
            self._set_plan_items_pending(
                pending.database_id,
                set(newly_deleted),
                set(newly_deleted),
                False,
            )
            matched_specs = [
                spec
                for pending_uid, spec in zip(pending.pending_uids, pending.specs)
                if pending_uid in newly_deleted
            ]
            self._publish_takeoffs_changed_for_pages(
                self._takeoff_spec_page_uids(matched_specs),
                sorted(newly_deleted),
                [str(spec.condition_uid) for spec in matched_specs],
            )
            if deleted == set(pending.pending_uids):
                self._write_svc.cancel_queued_sql_mutation(
                    pending.database_id,
                    operation_id,
                )
        return [uid for uid in uids if str(uid) not in consumed]

    def _queue_cancelled_takeoff_placement_delete(
        self,
        pending: _PendingTakeoffPlacement,
        takeoff_uids: list[str],
        specs: list[InsertTakeoffSpec],
    ) -> None:
        takeoff_uid_set = set(takeoff_uids)
        page_uids = tuple(self._takeoff_spec_page_uids(specs))
        dependencies = tuple(
            sorted(
                {
                    ResourceRef(
                        "condition",
                        str(spec.condition_uid),
                        int(pending.bid_uid),
                    )
                    for spec in specs
                }
            )
        )
        current_bid = self._ui_state.get_selected_bid_ref()
        project_pending_state = bool(
            current_bid is not None
            and current_bid.file_path == pending.database_id
            and current_bid.bid_uid == pending.bid_uid
        )
        if project_pending_state:
            self._set_plan_items_pending(
                pending.database_id,
                takeoff_uid_set,
                takeoff_uid_set,
                True,
            )
        handler_ref = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None or handler._sql_completion_was_applied(result):
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            if project_pending_state:
                handler._set_plan_items_pending(
                    pending.database_id,
                    takeoff_uid_set,
                    takeoff_uid_set,
                    False,
                )
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                handler._mark_sql_completion_applied(result)
                return
            current_bid = handler._ui_state.get_selected_bid_ref()
            if (
                current_bid is not None
                and current_bid.file_path == pending.database_id
                and current_bid.bid_uid == pending.bid_uid
            ):
                handler._restore_plan_selection_if_current(
                    current_bid,
                    page_uids,
                    takeoff_uid_set,
                )

        self._write_svc.queue_plan_items_delete(
            pending.database_id,
            pending.bid_uid,
            takeoff_uids,
            [],
            complete,
            page_uids=page_uids,
            dependency_resources=dependencies,
        )

    def _push_sql_takeoff_placement_history(
        self,
        bid_ref,
        specs: List[InsertTakeoffSpec],
        created_uids: List[str],
    ) -> None:
        targets = tuple(
            TakeoffHistoryTarget(bid_ref, str(spec.page_uid), uid)
            for uid, spec in zip(created_uids, specs)
        )
        parents = self._history_parent_targets(bid_ref, created_uids, specs)
        suspended_targets = ()
        page_uids = tuple(self._takeoff_spec_page_uids(specs))

        def undo_submit(done) -> None:
            def deleted(result):
                nonlocal suspended_targets
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    suspended_targets = self._undo_svc.suspend_deleted_takeoffs(
                        bid_ref, targets
                    )
                done(result)

            self._write_svc.queue_plan_items_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [target.uid for target in targets],
                [],
                deleted,
                page_uids=page_uids,
            )

        def redo_submit(done) -> None:
            operation_id = str(uuid.uuid4())

            def completed(result: QueuedMutationResult) -> None:
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    self._undo_svc.rebind_restored_takeoffs(
                        bid_ref,
                        {
                            (target.page_uid, target.uid): uid
                            for target, uid in zip(targets, result.created_resource_ids)
                        },
                        suspended_targets,
                    )
                done(result)

            self._write_svc.queue_takeoff_placement(
                bid_ref.file_path,
                bid_ref.bid_uid,
                self._specs_with_history_parents(specs, parents),
                operation_id,
                completed,
            )

        self._undo_svc.push_for_bid(
            bid_ref,
            undo_submit,
            redo_submit,
            takeoff_targets=(*targets, *parents.values()),
        )

    def hide_pending_takeoff_placement_previews(self) -> None:
        self._remove_pending_takeoff_placement_previews(
            tuple(self._pending_takeoff_placements.values())
        )

    def invalidate_pending_takeoff_placements(self) -> None:
        pending = tuple(self._pending_takeoff_placements.values())
        self._pending_takeoff_placements.clear()
        for placement in pending:
            self._undo_svc.finish_forward_mutation(placement.history_token)
        self._remove_pending_takeoff_placement_previews(pending)

    def _remove_pending_takeoff_placement_previews(
        self, pending: tuple[_PendingTakeoffPlacement, ...]
    ) -> None:
        current_bid = self._ui_state.get_selected_bid_ref()
        current_pending = tuple(
            placement
            for placement in pending
            if current_bid is None
            or (
                placement.database_id == current_bid.file_path
                and placement.bid_uid == current_bid.bid_uid
            )
        )
        removed_uids = [
            uid
            for placement in current_pending
            for uid in placement.pending_uids
            if (
                self._data_svc.get_takeoff(uid) is not None
                or uid
                in self._pending_plan_takeoff_uids_by_database.get(
                    placement.database_id, set()
                )
            )
        ]
        if not removed_uids:
            return
        self._data_svc.remove_takeoffs(removed_uids)
        self._set_plan_items_pending(
            current_bid.file_path if current_bid is not None else "",
            set(removed_uids),
            set(removed_uids),
            False,
        )
        page_uids = self._takeoff_spec_page_uids(
            [spec for placement in current_pending for spec in placement.specs]
        )
        condition_uids = list(
            dict.fromkeys(
                str(spec.condition_uid)
                for placement in current_pending
                for spec in placement.specs
            )
        )
        self._publish_takeoffs_changed_for_pages(
            page_uids, removed_uids, condition_uids
        )

    @staticmethod
    def _takeoff_spec_page_uids(specs: List[InsertTakeoffSpec]) -> List[str]:
        return list(dict.fromkeys(str(spec.page_uid) for spec in specs))

    def on_annotation_created(
        self, annotation_type: str, position: list, page_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_ANNOTATIONS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not annotation_type or not page_uid:
            return
        spec = build_placed_annotation_spec(annotation_type, page_uid, list(position))
        if spec is None:
            return
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_sql_annotation_insert(bid_ref, [spec])
            return
        self._insert_annotations_with_undo(bid_ref, [spec])

    def on_text_annotation_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._is_allowed(Feature.PLACE_ANNOTATIONS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not page_uid or not str(properties.get("Text", "")).strip():
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_TEXT, page_uid, list(position)
        )
        if spec is None:
            return
        spec.properties = dict(properties)
        font_color = spec.properties.get("FontColor")
        if isinstance(font_color, int):
            spec.color = int_color_to_hex(font_color)
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_sql_annotation_insert(
                bid_ref,
                [spec],
                lambda: self._plan_view.activate_annotation_placement(
                    ANNOTATION_TYPE_TEXT
                ),
            )
            return
        new_uids = self._insert_annotations_with_undo(bid_ref, [spec])
        if new_uids:
            self._plan_view.activate_annotation_placement(ANNOTATION_TYPE_TEXT)

    def on_named_view_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._is_allowed(Feature.PLACE_ANNOTATIONS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        name = str(properties.get("Text", "") or "").strip()
        if not bid_ref or not page_uid or not name:
            return
        if not self._validate_named_view_name(name, None):
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_NAMED_VIEW, page_uid, list(position)
        )
        if spec is None:
            return
        spec.properties = {"Text": name}
        color = properties.get("Color")
        if isinstance(color, str) and color:
            spec.color = color
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_sql_annotation_insert(
                bid_ref,
                [spec],
                lambda: self._plan_view.activate_annotation_placement(
                    ANNOTATION_TYPE_NAMED_VIEW
                ),
            )
            return
        new_uids = self._insert_annotations_with_undo(bid_ref, [spec])
        if new_uids:
            self._plan_view.activate_annotation_placement(ANNOTATION_TYPE_NAMED_VIEW)

    def on_hotlink_placement_requested(self, position: list, page_uid: str) -> None:
        if not self._is_allowed(Feature.PLACE_ANNOTATIONS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not page_uid or len(position) < 2:
            return
        page_identities = self._capture_page_identities((str(page_uid),))
        self._plan_view.cancel_place_mode()
        dialog = SelectNamedViewDialog(
            self._collect_named_view_choices(),
            parent=self._plan_view,
        )
        try:
            result_code = dialog.exec()
            if (
                not isValid(dialog)
                or not isValid(self._plan_view)
                or not self._plan_context_is_current(
                    bid_ref, (str(page_uid),), page_identities
                )
                or not self._is_allowed(Feature.PLACE_ANNOTATIONS)
            ):
                return
            if result_code != QtWidgets.QDialog.DialogCode.Accepted:
                return
            result = dialog.result_data()
        finally:
            delete_later_if_valid(dialog)
        if result.create_new:
            self._plan_view.activate_annotation_placement(ANNOTATION_TYPE_NAMED_VIEW)
            return
        if not result.named_view_uid:
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_HOTLINK, page_uid, list(position[:2])
        )
        if spec is None:
            return
        spec.properties = {"BidPageViewUID": result.named_view_uid}
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_sql_annotation_insert(
                bid_ref,
                [spec],
                lambda: self._plan_view.activate_annotation_placement(
                    ANNOTATION_TYPE_HOTLINK
                ),
            )
            return
        new_uids = self._insert_annotations_with_undo(bid_ref, [spec])
        if new_uids:
            self._plan_view.activate_annotation_placement(ANNOTATION_TYPE_HOTLINK)

    def _validate_named_view_name(
        self, name: str, exclude_uid: Optional[str] = None
    ) -> bool:
        if named_view_name_exists(
            self._collect_named_view_choices(),
            name,
            exclude_uid=exclude_uid,
        ):
            show_duplicate_named_view_name(self._plan_view)
            return False
        return True

    def _collect_named_view_choices(self) -> List[tuple[str, str, str, str]]:
        choices: List[tuple[str, str, str, str]] = []
        for annotation in self._data_svc.get_all_annotations():
            named_view = build_named_view_from_annotation(annotation)
            if named_view is None:
                continue
            page_name = self._data_svc.get_page_name(named_view.bid_page_uid)
            choices.append(
                (
                    named_view.uid,
                    named_view.bid_page_uid,
                    page_name,
                    named_view.name or named_view.uid,
                )
            )
        return choices

    def on_hole_created(
        self, condition_uid: str, position: list, page_uid: str, parent_uid: str
    ) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not condition_uid or not page_uid or not parent_uid:
            return
        if not self._is_condition_placeable(condition_uid):
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        spec = InsertTakeoffSpec(
            condition_uid=condition_uid,
            page_uid=page_uid,
            area_uid=area_uid,
            position=position,
            parent_uid=parent_uid,
            raw_extras=self._default_takeoff_label_extras(),
        )
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_takeoff_placement(bid_ref, [spec])
            return
        self._insert_takeoffs_with_undo(bid_ref, [spec], fast_refresh=True)

    def _queue_sql_annotation_insert(
        self,
        bid_ref,
        specs: List[InsertAnnotationSpec],
        after_success=None,
    ) -> None:
        self._annotation_writes.apply_default_annotation_layer(bid_ref, specs)
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        source_uids = tuple(
            annotation_resource_id(spec.annotation_type, str(uuid.uuid4()))
            for spec in specs
        )
        payload = PlanItemsPastePayload(
            source_bid_uid=str(bid_ref.bid_uid),
            destination_bid_uid=str(bid_ref.bid_uid),
            annotation_source_uids=source_uids,
            annotation_specs=tuple(specs),
        )
        dependencies = {
            *(
                self._layer_resource(bid_ref, spec.layer_uid)
                for spec in specs
                if spec.layer_uid
            ),
            *(
                ResourceRef(
                    "annotation",
                    f"namedview/{str(spec.properties.get('BidPageViewUID'))}",
                    int(bid_ref.bid_uid),
                )
                for spec in specs
                if spec.properties.get("BidPageViewUID")
            ),
        }
        originating_page_uids = tuple(
            dict.fromkeys(str(spec.page_uid) for spec in specs if spec.page_uid)
        )
        page_identities = self._capture_page_identities(originating_page_uids)
        selection_revision = self._plan_view.begin_deferred_selection()
        tool_revision = self._plan_view.tool_revision
        handler_ref = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None:
                return
            if handler._sql_completion_was_applied(result):
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                handler._undo_svc.finish_forward_mutation(history_token)
                return
            _takeoff_map, annotation_map = handler._created_uid_maps(result)
            uid_type_set = {
                (annotation_map[source_uid], spec.annotation_type)
                for source_uid, spec in zip(source_uids, specs)
                if source_uid in annotation_map
            }
            keys = handler._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
            originating_page_is_current = handler._plan_context_is_current(
                bid_ref,
                originating_page_uids,
                page_identities,
            )
            selection_is_current = (
                handler._plan_view.selection_revision == selection_revision
            )
            if originating_page_is_current and selection_is_current and keys:
                handler._plan_view.set_selected_uids(keys)
            if handler._undo_svc.is_forward_mutation_current(
                history_token
            ) and handler._page_identities_are_current(
                originating_page_uids, page_identities
            ):
                handler._push_sql_paste_history(
                    bid_ref,
                    payload,
                    {},
                    annotation_map,
                )
                handler._undo_svc.bind_latest_history_to_forward_mutation(history_token)
            if (
                after_success is not None
                and originating_page_is_current
                and selection_is_current
                and handler._plan_view.tool_revision == tool_revision
                and handler._is_allowed(Feature.PLACE_ANNOTATIONS)
            ):
                after_success()
            handler._mark_sql_completion_applied(result)
            handler._undo_svc.finish_forward_mutation(history_token)

        try:
            self._write_svc.queue_plan_items_paste(
                bid_ref.file_path,
                payload,
                complete,
                dependency_resources=tuple(sorted(dependencies)),
            )
        except Exception:
            self._undo_svc.finish_forward_mutation(history_token)
            raise

    def _insert_annotations_with_undo(
        self, bid_ref, specs: List[InsertAnnotationSpec]
    ) -> List[str]:
        new_uids = self._insert_annotations_fast(bid_ref, specs)
        if not new_uids:
            return []
        current_specs = specs[: len(new_uids)]
        uid_type_set = {
            (uid, current_specs[i].annotation_type) for i, uid in enumerate(new_uids)
        }
        keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self._plan_view.set_selected_uids(keys)
        targets = self._annotation_history_targets(
            bid_ref,
            [(uid, spec.annotation_type) for uid, spec in zip(new_uids, current_specs)],
        )
        suspended = ()
        current_specs_scales = self._capture_annotation_spec_scales(current_specs)
        selection_owner_is_current = self._history_selection_owner(
            bid_ref,
            tuple(spec.page_uid for spec in current_specs),
        )

        def _undo_insert():
            nonlocal suspended
            success = self._delete_annotations_fast(
                bid_ref.file_path,
                [uid for uid, _kind in self._annotation_history_keys(targets)],
                current_specs,
            )
            if success:
                suspended = self._undo_svc.suspend_deleted_annotations(
                    bid_ref, tuple(targets.values())
                )
                if selection_owner_is_current():
                    self._plan_view.clear_selection()
            return success

        def _redo_insert():
            redone_specs = self._annotation_specs_for_current_scales(
                current_specs, current_specs_scales
            )
            redone_uids = self._insert_annotations_fast(bid_ref, redone_specs)
            if len(redone_uids) != len(current_specs):
                return False
            self._undo_svc.rebind_restored_annotations(
                bid_ref,
                {
                    target.identity: uid
                    for target, uid in zip(targets.values(), redone_uids)
                },
                suspended,
            )
            if redone_uids and selection_owner_is_current():
                uid_type_set = {
                    (uid, current_specs[i].annotation_type)
                    for i, uid in enumerate(redone_uids)
                }
                keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
                self._plan_view.set_selected_uids(keys)
            return True

        self._undo_svc.push_local(
            _undo_insert, _redo_insert, annotation_targets=tuple(targets.values())
        )
        return list(new_uids)

    def _insert_annotations_fast(
        self,
        bid_ref,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        new_uids = self._annotation_writes.insert_annotations(
            bid_ref, specs, ref_remap=ref_remap
        )
        if specs and not new_uids:
            logger.warning(
                "Annotation insertion failed: database=%s bid=%s count=%s first_targets=%s",
                bid_ref.file_path,
                bid_ref.bid_uid,
                len(specs),
                [
                    (spec.page_uid, spec.annotation_type, spec.layer_uid)
                    for spec in specs[:10]
                ],
            )
            show_warning(
                self._plan_view,
                "Database Write",
                "The annotations could not be saved. Refresh the Bid and verify "
                "its Page and Layer settings before trying again. See the log for details.",
            )
        return new_uids

    def _delete_annotations_fast(
        self, db_path: str, uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> bool:
        return self._annotation_writes.delete_annotations(db_path, uids, specs)

    def _delete_saved_annotations_fast(
        self, db_path: str, saved_annotations: list
    ) -> bool:
        return self._annotation_writes.delete_saved_annotations(
            db_path, saved_annotations
        )

    def _insert_saved_annotations_fast(self, bid_ref, saved_annotations: list) -> list:
        return self._annotation_writes.insert_saved_annotations(
            bid_ref,
            saved_annotations,
            execute_paste=self._write_svc.execute_plan_items_paste_local,
        )

    @staticmethod
    def _unique_ordered(values) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def on_paste_backouts_placed(self, placements: list, source_bid_uid) -> None:
        if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not placements:
            return
        uses_sql_queue = self._uses_sql_mutation_queue(bid_ref.file_path)
        area_uid = self._page_settings_bar.get_current_area_uid()
        specs = [
            InsertTakeoffSpec(
                condition_uid=str(p["condition_uid"]),
                page_uid=p["page_uid"],
                area_uid=area_uid,
                position=p["position"],
                parent_uid=p["parent_uid"],
                curve=p.get("curve", -1),
                rotation=p["rotation"],
                is_negative=p["is_negative"],
                raw_extras=dict(p["extras"]),
                source_bid_uid=source_bid_uid,
            )
            for p in placements
        ]
        source_bid_key = str(source_bid_uid or bid_ref.bid_uid)
        payload = PlanItemsPastePayload(
            source_bid_uid=source_bid_key,
            destination_bid_uid=str(bid_ref.bid_uid),
            takeoff_source_uids=tuple(
                str(p.get("source_uid") or uuid.uuid4()) for p in placements
            ),
            takeoff_specs=tuple(specs),
            takeoff_external_parent_sources=tuple(
                str(p["source_uid"])
                for p in placements
                if p.get("source_uid") and not p.get("parent_is_internal", False)
            ),
        )
        dependencies = tuple(
            sorted(
                {
                    ResourceRef(
                        "condition",
                        str(spec.condition_uid),
                        int(source_bid_key),
                    )
                    for spec in specs
                    if source_bid_key != str(bid_ref.bid_uid)
                }
            )
        )
        if not uses_sql_queue:
            self._execute_mdb_plan_items_paste_payload(bid_ref, payload, dependencies)
            return
        self._queue_sql_plan_items_paste_payload(
            bid_ref,
            str(placements[0]["page_uid"]),
            payload,
            dependencies,
        )
        return

    def _insert_takeoffs_with_undo(
        self, bid_ref, specs: List[InsertTakeoffSpec], fast_refresh: bool = False
    ) -> bool:
        use_fast_refresh = fast_refresh and self._takeoff_specs_allow_fast_refresh(
            specs
        )
        result = self._write_svc.insert_takeoffs_result(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            publish_database_refreshed_after_write=not use_fast_refresh,
        )
        if result.failure_reason:
            show_warning(
                self._plan_view,
                "Database Write",
                result.failure_reason,
            )
            return False
        new_uids = list(result.value or ()) if result.success else []
        if not new_uids:
            return False
        if use_fast_refresh:
            self._add_inserted_takeoffs_to_model(new_uids, specs)
            self._publish_takeoffs_changed_for_pages(
                self._takeoff_spec_page_uids(specs), new_uids
            )
        self._plan_view.set_selected_uids(set(new_uids))
        selection_owner_is_current = self._history_selection_owner(
            bid_ref,
            tuple(spec.page_uid for spec in specs),
        )
        self._push_takeoff_insert_history(
            bid_ref,
            new_uids,
            specs,
            selection_owner_is_current,
            fast_refresh=use_fast_refresh,
        )
        return True

    def _push_takeoff_insert_history(
        self,
        bid_ref,
        new_uids: List[str],
        specs: List[InsertTakeoffSpec],
        selection_owner_is_current: Callable[[], bool],
        *,
        fast_refresh: bool = True,
    ) -> None:
        current_specs = specs[: len(new_uids)]
        targets = tuple(
            TakeoffHistoryTarget(bid_ref, str(spec.page_uid), uid)
            for uid, spec in zip(new_uids, current_specs)
        )
        parents = self._history_parent_targets(bid_ref, new_uids, current_specs)
        suspended_targets = ()
        current_specs_scales = self._capture_takeoff_spec_scales(current_specs)

        def _undo_insert():
            nonlocal suspended_targets
            uids = [target.uid for target in targets]
            success = (
                self._delete_takeoffs_fast(bid_ref.file_path, uids)
                if fast_refresh
                else self._write_svc.delete_takeoffs(bid_ref.file_path, uids)
            )
            if success:
                suspended_targets = self._undo_svc.suspend_deleted_takeoffs(
                    bid_ref, targets
                )
            if success and selection_owner_is_current():
                self._plan_view.clear_selection()
            return success

        def _redo_insert():
            redone_specs = self._takeoff_specs_for_current_scales(
                current_specs, current_specs_scales
            )
            redone_specs = self._specs_with_history_parents(redone_specs, parents)
            redone_uids = (
                self._insert_takeoffs_fast(bid_ref, redone_specs)
                if fast_refresh
                else self._write_svc.insert_takeoffs(
                    bid_ref.file_path, bid_ref.bid_uid, redone_specs
                )
            )
            if len(redone_uids) != len(current_specs):
                return False
            self._undo_svc.rebind_restored_takeoffs(
                bid_ref,
                {
                    (target.page_uid, target.uid): uid
                    for target, uid in zip(targets, redone_uids)
                },
                suspended_targets,
            )
            if redone_uids and selection_owner_is_current():
                self._plan_view.set_selected_uids(set(redone_uids))
            return True

        self._undo_svc.push_local(
            _undo_insert, _redo_insert, takeoff_targets=(*targets, *parents.values())
        )

    def _add_inserted_takeoffs_to_model(
        self,
        new_uids: List[str],
        specs: List[InsertTakeoffSpec],
        *,
        transient: bool = False,
    ) -> None:
        takeoffs = []
        for uid, spec in zip(new_uids, specs):
            takeoff = Takeoff(
                uid=str(uid),
                condition_uid=str(spec.condition_uid),
                page_uid=str(spec.page_uid),
                area_uid=normalize_area_uid(spec.area_uid),
                position=list(spec.position),
                rotation=spec.rotation,
                curve=spec.curve,
                parent_uid=str(spec.parent_uid or "0"),
                is_negative=spec.is_negative,
            )
            self._apply_takeoff_raw_extras(takeoff, spec.raw_extras)
            takeoffs.append(takeoff)
        if transient:
            self._data_svc.add_transient_takeoffs(takeoffs)
        else:
            self._data_svc.add_takeoffs(takeoffs)

    @staticmethod
    def _int_extra_or_none(extras: dict, key: str, *, abs_value: bool = False):
        value = extras.get(key)
        if value in (None, ""):
            return None
        value = int(value)
        return abs(value) if abs_value else value

    @staticmethod
    def _str_extra_or_none(extras: dict, key: str):
        value = extras.get(key)
        return str(value) if value else None

    def _apply_takeoff_raw_extras(self, takeoff: Takeoff, extras: dict) -> None:
        if not extras:
            return
        takeoff.dimension_font_name = self._str_extra_or_none(extras, "FontName")
        takeoff.dimension_font_color = self._int_extra_or_none(extras, "FontColor")
        takeoff.dimension_font_size = self._int_extra_or_none(
            extras, "FontSize", abs_value=True
        )
        takeoff.dimension_font_bold = bool(extras.get("FontBold", False))
        takeoff.dimension_font_italic = bool(extras.get("FontItalic", False))
        takeoff.dimension_font_underline = bool(extras.get("FontUnderline", False))
        takeoff.name_font_name = self._str_extra_or_none(extras, "NameFontName")
        takeoff.name_font_color = self._int_extra_or_none(extras, "NameFontColor")
        takeoff.name_font_size = self._int_extra_or_none(
            extras, "NameFontSize", abs_value=True
        )
        takeoff.name_font_bold = bool(extras.get("NameFontBold", False))
        takeoff.name_font_italic = bool(extras.get("NameFontItalic", False))
        takeoff.name_font_underline = bool(extras.get("NameFontUnderline", False))

    def on_elements_deleted(self, uids: list) -> None:
        if not self._is_allowed(Feature.EDIT_PLAN_ITEMS):
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref or not uids:
            return
        uids = self._request_pending_takeoff_deletions(uids)
        if not uids:
            return
        db_path = bid_ref.file_path
        saved_takeoffs = []
        saved_annotations = []
        annotation_selection_keys = {}
        for uid in uids:
            t = self._command_takeoff(uid)
            if t:
                saved_takeoffs.append(t)
                continue
            a = self._plan_view.get_annotation(uid)
            if a and a.is_interactive:
                saved_annotations.append(a)
                annotation_selection_keys[(str(a.uid), str(a.annotation_type))] = uid
        takeoff_uids = set(t.uid for t in saved_takeoffs)
        all_takeoffs = self._data_svc.get_all_takeoffs()
        descendant_uids = expand_takeoff_uids_with_descendants(
            all_takeoffs, takeoff_uids
        )
        saved_takeoffs.extend(
            item
            for item in all_takeoffs
            if item.uid in descendant_uids and item.uid not in takeoff_uids
        )
        takeoff_uids = descendant_uids
        skipped_namedview_uids: set[str] = set()
        if any(a.is_namedview for a in saved_annotations):
            delete_plan = plan_named_view_hotlink_delete(
                saved_annotations,
                self._data_svc.find_hotlinks_targeting,
                lambda _annotation: confirm(
                    self._plan_view,
                    "Delete Named View",
                    NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
                ),
            )
            saved_annotations = delete_plan.annotations_to_delete
            skipped_namedview_uids = delete_plan.skipped_named_view_uids
        skipped_selection_keys = skipped_named_view_selection_keys(
            annotation_selection_keys, skipped_namedview_uids
        )
        if not saved_takeoffs and not saved_annotations:
            self._select_skipped_named_views(skipped_selection_keys)
            return
        takeoff_uids = list(takeoff_uids)
        simple_takeoff_delete = bool(saved_takeoffs) and not saved_annotations
        saved_takeoff_extras = {
            t.uid: dict(self._data_svc.get_takeoff_extras(t.uid))
            for t in saved_takeoffs
        }
        if self._uses_sql_mutation_queue(db_path) and (
            saved_takeoffs or saved_annotations
        ):
            self._queue_sql_plan_items_delete(
                bid_ref,
                set(uids),
                saved_takeoffs,
                saved_annotations,
                saved_takeoff_extras,
                skipped_selection_keys,
                set(annotation_selection_keys),
            )
            return
        if simple_takeoff_delete:
            simple_takeoff_delete = self._takeoffs_allow_fast_delete(
                saved_takeoffs, saved_takeoff_extras
            )
        if simple_takeoff_delete:
            specs = [
                InsertTakeoffSpec(
                    condition_uid=t.condition_uid,
                    page_uid=t.page_uid,
                    area_uid=t.area_uid,
                    position=list(t.position),
                    parent_uid=t.parent_uid,
                    curve=t.curve,
                    rotation=t.rotation,
                    is_negative=t.is_negative,
                    raw_extras=dict(saved_takeoff_extras.get(t.uid, {})),
                )
                for t in saved_takeoffs
            ]
            specs_scales = self._capture_takeoff_spec_scales(specs)
            if not self._delete_takeoffs_fast(db_path, takeoff_uids):
                self._plan_view.set_selected_uids(set(uids))
                return
            targets = tuple(
                TakeoffHistoryTarget(bid_ref, str(item.page_uid), str(item.uid))
                for item in saved_takeoffs
            )
            parents = self._history_parent_targets(bid_ref, takeoff_uids, specs)
            suspended_targets = self._undo_svc.suspend_deleted_takeoffs(
                bid_ref, targets
            )
            selection_owner_is_current = self._history_selection_owner(
                bid_ref,
                tuple(spec.page_uid for spec in specs),
            )

            def _undo_delete():
                restore_specs = self._takeoff_specs_for_current_scales(
                    specs, specs_scales
                )
                restore_specs = self._specs_with_history_parents(restore_specs, parents)
                new_uids = self._insert_takeoffs_fast(bid_ref, restore_specs)
                if len(new_uids) != len(specs):
                    return False
                self._undo_svc.rebind_restored_takeoffs(
                    bid_ref,
                    {
                        (target.page_uid, target.uid): uid
                        for target, uid in zip(targets, new_uids)
                    },
                    suspended_targets,
                )
                if new_uids and selection_owner_is_current():
                    self._plan_view.set_selected_uids(set(new_uids))
                return True

            def _redo_delete():
                nonlocal suspended_targets
                success = self._delete_takeoffs_fast(
                    db_path, [target.uid for target in targets]
                )
                if success:
                    suspended_targets = self._undo_svc.suspend_deleted_takeoffs(
                        bid_ref, targets
                    )
                if success and selection_owner_is_current():
                    self._plan_view.clear_selection()
                return success

            self._undo_svc.push_local(
                _undo_delete,
                _redo_delete,
                takeoff_targets=(*targets, *parents.values()),
            )
            self._select_skipped_named_views(skipped_selection_keys)
            return
        if saved_annotations and not takeoff_uids:
            current_annotations = list(saved_annotations)
            targets = tuple(
                AnnotationHistoryTarget(
                    bid_ref, item.page_uid, item.annotation_type, item.uid
                )
                for item in current_annotations
            )
            current_annotation_scales = self._capture_saved_annotation_scales(
                current_annotations
            )
            if not self._delete_saved_annotations_fast(db_path, current_annotations):
                self._plan_view.set_selected_uids(set(uids))
                return
            suspended = self._undo_svc.suspend_deleted_annotations(bid_ref, targets)
            selection_owner_is_current = self._history_selection_owner(
                bid_ref,
                tuple(annotation.page_uid for annotation in current_annotations),
            )

            def _undo_annotation_delete():
                nonlocal current_annotations, current_annotation_scales
                restore_annotations = self._saved_annotations_for_current_scales(
                    current_annotations, current_annotation_scales
                )
                restored = self._insert_saved_annotations_fast(
                    bid_ref, restore_annotations
                )
                if len(restored) != len(restore_annotations):
                    return False
                self._undo_svc.rebind_restored_annotations(
                    bid_ref,
                    {
                        target.identity: item.uid
                        for target, item in zip(targets, restored)
                    },
                    suspended,
                )
                current_annotations = restored
                current_annotation_scales = self._capture_saved_annotation_scales(
                    current_annotations
                )
                if selection_owner_is_current():
                    uid_type_set = {
                        (annotation.uid, annotation.annotation_type)
                        for annotation in current_annotations
                    }
                    keys = self._plan_view.find_annotation_keys_by_uid_type(
                        uid_type_set
                    )
                    self._plan_view.set_selected_uids(keys)
                return True

            def _redo_annotation_delete():
                nonlocal suspended
                success = self._delete_saved_annotations_fast(
                    db_path, current_annotations
                )
                if success:
                    suspended = self._undo_svc.suspend_deleted_annotations(
                        bid_ref, targets
                    )
                    if selection_owner_is_current():
                        self._plan_view.clear_selection()
                return success

            self._undo_svc.push_local(
                _undo_annotation_delete,
                _redo_annotation_delete,
                annotation_targets=targets,
            )
            self._select_skipped_named_views(skipped_selection_keys)
            return
        deleted_annotations = [
            (str(item.uid), str(item.annotation_type)) for item in saved_annotations
        ]
        page_uids = tuple(
            dict.fromkeys(
                str(item.page_uid)
                for item in (*saved_takeoffs, *saved_annotations)
                if item.page_uid
            )
        )
        dependencies = tuple(
            sorted(
                {
                    *(
                        self._condition_resource(bid_ref, item.condition_uid)
                        for item in saved_takeoffs
                    ),
                    *(
                        self._layer_resource(bid_ref, item.layer_uid)
                        for item in saved_annotations
                        if item.layer_uid
                    ),
                }
            )
        )
        result = self._write_svc.execute_plan_items_delete_local(
            db_path,
            bid_ref.bid_uid,
            takeoff_uids,
            deleted_annotations,
            page_uids=page_uids,
            dependency_resources=dependencies,
            publish_database_refreshed_after_write=False,
        )
        if result.outcome_status != MutationOutcomeStatus.COMMITTED:
            if (
                result.outcome_status
                != MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED
            ):
                self._plan_view.set_selected_uids(set(uids))
            return
        self._project_mdb_plan_items_deleted(
            takeoff_uids,
            deleted_annotations,
            page_uids=page_uids,
            condition_uids=tuple(
                dict.fromkeys(str(item.condition_uid) for item in saved_takeoffs)
            ),
        )
        self._push_mdb_delete_history(
            bid_ref,
            saved_takeoffs,
            saved_annotations,
            saved_takeoff_extras,
            takeoff_uids,
            deleted_annotations,
            dependencies,
        )
        self._select_skipped_named_views(skipped_selection_keys)

    def _queue_sql_plan_items_delete(
        self,
        bid_ref,
        requested_selection_uids: set[str],
        saved_takeoffs: list,
        saved_annotations: list,
        saved_takeoff_extras: dict,
        skipped_selection_keys: set[str],
        requested_annotation_identities: set[tuple[str, str]],
    ) -> None:
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        takeoff_uids = [str(item.uid) for item in saved_takeoffs]
        annotations = [
            (str(item.uid), str(item.annotation_type)) for item in saved_annotations
        ]
        pending_annotation_identities = set(annotations)
        page_uids = tuple(
            dict.fromkeys(
                str(item.page_uid)
                for item in (*saved_takeoffs, *saved_annotations)
                if item.page_uid
            )
        )
        page_identities = self._capture_page_identities(page_uids)
        dependencies = {
            *(
                self._condition_resource(bid_ref, item.condition_uid)
                for item in saved_takeoffs
            ),
            *(
                self._layer_resource(bid_ref, item.layer_uid)
                for item in saved_annotations
                if item.layer_uid
            ),
        }
        plan_uids = set(requested_selection_uids).difference(skipped_selection_keys)
        takeoff_uid_set = set(takeoff_uids)
        requested_takeoff_uids = set(requested_selection_uids).intersection(
            takeoff_uid_set
        )
        skipped_annotation_identities = {
            identity
            for identity in requested_annotation_identities
            if set(
                self._plan_view.find_annotation_keys_by_uid_type({identity})
            ).intersection(skipped_selection_keys)
        }
        self._set_plan_items_pending(
            bid_ref.file_path,
            plan_uids,
            takeoff_uid_set,
            True,
            pending_annotation_identities,
        )
        self._plan_view.set_selected_uids(set(skipped_selection_keys))
        selection_revision = self._plan_view.begin_deferred_selection()
        handler_ref = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None:
                return
            if handler._sql_completion_was_applied(result):
                return
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            handler._set_plan_items_pending(
                bid_ref.file_path,
                plan_uids,
                takeoff_uid_set,
                False,
                pending_annotation_identities,
            )
            current_requested_annotations = set(
                handler._plan_view.find_annotation_keys_by_uid_type(
                    requested_annotation_identities
                )
            )
            current_skipped_annotations = set(
                handler._plan_view.find_annotation_keys_by_uid_type(
                    skipped_annotation_identities
                )
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                handler._restore_plan_selection_if_current(
                    bid_ref,
                    page_uids,
                    requested_takeoff_uids.union(current_requested_annotations),
                    page_identities,
                    selection_revision=selection_revision,
                )
                handler._undo_svc.finish_forward_mutation(history_token)
                return
            handler._restore_plan_selection_if_current(
                bid_ref,
                page_uids,
                current_skipped_annotations,
                page_identities,
                selection_revision=selection_revision,
            )
            if handler._undo_svc.is_forward_mutation_current(
                history_token
            ) and handler._page_identities_are_current(page_uids, page_identities):
                handler._push_sql_delete_history(
                    bid_ref,
                    saved_takeoffs,
                    saved_annotations,
                    saved_takeoff_extras,
                    takeoff_uids,
                    annotations,
                )
                handler._undo_svc.bind_latest_history_to_forward_mutation(history_token)
            else:
                handler._undo_svc.notify_annotation_deletion(
                    bid_ref,
                    {
                        (str(item.page_uid), item.annotation_type, str(item.uid))
                        for item in saved_annotations
                    },
                )
            handler._mark_sql_completion_applied(result)
            handler._undo_svc.finish_forward_mutation(history_token)

        try:
            self._write_svc.queue_plan_items_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                takeoff_uids,
                annotations,
                complete,
                page_uids=page_uids,
                dependency_resources=tuple(sorted(dependencies)),
            )
        except Exception:
            self._undo_svc.finish_forward_mutation(history_token)
            raise

    @staticmethod
    def _condition_resource(bid_ref, condition_uid):
        return ResourceRef("condition", str(condition_uid), int(bid_ref.bid_uid))

    @staticmethod
    def _layer_resource(bid_ref, layer_uid):
        return ResourceRef("layer", str(layer_uid), int(bid_ref.bid_uid))

    def _delete_restore_payload(
        self,
        bid_ref,
        saved_takeoffs: list,
        saved_annotations: list,
        saved_takeoff_extras: dict,
    ) -> PlanItemsPastePayload:
        return PlanItemsPastePayload(
            source_bid_uid=str(bid_ref.bid_uid),
            destination_bid_uid=str(bid_ref.bid_uid),
            takeoff_source_uids=tuple(str(item.uid) for item in saved_takeoffs),
            takeoff_specs=tuple(
                InsertTakeoffSpec(
                    condition_uid=item.condition_uid,
                    page_uid=item.page_uid,
                    area_uid=item.area_uid,
                    position=list(item.position),
                    parent_uid=item.parent_uid,
                    curve=item.curve,
                    rotation=item.rotation,
                    is_negative=item.is_negative,
                    raw_extras=dict(saved_takeoff_extras.get(item.uid, {})),
                )
                for item in saved_takeoffs
            ),
            annotation_source_uids=tuple(
                annotation_resource_id(item.annotation_type, item.uid)
                for item in saved_annotations
            ),
            annotation_specs=tuple(
                self._annotation_writes.annotation_specs_from_saved(saved_annotations)
            ),
        )

    def _push_mdb_delete_history(
        self,
        bid_ref,
        saved_takeoffs: list,
        saved_annotations: list,
        saved_takeoff_extras: dict,
        deleted_takeoff_uids: list[str],
        deleted_annotations: list[tuple[str, str]],
        dependency_resources: tuple[ResourceRef, ...],
    ) -> None:
        payload = self._delete_restore_payload(
            bid_ref,
            saved_takeoffs,
            saved_annotations,
            saved_takeoff_extras,
        )
        page_uids = tuple(
            dict.fromkeys(
                spec.page_uid
                for spec in (*payload.takeoff_specs, *payload.annotation_specs)
            )
        )
        targets = self._takeoff_restore_history_targets(
            bid_ref, payload, {uid: uid for uid in deleted_takeoff_uids}
        )
        parents = self._history_parent_targets(
            bid_ref,
            payload.takeoff_source_uids,
            payload.takeoff_specs,
            external_parent_sources=payload.takeoff_external_parent_sources,
        )
        annotation_targets = self._annotation_restore_history_targets(
            bid_ref,
            payload,
            {
                annotation_resource_id(kind, uid): uid
                for uid, kind in deleted_annotations
            },
        )
        current = {
            "suspended_annotations": self._undo_svc.suspend_deleted_annotations(
                bid_ref, tuple(annotation_targets.values())
            ),
            "suspended_targets": self._undo_svc.suspend_deleted_takeoffs(
                bid_ref, tuple(targets.values())
            ),
        }
        takeoff_scales = self._capture_takeoff_spec_scales(list(payload.takeoff_specs))
        annotation_scales = self._capture_annotation_spec_scales(
            list(payload.annotation_specs)
        )
        selection_owner_is_current = self._history_selection_owner(
            bid_ref,
            page_uids,
        )

        def undo() -> bool:
            restore_payload = self._paste_payload_for_current_scales(
                payload,
                takeoff_scales,
                annotation_scales,
            )
            restore_payload = self._paste_payload_with_history_parents(
                restore_payload, parents
            )
            result = self._write_svc.execute_plan_items_paste_local(
                bid_ref.file_path,
                restore_payload,
                dependency_resources=dependency_resources,
                publish_database_refreshed_after_write=False,
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                return False
            takeoff_map, annotation_map = self._created_uid_maps(result)
            if not self._project_mdb_plan_items_paste(
                bid_ref,
                restore_payload,
                result,
            ):
                return False
            self._rebind_restored_takeoff_history(
                bid_ref, targets, takeoff_map, current["suspended_targets"]
            )
            self._rebind_restored_annotation_history(
                bid_ref,
                annotation_targets,
                annotation_map,
                current["suspended_annotations"],
            )
            if selection_owner_is_current():
                self._plan_view.set_selected_uids(
                    self._selection_keys_for_paste_maps(
                        payload,
                        takeoff_map,
                        annotation_map,
                    )
                )
            return True

        def redo() -> bool:
            annotation_keys = self._annotation_history_keys(annotation_targets)
            result = self._write_svc.execute_plan_items_delete_local(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [target.uid for target in targets.values()],
                annotation_keys,
                page_uids=page_uids,
                dependency_resources=dependency_resources,
                publish_database_refreshed_after_write=False,
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                return False
            current["suspended_targets"] = self._undo_svc.suspend_deleted_takeoffs(
                bid_ref, tuple(targets.values())
            )
            current["suspended_annotations"] = (
                self._undo_svc.suspend_deleted_annotations(
                    bid_ref, tuple(annotation_targets.values())
                )
            )
            self._project_mdb_plan_items_deleted(
                [target.uid for target in targets.values()],
                annotation_keys,
                page_uids=page_uids,
                condition_uids=tuple(
                    dict.fromkeys(spec.condition_uid for spec in payload.takeoff_specs)
                ),
            )
            if selection_owner_is_current():
                self._plan_view.clear_selection()
            return True

        self._undo_svc.push_local(
            undo,
            redo,
            takeoff_targets=(*targets.values(), *parents.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    @staticmethod
    def _takeoff_restore_history_targets(bid_ref, payload, uid_map):
        return {
            source_uid: TakeoffHistoryTarget(
                bid_ref, str(spec.page_uid), uid_map[source_uid]
            )
            for source_uid, spec in zip(
                payload.takeoff_source_uids, payload.takeoff_specs
            )
        }

    def _rebind_restored_takeoff_history(
        self, bid_ref, targets_by_source, restored_map, suspended_targets
    ) -> None:
        self._undo_svc.rebind_restored_takeoffs(
            bid_ref,
            {
                (target.page_uid, target.uid): restored_map[source_uid]
                for source_uid, target in targets_by_source.items()
            },
            suspended_targets,
        )

    def _push_sql_delete_history(
        self,
        bid_ref,
        saved_takeoffs: list,
        saved_annotations: list,
        saved_takeoff_extras: dict,
        deleted_takeoff_uids: list[str],
        deleted_annotations: list[tuple[str, str]],
    ) -> None:
        paste_payload = self._delete_restore_payload(
            bid_ref,
            saved_takeoffs,
            saved_annotations,
            saved_takeoff_extras,
        )
        targets = self._takeoff_restore_history_targets(
            bid_ref,
            paste_payload,
            {uid: uid for uid in deleted_takeoff_uids},
        )
        parents = self._history_parent_targets(
            bid_ref, paste_payload.takeoff_source_uids, paste_payload.takeoff_specs
        )
        annotation_targets = self._annotation_restore_history_targets(
            bid_ref,
            paste_payload,
            {
                annotation_resource_id(kind, uid): uid
                for uid, kind in deleted_annotations
            },
        )
        current = {
            "suspended_annotations": self._undo_svc.suspend_deleted_annotations(
                bid_ref, tuple(annotation_targets.values())
            ),
            "suspended_targets": self._undo_svc.suspend_deleted_takeoffs(
                bid_ref, tuple(targets.values())
            ),
        }

        def undo_submit(done) -> None:
            def completed(result: QueuedMutationResult) -> None:
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    takeoff_map, annotation_map = self._created_uid_maps(result)
                    self._rebind_restored_takeoff_history(
                        bid_ref, targets, takeoff_map, current["suspended_targets"]
                    )
                    self._rebind_restored_annotation_history(
                        bid_ref,
                        annotation_targets,
                        annotation_map,
                        current["suspended_annotations"],
                    )
                done(result)

            self._write_svc.queue_plan_items_paste(
                bid_ref.file_path,
                self._paste_payload_with_history_parents(paste_payload, parents),
                completed,
            )

        def redo_submit(done) -> None:
            def deleted(result: QueuedMutationResult) -> None:
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    current["suspended_annotations"] = (
                        self._undo_svc.suspend_deleted_annotations(
                            bid_ref, tuple(annotation_targets.values())
                        )
                    )
                    current["suspended_targets"] = (
                        self._undo_svc.suspend_deleted_takeoffs(
                            bid_ref, tuple(targets.values())
                        )
                    )
                done(result)

            pages = tuple(
                dict.fromkeys(
                    spec.page_uid
                    for spec in (
                        *paste_payload.takeoff_specs,
                        *paste_payload.annotation_specs,
                    )
                )
            )
            self._write_svc.queue_plan_items_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [target.uid for target in targets.values()],
                self._annotation_history_keys(annotation_targets),
                deleted,
                page_uids=pages,
            )

        self._undo_svc.push_for_bid(
            bid_ref,
            undo_submit,
            redo_submit,
            takeoff_targets=(*targets.values(), *parents.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    @staticmethod
    def _created_uid_maps(
        result: QueuedMutationResult,
    ) -> tuple[dict[str, str], dict[str, str]]:
        authoritative = result.authoritative_result
        if authoritative is None:
            raise RuntimeError("Committed paste is missing authoritative UID maps")
        maps = {name: dict(values) for name, values in authoritative.created_uid_maps}
        return maps.get("takeoffs", {}), maps.get("annotations", {})

    def _select_skipped_named_views(self, skipped_selection_keys: set[str]) -> None:
        if skipped_selection_keys:
            self._plan_view.set_selected_uids(skipped_selection_keys)

    def on_copy_requested(self, uids: list) -> None:
        if not self._is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        takeoffs = []
        annotations = []
        for uid in uids:
            t = self._current_plan_takeoff(uid)
            if t:
                takeoffs.append(t)
                continue
            a = self._plan_view.get_annotation(uid)
            if a and a.is_interactive and not a.is_namedview:
                annotations.append(a)
        copied_uids = {takeoff.uid for takeoff in takeoffs}
        descendants = (
            expand_takeoff_uids_with_descendants(
                self._data_svc.get_all_takeoffs(), copied_uids
            )
            - copied_uids
        )
        for uid in sorted(descendants):
            takeoff = self._current_plan_takeoff(uid)
            if takeoff is not None:
                takeoffs.append(takeoff)
        if takeoffs or annotations:
            bid_ref = self._ui_state.get_selected_bid_ref()
            takeoff_extras = {
                t.uid: self._data_svc.get_takeoff_extras(t.uid) for t in takeoffs
            }
            self._clipboard_svc.copy(
                takeoffs,
                annotations,
                source_bid_uid=bid_ref.bid_uid if bid_ref else None,
                source_file_path=bid_ref.file_path if bid_ref else None,
                takeoff_extras=takeoff_extras,
                conditions=self._data_svc.get_bid_conditions(),
            )
            self._plan_view.clipboard_changed.emit()

    def on_paste_requested(self) -> None:
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            return
        page_uid = self._plan_view.current_page_uid or ""
        if not page_uid:
            return
        area_uid = self._page_settings_bar.get_current_area_uid()
        source_bid_uid = self._clipboard_svc.source_bid_uid
        all_items, clipboard_anns = self._permitted_paste_content(bid_ref)
        if not all_items and not clipboard_anns:
            return
        regulars = [t for t in all_items if not t.is_hole]
        holes = [t for t in all_items if t.is_hole]
        if holes and not regulars:
            if not self._is_allowed(Feature.PLACE_PLAN_ITEMS):
                return
            extras_by_uid = {
                h.uid: dict(self._clipboard_svc.get_extras(h.uid)) for h in holes
            }
            self._plan_view.begin_paste_backout(
                holes,
                extras_by_uid,
                source_bid_uid,
                conditions=(
                    self._data_svc.get_bid_conditions()
                    if source_bid_uid == bid_ref.bid_uid
                    else self._clipboard_svc.conditions
                ),
            )
            holes = []
        if self._uses_sql_mutation_queue(bid_ref.file_path):
            self._queue_sql_plan_items_paste(
                bid_ref,
                page_uid,
                area_uid,
                regulars,
                holes,
                clipboard_anns,
            )
            return
        self._execute_mdb_plan_items_paste(
            bid_ref,
            page_uid,
            area_uid,
            regulars,
            holes,
            clipboard_anns,
        )
        return

    def _execute_mdb_plan_items_paste(
        self,
        bid_ref,
        page_uid: str,
        area_uid: Optional[str],
        regulars: list,
        holes: list,
        annotations: list,
    ) -> None:
        prepared = self._prepare_plan_items_paste(
            bid_ref,
            page_uid,
            area_uid,
            regulars,
            holes,
            annotations,
        )
        if prepared is None:
            return
        payload, dependencies, source_anchor = prepared
        self._execute_mdb_plan_items_paste_payload(
            bid_ref, payload, dependencies, source_anchor
        )

    def _execute_mdb_plan_items_paste_payload(
        self, bid_ref, payload, dependencies, source_anchor=None
    ):
        result = self._write_svc.execute_plan_items_paste_local(
            bid_ref.file_path,
            payload,
            dependency_resources=dependencies,
            publish_database_refreshed_after_write=False,
        )
        if result.outcome_status != MutationOutcomeStatus.COMMITTED:
            return
        if not self._project_mdb_plan_items_paste(bid_ref, payload, result):
            return
        takeoff_map, annotation_map = self._created_uid_maps(result)
        selected = self._selection_keys_for_paste_maps(
            payload,
            takeoff_map,
            annotation_map,
        )
        self._plan_view.set_selected_uids(selected)
        if source_anchor and selected:
            ordered_selection = list(takeoff_map.values())
            ordered_selection.extend(sorted(selected.difference(ordered_selection)))
            self._plan_view.mark_intelligent_paste_drag_pending(
                ordered_selection,
                source_anchor,
            )
        self._push_mdb_paste_history(
            bid_ref,
            self._committed_paste_history_payload(payload, result),
            tuple(
                resource
                for resource in dependencies
                if resource.bid_uid == int(bid_ref.bid_uid)
            ),
            takeoff_map,
            annotation_map,
        )

    @staticmethod
    def _committed_paste_history_payload(payload, result):
        payload = prepare_plan_items_paste_payload(payload)
        maps = dict(result.authoritative_result.created_uid_maps)
        conditions = dict(maps.get("conditions", ()))
        return replace(
            payload,
            source_bid_uid=payload.destination_bid_uid,
            takeoff_specs=tuple(
                replace(
                    spec,
                    condition_uid=conditions.get(
                        str(spec.condition_uid), str(spec.condition_uid)
                    ),
                )
                for spec in payload.takeoff_specs
            ),
        )

    def _push_mdb_paste_history(
        self,
        bid_ref,
        payload: PlanItemsPastePayload,
        dependency_resources: tuple[ResourceRef, ...],
        takeoff_map: dict[str, str],
        annotation_map: dict[str, str],
    ) -> None:
        page_uids = tuple(
            dict.fromkeys(
                spec.page_uid
                for spec in (*payload.takeoff_specs, *payload.annotation_specs)
            )
        )
        targets = self._takeoff_restore_history_targets(bid_ref, payload, takeoff_map)
        parents = self._history_parent_targets(
            bid_ref,
            payload.takeoff_source_uids,
            payload.takeoff_specs,
            external_parent_sources=payload.takeoff_external_parent_sources,
        )
        annotation_targets = self._annotation_restore_history_targets(
            bid_ref, payload, annotation_map
        )
        current = {
            "suspended_targets": (),
            "suspended_annotations": (),
        }
        takeoff_scales = self._capture_takeoff_spec_scales(list(payload.takeoff_specs))
        annotation_scales = self._capture_annotation_spec_scales(
            list(payload.annotation_specs)
        )
        selection_owner_is_current = self._history_selection_owner(
            bid_ref,
            page_uids,
        )

        def undo() -> bool:
            annotation_keys = self._annotation_history_keys(annotation_targets)
            result = self._write_svc.execute_plan_items_delete_local(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [target.uid for target in targets.values()],
                annotation_keys,
                page_uids=page_uids,
                publish_database_refreshed_after_write=False,
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                return False
            current["suspended_targets"] = self._undo_svc.suspend_deleted_takeoffs(
                bid_ref, tuple(targets.values())
            )
            current["suspended_annotations"] = (
                self._undo_svc.suspend_deleted_annotations(
                    bid_ref, tuple(annotation_targets.values())
                )
            )
            self._project_mdb_plan_items_deleted(
                [target.uid for target in targets.values()],
                annotation_keys,
                page_uids=page_uids,
                condition_uids=tuple(
                    dict.fromkeys(spec.condition_uid for spec in payload.takeoff_specs)
                ),
            )
            if selection_owner_is_current():
                self._plan_view.clear_selection()
            return True

        def redo() -> bool:
            redo_payload = self._paste_payload_for_current_scales(
                payload,
                takeoff_scales,
                annotation_scales,
            )
            redo_payload = self._paste_payload_with_history_parents(
                redo_payload, parents
            )
            result = self._write_svc.execute_plan_items_paste_local(
                bid_ref.file_path,
                redo_payload,
                dependency_resources=dependency_resources,
                publish_database_refreshed_after_write=False,
            )
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                return False
            if not self._project_mdb_plan_items_paste(
                bid_ref,
                redo_payload,
                result,
            ):
                return False
            next_takeoffs, next_annotations = self._created_uid_maps(result)
            self._rebind_restored_takeoff_history(
                bid_ref,
                targets,
                next_takeoffs,
                current["suspended_targets"],
            )
            self._rebind_restored_annotation_history(
                bid_ref,
                annotation_targets,
                next_annotations,
                current["suspended_annotations"],
            )
            if selection_owner_is_current():
                self._plan_view.set_selected_uids(
                    self._selection_keys_for_paste_maps(
                        payload,
                        next_takeoffs,
                        next_annotations,
                    )
                )
            return True

        self._undo_svc.push_local(
            undo,
            redo,
            takeoff_targets=(*targets.values(), *parents.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    def _project_mdb_plan_items_paste(
        self,
        bid_ref,
        payload: PlanItemsPastePayload,
        result: MutationExecutionResult,
    ) -> bool:
        takeoff_map, annotation_map = self._created_uid_maps(result)
        authoritative = result.authoritative_result
        maps = (
            {name: dict(values) for name, values in authoritative.created_uid_maps}
            if authoritative is not None
            else {}
        )
        condition_map = maps.get("conditions", {})
        targeted = not condition_map and all(
            self._same_bid_takeoff_extras_allow_fast_refresh(dict(spec.raw_extras))
            for spec in payload.takeoff_specs
        )
        if not targeted:
            return self._write_svc.reload_and_notify(bid_ref.file_path)
        if payload.takeoff_specs:
            takeoff_uids = [
                takeoff_map[source_uid] for source_uid in payload.takeoff_source_uids
            ]
            self._add_inserted_takeoffs_to_model(
                takeoff_uids,
                [
                    (
                        replace(spec, parent_uid=takeoff_map[str(spec.parent_uid)])
                        if str(spec.parent_uid) in takeoff_map
                        and source_uid not in payload.takeoff_external_parent_sources
                        else spec
                    )
                    for source_uid, spec in zip(
                        payload.takeoff_source_uids, payload.takeoff_specs
                    )
                ],
            )
            self._publish_takeoffs_changed_for_pages(
                self._takeoff_spec_page_uids(list(payload.takeoff_specs)),
                takeoff_uids,
                condition_uids=tuple(
                    dict.fromkeys(spec.condition_uid for spec in payload.takeoff_specs)
                ),
            )
        if payload.annotation_specs:
            annotation_uids = [
                annotation_map[source_uid]
                for source_uid in payload.annotation_source_uids
            ]
            ref_remap = PasteRefRemap(
                takeoff_uids=dict(takeoff_map),
                namedview_uids={
                    parse_annotation_resource_id(source_uid)[1]: annotation_map[
                        source_uid
                    ]
                    for source_uid, spec in zip(
                        payload.annotation_source_uids,
                        payload.annotation_specs,
                    )
                    if spec.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
                },
            )
            self._annotation_writes.project_inserted_annotations(
                annotation_uids,
                list(payload.annotation_specs),
                ref_remap=ref_remap,
            )
        return True

    def _project_mdb_plan_items_deleted(
        self,
        takeoff_uids: list[str],
        annotations: list[tuple[str, str]],
        *,
        page_uids: tuple[str, ...],
        condition_uids: tuple[str, ...],
    ) -> None:
        if takeoff_uids:
            removed_pages = self._data_svc.remove_takeoffs(takeoff_uids)
            self._publish_takeoffs_changed_for_pages(
                self._unique_ordered((*removed_pages, *page_uids)),
                takeoff_uids,
                condition_uids=condition_uids,
            )
        if annotations:
            self._annotation_writes.project_deleted_annotations(
                annotations,
                page_uids=list(page_uids),
            )

    def _paste_payload_for_current_scales(
        self,
        payload: PlanItemsPastePayload,
        takeoff_scales: dict[str, PageScale],
        annotation_scales: dict[str, PageScale],
    ) -> PlanItemsPastePayload:
        return replace(
            payload,
            takeoff_specs=tuple(
                self._takeoff_specs_for_current_scales(
                    list(payload.takeoff_specs),
                    takeoff_scales,
                )
            ),
            annotation_specs=tuple(
                self._annotation_specs_for_current_scales(
                    list(payload.annotation_specs),
                    annotation_scales,
                )
            ),
        )

    def _queue_sql_plan_items_paste(
        self,
        bid_ref,
        page_uid: str,
        area_uid: Optional[str],
        regulars: list,
        holes: list,
        annotations: list,
    ) -> None:
        prepared = self._prepare_plan_items_paste(
            bid_ref,
            page_uid,
            area_uid,
            regulars,
            holes,
            annotations,
        )
        if prepared is None:
            return
        payload, dependencies, _source_anchor = prepared
        self._queue_sql_plan_items_paste_payload(
            bid_ref,
            page_uid,
            payload,
            dependencies,
        )

    def _queue_sql_plan_items_paste_payload(
        self,
        bid_ref,
        page_uid: str,
        payload: PlanItemsPastePayload,
        dependencies: tuple[ResourceRef, ...],
    ) -> None:
        page_identities = self._capture_page_identities((page_uid,))
        history_token = self._undo_svc.begin_forward_mutation(bid_ref)
        previous_selection = set(self._plan_view.get_selected_uids())
        previous_takeoff_selection, previous_annotation_selection = (
            self._plan_identities_for_keys(previous_selection)
        )
        self._plan_view.clear_selection()
        selection_revision = self._plan_view.begin_deferred_selection()
        handler_ref = weakref.ref(self)

        def complete(result: QueuedMutationResult) -> None:
            handler = handler_ref()
            if handler is None:
                return
            if handler._sql_completion_was_applied(result):
                return
            if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                if result.outcome_status not in {
                    MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                }:
                    active_bid = handler._ui_state.get_selected_bid_ref()
                    if (
                        active_bid == bid_ref
                        and handler._plan_context_is_current(
                            bid_ref, (page_uid,), page_identities
                        )
                        and handler._plan_view.selection_revision == selection_revision
                    ):
                        handler._plan_view.set_selected_uids(
                            handler._current_plan_keys_for_identities(
                                previous_takeoff_selection,
                                previous_annotation_selection,
                            )
                        )
                if result.outcome_status not in {
                    MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                }:
                    handler._undo_svc.finish_forward_mutation(history_token)
                return
            takeoff_map, annotation_map = handler._created_uid_maps(result)
            selected = handler._selection_keys_for_paste_maps(
                payload,
                takeoff_map,
                annotation_map,
            )
            active_bid = handler._ui_state.get_selected_bid_ref()
            if (
                active_bid == bid_ref
                and handler._plan_context_is_current(
                    bid_ref, (page_uid,), page_identities
                )
                and handler._plan_view.selection_revision == selection_revision
            ):
                handler._plan_view.set_selected_uids(selected)
            if handler._undo_svc.is_forward_mutation_current(
                history_token
            ) and handler._page_identities_are_current((page_uid,), page_identities):
                handler._push_sql_paste_history(
                    bid_ref,
                    handler._committed_paste_history_payload(payload, result),
                    takeoff_map,
                    annotation_map,
                )
                handler._undo_svc.bind_latest_history_to_forward_mutation(history_token)
            handler._mark_sql_completion_applied(result)
            handler._undo_svc.finish_forward_mutation(history_token)

        try:
            self._write_svc.queue_plan_items_paste(
                bid_ref.file_path,
                payload,
                complete,
                dependency_resources=dependencies,
            )
        except Exception:
            self._undo_svc.finish_forward_mutation(history_token)
            raise

    def _prepare_plan_items_paste(
        self,
        bid_ref,
        page_uid: str,
        area_uid: Optional[str],
        regulars: list,
        holes: list,
        annotations: list,
    ):
        source_bid_uid = str(self._clipboard_svc.source_bid_uid or bid_ref.bid_uid)
        source_takeoffs = regulars + holes
        paste_dx, paste_dy, source_anchor = self._paste_translation(
            regulars,
            annotations,
        )
        takeoff_specs = tuple(
            InsertTakeoffSpec(
                condition_uid=str(item.condition_uid),
                page_uid=page_uid,
                area_uid=area_uid,
                position=self._translate_position(item.position, paste_dx, paste_dy),
                parent_uid=item.parent_uid,
                curve=item.curve,
                rotation=item.rotation,
                is_negative=item.is_negative,
                raw_extras=dict(self._clipboard_svc.get_extras(item.uid)),
                source_bid_uid=source_bid_uid,
            )
            for item in source_takeoffs
        )
        source_uids = {str(item.uid) for item in source_takeoffs}
        external_indexes = [
            index
            for index, item in enumerate(source_takeoffs)
            if item.is_hole and str(item.parent_uid) not in source_uids
        ]
        if external_indexes:
            conditions = (
                self._data_svc.get_bid_conditions()
                if source_bid_uid == str(bid_ref.bid_uid)
                else self._clipboard_svc.conditions
            )
            parents, valid = self._plan_view.resolve_pasted_child_parents(
                [source_takeoffs[index] for index in external_indexes],
                [takeoff_specs[index].position for index in external_indexes],
                conditions,
            )
            if not valid:
                return None
            replacement_parents = dict(
                zip(external_indexes, (uid for uid, _valid in parents))
            )
            takeoff_specs = tuple(
                (
                    replace(spec, parent_uid=replacement_parents[index])
                    if index in replacement_parents
                    else spec
                )
                for index, spec in enumerate(takeoff_specs)
            )
        annotation_specs = [
            InsertAnnotationSpec(
                page_uid=page_uid,
                annotation_type=item.annotation_type,
                position=translate_annotation_position(item, paste_dx, paste_dy),
                color=item.color,
                width=item.width,
                properties=dict(item.properties),
                layer_uid=item.layer_uid,
            )
            for item in annotations
        ]
        annotations, annotation_specs = (
            self._annotation_writes.filter_copyable_annotations(
                annotations,
                annotation_specs,
            )
        )
        if not source_takeoffs and not annotations:
            return None
        self._annotation_writes.apply_default_annotation_layer(
            bid_ref, annotation_specs
        )
        payload = PlanItemsPastePayload(
            source_bid_uid=source_bid_uid,
            destination_bid_uid=str(bid_ref.bid_uid),
            takeoff_source_uids=tuple(str(item.uid) for item in source_takeoffs),
            takeoff_specs=takeoff_specs,
            takeoff_external_parent_sources=tuple(
                str(source_takeoffs[index].uid) for index in external_indexes
            ),
            annotation_source_uids=tuple(
                annotation_resource_id(item.annotation_type, item.uid)
                for item in annotations
            ),
            annotation_specs=tuple(annotation_specs),
        )
        dependencies = tuple(
            sorted(
                {
                    *(
                        ResourceRef(
                            "condition",
                            str(spec.condition_uid),
                            int(source_bid_uid),
                        )
                        for spec in takeoff_specs
                        if source_bid_uid != str(bid_ref.bid_uid)
                    ),
                    *(
                        ResourceRef("layer", str(spec.layer_uid), int(bid_ref.bid_uid))
                        for spec in annotation_specs
                        if spec.layer_uid
                    ),
                }
            )
        )
        return payload, dependencies, source_anchor

    def _selection_keys_for_paste_maps(
        self,
        payload: PlanItemsPastePayload,
        takeoff_map: dict[str, str],
        annotation_map: dict[str, str],
    ) -> set[str]:
        selected = set(takeoff_map.values())
        annotation_type_by_source = {
            source_uid: spec.annotation_type
            for source_uid, spec in zip(
                payload.annotation_source_uids,
                payload.annotation_specs,
            )
        }
        selected.update(
            self._plan_view.find_annotation_keys_by_uid_type(
                {
                    (uid, annotation_type_by_source[source_uid])
                    for source_uid, uid in annotation_map.items()
                }
            )
        )
        return selected

    def _push_sql_paste_history(
        self,
        bid_ref,
        payload: PlanItemsPastePayload,
        takeoff_map: dict[str, str],
        annotation_map: dict[str, str],
    ) -> None:
        targets = self._takeoff_restore_history_targets(bid_ref, payload, takeoff_map)
        parents = self._history_parent_targets(
            bid_ref,
            payload.takeoff_source_uids,
            payload.takeoff_specs,
            external_parent_sources=payload.takeoff_external_parent_sources,
        )
        annotation_targets = self._annotation_restore_history_targets(
            bid_ref, payload, annotation_map
        )
        current = {
            "suspended_targets": (),
            "suspended_annotations": (),
        }
        page_uids = tuple(
            dict.fromkeys(
                spec.page_uid
                for spec in (*payload.takeoff_specs, *payload.annotation_specs)
            )
        )
        takeoff_scales = self._capture_takeoff_spec_scales(list(payload.takeoff_specs))
        annotation_scales = self._capture_annotation_spec_scales(
            list(payload.annotation_specs)
        )

        def undo_submit(done) -> None:
            def deleted(result: QueuedMutationResult) -> None:
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    current["suspended_annotations"] = (
                        self._undo_svc.suspend_deleted_annotations(
                            bid_ref, tuple(annotation_targets.values())
                        )
                    )
                    current["suspended_targets"] = (
                        self._undo_svc.suspend_deleted_takeoffs(
                            bid_ref, tuple(targets.values())
                        )
                    )
                done(result)

            self._write_svc.queue_plan_items_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [target.uid for target in targets.values()],
                self._annotation_history_keys(annotation_targets),
                deleted,
                page_uids=page_uids,
            )

        def redo_submit(done) -> None:
            def completed(result: QueuedMutationResult) -> None:
                if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                    next_takeoffs, next_annotations = self._created_uid_maps(result)
                    self._rebind_restored_takeoff_history(
                        bid_ref,
                        targets,
                        next_takeoffs,
                        current["suspended_targets"],
                    )
                    self._rebind_restored_annotation_history(
                        bid_ref,
                        annotation_targets,
                        next_annotations,
                        current["suspended_annotations"],
                    )
                done(result)

            redo_payload = self._paste_payload_for_current_scales(
                payload, takeoff_scales, annotation_scales
            )
            redo_payload = self._paste_payload_with_history_parents(
                redo_payload, parents
            )
            self._write_svc.queue_plan_items_paste(
                bid_ref.file_path,
                redo_payload,
                completed,
            )

        self._undo_svc.push_for_bid(
            bid_ref,
            undo_submit,
            redo_submit,
            takeoff_targets=(*targets.values(), *parents.values()),
            annotation_targets=tuple(annotation_targets.values()),
        )

    def _paste_translation(
        self, regulars: list, annotations: list
    ) -> tuple[float, float, Optional[tuple]]:
        step = (
            self._plan_view.snap_increments
            if self._plan_view.snap_increments > 0
            else 1.0
        )
        if not self._plan_view.intelligent_paste_enabled:
            return step, step, None
        source_anchor = self._paste_source_anchor(regulars, annotations)
        if source_anchor is None:
            return step, step, None
        mouse_anchor = self._plan_view.current_mouse_ost_position()
        if mouse_anchor is None:
            return 0.0, 0.0, source_anchor
        return (
            mouse_anchor[0] - source_anchor[0],
            mouse_anchor[1] - source_anchor[1],
            source_anchor,
        )

    def _paste_source_anchor(
        self, regulars: list, annotations: list
    ) -> Optional[tuple]:
        for takeoff in regulars:
            if len(takeoff.position) >= 2:
                return float(takeoff.position[0]), float(takeoff.position[1])
        for annotation in annotations:
            anchor = annotation_paste_anchor(annotation)
            if anchor is not None:
                return anchor
        return None

    def _translate_position(self, position: list, dx: float, dy: float) -> list:
        translated = list(position)
        for i in range(0, len(translated) - 1, 2):
            translated[i] += dx
            translated[i + 1] += dy
        return translated

    def _is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self._data_svc.get_bid_conditions().get(condition_uid)
        return bool(condition and condition.layer_visible)

    def _target_place_condition_uids(self, active_uid: str, place_uids: list) -> list:
        conditions = self._data_svc.get_bid_conditions()
        active = conditions.get(active_uid)
        if not active or not active.layer_visible:
            return [active_uid]
        target_uids = []
        seen = set()
        for uid in list(place_uids or []) + [active_uid]:
            if not uid or uid in seen:
                continue
            seen.add(uid)
            condition = conditions.get(uid)
            if (
                condition
                and condition.layer_visible
                and condition.condition_type == active.condition_type
            ):
                target_uids.append(uid)
        return target_uids or [active_uid]
