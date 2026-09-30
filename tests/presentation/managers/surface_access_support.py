import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.managers.ui_access_manager import (
    MAIN_PLAN_SURFACE_ID,
    PlanSurfaceAccessContext,
    PlanSurfaceAccessState,
    UIAccessManager,
)


class _EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        self.subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type, callback):
        self.subscribers[event_type].remove(callback)

    def publish(self, event_type, **kwargs):
        for callback in list(self.subscribers.get(event_type, ())):
            callback(**kwargs)


class _License:
    def __init__(self, valid=True):
        self.valid = valid

    def has_valid_license(self):
        return self.valid


class _TransactionMonitor:
    def __init__(self):
        self.active = False

    def is_ost_active(self):
        return self.active


class _ProjectData:
    def __init__(self, bid_ref):
        self.bid_ref = bid_ref
        self.locked = False
        self.annotation_layer_visible = True

    def get_current_bid_ref(self):
        return self.bid_ref

    def is_current_bid_locked(self):
        return self.locked

    def is_annotation_layer_visible(self):
        return self.annotation_layer_visible


class _UiState:
    def __init__(self, bid_ref, page_uid="page-a"):
        self.bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path if bid_ref else None
        self.active_page_uid = page_uid
        self.place_condition_uid = None
        self.selected_project_uid = None
        self.highlighted_condition_uids = set()

    def get_selected_bid_ref(self):
        return self.bid_ref

    def is_database_selected(self):
        return bool(self.selected_file_path)


class _Capabilities:
    def __init__(self):
        self.database_editable = True
        self.locked_pages = set()
        self.requests = []

    def is_editable(self, database_id, resource=None):
        self.requests.append((database_id, resource))
        if not self.database_editable:
            return False
        return not (
            resource is not None
            and resource.resource_type == "page"
            and resource.resource_id in self.locked_pages
        )
