import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TrackableSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        self.disconnected.append(callback)


class CleanupSignal:
    def __init__(self):
        self.disconnected = []
        self.fail_disconnect = False

    def disconnect(self, callback):
        self.disconnected.append(callback)
        if self.fail_disconnect:
            raise RuntimeError("disconnect failed")


class CleanupPlanView:
    def __init__(self):
        self.page_geometry_ready = CleanupSignal()
        self.page_fully_loaded = CleanupSignal()
        self.page_view_state_changed = CleanupSignal()
        self.positions_flushed = CleanupSignal()
        self.annotation_text_properties_flushed = CleanupSignal()
        self.annotation_styles_flushed = CleanupSignal()
        self.elements_deleted = CleanupSignal()
        self.annotation_created = CleanupSignal()
        self.text_annotation_created = CleanupSignal()
        self.named_view_created = CleanupSignal()
        self.hotlink_placement_requested = CleanupSignal()
        self.geometry_edit_lease_requested = CleanupSignal()
        self.plan_item_selection_changed = CleanupSignal()
        self.cursor_mode_change_requested = CleanupSignal()
        self.area_placement_in_progress = CleanupSignal()
        self.text_annotation_edit_mode_changed = CleanupSignal()
        self.undo_requested = CleanupSignal()
        self.redo_requested = CleanupSignal()
        self.blocked = None
        self.cleaned = False
        self.fail_disable_geometry_edit_leasing = False

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)

    def cleanup(self):
        self.cleaned = True

    def disable_geometry_edit_leasing(self):
        if self.fail_disable_geometry_edit_leasing:
            raise RuntimeError("lease UI cleanup failed")


class CleanupCombo:
    def __init__(self):
        self.page_activated = CleanupSignal()
        self.currentIndexChanged = CleanupSignal()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True

    def cleanup_popup(self):
        self.cleaned = True


class TrackableDetachedWindow:
    def __init__(self):
        self.installed_filters = []
        self.dropdown_size_changed = TrackableSignal()
        self.destroyed = TrackableSignal()

    def installEventFilter(self, event_filter):
        self.installed_filters.append(event_filter)

    def removeEventFilter(self, event_filter):
        if event_filter in self.installed_filters:
            self.installed_filters.remove(event_filter)


class FakeSignal:
    def __init__(self, calls):
        self._calls = calls

    def connect(self, callback):
        self._calls.append("destroyed_connected")


class FakeConstructedWindow:
    def __init__(self, calls):
        self._calls = calls
        self.destroyed = FakeSignal(calls)
        self.area_placement_state_changed = TrackableSignal()
        self.inline_text_edit_state_changed = TrackableSignal()
        self.annotation_tools_enabled = False
        self.closed = False

    def set_access_state(self, access_state):
        self.annotation_tools_enabled = access_state.can_place_annotations
        self._calls.append(("set_access_state", access_state))

    def show_when_page_ready(self):
        self._calls.append("show_when_page_ready")

    def close(self):
        self.closed = True
        self._calls.append("close")
