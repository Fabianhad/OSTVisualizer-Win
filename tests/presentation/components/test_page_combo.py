import os
import sys
import unittest
from pathlib import Path
from unittest import mock
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.folder import Folder
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.presentation.components.page_combo import (
    _ITEM_ROLE_KIND,
    _ITEM_ROLE_PAGE,
    _ITEM_ROLE_PRECHECK_ICON,
    _ITEM_ROLE_UID,
    PageComboBox,
    SinglePageComboBox,
    _PageComboItemDelegate,
    _format_page_label,
)
from ost_visualizer.presentation.config import VIEWER_PAGE_COMBO_MIN_WIDTH
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import isValid
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.page_combo import PageComboBox
from PySide6 import QtWidgets
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyPageInfo,
    HierarchyFolderInfo,
)
import tests.integration.pages.test_set_scale_apply as scale_fixture

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PageComboPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_page_label_preferences_update_page_combo_labels(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(
                    uid="p1",
                    name="A101",
                    sheet_no="S1",
                    sequence=3,
                    page_index=0,
                )
            ],
        )
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.set_label_options(True, False)
        self.assertEqual(combo._page_items["p1"].text(), "3 - A101")
        combo.set_label_options(False, True)
        self.assertEqual(combo._page_items["p1"].text(), "S1 - A101")
        combo.set_label_options(True, True)
        self.assertEqual(combo._page_items["p1"].text(), "3 - S1 - A101")
        combo.set_label_options(False, False)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.close()

    def test_page_label_options_apply_to_pages_inside_nested_folders(self):
        nested = Folder(
            uid="f2",
            name="Nested",
            pages=[Page(uid="p2", name="A102", sheet_no="S2", sequence=2)],
        )
        folder = Folder(
            uid="f1",
            name="Folder",
            pages=[Page(uid="p1", name="A101", sheet_no="S1", sequence=1)],
            subfolders={"f2": nested},
        )
        bid = Bid(uid="bid-1", name="Bid", folders={"f1": folder})
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = combo_type()
                combo.set_label_options(True, True)
                combo.load_bid(bid)
                self.assertEqual(combo._page_items["p1"].text(), "1 - S1 - A101")
                self.assertEqual(combo._page_items["p2"].text(), "2 - S2 - A102")
                combo.set_label_options(False, False)
                self.assertEqual(combo._page_items["p1"].text(), "A101")
                self.assertEqual(combo._page_items["p2"].text(), "A102")
                self.assertEqual(combo.get_page_order(), ["p2", "p1"])
                combo.cleanup()
                combo.deleteLater()

    def test_page_combo_emits_every_uncheck_switch_and_recheck_state(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid="page-a", name="A101"),
                    Page(uid="page-b", name="A102"),
                ],
            )
        )
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        combo._page_items["page-b"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["page-b"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(
            emitted,
            [["page-a"], [], ["page-b"], [], ["page-a"]],
        )
        combo.close()

    @staticmethod
    def _folder_bid():
        nested = Folder(
            uid="f2",
            name="Nested",
            pages=[Page(uid="p3", name="A103"), Page(uid="p4", name="A104")],
        )
        folder = Folder(
            uid="f1",
            name="Folder",
            pages=[Page(uid="p1", name="A101"), Page(uid="p2", name="A102")],
            subfolders={"f2": nested},
        )
        other = Folder(uid="f3", name="Other", pages=[Page(uid="p5", name="A105")])
        return Bid(
            uid="bid-1",
            name="Bid",
            folders={"f1": folder, "f3": other},
            pages_without_folder=[Page(uid="p6", name="A106")],
        )

    @staticmethod
    def _folder_item(combo, name):
        model = combo.popup_model()
        stack = [model.invisibleRootItem()]
        while stack:
            parent = stack.pop()
            for row in range(parent.rowCount()):
                child = parent.child(row)
                if child.text() == name:
                    return child
                stack.append(child)
        raise AssertionError(name)

    def test_folder_checkbox_checks_and_unchecks_every_page_beneath_it(self):
        combo = PageComboBox()
        combo.load_bid(self._folder_bid())
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        folder = self._folder_item(combo, "Folder")
        nested = self._folder_item(combo, "Nested")
        self.assertTrue(folder.isCheckable())
        folder.setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(len(emitted), 1)
        self.assertCountEqual(emitted[0], ["p1", "p2", "p3", "p4"])
        self.assertCountEqual(combo.get_selected_page_uids(), ["p1", "p2", "p3", "p4"])
        self.assertEqual(nested.checkState(), QtCore.Qt.CheckState.Checked)
        self.assertEqual(
            self._folder_item(combo, "Other").checkState(),
            QtCore.Qt.CheckState.Unchecked,
        )
        self.assertEqual(
            combo._page_items["p5"].checkState(), QtCore.Qt.CheckState.Unchecked
        )
        folder.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(emitted[-1], [])
        self.assertEqual(len(emitted), 2)
        self.assertEqual(nested.checkState(), QtCore.Qt.CheckState.Unchecked)
        for uid in ("p1", "p2", "p3", "p4"):
            self.assertEqual(
                combo._page_items[uid].checkState(), QtCore.Qt.CheckState.Unchecked
            )
        combo.close()

    def test_folder_checkbox_keeps_pages_checked_elsewhere(self):
        combo = PageComboBox()
        combo.load_bid(self._folder_bid())
        combo._page_items["p5"].setCheckState(QtCore.Qt.CheckState.Checked)
        folder = self._folder_item(combo, "Folder")
        folder.setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(combo.get_selected_page_uids()[0], "p5")
        folder.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(combo.get_selected_page_uids(), ["p5"])
        combo.close()

    def test_folder_checkbox_is_partial_until_all_pages_are_checked(self):
        combo = PageComboBox()
        combo.load_bid(self._folder_bid())
        folder = self._folder_item(combo, "Folder")
        nested = self._folder_item(combo, "Nested")
        combo._page_items["p3"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(nested.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        combo._page_items["p4"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(nested.checkState(), QtCore.Qt.CheckState.Checked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        combo._page_items["p1"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["p2"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Checked)
        combo._page_items["p2"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        for uid in ("p1", "p3", "p4"):
            combo._page_items[uid].setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(nested.checkState(), QtCore.Qt.CheckState.Unchecked)
        combo.close()

    def test_toggling_a_partial_folder_checks_all_of_its_pages(self):
        combo = PageComboBox()
        combo.load_bid(self._folder_bid())
        folder = self._folder_item(combo, "Folder")
        combo._page_items["p1"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        # The view toggles a partially checked, non-tristate item to Checked.
        folder.setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "p1")
        self.assertCountEqual(emitted[0], ["p1", "p2", "p3", "p4"])
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Checked)
        combo.close()

    def test_folder_checkbox_state_follows_reload_and_restore(self):
        combo = PageComboBox()
        bid = self._folder_bid()
        combo.load_bid(bid)
        folder = self._folder_item(combo, "Folder")
        combo.restore_selection(["p1", "p2", "p3", "p4"], "p1")
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Checked)
        combo.restore_selection(["p1"], "p1")
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        combo.load_bid(bid)
        self.assertEqual(
            self._folder_item(combo, "Folder").checkState(),
            QtCore.Qt.CheckState.PartiallyChecked,
        )
        combo.clear()
        combo.close()

    def test_folder_without_pages_has_no_checkbox(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                folders={"f1": Folder(uid="f1", name="Empty")},
            )
        )
        self.assertFalse(self._folder_item(combo, "Empty").isCheckable())
        combo.close()

    def test_clicking_a_folder_checkbox_selects_its_pages(self):
        combo = PageComboBox()
        combo.load_bid(self._folder_bid())
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        tree = combo._tree
        folder = self._folder_item(combo, "Folder")
        index = folder.index()
        rect = combo._page_delegate.checkbox_rect(
            tree.style(), tree, index, tree.visualRect(index)
        )
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        QTest.mouseClick(
            tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
        )
        self.assertEqual(len(emitted), 1)
        self.assertCountEqual(emitted[0], ["p1", "p2", "p3", "p4"])
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Checked)
        QTest.mouseClick(
            tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center()
        )
        self.assertEqual(emitted[-1], [])
        self.assertEqual(folder.checkState(), QtCore.Qt.CheckState.Unchecked)
        combo.close()

    def test_unchecking_final_3d_page_preserves_active_2d_page(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-a", name="A101")],
            )
        )
        combo.restore_selection(["page-a"], active_uid="page-a")
        active_changes = []
        combo.active_page_changed.connect(active_changes.append)
        combo._page_items["page-a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertEqual(combo.get_active_page_uid(), "page-a")
        self.assertEqual(active_changes, [])
        self.assertEqual(combo.lineEdit().text(), "A101")
        combo.close()

    def test_page_combo_does_not_emit_selection_for_label_or_indicator_updates(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid="page-a", name="A101", sequence=1),
                    Page(uid="page-b", name="A102", sequence=2),
                ],
            )
        )
        combo.restore_selection(["page-a"], active_uid="page-a")
        emitted = []
        combo.page_selection_changed.connect(lambda pages: emitted.append(list(pages)))
        active_changes = []
        combo.active_page_changed.connect(active_changes.append)
        default_key = combo._draft_icon_default.cacheKey()
        active_key = combo._draft_icon_active.cacheKey()
        self.assertNotEqual(default_key, active_key)
        combo.set_page_has_takeoffs("page-a", True)
        self.assertEqual(
            combo._page_items["page-a"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
            active_key,
        )
        combo.set_pages_with_takeoffs({"page-b"})
        self.assertEqual(
            combo._page_items["page-a"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
            default_key,
        )
        self.assertEqual(
            combo._page_items["page-b"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
            active_key,
        )
        combo.set_label_options(True, False)
        self.assertEqual(combo._page_items["page-a"].text(), "1 - A101")
        self.assertEqual(emitted, [])
        self.assertEqual(active_changes, [])
        self.assertEqual(combo.get_selected_page_uids(), ["page-a"])
        combo.close()

    def test_page_combo_same_bid_reload_preserves_navigation_state_by_uid(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="page-a", name="Duplicate"),
                Page(uid="page-b", name="Duplicate"),
                Page(uid="page-c", name="A103"),
            ],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-b"], active_uid="page-b")
        combo.load_bid(bid)
        order = combo.get_page_order()
        self.assertEqual(order, ["page-a", "page-b", "page-c"])
        self.assertEqual(combo.get_selected_page_uids(), ["page-b"])
        self.assertEqual(combo.get_active_page_uid(), "page-b")
        self.assertEqual(combo.lineEdit().text(), "Duplicate")
        self.assertEqual(
            combo._page_items["page-b"].checkState(), QtCore.Qt.CheckState.Checked
        )
        self.assertEqual(
            combo._page_items["page-a"].checkState(), QtCore.Qt.CheckState.Unchecked
        )
        combo.go_next()
        self.assertEqual(combo.get_active_page_uid(), "page-c")
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "page-b")
        combo.close()

    def test_page_combo_model_refresh_notifies_navigation_without_reselecting(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="page-a", name="A101")],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-a"], active_uid="page-a")
        active_changes = []
        selection_changes = []
        model_changes = []
        combo.active_page_changed.connect(active_changes.append)
        combo.page_selection_changed.connect(selection_changes.append)
        combo.navigation_state_changed.connect(lambda: model_changes.append(True))
        combo.load_bid(bid)
        self.assertEqual(active_changes, [])
        self.assertEqual(selection_changes, [])
        self.assertEqual(combo.get_selected_page_uids(), ["page-a"])
        self.assertEqual(model_changes, [True])
        self.assertEqual(combo.lineEdit().text(), "A101")
        combo.close()

    def test_page_combo_model_refresh_keeps_arrow_actions_projected(self):
        combo = PageComboBox()
        previous_action = QtGui.QAction(combo)
        next_action = QtGui.QAction(combo)

        def update_actions(*_args):
            order = combo.get_page_order()
            active_uid = combo.get_active_page_uid()
            index = order.index(active_uid) if active_uid in order else -1
            previous_action.setEnabled(index > 0)
            next_action.setEnabled(index >= 0 and index < len(order) - 1)

        combo.active_page_changed.connect(update_actions)
        combo.navigation_state_changed.connect(update_actions)
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="page-a", name="A101"),
                Page(uid="page-b", name="A102"),
                Page(uid="page-c", name="A103"),
            ],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-b"], active_uid="page-b")
        self.assertTrue(previous_action.isEnabled())
        self.assertTrue(next_action.isEnabled())
        previous_action.setEnabled(False)
        next_action.setEnabled(False)
        combo.load_bid(bid)
        self.assertEqual(combo.lineEdit().text(), "A102")
        self.assertTrue(previous_action.isEnabled())
        self.assertTrue(next_action.isEnabled())
        combo.clear()
        self.assertFalse(previous_action.isEnabled())
        self.assertFalse(next_action.isEnabled())
        combo.close()

    def test_page_combo_different_bid_reload_does_not_reuse_colliding_page_uid(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="First",
                pages_without_folder=[Page(uid="1", name="First page")],
            )
        )
        combo.restore_selection(["1"], active_uid="1")
        combo.load_bid(
            Bid(
                uid="bid-2",
                name="Second",
                pages_without_folder=[Page(uid="1", name="Second page")],
            )
        )
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(combo.lineEdit().text(), "")
        self.assertEqual(
            combo._page_items["1"].checkState(), QtCore.Qt.CheckState.Unchecked
        )
        combo.close()

    @staticmethod
    def _mouse_event(event_type, button_state):
        return QtGui.QMouseEvent(
            event_type,
            QtCore.QPointF(5.0, 5.0),
            QtCore.QPointF(5.0, 5.0),
            QtCore.Qt.MouseButton.LeftButton,
            button_state,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _press_and_release_on_page(self, combo, press_page_uid, rebuild_bid=None):
        press_index = combo._page_items[press_page_uid].index()
        press = self._mouse_event(
            QtCore.QEvent.Type.MouseButtonPress, QtCore.Qt.MouseButton.LeftButton
        )
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=press_index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            combo.eventFilter(combo._tree.viewport(), press)
        if rebuild_bid is not None:
            combo.load_bid(rebuild_bid)
        release_index = combo._page_items[press_page_uid].index()
        release = self._mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease, QtCore.Qt.MouseButton.NoButton
        )
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=release_index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            return combo.eventFilter(combo._tree.viewport(), release)

    def test_page_combo_press_release_on_same_page_activates_it(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-a", name="A101")],
            )
        )
        activated = []
        combo.active_page_changed.connect(activated.append)
        self._press_and_release_on_page(combo, "page-a")
        self.assertEqual(combo.get_active_page_uid(), "page-a")
        self.assertEqual(activated, ["page-a"])
        combo.close()

    def test_page_combo_model_rebuild_cancels_pressed_page_activation(self):
        combo = PageComboBox()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-a", name="A101")],
            )
        )
        activated = []
        combo.active_page_changed.connect(activated.append)
        handled = self._press_and_release_on_page(
            combo,
            "page-a",
            rebuild_bid=Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-a", name="A101 renamed")],
            ),
        )
        self.assertTrue(handled)
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(activated, [])
        combo.close()

    def test_page_combo_one_page_refresh_keeps_text_with_no_navigation(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="page-a", name="A101")],
        )
        combo.load_bid(bid)
        combo.restore_selection(["page-a"], active_uid="page-a")
        combo.load_bid(bid)
        self.assertEqual(combo.get_page_order(), ["page-a"])
        self.assertEqual(combo.get_active_page_uid(), "page-a")
        self.assertEqual(combo.lineEdit().text(), "A101")
        combo.go_prev()
        combo.go_next()
        self.assertEqual(combo.get_active_page_uid(), "page-a")
        combo.close()

    def test_page_label_index_uses_sequence_not_pdf_page_index(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sequence=7, page_index=0),
                Page(uid="p2", name="A102", sequence=8, page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "7 - A101")
        self.assertEqual(combo._page_items["p2"].text(), "8 - A102")
        self.assertNotEqual(combo._page_items["p1"].text(), "1 - A101")
        self.assertNotEqual(combo._page_items["p2"].text(), "1 - A102")
        combo.restore_selection(["p2"], active_uid="p2")
        self.assertEqual(combo.get_selected_page_uids(), ["p2"])
        self.assertEqual(combo.get_active_page_uid(), "p2")
        self.assertEqual(combo.lineEdit().text(), "8 - A102")
        combo.close()

    def test_page_label_missing_sequence_does_not_show_duplicate_one(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", page_index=0),
                Page(uid="p2", name="A102", page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        self.assertEqual(combo._page_items["p2"].text(), "A102")
        combo.close()

    def test_multi_page_combo_cleanup_releases_popup_after_state_clear(self):
        combo = PageComboBox()
        try:
            combo.load_bid(
                Bid(
                    uid="bid-1",
                    name="Bid",
                    pages_without_folder=[Page(uid="p1", name="A101")],
                )
            )
            tree = combo._tree
            popup = combo._popup
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._selected_uids)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
            self.assertIsNone(tree.model())
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(popup))
        finally:
            combo.deleteLater()

    def test_single_page_combo_uses_shared_page_label_format(self):
        combo = SinglePageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sheet_no="S1", sequence=3)
            ],
        )
        combo.set_label_options(True, True)
        combo.load_bid(bid)
        combo.set_current_page_uid("p1")
        self.assertEqual(combo.lineEdit().text(), "3 - S1 - A101")
        combo.close()

    def test_single_page_combo_cleanup_releases_popup_after_state_clear(self):
        combo = SinglePageComboBox()
        try:
            combo.load_bid(
                Bid(
                    uid="bid-1",
                    name="Bid",
                    pages_without_folder=[Page(uid="p1", name="A101")],
                )
            )
            tree = combo._tree
            popup = combo._popup
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
            self.assertIsNone(tree.model())
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(popup))
        finally:
            combo.deleteLater()

    def test_single_page_combo_clears_deleted_selected_page_on_reload(self):
        combo = SinglePageComboBox()
        first_bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="p1", name="A101")],
        )
        refreshed_bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[Page(uid="p2", name="A102")],
        )
        combo.load_bid(first_bid)
        combo.set_current_page_uid("p1")
        self.assertEqual(combo._selected_uid, "p1")
        combo.load_bid(refreshed_bid)
        self.assertEqual(combo._selected_uid, "")
        self.assertEqual(combo.lineEdit().text(), "")
        combo.set_current_page_uid("missing")
        self.assertEqual(combo._selected_uid, "")
        combo.close()

    def test_single_page_combo_same_page_reload_keeps_selection_without_activation(
        self,
    ):
        combo = SinglePageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101"),
                Page(uid="p2", name="A102"),
            ],
        )
        combo.load_bid(bid)
        combo.set_current_page_uid("p2")
        activated = []
        combo.page_activated.connect(activated.append)
        combo.load_bid(bid)
        self.assertEqual(combo._selected_uid, "p2")
        self.assertEqual(combo.lineEdit().text(), "A102")
        self.assertEqual(activated, [])
        combo.close()


class PageScaleSurfaceSyncRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_page_combo_reports_whether_active_page_signal_was_emitted(self) -> None:
        page = Page(uid="page-1", name="A101")
        combo = PageComboBox()
        self.addCleanup(combo.close)
        combo.load_bid(Bid(uid="7", name="Bid", pages_without_folder=[page]))
        emitted = []
        combo.active_page_changed.connect(emitted.append)
        self.assertTrue(combo.restore_selection([page.uid], page.uid))
        self.assertFalse(combo.restore_selection([page.uid], page.uid))
        self.assertEqual(emitted, [page.uid])


class RefreshScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scale_fixture.SetScaleRepeatedApplyTests.setUpClass()

    def setUp(self):
        self.fixture = scale_fixture.SetScaleRepeatedApplyTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        self.info = HierarchyPageInfo("42", "Page 42")
        self.fixture.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        "test.mdb",
                        orphan_bids=[
                            HierarchyBidInfo("7", pages_without_folder=[self.info])
                        ],
                    )
                ]
            )
        )

    def test_page_label_projection_keeps_qt_items_selection_and_signals(self):
        bid = self.fixture.model.current_bid
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = combo_type()
                combo.load_bid(bid)
                calls = []
                if isinstance(combo, PageComboBox):
                    combo.restore_selection(["42"], "42")
                    combo.page_selection_changed.connect(
                        lambda *_args: calls.append("selection")
                    )
                else:
                    combo.set_current_page_uid("42")
                    combo.page_activated.connect(
                        lambda *_args: calls.append("activation")
                    )
                item = combo._page_items["42"]
                state = item.checkState()
                combo._model.modelReset.connect(lambda: calls.append("reset"))
                combo._model.itemChanged.connect(lambda *_: calls.append("item"))
                combo._model.dataChanged.connect(lambda *_: calls.append("data"))
                self.fixture.original.name = "New label"
                combo.refresh_page_labels([self.fixture.original])
                self.assertIs(combo._page_items["42"], item)
                self.assertEqual(item.text(), "New label")
                self.assertEqual(item.checkState(), state)
                self.assertIs(item.data(_ITEM_ROLE_PAGE), self.fixture.original)
                self.assertEqual(combo.currentText(), "New label")
                self.assertEqual(calls, [])
                combo.cleanup()
                combo.deleteLater()


