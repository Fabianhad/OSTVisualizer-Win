import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
        sync_saves = []
        async_saves = []
        refreshes = []
        changes = SimpleNamespace(deleted_uids=("area-9",))

        def completed(*_args):
            pass

        def save_areas(*args, **kwargs):
            sync_saves.append((args, kwargs))
            return {"saved": True}

        def save_areas_async(*args):
            async_saves.append(args)
            return True

        def inspect_dialog(dialog, _event_bus):
            observed.append(
                (
                    dialog._bid_ref.file_path,
                    dialog._save_async_fn is not None,
                    set(dialog._used_uids),
                    callable(dialog._on_saved_fn),
                )
            )
            # Drive the save callbacks the real dialog was handed: they must
            # reach the backend selected for this database, with its Bid.
            if dialog._save_async_fn is None:
                self.assertEqual(
                    dialog._save_fn(changes), {"saved": True}, "sync save result"
                )
            else:
                self.assertTrue(dialog._save_async_fn(changes, completed))
            return QtWidgets.QDialog.DialogCode.Rejected

        from ost_visualizer.presentation.components import page_settings_bar

        with patch.object(page_settings_bar, "exec_with_ost_blocking", inspect_dialog):
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
                    save_areas_fn=save_areas,
                    save_areas_async_fn=save_areas_async,
                    uses_async_areas_fn=lambda _file_path, value=uses_async: value,
                    refresh_areas_fn=lambda *args: refreshes.append(args)
                    or [BidArea("area-1", "bid-1", "", "Area 1", 1)],
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
        self.assertEqual(
            observed,
            [
                ("access.mdb", False, {"area-1"}, True),
                ("sql-database", True, {"area-1"}, True),
            ],
        )
        # Access saved synchronously (then refreshed); SQL went only through the
        # asynchronous queue with the same Bid identity and completion callback.
        self.assertEqual(
            sync_saves,
            [
                (
                    ("access.mdb", "bid-1", changes),
                    {"publish_database_refreshed_after_write": False},
                )
            ],
        )
        self.assertEqual(refreshes, [("access.mdb", "bid-1", ("area-9",))])
        self.assertEqual(
            async_saves, [(BidRef("sql-database", "bid-1"), changes, completed)]
        )
