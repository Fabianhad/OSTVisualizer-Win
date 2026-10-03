import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.utils.overlay_context_menu import (
    add_overlay_submenu_with_select,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.cover_sheet.path_support import (
    CoverSheetDialog as _path_support_CoverSheetDialog,
    _FakeIconProvider as _path_support__FakeIconProvider,
    _app as _path_support__app,
    _cover_sheet_data as _path_support__cover_sheet_data,
    _first_page_update as _path_support__first_page_update,
    _path_buttons as _path_support__path_buttons,
)


class ImageModeCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_clearing_overlay_only_cover_sheet_row_immediately_owns_original_mode(
        self,
    ):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(
                image_path=r"C:\Plans\original.pdf",
                overlay_image_path=r"C:\Plans\overlay.pdf",
                show_mode=1,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            # Positive control: before the clear the row owns overlay mode and the
            # overlay-only load strategy, so the Original assertions below can only
            # come from the clear action.
            before = _path_support__first_page_update(dialog)
            self.assertEqual(before["overlay_path"], r"C:\Plans\overlay.pdf")
            self.assertEqual(before["show_mode"], 1)
            self.assertEqual(item.text(dialog._SHOW_COLUMN), "Overlay")
            before_strategy = PageLoadStrategyService(
                SimpleNamespace(get_page_size=lambda _path, _index: (3024.0, 2160.0))
            ).determine_load_strategy(
                Page(
                    uid="p1",
                    name="Level 1",
                    image_path=before["image_path"],
                    overlay_image_path=before["overlay_path"],
                    image_show_mode=before["show_mode"],
                    width_pts=3024.0,
                    height_pts=2160.0,
                )
            )
            self.assertFalse(before_strategy.load_main)
            self.assertTrue(before_strategy.load_overlay)
            _overlay_browse, overlay_clear = _path_support__path_buttons(
                dialog, item, 5
            )
            overlay_clear.click()
            page_update = _path_support__first_page_update(dialog)
            self.assertEqual(page_update["overlay_path"], "")
            self.assertEqual(page_update["show_mode"], 0)
            self.assertEqual(item.text(dialog._SHOW_COLUMN), "Original")
            self.assertEqual(
                dialog._show_options("p1"),
                [("Original", 0, None)],
            )
            page = Page(
                uid="p1",
                name="Level 1",
                image_path=page_update["image_path"],
                overlay_image_path=page_update["overlay_path"],
                image_show_mode=page_update["show_mode"],
                width_pts=3024.0,
                height_pts=2160.0,
            )
            strategy = PageLoadStrategyService(
                SimpleNamespace(get_page_size=lambda _path, _index: (3024.0, 2160.0))
            ).determine_load_strategy(page)
            self.assertTrue(strategy.load_main)
            self.assertFalse(strategy.load_overlay)
            self.assertFalse(strategy.load_composite)
            menu = QtWidgets.QMenu(dialog)
            _select_action, overlay_action, original_action = (
                add_overlay_submenu_with_select(
                    menu,
                    page.image_show_mode,
                    lambda: None,
                    True,
                    page.has_overlay,
                )
            )
            self.assertFalse(overlay_action.isEnabled())
            self.assertTrue(original_action.isChecked())
        finally:
            dialog.close()
            dialog.deleteLater()