def _two_page_bid(uid="bid-1"):
    return Bid(
        uid=uid,
        name="Bid",
        pages_without_folder=[
            Page(uid="p1", name="A101", sheet_no="S1", sequence=1),
            Page(uid="p2", name="A102", sheet_no="S2", sequence=2),
        ],
    )


class _ComboTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def make(self, combo_type=PageComboBox):
        combo = combo_type()
        self.addCleanup(combo.close)
        return combo

    def capture_slot_errors(self):
        """Collect exceptions raised inside Qt slots (PySide prints them, never raises)."""
        errors = []
        previous = sys.excepthook
        sys.excepthook = lambda *args: errors.append(args)
        self.addCleanup(setattr, sys, "excepthook", previous)
        return errors


class PageComboItemDelegateTests(_ComboTestCase):
    """The delegate that reserves room for, and paints, the takeoff indicator."""

    def test_icon_rect_is_centred_vertically_at_the_row_origin(self):
        rect = _PageComboItemDelegate.icon_rect(QtCore.QRect(10, 20, 100, 31))
        self.assertEqual(rect, QtCore.QRect(10, 27, 16, 16))

    def _paint(self, role_icon, with_decoration=False):
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("Row text")
        if role_icon is not None:
            item.setData(role_icon, _ITEM_ROLE_PRECHECK_ICON)
        if with_decoration:
            pixmap = QtGui.QPixmap(16, 16)
            pixmap.fill(QtGui.QColor("green"))
            item.setIcon(QtGui.QIcon(pixmap))
        model.appendRow(item)
        delegate = _PageComboItemDelegate()
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 200, 24)
        image = QtGui.QImage(200, 24, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(image)
        calls = []

        def record(_self, _painter, opt, index):
            calls.append(
                {
                    "rect": QtCore.QRect(opt.rect),
                    "text": opt.text,
                    "icon_null": opt.icon.isNull(),
                    "index_text": index.data(),
                }
            )

        try:
            with mock.patch.object(QtWidgets.QStyledItemDelegate, "paint", record):
                delegate.paint(painter, option, model.index(0, 0))
        finally:
            painter.end()
        return calls, image

    def test_paint_shifts_the_row_and_draws_the_indicator_in_the_reserved_slot(self):
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtGui.QColor(255, 0, 0))
        calls, image = self._paint(QtGui.QIcon(pixmap), with_decoration=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["rect"], QtCore.QRect(20, 0, 180, 24))
        self.assertEqual(calls[0]["text"], "Row text")
        self.assertTrue(calls[0]["icon_null"])
        slot = _PageComboItemDelegate.icon_rect(QtCore.QRect(0, 0, 200, 24))
        self.assertEqual(image.pixelColor(slot.center()).getRgb()[:3], (255, 0, 0))
        self.assertEqual(
            image.pixelColor(QtCore.QPoint(100, 12)).getRgb()[:3], (255, 255, 255)
        )

    def test_paint_without_an_indicator_delegates_the_unshifted_option(self):
        calls, image = self._paint(None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["rect"], QtCore.QRect(0, 0, 200, 24))
        self.assertEqual(calls[0]["index_text"], "Row text")
        for x in range(0, 200, 7):
            self.assertEqual(image.pixelColor(x, 12).getRgb()[:3], (255, 255, 255))

    def test_checkbox_rect_moves_right_of_the_indicator_only_when_one_is_shown(self):
        combo = self.make()
        combo.load_bid(_two_page_bid())
        tree = combo._tree
        item = combo._page_items["p1"]
        index = item.index()
        item_rect = QtCore.QRect(0, 0, 200, 25)
        delegate = combo._page_delegate

        def expected(offset):
            option = QtWidgets.QStyleOptionViewItem()
            option.rect = item_rect.adjusted(offset, 0, 0, 0)
            option.features |= (
                QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
            )
            option.widget = tree
            return tree.style().subElementRect(
                QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
                option,
                tree,
            )

        with_icon = delegate.checkbox_rect(tree.style(), tree, index, item_rect)
        self.assertEqual(with_icon, expected(20))
        item.setData(None, _ITEM_ROLE_PRECHECK_ICON)
        without_icon = delegate.checkbox_rect(tree.style(), tree, index, item_rect)
        self.assertEqual(without_icon, expected(0))
        self.assertEqual(with_icon.x() - without_icon.x(), 20)
        self.assertEqual(with_icon.y(), without_icon.y())


