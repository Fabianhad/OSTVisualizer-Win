import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.managers.ui_access_manager import Feature


class _Action:
    def __init__(self, callback=None):
        self.enabled = True
        self._callback = callback

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isEnabled(self):
        return self.enabled

    def trigger(self):
        if self._callback:
            self._callback()


class _Menu(_Action):
    pass


class _Access:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_allowed(self, _feature: Feature) -> bool:
        return self.allowed


class _UiState:
    def __init__(self, bid_ref=None):
        self._bid_ref = bid_ref
        self.selected_project_uid = None
        self.active_page_uid = None

    def get_selected_bid_ref(self):
        return self._bid_ref


class _ProjectData:
    def __init__(self, current_bid_ref=None):
        self.current_bid_ref = current_bid_ref
        self.selected_page_uids = ["page-1"]
        self.conditions = {"condition-1": object()}
        self.takeoffs = [object()]
        self.page = Page(uid="page-1", name="A1", width_pts=612.0, height_pts=792.0)

    def get_current_bid_ref(self):
        return self.current_bid_ref

    def get_selected_page_uids(self):
        return list(self.selected_page_uids)

    def has_takeoffs_for_pages(self, page_uids):
        return bool(page_uids and self.takeoffs)

    def get_page(self, _page_uid):
        return self.page

    def get_bid_conditions(self):
        return self.conditions

    def get_all_takeoffs(self):
        return self.takeoffs


def _controller(ui_state, project_data, csv_calls=None):
    controller = MenuController.__new__(MenuController)
    controller.menu_bar = object()
    controller._export_formats = ["html"]
    controller._actions = {
        "export_as_html": _Action(),
        "export_as_pdf": _Action(),
        "export_summary_csv": _Action(
            callback=(
                (lambda: csv_calls.append("csv")) if csv_calls is not None else None
            )
        ),
        "export_as_ost": _Action(),
        "export_as_osp": _Action(),
    }
    controller._menus = {
        "import": _Menu(),
        "export": _Menu(),
        "html export options": _Menu(),
    }
    controller._variable_actions = {}
    controller._tool_action_enabled_state = {}
    controller.window = SimpleNamespace(
        is_takeoff_tab_active=lambda: False,
        is_summary_tab_active=lambda: False,
        get_takeoff_plan_view=lambda: None,
    )
    controller.ui_state_manager = ui_state
    controller.project_data = project_data
    controller.ui_access_manager = _Access()
    controller.handlers = SimpleNamespace(ui_event=SimpleNamespace())
    controller._sync_variable_actions = lambda *_args: None
    controller._should_enable_project_tree_creation = lambda: False
    controller._can_open_master_data_dialog = lambda: False
    return controller


class ExportMenuStateTests(unittest.TestCase):
    def test_import_menu_remains_enabled_when_switching_across_all_tabs(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        tab_state = {"takeoff": False, "summary": False}
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: tab_state["takeoff"],
            is_summary_tab_active=lambda: tab_state["summary"],
            get_takeoff_plan_view=lambda: None,
        )
        for takeoff, summary in ((False, False), (True, False), (False, True)):
            tab_state.update(takeoff=takeoff, summary=summary)
            controller.update_menu_states()
            self.assertTrue(controller._menus["import"].isEnabled())

    def test_import_menu_is_disabled_without_import_capability(self):
        controller = _controller(_UiState(), _ProjectData())
        controller.ui_access_manager = _Access(allowed=False)
        controller.update_menu_states()
        self.assertFalse(controller._menus["import"].isEnabled())

    def test_bid_exports_disable_when_loaded_bid_is_not_selected(self):
        old_bid = BidRef("db.mdb", "old-bid")
        csv_calls = []
        controller = _controller(
            _UiState(bid_ref=None), _ProjectData(old_bid), csv_calls
        )
        controller.update_menu_states()
        self.assertFalse(controller._actions["export_as_html"].isEnabled())
        self.assertFalse(controller._actions["export_as_pdf"].isEnabled())
        self.assertFalse(controller._actions["export_summary_csv"].isEnabled())
        self.assertFalse(controller._actions["export_as_ost"].isEnabled())
        self.assertFalse(controller._actions["export_as_osp"].isEnabled())
        self.assertFalse(controller._menus["export"].isEnabled())
        controller.trigger_menu_action("export_summary_csv")
        self.assertEqual(csv_calls, [])

    def test_bid_exports_enable_from_matching_selected_loaded_bid(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        controller.update_menu_states()
        self.assertTrue(controller._actions["export_as_html"].isEnabled())
        self.assertTrue(controller._actions["export_as_pdf"].isEnabled())
        self.assertTrue(controller._actions["export_summary_csv"].isEnabled())
        self.assertTrue(controller._actions["export_as_ost"].isEnabled())
        self.assertTrue(controller._actions["export_as_osp"].isEnabled())
        self.assertTrue(controller._menus["export"].isEnabled())

    def test_select_current_area_menu_and_handler_require_selection_access(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        selected = []
        plan_view = SimpleNamespace(
            current_page_uid="page-1",
            has_takeoff_objects=True,
            has_selected_takeoffs=False,
            select_takeoffs_in_area=lambda area_uid: selected.append(area_uid),
        )
        controller._actions["select_objects_in_current_area"] = _Action()
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: True,
            is_summary_tab_active=lambda: False,
            get_takeoff_plan_view=lambda: plan_view,
            get_page_settings_bar=lambda: SimpleNamespace(
                get_selected_area_uid=lambda: "area-1"
            ),
        )
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        controller.ui_access_manager = _Access(allowed=False)

        controller.update_menu_states()
        controller._select_objects_in_current_area()

        self.assertFalse(
            controller._actions["select_objects_in_current_area"].isEnabled()
        )
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
