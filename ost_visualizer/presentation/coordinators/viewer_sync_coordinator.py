from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Dict, List, Optional
from ...application.dtos.remote_projection_dtos import RemoteProjectionBarrier
from ...application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
    parse_annotation_resource_id,
)
from ...domain.entities.identity_refs import BidRef
from ..managers.ui_access_manager import Feature
from .remote_plan_update_pipeline import RemotePlanUpdatePipeline


@dataclass(frozen=True)
class _RemotePlanIdentity:
    database_id: str
    bid_uid: str
    page_uid: str
    surface_id: str
    update_generation: int
    barrier: RemoteProjectionBarrier


@dataclass(frozen=True)
class _PlanUpdateSnapshot:
    page: object
    takeoffs: tuple
    conditions: tuple
    annotations: tuple
    display_mode: str
    grayscale_enabled: bool
    place_condition_uids: tuple[str, ...]
    bid_ref: Optional[BidRef]
    page_area_selections: tuple
    hidden_layer_uids: frozenset[str]
    snap_settings: Optional[tuple]
    ordered_pages: tuple
    changed_takeoff_uids: tuple[str, ...]
    changed_annotation_uids: tuple[str, ...]
    changed_annotation_types: tuple[str, ...]
    remote_identity: Optional[_RemotePlanIdentity] = None


@dataclass(frozen=True)
class _PreparedPlanUpdate:
    snapshot: _PlanUpdateSnapshot
    color_map: Dict
    annotations: tuple