class PageComboConstructionAndModelTests(_ComboTestCase):
    def test_multi_combo_wires_its_model_width_policy_and_delegate(self):
        combo = self.make()
        self.assertIs(combo.model(), combo.popup_model())
        self.assertEqual(combo.minimumWidth(), VIEWER_PAGE_COMBO_MIN_WIDTH)
        self.assertEqual(
            combo.sizeAdjustPolicy(),
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon,
        )
        self.assertIs(combo._tree.itemDelegate(), combo._page_delegate)
        self.assertIsInstance(combo._page_delegate, _PageComboItemDelegate)

    def test_single_combo_wires_its_delegate_and_defaults_to_plain_labels(self):
        combo = self.make(SinglePageComboBox)
        self.assertIs(combo._tree.itemDelegate(), combo._page_delegate)
        combo.load_bid(_two_page_bid())
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        self.assertNotEqual(
            combo._draft_icon_default.cacheKey(), combo._draft_icon_active.cacheKey()
        )

    def test_folder_and_page_items_carry_their_roles_and_flags(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                combo.load_bid(PageComboPreferenceTests._folder_bid())
                folder = PageComboPreferenceTests._folder_item(combo, "Folder")
                self.assertEqual(folder.data(_ITEM_ROLE_KIND), "folder")
                self.assertFalse(folder.isSelectable())
                self.assertTrue(folder.font().bold())
                self.assertEqual(
                    folder.foreground().color(), QtGui.QColor(120, 120, 120)
                )
                page = combo._page_items["p1"]
                self.assertEqual(page.data(_ITEM_ROLE_KIND), "page")
                self.assertEqual(page.data(_ITEM_ROLE_UID), "p1")
                self.assertIsInstance(page.data(_ITEM_ROLE_PAGE), Page)
                self.assertFalse(page.font().bold())
                if combo_type is PageComboBox:
                    self.assertEqual(folder.data(_ITEM_ROLE_UID), "f1")
                    self.assertTrue(folder.isEnabled())
                    self.assertTrue(page.isCheckable())
                    self.assertEqual(page.checkState(), QtCore.Qt.CheckState.Unchecked)
                else:
                    self.assertFalse(page.isEditable())
                    self.assertFalse(folder.isEditable())

    def test_sheet_number_is_omitted_when_the_page_has_none(self):
        page = Page(uid="p1", name="A101", sheet_no="", sequence=0)
        self.assertEqual(_format_page_label(page, True, True), "A101")
        page.sheet_no = None
        self.assertEqual(_format_page_label(page, False, True), "A101")
        page.sheet_no = "S1"
        self.assertEqual(_format_page_label(page, False, True), "S1 - A101")
        self.assertEqual(_format_page_label(page, False, False), "A101")

    def test_pages_with_takeoffs_choose_the_active_indicator_at_load(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                marked = {"p2"}
                combo.load_bid(_two_page_bid(), marked)
                marked.add("p1")
                active = combo._draft_icon_active.cacheKey()
                default = combo._draft_icon_default.cacheKey()
                self.assertEqual(
                    combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
                    active,
                )
                self.assertEqual(
                    combo._page_items["p1"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
                    default,
                )
                self.assertEqual(combo._pages_with_takeoffs, {"p2"})
                combo.load_bid(_two_page_bid(), None)
                self.assertEqual(combo._pages_with_takeoffs, set())
                self.assertEqual(
                    combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
                    default,
                )

    def test_takeoff_marker_toggles_on_and_off_and_ignores_unknown_pages(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                combo.load_bid(_two_page_bid())
                active = combo._draft_icon_active.cacheKey()
                default = combo._draft_icon_default.cacheKey()

                def key(uid):
                    return (
                        combo._page_items[uid].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey()
                    )

                combo.set_page_has_takeoffs("missing", True)
                combo.set_page_has_takeoffs("", True)
                self.assertEqual(combo._pages_with_takeoffs, set())
                combo.set_page_has_takeoffs("p1")
                self.assertEqual((key("p1"), key("p2")), (active, default))
                self.assertEqual(combo._pages_with_takeoffs, {"p1"})
                combo.set_page_has_takeoffs("p1", True)
                self.assertEqual(combo._pages_with_takeoffs, {"p1"})
                combo.set_page_has_takeoffs("p1", False)
                self.assertEqual(key("p1"), default)
                self.assertEqual(combo._pages_with_takeoffs, set())
                combo.set_page_has_takeoffs("p1", False)
                self.assertEqual(key("p1"), default)
                # a bulk marker is the baseline the single toggle compares against
                combo.set_pages_with_takeoffs({"p2"})
                self.assertEqual(combo._pages_with_takeoffs, {"p2"})
                combo.set_page_has_takeoffs("p2", True)
                combo.set_page_has_takeoffs("p2", False)
                self.assertEqual(key("p2"), default)
                combo.set_pages_with_takeoffs(None)
                self.assertEqual(combo._pages_with_takeoffs, set())
                self.assertEqual((key("p1"), key("p2")), (default, default))
                combo.set_pages_with_takeoffs({"p1", "p2"})
                self.assertEqual((key("p1"), key("p2")), (active, active))

    def test_same_bid_reload_drops_selection_and_active_page_that_vanished(self):
        combo = self.make()
        combo.load_bid(_two_page_bid())
        combo.restore_selection(["p1", "p2"], "p1")
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="p2", name="A102")],
            )
        )
        self.assertEqual(combo.get_selected_page_uids(), ["p2"])
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(combo.get_page_order(), ["p2"])
        self.assertEqual(combo.lineEdit().text(), "1 pages")

    def test_reload_keeps_the_active_page_bold_and_only_that_page(self):
        combo = self.make()
        bid = _two_page_bid()
        combo.load_bid(bid)
        combo.restore_selection(["p1"], "p1")
        combo.load_bid(bid)
        self.assertTrue(combo._page_items["p1"].font().bold())
        self.assertFalse(combo._page_items["p2"].font().bold())

    def test_clear_resets_every_projection_and_forgets_the_bid(self):
        combo = self.make()
        bid = _two_page_bid()
        combo.load_bid(bid, {"p1"})
        combo.restore_selection(["p1"], "p1")
        revision = combo._model_revision
        navigation = []
        combo.navigation_state_changed.connect(lambda: navigation.append(True))
        combo._page_pointer_owner = (revision, "p1", False)
        combo.clear()
        self.assertEqual(navigation, [True])
        self.assertEqual(combo.popup_model().rowCount(), 0)
        self.assertEqual(combo._page_items, {})
        self.assertEqual(combo._pages_with_takeoffs, set())
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertIsNone(combo.get_active_page_uid())
        self.assertIsNone(combo._bid_uid)
        self.assertEqual(combo.lineEdit().text(), "")
        self.assertEqual(combo._model_revision, revision + 1)
        self.assertIsNone(combo._page_pointer_owner)
        # the forgotten bid uid means a reload of the same bid keeps nothing
        combo.load_bid(bid)
        self.assertEqual(combo.get_selected_page_uids(), [])
        self.assertIsNone(combo.get_active_page_uid())
        # signals are live again after clear + reload
        selections = []
        combo.page_selection_changed.connect(selections.append)
        combo._page_items["p2"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(selections, [["p2"]])

    def test_load_bid_invalidates_a_pressed_page_and_advances_the_revision(self):
        combo = self.make()
        combo.load_bid(_two_page_bid())
        revision = combo._model_revision
        combo._page_pointer_owner = (revision, "p1", False)
        combo.load_bid(_two_page_bid())
        self.assertEqual(combo._model_revision, revision + 1)
        self.assertIsNone(combo._page_pointer_owner)

    def test_single_combo_clear_forgets_items_selection_and_text(self):
        combo = self.make(SinglePageComboBox)
        bid = _two_page_bid()
        combo.load_bid(bid, {"p1"})
        combo.set_current_page_uid("p1")
        combo.clear()
        self.assertEqual(combo.popup_model().rowCount(), 0)
        self.assertEqual(combo._page_items, {})
        self.assertEqual(combo._pages_with_takeoffs, set())
        self.assertEqual(combo._selected_uid, "")
        self.assertEqual(combo.lineEdit().text(), "")
        combo.load_bid(bid)
        self.assertEqual(combo._selected_uid, "")
        self.assertEqual(combo.lineEdit().text(), "")

    def test_single_combo_reload_replaces_the_previous_bid_rows(self):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(_two_page_bid("bid-1"))
        combo.load_bid(
            Bid(
                uid="bid-2",
                name="Other",
                pages_without_folder=[Page(uid="q1", name="B1")],
            )
        )
        self.assertEqual(combo.get_page_order(), ["q1"])
        self.assertEqual(combo.popup_model().rowCount(), 1)
        self.assertEqual(list(combo._page_items), ["q1"])


class PageComboDisplayAndSelectionTests(_ComboTestCase):
    def _combo(self):
        combo = self.make()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid="a", name="A101"),
                    Page(uid="b", name="A102"),
                    Page(uid="c", name="A103"),
                ],
            )
        )
        return combo

    def test_display_text_counts_extra_selected_pages_beside_the_active_one(self):
        combo = self._combo()
        combo.restore_selection(["a"], "a")
        self.assertEqual(combo.lineEdit().text(), "A101")
        combo._page_items["b"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(combo.lineEdit().text(), "A101 (+1)")
        combo._page_items["c"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(combo.lineEdit().text(), "A101 (+2)")
        combo._page_items["a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        # active page unselected: both other pages count as extra
        self.assertEqual(combo.lineEdit().text(), "A101 (+2)")

    def test_display_text_without_an_active_page_counts_the_selection(self):
        combo = self._combo()
        combo._page_items["a"].setCheckState(QtCore.Qt.CheckState.Checked)
        combo._page_items["b"].setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(combo.lineEdit().text(), "2 pages")
        combo._page_items["a"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        combo._page_items["b"].setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(combo.lineEdit().text(), "")

    def test_folder_check_updates_the_display_text(self):
        combo = self.make()
        combo.load_bid(PageComboPreferenceTests._folder_bid())
        folder = PageComboPreferenceTests._folder_item(combo, "Folder")
        folder.setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(combo.lineEdit().text(), "4 pages")
        folder.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(combo.lineEdit().text(), "")

    def test_label_option_change_and_label_refresh_update_the_editor_text(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                combo.load_bid(_two_page_bid())
                if combo_type is PageComboBox:
                    combo.restore_selection(["p1"], "p1")
                else:
                    combo.set_current_page_uid("p1")
                self.assertEqual(combo.lineEdit().text(), "A101")
                combo.set_label_options(True, True)
                self.assertEqual(combo.lineEdit().text(), "1 - S1 - A101")
                replacement = Page(uid="p1", name="Renamed", sheet_no="S9", sequence=5)
                combo.refresh_page_labels([replacement])
                self.assertEqual(combo.lineEdit().text(), "5 - S9 - Renamed")
                self.assertIs(
                    combo._page_items["p1"].data(_ITEM_ROLE_PAGE), replacement
                )
                # later label options use the replacement, not the original page
                combo.set_label_options(False, False)
                self.assertEqual(combo._page_items["p1"].text(), "Renamed")

    def test_label_refresh_ignores_pages_that_are_not_in_the_combo(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                combo.load_bid(_two_page_bid())
                combo.refresh_page_labels([Page(uid="ghost", name="Ghost")])
                self.assertEqual(list(combo._page_items), ["p1", "p2"])
                self.assertEqual(combo._page_items["p1"].text(), "A101")

    def test_restore_selection_falls_back_to_the_first_selected_page(self):
        combo = self._combo()
        self.assertTrue(combo.restore_selection(["c", "b"], "missing"))
        self.assertEqual(combo.get_selected_page_uids(), ["b", "c"])
        self.assertEqual(combo.get_active_page_uid(), "b")
        self.assertEqual(combo.lineEdit().text(), "A102 (+1)")

    def test_restore_selection_without_pages_clears_the_active_page(self):
        combo = self._combo()
        combo.restore_selection(["a"], "a")
        active = []
        selection = []
        combo.active_page_changed.connect(active.append)
        combo.page_selection_changed.connect(selection.append)
        self.assertTrue(combo.restore_selection([], None))
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(active, [None])
        self.assertEqual(selection, [[]])
        self.assertEqual(combo.lineEdit().text(), "")
        self.assertFalse(combo._page_items["a"].font().bold())

    def test_restore_selection_moves_the_bold_marker_and_emits_only_real_changes(self):
        combo = self._combo()
        selection = []
        active = []
        combo.restore_selection(["a"], "a")
        combo.page_selection_changed.connect(selection.append)
        combo.active_page_changed.connect(active.append)
        self.assertTrue(combo._page_items["a"].font().bold())
        self.assertTrue(combo.restore_selection(["b"], "b"))
        self.assertFalse(combo._page_items["a"].font().bold())
        self.assertTrue(combo._page_items["b"].font().bold())
        self.assertEqual((selection, active), ([["b"]], ["b"]))
        self.assertFalse(combo.restore_selection(["b"], "b"))
        self.assertEqual((selection, active), ([["b"]], ["b"]))
        self.assertFalse(combo.restore_selection(["b", "c"], "b"))
        self.assertEqual((selection, active), ([["b"], ["b", "c"]], ["b"]))

    def test_a_partial_check_state_on_an_unchecked_page_changes_nothing(self):
        combo = self._combo()
        selection = []
        errors = self.capture_slot_errors()
        combo.page_selection_changed.connect(selection.append)
        combo._page_items["a"].setCheckState(QtCore.Qt.CheckState.PartiallyChecked)
        self.assertEqual(errors, [])
        self.assertEqual(selection, [])
        self.assertEqual(combo.get_selected_page_uids(), [])

    def test_update_bold_only_touches_known_pages_and_follows_the_active_page(self):
        combo = self._combo()
        combo._update_bold(None)
        combo._update_bold("missing")
        combo._set_active("a")
        self.assertTrue(combo._page_items["a"].font().bold())
        combo._set_active("b")
        self.assertFalse(combo._page_items["a"].font().bold())
        self.assertTrue(combo._page_items["b"].font().bold())
        self.assertEqual(combo.lineEdit().text(), "A102")

    def test_get_first_page_uid_follows_model_order_and_is_none_when_empty(self):
        combo = self.make()
        self.assertIsNone(combo.get_first_page_uid())
        combo.load_bid(PageComboPreferenceTests._folder_bid())
        self.assertEqual(combo.get_first_page_uid(), combo.get_page_order()[0])
        self.assertEqual(combo.get_page_order()[0], "p3")
        combo.clear()
        self.assertIsNone(combo.get_first_page_uid())

    def test_navigation_starts_at_the_first_page_and_stops_at_both_ends(self):
        combo = self._combo()
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "a")
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "a")
        combo.go_next()
        combo.go_next()
        self.assertEqual(combo.get_active_page_uid(), "c")
        combo.go_next()
        self.assertEqual(combo.get_active_page_uid(), "c")
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "b")
        combo.go_prev()
        self.assertEqual(combo.get_active_page_uid(), "a")
        self.assertEqual(combo.lineEdit().text(), "A101")
        fresh = self.make()
        fresh.go_next()
        self.assertIsNone(fresh.get_active_page_uid())
        fresh.load_bid(_two_page_bid())
        fresh.go_next()
        self.assertEqual(fresh.get_active_page_uid(), "p1")


class PageComboPointerTests(_ComboTestCase):
    def _open(self, combo_type=PageComboBox, bid=None):
        combo = self.make(combo_type)
        combo.load_bid(bid or PageComboPreferenceTests._folder_bid())
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        return combo

    @staticmethod
    def _page_pos(combo, uid, checkbox=False):
        tree = combo._tree
        index = combo._page_items[uid].index()
        rect = tree.visualRect(index)
        if checkbox:
            return combo._page_delegate.checkbox_rect(
                tree.style(), tree, index, rect
            ).center()
        return QtCore.QPoint(rect.right() - 10, rect.center().y())

    def test_clicking_a_page_row_activates_it_without_toggling_its_check(self):
        combo = self._open()
        activated = []
        selected = []
        combo.active_page_changed.connect(activated.append)
        combo.page_selection_changed.connect(selected.append)
        pos = self._page_pos(combo, "p5")
        QTest.mouseClick(
            combo._tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos
        )
        self.assertEqual(combo.get_active_page_uid(), "p5")
        self.assertEqual(activated, ["p5"])
        self.assertEqual(selected, [])
        self.assertEqual(
            combo._page_items["p5"].checkState(), QtCore.Qt.CheckState.Unchecked
        )
        self.assertEqual(combo.lineEdit().text(), "A105")
        self.assertTrue(combo._page_items["p5"].font().bold())
        QTest.mouseClick(
            combo._tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos
        )
        self.assertEqual(activated, ["p5"])

    def test_clicking_a_page_checkbox_toggles_the_check_and_keeps_the_active_page(self):
        combo = self._open()
        activated = []
        selected = []
        combo.active_page_changed.connect(activated.append)
        combo.page_selection_changed.connect(selected.append)
        pos = self._page_pos(combo, "p5", checkbox=True)
        QTest.mouseClick(
            combo._tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos
        )
        self.assertEqual(selected, [["p5"]])
        self.assertEqual(
            combo._page_items["p5"].checkState(), QtCore.Qt.CheckState.Checked
        )
        QTest.mouseClick(
            combo._tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos
        )
        self.assertEqual(selected, [["p5"], []])
        self.assertEqual(
            combo._page_items["p5"].checkState(), QtCore.Qt.CheckState.Unchecked
        )
        self.assertEqual(activated, [])
        self.assertIsNone(combo.get_active_page_uid())

    def test_checkbox_hit_test_extends_four_pixels_sideways_and_not_vertically(self):
        combo = self._open()
        tree = combo._tree
        index = combo._page_items["p5"].index()
        rect = combo._page_delegate.checkbox_rect(
            tree.style(), tree, index, tree.visualRect(index)
        )
        y = rect.center().y()
        cx = rect.center().x()
        hit = combo._is_click_on_checkbox
        self.assertIs(hit(index, rect.center()), True)
        self.assertIs(hit(index, QtCore.QPoint(rect.left() - 4, y)), True)
        self.assertIs(hit(index, QtCore.QPoint(rect.left() - 5, y)), False)
        self.assertIs(hit(index, QtCore.QPoint(rect.right() + 4, y)), True)
        self.assertIs(hit(index, QtCore.QPoint(rect.right() + 5, y)), False)
        self.assertIs(hit(index, QtCore.QPoint(cx, rect.top())), True)
        self.assertIs(hit(index, QtCore.QPoint(cx, rect.top() - 1)), False)
        self.assertIs(hit(index, QtCore.QPoint(cx, rect.bottom())), True)
        self.assertIs(hit(index, QtCore.QPoint(cx, rect.bottom() + 1)), False)

    @staticmethod
    def _mouse(event_type, button, buttons=None):
        point = QtCore.QPointF(5.0, 5.0)
        return QtGui.QMouseEvent(
            event_type,
            point,
            point,
            button,
            buttons if buttons is not None else button,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _send(self, combo, obj, event, uid):
        """Dispatch ``event`` to the filter as if it landed on page ``uid``'s row."""
        index = combo._page_items[uid].index() if uid else QtCore.QModelIndex()
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            return combo.eventFilter(obj, event)

    def test_only_left_button_presses_and_releases_on_the_viewport_activate_pages(self):
        combo = self._open(bid=_two_page_bid())
        viewport = combo._tree.viewport()
        left = QtCore.Qt.MouseButton.LeftButton
        right = QtCore.Qt.MouseButton.RightButton
        none = QtCore.Qt.MouseButton.NoButton
        press = QtCore.QEvent.Type.MouseButtonPress
        release = QtCore.QEvent.Type.MouseButtonRelease
        move = QtCore.QEvent.Type.MouseMove
        # a right-button press never starts an activation
        self._send(combo, viewport, self._mouse(press, right), "p1")
        self.assertIsNone(combo._page_pointer_owner)
        self._send(combo, viewport, self._mouse(press, left), "p1")
        self.assertIsNotNone(combo._page_pointer_owner)
        # nor does a right-button release complete one
        self._send(combo, viewport, self._mouse(release, right, none), "p1")
        self.assertIsNone(combo.get_active_page_uid())
        self.assertIsNotNone(combo._page_pointer_owner)
        # a mouse move is neither a press nor a release
        self._send(combo, viewport, self._mouse(move, left), "p2")
        self.assertEqual(combo._page_pointer_owner[1], "p1")
        self._send(combo, viewport, self._mouse(release, left, none), "p1")
        self.assertEqual(combo.get_active_page_uid(), "p1")
        self.assertIsNone(combo._page_pointer_owner)
        # events for any object other than the viewport are ignored
        self._send(combo, combo, self._mouse(press, left), "p2")
        self.assertIsNone(combo._page_pointer_owner)
        self._send(combo, viewport, self._mouse(press, left), "p2")
        self._send(combo, combo, self._mouse(release, left, none), "p2")
        self.assertEqual(combo.get_active_page_uid(), "p1")

    def test_pressing_off_a_page_cancels_an_earlier_press_and_releasing_needs_a_press(
        self,
    ):
        combo = self._open()
        viewport = combo._tree.viewport()
        left = QtCore.Qt.MouseButton.LeftButton
        none = QtCore.Qt.MouseButton.NoButton
        press = QtCore.QEvent.Type.MouseButtonPress
        release = QtCore.QEvent.Type.MouseButtonRelease
        self._send(combo, viewport, self._mouse(press, left), "p5")
        self.assertEqual(combo._page_pointer_owner[1], "p5")
        folder = PageComboPreferenceTests._folder_item(combo, "Folder")
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=folder.index()),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            combo.eventFilter(viewport, self._mouse(press, left))
        self.assertIsNone(combo._page_pointer_owner)
        self._send(combo, viewport, self._mouse(press, left), "p5")
        self._send(combo, viewport, self._mouse(press, left), None)
        self.assertIsNone(combo._page_pointer_owner)
        self.assertTrue(
            self._send(combo, viewport, self._mouse(release, left, none), "p5")
        )
        self.assertIsNone(combo.get_active_page_uid())

    def test_release_on_a_folder_is_left_to_qt_and_unrelated_events_pass_through(self):
        combo = self._open()
        viewport = combo._tree.viewport()
        folder = PageComboPreferenceTests._folder_item(combo, "Folder")
        release = self._mouse(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
        )
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=folder.index()),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            handled = combo.eventFilter(viewport, release)
        self.assertIs(handled, False)
        self.assertIs(
            combo.eventFilter(viewport, QtCore.QEvent(QtCore.QEvent.Type.Leave)), False
        )

    def test_release_after_a_press_on_the_checkbox_swallows_a_mismatched_hit(self):
        combo = self._open(bid=_two_page_bid())
        viewport = combo._tree.viewport()
        left = QtCore.Qt.MouseButton.LeftButton
        index = combo._page_items["p1"].index()
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=True),
        ):
            combo.eventFilter(
                viewport, self._mouse(QtCore.QEvent.Type.MouseButtonPress, left)
            )
        self.assertEqual(combo._page_pointer_owner[2], True)
        # released on the row text instead: the press and release disagree
        handled = self._send(
            combo,
            viewport,
            self._mouse(
                QtCore.QEvent.Type.MouseButtonRelease,
                left,
                QtCore.Qt.MouseButton.NoButton,
            ),
            "p1",
        )
        self.assertTrue(handled)
        self.assertIsNone(combo.get_active_page_uid())
        self.assertEqual(
            combo._page_items["p1"].checkState(), QtCore.Qt.CheckState.Unchecked
        )

    def test_popup_opens_scrolled_to_the_active_page_and_tolerates_a_detached_item(
        self,
    ):
        combo = self.make()
        combo.load_bid(PageComboPreferenceTests._folder_bid())
        combo.restore_selection(["p4"], "p4")
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        self.assertEqual(combo._tree.currentIndex(), combo._page_items["p4"].index())
        combo.hidePopup()
        combo._tree.setCurrentIndex(combo._page_items["p1"].index())
        stale = combo._page_items["p4"]
        stale.parent().takeRow(stale.row())
        self.assertFalse(stale.index().isValid())
        combo.showPopup()
        self.assertEqual(combo._tree.currentIndex(), combo._page_items["p1"].index())
        combo.hidePopup()
        fresh = self.make()
        fresh.show()
        fresh.showPopup()
        self.assertFalse(fresh._tree.currentIndex().isValid())

    def test_single_combo_popup_opens_scrolled_to_the_selected_page(self):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(PageComboPreferenceTests._folder_bid())
        combo.set_current_page_uid("p4")
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        self.assertEqual(combo._tree.currentIndex(), combo._page_items["p4"].index())
        combo.hidePopup()
        combo._tree.setCurrentIndex(combo._page_items["p1"].index())
        stale = combo._page_items["p4"]
        stale.parent().takeRow(stale.row())
        combo.showPopup()
        self.assertEqual(combo._tree.currentIndex(), combo._page_items["p1"].index())
        combo.hidePopup()
        fresh = self.make(SinglePageComboBox)
        fresh.show()
        fresh.showPopup()
        self.assertFalse(fresh._tree.currentIndex().isValid())


