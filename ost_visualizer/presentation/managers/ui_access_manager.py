from enum import Enum, auto
from typing import FrozenSet, List, Tuple
from ...application.dtos.collaboration_dtos import ResourceRef
from ...application.events.app_events import AppEvents


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
        self._area_placement_active: bool = False
        self._text_annotation_edit_active: bool = False
        self._placement_coordinator = None
        self._subscriptions: List[Tuple] = []
        self._subscribe(AppEvents.OST_STATUS_CHANGED, self._on_ost_status_changed)
        self.refresh()

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

    def set_area_placement_active(self, active: bool) -> None:
        self._area_placement_active = active

    def set_text_annotation_edit_active(self, active: bool) -> None:
        self._text_annotation_edit_active = bool(active)

    def is_allowed(self, feature: Feature, resource: ResourceRef | None = None) -> bool:
        if resource is None:
            resource = self._current_resource_context(feature)
        return not self._feature_blocked(
            feature,
            require_current_selection=True,
            resource=resource,
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

    def is_project_bid_clipboard_allowed(self, feature: Feature) -> bool:
        if feature not in (Feature.DELETE_BID, Feature.DUPLICATE_BID):
            return self.is_allowed(feature)
        return not self._feature_blocked(
            feature,
            require_current_selection=False,
            resource=None,
        )

    def _feature_blocked(
        self,
        feature: Feature,
        *,
        require_current_selection: bool,
        resource: ResourceRef | None,
    ) -> bool:
        if not isinstance(feature, Feature):
            return True
        if self._text_annotation_edit_active and feature in _TEXT_EDIT_BLOCKED:
            return True
        if self._area_placement_active and feature in _PLACEMENT_BLOCKED:
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
            if not self.is_database_editable(resource):
                return True
        if (
            feature == Feature.PLACE_ANNOTATIONS
            and self._project_data
            and not self._project_data.is_annotation_layer_visible()
        ):
            return True
        if require_current_selection:
            if not self._bid_selected and feature in _REQUIRES_BID:
                return True
            if not self._any_selection and feature in _REQUIRES_ANY_SELECTION:
                return True
            if not self._database_selected and feature in _REQUIRES_DATABASE:
                return True
        return False

    def _on_ost_status_changed(self, active: bool = False) -> None:
        self._ost_active = bool(active)
        self._cancel_place_if_blocked()

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

    def cleanup(self) -> None:
        for event_type, callback in self._subscriptions:
            self._event_bus.unsubscribe(event_type, callback)
        self._subscriptions.clear()
        self._event_bus = None
        self._license_orchestrator = None
        self._transaction_monitor = None
        self._project_data = None
        self._ui_state_manager = None
        self._database_capability_service = None
        self._placement_coordinator = None