class ViewerSyncCoordinator:
    def __init__(
        self,
        ui_state_manager,
        ui_access_manager,
        color_service,
        project_data,
        callback_bridge,
        plan_update_thread_pool=None,
    ):
        self._ui_state = ui_state_manager
        self._access = ui_access_manager
        self._color_service = color_service
        self._project_data = project_data
        self._remote_update_generation = 0
        self._remote_pipeline = RemotePlanUpdatePipeline(
            callback_bridge=callback_bridge,
            prepare=self._prepare_plan_update,
            apply=self._apply_plan_update,
            is_current=self._is_remote_plan_update_current,
            coalesce=self._coalesce_remote_plan_updates,
            can_coalesce=self._can_coalesce_remote_plan_updates,
            thread_pool=plan_update_thread_pool,
        )
        self.plan_view = None

    def clear_plan_view(self) -> None:
        self._remote_update_generation += 1
        if self.plan_view:
            self.plan_view.clear()

    def _ordered_pages(self) -> List:
        return list(self._project_data.get_all_pages())

    def update_plan_view_for_active(
        self,
        changed_takeoff_uids: Optional[List[str]] = None,
        changed_annotation_uids: Optional[List[str]] = None,
        changed_annotation_types: Optional[List[str]] = None,
    ) -> None:
        uid = self._ui_state.active_page_uid
        if not uid:
            pages = self._project_data.get_selected_page_uids()
            uid = pages[0] if pages else None
        if uid:
            self.update_plan_view(
                uid,
                changed_takeoff_uids=changed_takeoff_uids,
                changed_annotation_uids=changed_annotation_uids,
                changed_annotation_types=changed_annotation_types,
            )
        else:
            self.clear_plan_view()

    def update_plan_view(
        self,
        page_uid: Optional[str],
        changed_takeoff_uids: Optional[List[str]] = None,
        changed_annotation_uids: Optional[List[str]] = None,
        changed_annotation_types: Optional[List[str]] = None,
    ) -> None:
        snapshot = self._capture_plan_update(
            page_uid,
            changed_takeoff_uids=changed_takeoff_uids,
            changed_annotation_uids=changed_annotation_uids,
            changed_annotation_types=changed_annotation_types,
        )
        if snapshot is None:
            self.clear_plan_view()
            return
        self._remote_update_generation += 1
        self._apply_plan_update(self._prepare_plan_update(snapshot))

    def request_remote_plan_update(
        self,
        *,
        database_id: str,
        runtime_generation: int,
        bid_uid: str,
        resource_uids_by_family: dict[str, tuple[str, ...]],
        barrier: RemoteProjectionBarrier,
        completion,
    ) -> bool:
        bid_ref = self._ui_state.get_selected_bid_ref()
        page_uid = self._ui_state.active_page_uid
        if (
            self.plan_view is None
            or bid_ref != BidRef(database_id, bid_uid)
            or not page_uid
            or barrier.database_id != database_id
            or barrier.runtime_generation != runtime_generation
        ):
            return False
        self._remote_update_generation += 1
        takeoff_uids = resource_uids_by_family.get(
            CollaborationResourceFamily.TAKEOFFS.value, ()
        )
        annotation_uids = resource_uids_by_family.get(
            CollaborationResourceFamily.ANNOTATIONS.value, ()
        )
        annotation_identities = tuple(
            parse_annotation_resource_id(resource_id) for resource_id in annotation_uids
        )
        snapshot = self._capture_plan_update(
            page_uid,
            changed_takeoff_uids=list(takeoff_uids),
            changed_annotation_uids=[
                uid for _annotation_type, uid in annotation_identities
            ],
            changed_annotation_types=[
                annotation_type for annotation_type, _uid in annotation_identities
            ],
            remote_identity=_RemotePlanIdentity(
                database_id=database_id,
                bid_uid=bid_uid,
                page_uid=page_uid,
                surface_id="main-plan",
                update_generation=self._remote_update_generation,
                barrier=barrier,
            ),
        )
        if snapshot is None:
            return False
        self._remote_pipeline.submit(snapshot, completion)
        return True

    def _capture_plan_update(
        self,
        page_uid: Optional[str],
        *,
        changed_takeoff_uids: Optional[List[str]] = None,
        changed_annotation_uids: Optional[List[str]] = None,
        changed_annotation_types: Optional[List[str]] = None,
        remote_identity: Optional[_RemotePlanIdentity] = None,
    ) -> Optional[_PlanUpdateSnapshot]:
        if not self.plan_view or not page_uid:
            return None
        page = self._project_data.get_page(page_uid)
        if not page:
            return None
        conditions = deepcopy(self._project_data.get_bid_conditions())
        page_takeoffs = self._project_data.get_page_takeoffs(page_uid)
        page_annotations = self._project_data.get_page_annotations(page_uid)
        copy_for_worker = remote_identity is not None
        if copy_for_worker:
            page = deepcopy(page)
            page_takeoffs = deepcopy(page_takeoffs)
            page_annotations = deepcopy(page_annotations)
        display_mode = self._ui_state.state.display_mode_2d
        grayscale_enabled = self._ui_state.state.grayscale_enabled
        bid_ref = self._ui_state.get_selected_bid_ref()
        bid = self._project_data.get_bid(bid_ref) if bid_ref else None
        return _PlanUpdateSnapshot(
            page=page,
            takeoffs=tuple(page_takeoffs),
            conditions=tuple(conditions.items()),
            annotations=tuple(page_annotations),
            display_mode=display_mode,
            grayscale_enabled=grayscale_enabled,
            place_condition_uids=tuple(self._ui_state.place_condition_uids),
            bid_ref=bid_ref,
            page_area_selections=tuple(
                (
                    deepcopy(self._project_data.get_page_area_selections())
                    if copy_for_worker
                    else self._project_data.get_page_area_selections()
                ).items()
            ),
            hidden_layer_uids=frozenset(self._project_data.get_hidden_layer_uids()),
            snap_settings=((bid.takeoff_increments, bid.measure_base) if bid else None),
            ordered_pages=tuple(
                deepcopy(self._ordered_pages())
                if copy_for_worker
                else self._ordered_pages()
            ),
            changed_takeoff_uids=tuple(changed_takeoff_uids or ()),
            changed_annotation_uids=tuple(changed_annotation_uids or ()),
            changed_annotation_types=tuple(changed_annotation_types or ()),
            remote_identity=remote_identity,
        )

    def _prepare_plan_update(
        self, snapshot: _PlanUpdateSnapshot
    ) -> _PreparedPlanUpdate:
        conditions = dict(snapshot.conditions)
        placement_condition_uids = set(snapshot.place_condition_uids)
        _, color_map = self._color_service.get_color_mapping(
            conditions,
            snapshot.takeoffs,
            snapshot.display_mode,
            snapshot.grayscale_enabled,
            placement_condition_uids,
        )
        annotation_types = snapshot.changed_annotation_types
        if snapshot.changed_annotation_uids and not annotation_types:
            annotations_by_uid = {
                str(annotation.uid): annotation for annotation in snapshot.annotations
            }
            if all(
                uid in annotations_by_uid for uid in snapshot.changed_annotation_uids
            ):
                annotation_types = tuple(
                    str(annotations_by_uid[uid].annotation_type)
                    for uid in snapshot.changed_annotation_uids
                )
                snapshot = replace(snapshot, changed_annotation_types=annotation_types)
        return _PreparedPlanUpdate(
            snapshot=snapshot,
            color_map=color_map,
            annotations=snapshot.annotations,
        )

    def _apply_plan_update(self, prepared: _PreparedPlanUpdate) -> bool:
        if self.plan_view is None:
            return False
        snapshot = prepared.snapshot
        page = snapshot.page
        conditions = dict(snapshot.conditions)
        takeoffs = list(snapshot.takeoffs)
        page_area_selections = dict(snapshot.page_area_selections)
        if (
            self.plan_view.current_page_uid == page.uid
            and self.plan_view.refresh_current_page_overlays(
                page=page,
                takeoffs=takeoffs,
                conditions=conditions,
                color_map=prepared.color_map,
                bid_ref=snapshot.bid_ref,
                annotations=list(prepared.annotations),
                page_area_selections=page_area_selections,
                hidden_layer_uids=set(snapshot.hidden_layer_uids),
                changed_takeoff_uids=list(snapshot.changed_takeoff_uids),
                changed_annotation_uids=list(snapshot.changed_annotation_uids),
                changed_annotation_types=list(snapshot.changed_annotation_types),
            )
        ):
            if snapshot.snap_settings:
                self.plan_view.set_snap_settings(*snapshot.snap_settings)
            return True
        self.plan_view.load_page(
            page=page,
            takeoffs=takeoffs,
            conditions=conditions,
            color_map=prepared.color_map,
            bid_ref=snapshot.bid_ref,
            annotations=list(prepared.annotations),
            page_area_selections=page_area_selections,
            hidden_layer_uids=set(snapshot.hidden_layer_uids),
        )
        if snapshot.snap_settings:
            self.plan_view.set_snap_settings(*snapshot.snap_settings)
        self.plan_view.prefetch_nearby_pages(
            page, list(snapshot.ordered_pages), snapshot.bid_ref
        )
        return True

    def _is_remote_plan_update_current(self, snapshot: _PlanUpdateSnapshot) -> bool:
        identity = snapshot.remote_identity
        if identity is None:
            return False
        return (
            identity.update_generation == self._remote_update_generation
            and identity.surface_id == "main-plan"
            and identity.barrier.is_current()
            and self._ui_state.get_selected_bid_ref()
            == BidRef(identity.database_id, identity.bid_uid)
            and self._ui_state.active_page_uid == identity.page_uid
            and self.plan_view is not None
            and not self.plan_view.has_active_remote_projection_blocker()
        )

    @staticmethod
    def _can_coalesce_remote_plan_updates(
        previous: _PlanUpdateSnapshot, current: _PlanUpdateSnapshot
    ) -> bool:
        previous_identity = previous.remote_identity
        current_identity = current.remote_identity
        if previous_identity is None or current_identity is None:
            return False
        return (
            previous_identity.database_id,
            previous_identity.bid_uid,
            previous_identity.page_uid,
            previous_identity.surface_id,
            previous_identity.barrier.database_id,
            previous_identity.barrier.runtime_generation,
        ) == (
            current_identity.database_id,
            current_identity.bid_uid,
            current_identity.page_uid,
            current_identity.surface_id,
            current_identity.barrier.database_id,
            current_identity.barrier.runtime_generation,
        )

    @staticmethod
    def _coalesce_remote_plan_updates(
        previous: _PlanUpdateSnapshot, current: _PlanUpdateSnapshot
    ) -> _PlanUpdateSnapshot:
        annotation_identities = sorted(
            set(
                zip(
                    previous.changed_annotation_uids,
                    previous.changed_annotation_types,
                )
            )
            | set(
                zip(
                    current.changed_annotation_uids,
                    current.changed_annotation_types,
                )
            )
        )
        return replace(
            current,
            changed_takeoff_uids=tuple(
                sorted(
                    set(previous.changed_takeoff_uids)
                    | set(current.changed_takeoff_uids)
                )
            ),
            changed_annotation_uids=tuple(
                uid for uid, _annotation_type in annotation_identities
            ),
            changed_annotation_types=tuple(
                annotation_type for _uid, annotation_type in annotation_identities
            ),
        )

    def update_license_plan_state(self) -> None:
        if self._access.is_allowed(Feature.VIEW_2D):
            self.update_plan_view_for_active()
        else:
            self.clear_plan_view()

    def cleanup(self) -> None:
        self._remote_update_generation += 1
        self._remote_pipeline.cleanup()
        self._remote_pipeline = None
        self.plan_view = None
        self._ui_state = None
        self._access = None
        self._color_service = None
        self._project_data = None
