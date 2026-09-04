from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, FrozenSet, List, Optional, Tuple
from ...application.dtos.collaboration_dtos import ResourceRef
from ...application.events.app_events import AppEvents
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.file_state import normalize_path

MAIN_PLAN_SURFACE_ID = "main-plan"


class Feature(Enum):
    DELETE_BID = auto()
    DUPLICATE_BID = auto()
    COPY_BID = auto()
    EDIT_PROJECT_TREE_STRUCTURE = auto()
    EDIT_CONDITION_STRUCTURE = auto()
    IMPORT = auto()
    COVER_SHEET = auto()
    EDIT_PAGE_SETTINGS = auto()
    SELECT_PLAN_ITEMS = auto()
    EDIT_PLAN_ITEMS = auto()
    EXPORT = auto()
    VIEW_3D = auto()
    VIEW_2D = auto()
    EXPORT_BID_FILE = auto()
    PLACE_PLAN_ITEMS = auto()
    PLACE_ANNOTATIONS = auto()
    DUPLICATE_CONDITION = auto()
    COPY_CONDITION = auto()
    DELETE_CONDITION = auto()
    EDIT_CONDITION = auto()
    UNLOAD_FILE = auto()
    EDIT_BID_JOB_STATUS = auto()
    CREATE_DATABASE = auto()
    EDIT_MASTER_DATA = auto()
    EDIT_ANNOTATION_TEXT = auto()


@dataclass(frozen=True)
class PlanSurfaceAccessContext:
    surface_id: str
    database_id: str
    bid_ref: Optional[BidRef]
    page_uid: str
    annotation_layer_visible: bool


@dataclass(frozen=True)
class _PlanSurfaceInteractionState:
    area_placement_active: bool = False
    inline_text_edit_active: bool = False


@dataclass(frozen=True)
class PlanSurfaceAccessState:
    can_select_plan_items: bool = False
    can_place_plan_items: bool = False
    can_edit_plan_items: bool = False
    can_place_annotations: bool = False
    can_continue_annotation_placement: bool = False
    can_edit_annotations: bool = False
    can_edit_annotation_text: bool = False
    can_edit_page_settings: bool = False


