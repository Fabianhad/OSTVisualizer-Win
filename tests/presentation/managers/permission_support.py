from ost_visualizer.presentation.managers.ui_access_manager import Feature


class _License:
    def has_valid_license(self):
        return True


class _UiState:
    def __init__(self, bid_ref):
        self._bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path
        self.selected_project_uid = None
        self.place_condition_uid = None
        self.selected_page_uids = ["page-1"]
        self.active_page_uid = "page-1"
        self.highlighted_condition_uids = set()

    def get_selected_bid_ref(self):
        return self._bid_ref

    def is_database_selected(self):
        return True


class _ToolbarUiState(_UiState):
    selected_project_uid = None
    selected_project_uids = []

    def get_selected_bid_refs(self):
        return [self._bid_ref] if self._bid_ref else []


class _FakeAction:
    def __init__(self):
        self.enabled = None
        self.checked = False

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isChecked(self):
        return self.checked

    def isEnabled(self):
        return bool(self.enabled)


class _FakeLayersSidebar:
    def __init__(self):
        self.interactive = None

    def set_interactive(self, interactive):
        self.interactive = bool(interactive)


class _FakeConditionsSidebar:
    def __init__(self):
        self.create_folder_enabled = None

    def get_selected_condition_uids(self):
        return []

    def get_active_condition_uid(self):
        return None

    def is_condition_placeable(self, _uid):
        return False

    def set_create_enabled(self, _enabled):
        pass

    def set_duplicate_enabled(self, _enabled):
        pass

    def set_copy_enabled(self, _enabled):
        pass

    def set_delete_enabled(self, _enabled):
        pass

    def set_edit_enabled(self, _enabled, read_only_enabled=False):
        pass

    def set_create_folder_enabled(self, enabled):
        self.create_folder_enabled = bool(enabled)


class _FakeTabWidget:
    def __init__(self, index):
        self._index = index

    def currentIndex(self):
        return self._index


class _FakePlanView:
    has_selection = True
    place_condition_uid = None
    current_page_uid = "page-1"

    def __init__(self):
        self.deleted = 0
        self.selected_all = 0
        self.inline_edit_enabled = []

    def selected_takeoff_condition_uid(self):
        return None

    def set_selection_enabled(self, _enabled):
        pass

    def set_editing_enabled(self, _enabled):
        pass

    def set_text_annotation_inline_edit_enabled(self, enabled):
        self.inline_edit_enabled.append(bool(enabled))

    def can_move_overlay_image(self):
        return False

    def delete_selected(self):
        self.deleted += 1

    def select_all(self):
        self.selected_all += 1

    def is_text_annotation_inline_edit_active(self):
        return False


class _FakeAccess:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.checked = []

    def is_allowed(self, feature):
        self.checked.append(feature)
        return feature in self.allowed

    def is_project_bid_clipboard_allowed(
        self, feature, _database_id, _bid_refs, _target_project_uid
    ):
        self.checked.append(feature)
        return feature in self.allowed

    def can_delete_bids(self, _bid_refs):
        self.checked.append(Feature.DELETE_BID)
        return Feature.DELETE_BID in self.allowed

    def can_edit_bid_structure(self, _bid_refs):
        self.checked.append(Feature.EDIT_PROJECT_TREE_STRUCTURE)
        return Feature.EDIT_PROJECT_TREE_STRUCTURE in self.allowed

    def can_delete_projects(self, _database_id, _project_uids):
        self.checked.append(Feature.EDIT_PROJECT_TREE_STRUCTURE)
        return Feature.EDIT_PROJECT_TREE_STRUCTURE in self.allowed

    def subscribe_access_state_changed(self, _callback):
        pass

    def unsubscribe_access_state_changed(self, _callback):
        pass
