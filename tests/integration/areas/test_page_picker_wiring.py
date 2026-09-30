import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import (
    PageSettingsBar as MasterPageSettingsBar,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterPageSettingsBar as _master_data_support_MasterPageSettingsBar,
    _app as _master_data_support__app,
)


class PageAreaPickerBackendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_page_settings_area_picker_selects_backend_with_real_dialog(self):
        observed = []

        def inspect_dialog(dialog, _event_bus):
            observed.append(
                (
                    dialog._bid_ref.file_path,
                    dialog._save_async_fn,
                    set(dialog._used_uids),
                    callable(dialog._on_saved_fn),
                )
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        from ost_visualizer.presentation.components import page_settings_bar

        old_exec = page_settings_bar.exec_with_ost_blocking
        page_settings_bar.exec_with_ost_blocking = inspect_dialog
        try:
            for database_id, uses_async in (
                ("access.mdb", False),
                ("sql-database", True),
            ):
                bar = _master_data_support_MasterPageSettingsBar(
                    _master_data_support_FakeIconProvider(),
                    event_bus=EventBus(),
                    load_areas_fn=lambda _file_path, bid_uid: [
                        BidArea("area-1", bid_uid, "", "Area 1", 1)
                    ],
                    save_areas_fn=lambda *_args, **_kwargs: {},
                    save_areas_async_fn=lambda *_args: True,
                    uses_async_areas_fn=lambda _file_path, value=uses_async: value,
                    refresh_areas_fn=lambda _file_path: None,
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                    get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
                )
                bar.load_bid_areas(
                    BidRef(database_id, "bid-1"),
                    areas_with_takeoff={"area-1"},
                )
                bar.load_page("page-1", 1.0, 1.0, "area-1")
                bar.set_interactive(True)
                try:
                    bar._on_area_browse()
                finally:
                    bar.deleteLater()
        finally:
            page_settings_bar.exec_with_ost_blocking = old_exec
        self.assertEqual(
            [
                (database_id, callback is not None, used, has_saved_callback)
                for database_id, callback, used, has_saved_callback in observed
            ],
            [
                ("access.mdb", False, {"area-1"}, True),
                ("sql-database", True, {"area-1"}, True),
            ],
        )
