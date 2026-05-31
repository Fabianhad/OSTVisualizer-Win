from enum import Enum, auto
from typing import FrozenSet, List, Tuple
from ...application.events.app_events import AppEvents


class Feature(Enum):
    DELETE_BID = auto()
    DUPLICATE_BID = auto()
    EDIT_PROJECT_TREE_STRUCTURE = auto()
    EDIT_CONDITION_STRUCTURE = auto()
    IMPORT = auto()
    COVER_SHEET = auto()
    EDIT_PAGE_SETTINGS = auto()
    SELECT_PLAN_ITEMS = auto()
    EXPORT = auto()
    VIEW_3D = auto()
    VIEW_2D = auto()
    EXPORT_BID_FILE = auto()
    PLACE_PLAN_ITEMS = auto()
    DUPLICATE_CONDITION = auto()
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
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.DUPLICATE_CONDITION,
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
        Feature.PLACE_PLAN_ITEMS,
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
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.IMPORT,
        Feature.DELETE_BID,
        Feature.DUPLICATE_BID,
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.PLACE_PLAN_ITEMS,
        Feature.DUPLICATE_CONDITION,
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
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.PLACE_PLAN_ITEMS,
        Feature.EXPORT_BID_FILE,
        Feature.DUPLICATE_CONDITION,
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
        Feature.EDIT_PROJECT_TREE_STRUCTURE,
        Feature.EDIT_CONDITION_STRUCTURE,
        Feature.IMPORT,
        Feature.COVER_SHEET,
        Feature.EDIT_PAGE_SETTINGS,
        Feature.SELECT_PLAN_ITEMS,
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.DUPLICATE_CONDITION,
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
        Feature.EXPORT,
        Feature.EXPORT_BID_FILE,
        Feature.PLACE_PLAN_ITEMS,
        Feature.DUPLICATE_CONDITION,
        Feature.DELETE_CONDITION,
        Feature.EDIT_CONDITION,
        Feature.UNLOAD_FILE,
        Feature.EDIT_BID_JOB_STATUS,
        Feature.CREATE_DATABASE,
        Feature.EDIT_MASTER_DATA,
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
    ):
        self._event_bus = event_bus
        self._license_orchestrator = license_orchestrator
        self._transaction_monitor = transaction_monitor
        self._project_data = project_data
        self._ui_state_manager = ui_state_manager
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

    def is_allowed(self, feature: Feature) -> bool:
        if self._text_annotation_edit_active and feature in _TEXT_EDIT_BLOCKED:
            return False
        if self._area_placement_active and feature in _PLACEMENT_BLOCKED:
            return False
        if self._ost_active and feature in _OST_BLOCKED:
            return False
        if self._bid_locked and feature in _LOCK_BLOCKED:
            return False
        if not self.has_license() and feature in _LICENSE_REQUIRED:
            return False
        if not self._bid_selected and feature in _REQUIRES_BID:
            return False
        if not self._any_selection and feature in _REQUIRES_ANY_SELECTION:
            return False
        if not self._database_selected and feature in _REQUIRES_DATABASE:
            return False
        return True

    def _on_ost_status_changed(self, **kwargs) -> None:
        self._ost_active = kwargs.get("active", False)
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
        self._placement_coordinator = None