class SinglePageComboInteractionTests(_ComboTestCase):
    def _open(self):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(PageComboPreferenceTests._folder_bid())
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        return combo

    def _click(self, combo, item):
        tree = combo._tree
        rect = tree.visualRect(item.index())
        QTest.mouseClick(
            tree.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=QtCore.QPoint(rect.right() - 10, rect.center().y()),
        )

    def test_clicking_a_page_selects_it_closes_the_popup_and_announces_it(self):
        combo = self._open()
        activated = []
        combo.page_activated.connect(activated.append)
        self.assertTrue(combo._popup.isVisible())
        self._click(combo, combo._page_items["p5"])
        self.assertEqual(activated, ["p5"])
        self.assertEqual(combo._selected_uid, "p5")
        self.assertEqual(combo.lineEdit().text(), "A105")
        self.assertFalse(combo._popup.isVisible())

    def test_clicking_a_folder_or_an_empty_page_uid_changes_nothing(self):
        combo = self._open()
        combo.set_current_page_uid("p1")
        activated = []
        combo.page_activated.connect(activated.append)
        self._click(combo, PageComboPreferenceTests._folder_item(combo, "Folder"))
        self.assertEqual(activated, [])
        self.assertEqual(combo._selected_uid, "p1")
        self.assertTrue(combo._popup.isVisible())
        blank = QtGui.QStandardItem("blank")
        blank.setData("page", _ITEM_ROLE_KIND)
        blank.setData("", _ITEM_ROLE_UID)
        combo.popup_model().appendRow(blank)
        combo._on_tree_clicked(blank.index())
        combo._on_tree_clicked(QtCore.QModelIndex())
        self.assertEqual(activated, [])
        self.assertEqual(combo._selected_uid, "p1")
        self.assertTrue(combo._popup.isVisible())

    def test_programmatic_selection_is_silent_and_unknown_pages_clear_it(self):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(_two_page_bid())
        activated = []
        combo.page_activated.connect(activated.append)
        combo.set_current_page_uid("p2")
        self.assertEqual(activated, [])
        self.assertEqual(combo._selected_uid, "p2")
        combo.set_current_page_uid(None)
        self.assertEqual(combo._selected_uid, "")
        self.assertEqual(combo.lineEdit().text(), "")
        self.assertEqual(activated, [])

    def test_pressing_the_line_edit_opens_the_popup_and_cleanup_restores_the_handler(
        self,
    ):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(_two_page_bid())
        combo.set_current_page_uid("p1")
        combo.show()
        original = combo._line_edit_mouse_press_event
        self.assertEqual(
            combo.lineEdit().mousePressEvent, combo._on_line_edit_mouse_press
        )
        self.assertFalse(combo._popup.isVisible())
        combo.lineEdit().mousePressEvent(None)
        self.assertTrue(combo._popup.isVisible())
        combo.cleanup()
        self.assertEqual(combo.lineEdit().mousePressEvent, original)
        self.assertIsNone(combo._line_edit_mouse_press_event)
        self.assertIsNone(combo._page_delegate)
        self.assertEqual(combo._selected_uid, "")


