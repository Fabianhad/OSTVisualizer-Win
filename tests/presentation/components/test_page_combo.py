import os
import unittest
from pathlib import Path
from unittest import mock
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.presentation.components.page_combo import (
    PageComboBox,
    SinglePageComboBox,
)
from PySide6 import QtCore, QtGui, QtWidgets
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
        combo.set_page_has_takeoffs("page-a", True)
        combo.set_pages_with_takeoffs({"page-b"})
        combo.set_label_options(True, False)
        self.assertEqual(emitted, [])
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
        active_index = order.index(combo.get_active_page_uid())
        self.assertEqual(combo.get_selected_page_uids(), ["page-b"])
        self.assertEqual(combo.get_active_page_uid(), "page-b")
        self.assertEqual(combo.lineEdit().text(), "Duplicate")
        self.assertTrue(active_index > 0)
        self.assertTrue(active_index < len(order) - 1)
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
        model_changes = []
        combo.active_page_changed.connect(active_changes.append)
        combo.navigation_state_changed.connect(lambda: model_changes.append(True))
        combo.load_bid(bid)
        self.assertEqual(active_changes, [])
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
        old_index = combo._page_items["page-a"].index()
        press = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(5.0, 5.0),
            QtCore.QPointF(5.0, 5.0),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        with mock.patch.object(combo._tree, "indexAt", return_value=old_index):
            combo.eventFilter(combo._tree.viewport(), press)
        combo.load_bid(
            Bid(
                uid="bid-1",
                name="Bid",
                pages_without_folder=[Page(uid="page-b", name="A102")],
            )
        )
        new_index = combo._page_items["page-b"].index()
        activated = []
        combo.active_page_changed.connect(activated.append)
        release = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(5.0, 5.0),
            QtCore.QPointF(5.0, 5.0),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        with (
            mock.patch.object(combo._tree, "indexAt", return_value=new_index),
            mock.patch.object(combo, "_is_click_on_checkbox", return_value=False),
        ):
            combo.eventFilter(combo._tree.viewport(), release)
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
        order = combo.get_page_order()
        active_index = order.index(combo.get_active_page_uid())
        self.assertEqual(combo.lineEdit().text(), "A101")
        self.assertFalse(active_index > 0)
        self.assertFalse(active_index < len(order) - 1)
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
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._selected_uids)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
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
            combo.cleanup()
            combo.cleanup()
            self.assertIsNone(combo._page_items)
            self.assertIsNone(combo._pages_with_takeoffs)
            self.assertIsNone(combo._popup)
            self.assertIsNone(combo._tree)
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
                self.fixture.original.name = "New label"
                combo.refresh_page_labels([self.fixture.original])
                self.assertIs(combo._page_items["42"], item)
                self.assertEqual(item.text(), "New label")
                self.assertEqual(item.checkState(), state)
                self.assertIn("New label", combo.currentText())
                self.assertEqual(calls, [])
                combo.cleanup()
                combo.deleteLater()