_OST_BLOCKED: FrozenSet[Feature] = frozenset(
    {
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.COPY_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.DUPLICATE_CONDITION,
        Feature.COPY_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.EDIT_MASTER_DATA,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)
_LOCK_BLOCKED: FrozenSet[Feature] = frozenset(
    {
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.DUPLICATE_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)
_LICENSE_REQUIRED: FrozenSet[Feature] = frozenset(
    {
        Feature.VIEW_3D,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.IMPORT,
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.COPY_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.DUPLICATE_CONDITION,
        Feature.COPY_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.COVER_SHEET,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.CREATE_DATABASE,
        Feature.EDIT_MASTER_DATA,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)
_REQUIRES_BID: FrozenSet[Feature] = frozenset(
    {
        Feature.COVER_SHEET,
        Feature.DUPLICATE_BID,
        Feature.COPY_BID,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.EXPORT_BID_FILE,
        Feature.DUPLICATE_CONDITION,
        Feature.COPY_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)
_REQUIRES_ANY_SELECTION: FrozenSet[Feature] = frozenset(
    {
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
    }
)
_REQUIRES_DATABASE: FrozenSet[Feature] = frozenset(
    {
        Feature.UNLOAD_FILE,
    }
)
_PLACEMENT_BLOCKED: FrozenSet[Feature] = frozenset(
    {
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.COPY_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.DUPLICATE_CONDITION,
        Feature.COPY_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.UNLOAD_FILE,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.CREATE_DATABASE,
        Feature.EDIT_MASTER_DATA,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)
_TEXT_EDIT_BLOCKED: FrozenSet[Feature] = frozenset(
    {
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.DUPLICATE_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.UNLOAD_FILE,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.CREATE_DATABASE,
        Feature.EDIT_MASTER_DATA,
    }
)
_DATABASE_EDIT_FEATURES: FrozenSet[Feature] = frozenset(
    {
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.EDIT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.PLACE_ANNOTATIONS,
        Feature.DUPLICATE_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.CREATE_DATABASE,
        Feature.EDIT_MASTER_DATA,
        Feature.EDIT_ANNOTATION_TEXT,
    }
)


class UIAccessManager:
    def __init__(
        self,
        event_bus,
        license_orchestrator,
        transaction_monitor,
        project_data,
        ui_state_manager,
        database_capability_service,
    ):
        self._event_bus = event_bus
        self._license_orchestrator = license_orchestrator
        self._transaction_monitor = transaction_monitor
        self._project_data = project_data
        self._ui_state_manager = ui_state_manager
        self._database_capability_service = database_capability_service
        self._ost_active: bool = False
        self._surface_interactions: dict[str, _PlanSurfaceInteractionState] = {}
        self._access_state_listeners: List[Callable[[], None]] = []
        self._placement_coordinator = None
        self._subscriptions: List[Tuple] = []
        self._subscribe(AppEvents.OST_STATUS_CHANGED, self._on_ost_status_changed)
        self._subscribe(
            AppEvents.LICENSE_STATUS_CHANGED, self._on_license_status_changed
        )
        try:
            self.refresh()
        except Exception as initialization_error:
            try:
                self.cleanup()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "UI access initialization and cleanup failed",
                    [initialization_error, cleanup_error],
                ) from initialization_error
            raise

    @property
    def _bid_locked(self) -> bool:
        return bool(self._project_data and self._project_data.is_current_bid_locked())

    @property
    def _bid_selected(self) -> bool:
        return bool(
            self._ui_state_manager
            and self._ui_state_manager.get_selected_bid_ref() is not None
        )

    @property
    def _any_selection(self) -> bool:
        if not self._ui_state_manager:
            return False
        return bool(
            self._ui_state_manager.selected_file_path is not None
            or self._ui_state_manager.get_selected_bid_ref() is not None
            or self._ui_state_manager.selected_project_uid is not None
        )

    @property
    def _database_selected(self) -> bool:
        return bool(
            self._ui_state_manager and self._ui_state_manager.is_database_selected()
        )

    def refresh(self) -> None:
        self._ost_active = bool(
            self._transaction_monitor and self._transaction_monitor.is_ost_active()
        )
        self._cancel_place_if_blocked()
        self._notify_access_state_changed()

    def has_license(self) -> bool:
        return bool(
            self._license_orchestrator
            and self._license_orchestrator.has_valid_license()
        )

    def is_bid_locked(self) -> bool:
        return self._bid_locked

    def can_create_project_tree_items(self, has_file_context: bool) -> bool:
        if not has_file_context:
            return False
        return self.is_allowed(Feature.EDIT_PROJECT_TREE_STRUCTURE)

    def can_create_bid(self, database_id: str, project_uid: str | None) -> bool:
        if not database_id:
            return False
        if project_uid and self._feature_blocked(
            Feature.EDIT_PROJECT_TREE_STRUCTURE,
            require_current_selection=False,
            resource=ResourceRef("project", str(project_uid)),
            database_id=database_id,
        ):
            return False
        return not self._feature_blocked(
            Feature.EDIT_PROJECT_TREE_STRUCTURE,
            require_current_selection=False,
            resource=ResourceRef("project_bids", project_uid or "orphan"),
            database_id=database_id,
        )

    def can_create_project(self, database_id: str) -> bool:
        return bool(database_id) and not self._feature_blocked(
            Feature.EDIT_PROJECT_TREE_STRUCTURE,
            require_current_selection=False,
            resource=ResourceRef("projects_collection", "database"),
            database_id=database_id,
        )

    def can_import_project_file(
        self, database_id: str, project_uid: str | None
    ) -> bool:
        if not database_id:
            return False
        if project_uid and self._feature_blocked(
            Feature.IMPORT,
            require_current_selection=False,
            resource=ResourceRef("project", str(project_uid)),
            database_id=database_id,
        ):
            return False
        return not self._feature_blocked(
            Feature.IMPORT,
            require_current_selection=False,
            resource=ResourceRef("project_bids", project_uid or "orphan"),
            database_id=database_id,
        )

    def set_area_placement_active(self, active: bool, *, surface_id: str) -> None:
        self._update_surface_interaction(surface_id, area_placement_active=bool(active))

    def set_text_annotation_edit_active(self, active: bool, *, surface_id: str) -> None:
        self._update_surface_interaction(
            surface_id, inline_text_edit_active=bool(active)
        )

    def clear_plan_surface_interaction(self, surface_id: str) -> None:
        if not surface_id or surface_id not in self._surface_interactions:
            return
        self._surface_interactions.pop(surface_id, None)
        self._notify_access_state_changed()

    def subscribe_access_state_changed(self, callback: Callable[[], None]) -> None:
        if callback not in self._access_state_listeners:
            self._access_state_listeners.append(callback)

    def unsubscribe_access_state_changed(self, callback: Callable[[], None]) -> None:
        try:
            self._access_state_listeners.remove(callback)
        except ValueError:
            pass

    def current_plan_surface_context(self) -> PlanSurfaceAccessContext:
        bid_ref = (
            self._ui_state_manager.get_selected_bid_ref()
            if self._ui_state_manager is not None
            else None
        )
        database_id = (
            str(self._ui_state_manager.selected_file_path or "")
            if self._ui_state_manager is not None
            else ""
        )
        page_uid = (
            str(self._ui_state_manager.active_page_uid or "")
            if self._ui_state_manager is not None
            else ""
        )
        annotation_layer_visible = bool(
            self._project_data and self._project_data.is_annotation_layer_visible()
        )
        return PlanSurfaceAccessContext(
            surface_id=MAIN_PLAN_SURFACE_ID,
            database_id=database_id,
            bid_ref=bid_ref,
            page_uid=page_uid,
            annotation_layer_visible=annotation_layer_visible,
        )

    def get_plan_surface_access(
        self, context: PlanSurfaceAccessContext
    ) -> PlanSurfaceAccessState:
        if not self._is_valid_plan_surface_context(context):
            return PlanSurfaceAccessState()
        page_resource = self._page_resource(context)
        can_select = not self._feature_blocked(
            Feature.SELECT_PLAN_ITEMS,
            require_current_selection=True,
            resource=None,
            context=context,
        )
        can_place_plan = not self._feature_blocked(
            Feature.PLACE_PLAN_ITEMS,
            require_current_selection=True,
            resource=None,
            context=context,
        )
        can_edit_plan = not self._feature_blocked(
            Feature.EDIT_PLAN_ITEMS,
            require_current_selection=True,
            resource=None,
            context=context,
        )
        can_place_annotations = not self._feature_blocked(
            Feature.PLACE_ANNOTATIONS,
            require_current_selection=True,
            resource=None,
            context=context,
        )
        can_continue_annotations = not self._feature_blocked(
            Feature.PLACE_ANNOTATIONS,
            require_current_selection=True,
            resource=None,
            context=context,
            ignore_area_surface_id=context.surface_id,
        )
        can_edit_annotation_text = not self._feature_blocked(
            Feature.EDIT_ANNOTATION_TEXT,
            require_current_selection=True,
            resource=None,
            context=context,
        )
        can_edit_page_settings = bool(page_resource) and not self._feature_blocked(
            Feature.EDIT_PAGE_SETTINGS,
            require_current_selection=True,
            resource=page_resource,
            context=context,
        )
        return PlanSurfaceAccessState(
            can_select_plan_items=can_select,
            can_place_plan_items=can_place_plan,
            can_edit_plan_items=can_edit_plan,
            can_place_annotations=can_place_annotations,
            can_continue_annotation_placement=can_continue_annotations,
            can_edit_annotations=can_edit_plan,
            can_edit_annotation_text=can_edit_annotation_text,
            can_edit_page_settings=can_edit_page_settings,
        )

    def is_allowed(self, feature: Feature, resource: ResourceRef | None = None) -> bool:
        if resource is None:
            resource = self._current_resource_context(feature)
        return not self._feature_blocked(
            feature,
            require_current_selection=True,
            resource=resource,
        )

    def can_duplicate_bid(self, bid_ref: BidRef) -> bool:
        return self._is_bid_action_allowed(Feature.DUPLICATE_BID, bid_ref)

    def can_edit_bid_job_status(self, bid_ref: BidRef) -> bool:
        return self._is_bid_action_allowed(Feature.EDIT_BID_JOB_STATUS, bid_ref)

    def can_delete_bids(self, bid_refs: List[BidRef]) -> bool:
        return bool(bid_refs) and all(
            self._is_bid_action_allowed(Feature.DELETE_BID, bid_ref)
            for bid_ref in bid_refs
        )

    def can_edit_bid_structure(self, bid_refs: List[BidRef]) -> bool:
        return bool(bid_refs) and all(
            not self._feature_blocked(
                Feature.EDIT_PROJECT_TREE_STRUCTURE,
                require_current_selection=False,
                resource=ResourceRef(
                    "bid",
                    str(bid_ref.bid_uid),
                    (
                        int(bid_ref.bid_uid)
                        if str(bid_ref.bid_uid).isdecimal()
                        else None
                    ),
                ),
                database_id=bid_ref.file_path,
            )
            for bid_ref in bid_refs
        )

    def can_edit_project(self, file_path: str, project_uid: str) -> bool:
        storage_uid = int(project_uid) if str(project_uid).isdecimal() else None
        return not self._feature_blocked(
            Feature.EDIT_PROJECT_TREE_STRUCTURE,
            require_current_selection=False,
            resource=ResourceRef("project", str(project_uid), storage_uid),
            database_id=file_path,
        )

    def can_delete_projects(self, database_id: str, project_uids: List[str]) -> bool:
        if not database_id or not project_uids:
            return False
        if any(
            self._feature_blocked(
                Feature.EDIT_PROJECT_TREE_STRUCTURE,
                require_current_selection=False,
                resource=ResourceRef("project", str(project_uid)),
                database_id=database_id,
            )
            for project_uid in project_uids
        ):
            return False
        return not self._feature_blocked(
            Feature.EDIT_PROJECT_TREE_STRUCTURE,
            require_current_selection=False,
            resource=ResourceRef("projects_collection", "database"),
            database_id=database_id,
        )

    def can_close_database(self, database_id: str) -> bool:
        return bool(database_id) and not self._feature_blocked(
            Feature.UNLOAD_FILE,
            require_current_selection=False,
            resource=None,
            database_id=database_id,
        )

    def _is_bid_action_allowed(self, feature: Feature, bid_ref: BidRef) -> bool:
        bid_uid = int(bid_ref.bid_uid) if str(bid_ref.bid_uid).isdecimal() else None
        return not self._feature_blocked(
            feature,
            require_current_selection=False,
            resource=ResourceRef("bid", str(bid_ref.bid_uid), bid_uid),
            database_id=bid_ref.file_path,
        )

    def is_allowed_for_active_placement(
        self,
        feature: Feature,
        resource: ResourceRef | None = None,
    ) -> bool:
        if feature not in {
            Feature.PLACE_PLAN_ITEMS,
            Feature.PLACE_ANNOTATIONS,
        }:
            return False
        if resource is None:
            resource = self._current_resource_context(feature)
        return not self._feature_blocked(
            feature,
            require_current_selection=True,
            resource=resource,
            ignore_area_placement=True,
        )

    def _current_resource_context(self, feature: Feature) -> ResourceRef | None:
        if self._ui_state_manager is None:
            return None
        bid_ref = self._ui_state_manager.get_selected_bid_ref()
        if bid_ref is None:
            project_uid = self._ui_state_manager.selected_project_uid
            if feature == Feature.EDIT_PROJECT_TREE_STRUCTURE and project_uid:
                return ResourceRef("project", str(project_uid))
            return None
        bid_uid = int(bid_ref.bid_uid) if str(bid_ref.bid_uid).isdecimal() else None
        if feature in {
            Feature.DELETE_BID,
            Feature.DUPLICATE_BID,
            Feature.EDIT_BID_JOB_STATUS,
        }:
            return ResourceRef("bid", str(bid_ref.bid_uid), bid_uid)
        if feature == Feature.COVER_SHEET:
            return ResourceRef("cover_sheet", str(bid_ref.bid_uid), bid_uid)
        if feature == Feature.EDIT_PAGE_SETTINGS:
            page_uid = self._ui_state_manager.active_page_uid
            if page_uid:
                return ResourceRef("page", str(page_uid), bid_uid)
        if feature in {
            Feature.EDIT_CONDITION,
            Feature.DELETE_CONDITION,
            Feature.DUPLICATE_CONDITION,
        }:
            highlighted = sorted(self._ui_state_manager.highlighted_condition_uids)
            if len(highlighted) == 1:
                return ResourceRef("condition", highlighted[0], bid_uid)
        if feature == Feature.EDIT_CONDITION_STRUCTURE:
            return ResourceRef("conditions_collection", str(bid_ref.bid_uid), bid_uid)
        return None

    def is_database_editable(self, resource: ResourceRef | None = None) -> bool:
        locator = (
            self._ui_state_manager.selected_file_path
            if self._ui_state_manager is not None
            else None
        )
        if not locator or self._database_capability_service is None:
            return False
        if resource is None:
            return self._database_capability_service.is_editable(locator)
        return self._database_capability_service.is_editable(locator, resource)

    def is_project_bid_clipboard_allowed(
        self,
        feature: Feature,
        database_id: str,
        bid_refs: List[BidRef],
        target_project_uid: str | None,
    ) -> bool:
        if feature not in (Feature.DELETE_BID, Feature.DUPLICATE_BID):
            return False
        database_key = normalize_path(database_id)
        if not bid_refs or any(
            normalize_path(ref.file_path) != database_key for ref in bid_refs
        ):
            return False
        if any(
            self._feature_blocked(
                feature,
                require_current_selection=False,
                resource=ResourceRef(
                    "bid",
                    str(ref.bid_uid),
                    int(ref.bid_uid) if str(ref.bid_uid).isdecimal() else None,
                ),
                database_id=database_id,
            )
            for ref in bid_refs
        ):
            return False
        return not self._feature_blocked(
            feature,
            require_current_selection=False,
            resource=ResourceRef("project_bids", target_project_uid or "orphan"),
            database_id=database_id,
        )

    def _feature_blocked(
        self,
        feature: Feature,
        *,
        require_current_selection: bool,
        resource: ResourceRef | None,
        database_id: str | None = None,
        ignore_area_placement: bool = False,
        context: PlanSurfaceAccessContext | None = None,
        ignore_area_surface_id: str | None = None,
    ) -> bool:
        if not isinstance(feature, Feature):
            return True
        if self._has_inline_text_edit() and feature in _TEXT_EDIT_BLOCKED:
            return True
        if (
            not ignore_area_placement
            and self._has_area_placement(ignore_area_surface_id)
            and feature in _PLACEMENT_BLOCKED
        ):
            return True
        if self._ost_active and feature in _OST_BLOCKED:
            return True
        if self._bid_locked and feature in _LOCK_BLOCKED:
            return True
        if not self.has_license() and feature in _LICENSE_REQUIRED:
            return True
        if (
            feature in _DATABASE_EDIT_FEATURES
            and feature is not Feature.CREATE_DATABASE
        ):
            if context is None:
                editable = (
                    self._database_capability_service.is_editable(database_id, resource)
                    if database_id is not None
                    and self._database_capability_service is not None
                    else self.is_database_editable(resource)
                )
            else:
                editable = self._is_context_database_editable(context, resource)
            if not editable:
                return True
        if feature == Feature.PLACE_ANNOTATIONS and not (
            context.annotation_layer_visible
            if context is not None
            else bool(
                self._project_data and self._project_data.is_annotation_layer_visible()
            )
        ):
            return True
        if require_current_selection:
            has_bid = (
                context.bid_ref is not None
                if context is not None
                else self._bid_selected
            )
            has_selection = (
                bool(context.database_id or context.bid_ref)
                if context is not None
                else self._any_selection
            )
            has_database = (
                bool(context.database_id)
                if context is not None
                else self._database_selected
            )
            if not has_bid and feature in _REQUIRES_BID:
                return True
            if not has_selection and feature in _REQUIRES_ANY_SELECTION:
                return True
            if not has_database and feature in _REQUIRES_DATABASE:
                return True
        return False

    def _on_ost_status_changed(self, active: bool = False) -> None:
        self._ost_active = bool(active)
        self._cancel_place_if_blocked()
        self._notify_access_state_changed()

    def _on_license_status_changed(self, has_license: bool = False) -> None:
        del has_license
        self._notify_access_state_changed()

    def set_placement_coordinator(self, placement_coordinator) -> None:
        self._placement_coordinator = placement_coordinator

    def _cancel_place_if_blocked(self) -> None:
        if not self._ui_state_manager:
            return
        if self._ui_state_manager.place_condition_uid and not self.is_allowed(
            Feature.PLACE_PLAN_ITEMS
        ):
            if self._placement_coordinator:
                self._placement_coordinator.force_exit()

    def _subscribe(self, event_type, callback) -> None:
        self._event_bus.subscribe(event_type, callback)
        self._subscriptions.append((event_type, callback))

    def _update_surface_interaction(
        self,
        surface_id: str,
        *,
        area_placement_active: Optional[bool] = None,
        inline_text_edit_active: Optional[bool] = None,
    ) -> None:
        if not surface_id:
            return
        current = self._surface_interactions.get(
            surface_id, _PlanSurfaceInteractionState()
        )
        updated = _PlanSurfaceInteractionState(
            area_placement_active=(
                current.area_placement_active
                if area_placement_active is None
                else bool(area_placement_active)
            ),
            inline_text_edit_active=(
                current.inline_text_edit_active
                if inline_text_edit_active is None
                else bool(inline_text_edit_active)
            ),
        )
        if updated == current:
            return
        if updated == _PlanSurfaceInteractionState():
            self._surface_interactions.pop(surface_id, None)
        else:
            self._surface_interactions[surface_id] = updated
        self._notify_access_state_changed()

    def _has_area_placement(self, ignore_surface_id: str | None = None) -> bool:
        return any(
            state.area_placement_active
            for surface_id, state in self._surface_interactions.items()
            if surface_id != ignore_surface_id
        )

    def _has_inline_text_edit(self) -> bool:
        return any(
            state.inline_text_edit_active
            for state in self._surface_interactions.values()
        )

    def _notify_access_state_changed(self) -> None:
        for callback in list(self._access_state_listeners):
            callback()

    def _is_valid_plan_surface_context(self, context: PlanSurfaceAccessContext) -> bool:
        if (
            not context.surface_id
            or not context.database_id
            or context.bid_ref is None
            or not context.page_uid
            or context.database_id != str(context.bid_ref.file_path or "")
        ):
            return False
        current_bid_ref = (
            self._project_data.get_current_bid_ref() if self._project_data else None
        )
        return context.bid_ref == current_bid_ref

    @staticmethod
    def _page_resource(
        context: PlanSurfaceAccessContext,
    ) -> ResourceRef | None:
        if context.bid_ref is None or not context.page_uid:
            return None
        bid_value = str(context.bid_ref.bid_uid)
        bid_uid = int(bid_value) if bid_value.isdecimal() else None
        return ResourceRef("page", str(context.page_uid), bid_uid)

    def _is_context_database_editable(
        self,
        context: PlanSurfaceAccessContext,
        resource: ResourceRef | None = None,
    ) -> bool:
        if not context.database_id or self._database_capability_service is None:
            return False
        if resource is None:
            return self._database_capability_service.is_editable(context.database_id)
        return self._database_capability_service.is_editable(
            context.database_id, resource
        )

    def cleanup(self) -> None:
        failures = []
        remaining = []
        event_bus = self._event_bus
        if event_bus is not None:
            for event_type, callback in self._subscriptions:
                try:
                    event_bus.unsubscribe(event_type, callback)
                except Exception as exc:
                    failures.append(exc)
                    remaining.append((event_type, callback))
        self._subscriptions = remaining
        if failures:
            raise ExceptionGroup("UI access cleanup failed", failures)
        self._access_state_listeners.clear()
        self._surface_interactions.clear()
        self._event_bus = None
        self._license_orchestrator = None
        self._transaction_monitor = None
        self._project_data = None
        self._ui_state_manager = None
        self._database_capability_service = None
        self._placement_coordinator = None