class PageComboCleanupContractTests(_ComboTestCase):
    def _capture_hook(self):
        return self.capture_slot_errors()

    def test_multi_cleanup_disconnects_the_model_and_drops_every_reference(self):
        combo = self.make()
        combo.load_bid(_two_page_bid(), {"p1"})
        combo.restore_selection(["p1"], "p1")
        combo._page_pointer_owner = (1, "p1", False)
        model = combo.popup_model()
        errors = self._capture_hook()
        combo.cleanup()
        self.assertEqual(model.rowCount(), 0)
        self.assertIsNone(combo._active_uid)
        self.assertIsNone(combo._bid_uid)
        self.assertIsNone(combo._page_pointer_owner)
        self.assertIsNone(combo._page_delegate)
        # a late model change must no longer reach the released combo
        late = QtGui.QStandardItem("late")
        late.setData("page", _ITEM_ROLE_KIND)
        late.setData("late", _ITEM_ROLE_UID)
        late.setCheckable(True)
        model.appendRow(late)
        late.setCheckState(QtCore.Qt.CheckState.Checked)
        self.app.processEvents()
        self.assertEqual(errors, [])

    def test_single_cleanup_disconnects_the_tree_click_and_clears_state(self):
        combo = self.make(SinglePageComboBox)
        combo.load_bid(_two_page_bid(), {"p1"})
        combo.set_current_page_uid("p1")
        model = combo.popup_model()
        tree = combo._tree
        activated = []
        combo.page_activated.connect(activated.append)
        errors = self._capture_hook()
        combo.cleanup()
        self.assertEqual(model.rowCount(), 0)
        late = QtGui.QStandardItem("late")
        late.setData("page", _ITEM_ROLE_KIND)
        late.setData("late", _ITEM_ROLE_UID)
        model.appendRow(late)
        tree.clicked.emit(late.index())
        self.app.processEvents()
        self.assertEqual(errors, [])
        self.assertEqual(activated, [])


class PageComboRemainingContractTests(_ComboTestCase):
    def _combo(self, count=3):
        combo = self.make()
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[
                    Page(uid=f"p{i}", name=f"A{100 + i}") for i in range(count)
                ],
            )
        )
        return combo

    def test_restore_selection_keeps_an_explicit_active_page_that_is_not_first(self):
        combo = self._combo()
        self.assertTrue(combo.restore_selection(["p0", "p1"], "p1"))
        self.assertEqual(combo.get_active_page_uid(), "p1")
        self.assertEqual(combo.lineEdit().text(), "A101 (+1)")
        self.assertTrue(combo._page_items["p1"].font().bold())
        self.assertFalse(combo._page_items["p0"].font().bold())

    def test_model_data_change_handler_respects_blocking_and_a_released_combo(self):
        combo = self._combo()
        combo.restore_selection(["p0"], "p0")
        with mock.patch.object(combo, "_update_display_text") as update:
            combo._block_signals = True
            combo._on_model_data_changed()
            self.assertEqual(update.call_count, 0)
            combo._block_signals = False
            combo._on_model_data_changed()
            self.assertEqual(update.call_count, 1)
        combo.cleanup()
        with mock.patch.object(combo, "_update_display_text") as update:
            combo._on_model_data_changed()
            self.assertEqual(update.call_count, 0)

    def test_checkbox_click_is_consumed_and_toggles_exactly_once(self):
        combo = self._combo(1)
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        viewport = combo._tree.viewport()
        index = combo._page_items["p0"].index()
        left = QtCore.Qt.MouseButton.LeftButton
        point = QtCore.QPointF(5.0, 5.0)

        def event(kind, buttons):
            return QtGui.QMouseEvent(
                kind, point, point, left, buttons, QtCore.Qt.KeyboardModifier.NoModifier
            )

        with (
            mock.patch.object(combo._tree, "indexAt", return_value=index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=True),
        ):
            combo.eventFilter(viewport, event(QtCore.QEvent.Type.MouseButtonPress, left))
            handled = combo.eventFilter(
                viewport,
                event(QtCore.QEvent.Type.MouseButtonRelease, QtCore.Qt.MouseButton.NoButton),
            )
        self.assertIs(handled, True)
        self.assertEqual(
            combo._page_items["p0"].checkState(), QtCore.Qt.CheckState.Checked
        )
        self.assertEqual(combo.get_selected_page_uids(), ["p0"])

    def test_popup_centres_the_active_page_in_a_long_list(self):
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = self.make(combo_type)
                combo.load_bid(
                    Bid(
                        uid="bid-1",
                        name="Bid",
                        pages_without_folder=[
                            Page(uid=f"p{i}", name=f"A{i}") for i in range(80)
                        ],
                    )
                )
                if combo_type is PageComboBox:
                    combo.restore_selection(["p40"], "p40")
                else:
                    combo.set_current_page_uid("p40")
                combo.show()
                combo.showPopup()
                self.app.processEvents()
                tree = combo._tree
                row = tree.visualRect(combo._page_items["p40"].index())
                self.assertGreater(tree.verticalScrollBar().value(), 0)
                self.assertLessEqual(
                    abs(row.center().y() - tree.viewport().height() // 2),
                    row.height(),
                )
