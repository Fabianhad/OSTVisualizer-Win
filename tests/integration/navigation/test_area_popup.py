import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from tests.helpers.workspace_state import make_workspace_state_model


class _IconProvider:
    def set_window_icon(self, _window) -> None:
        pass


class _AccessManager:
    def is_allowed(self, _feature) -> bool:
        return True


class AreaComboPopupSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self) -> None:
        self._original_style_name = self.app.style().objectName()
        self._bars: list[PageSettingsBar] = []

    def tearDown(self) -> None:
        for bar in self._bars:
            bar.area_combo.hidePopup()
            bar.scale_combo.hidePopup()
            bar.deleteLater()
        self._bars.clear()
        original_style = QtWidgets.QStyleFactory.create(self._original_style_name)
        if original_style is not None:
            self.app.setStyle(original_style)
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _make_bar(self, *, database_id: str = "db.mdb", bid_uid: str = "bid-1"):
        bar = PageSettingsBar(
            _IconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=_AccessManager(),
            workspace_state_model=make_workspace_state_model(),
            get_page_fn=lambda _uid: object(),
        )
        bar.load_bid_areas(
            BidRef(database_id, bid_uid),
            areas=[
                BidArea("area-1", bid_uid, "", "Area 1", 0),
                BidArea("area-3", bid_uid, "", "Area 3", 1),
            ],
        )
        bar.set_interactive(True)
        bar.show()
        self.app.processEvents()
        self._bars.append(bar)
        return bar

    def _click_popup_area(self, bar: PageSettingsBar, area_uid: str) -> None:
        combo = bar.area_combo
        combo.showPopup()
        self.app.processEvents()
        index = combo._area_items[area_uid].index()
        combo._tree.scrollTo(index)
        self.app.processEvents()
        item_rect = combo._tree.visualRect(index)
        self.assertTrue(item_rect.isValid())
        QTest.mouseClick(
            combo._tree.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            item_rect.center(),
        )
        self.app.processEvents()
        self.assertEqual(combo.get_current_area_uid(), area_uid)

    def _open_and_assert_popup_area(
        self, bar: PageSettingsBar, expected_uid: str
    ) -> None:
        combo = bar.area_combo
        combo.showPopup()
        self.app.processEvents()
        current = combo._tree.currentIndex()
        self.assertTrue(current.isValid())
        self.assertEqual(current.data(QtCore.Qt.ItemDataRole.UserRole), expected_uid)
        self.assertEqual(combo._tree.selectionModel().selectedIndexes(), [])

    def _available_target_styles(self) -> list[str]:
        available = {
            style_name.lower(): style_name
            for style_name in QtWidgets.QStyleFactory.keys()
        }
        return [
            available[key]
            for key in ("fusion", "windowsvista", "windows", "windows11")
            if key in available
        ]

    def test_page_switch_synchronizes_real_popup_current_item_for_each_style(self):
        self.assertTrue(self._available_target_styles())
        for style_name in self._available_target_styles():
            for target_uid in ("", "area-1"):
                with self.subTest(style=style_name, target_uid=target_uid):
                    style = QtWidgets.QStyleFactory.create(style_name)
                    self.assertIsNotNone(style)
                    self.app.setStyle(style)
                    bar = self._make_bar()
                    bar.load_page("page-1", 1.0, 1.0, "")
                    self._click_popup_area(bar, "area-3")
                    bar.load_page("page-2", 1.0, 1.0, target_uid)
                    self.assertEqual(bar.area_combo.get_current_area_uid(), target_uid)
                    expected_text = "(All Areas)" if target_uid == "" else "Area 1"
                    self.assertEqual(bar.area_combo.currentText(), expected_text)
                    self._open_and_assert_popup_area(bar, target_uid)
                    bar.area_combo.hidePopup()

    def test_popup_tracks_rapid_page_switches_open_updates_and_repeated_open(self):
        style = QtWidgets.QStyleFactory.create("Fusion")
        self.assertIsNotNone(style)
        self.app.setStyle(style)
        bar = self._make_bar()
        bar.load_page("page-1", 1.0, 1.0, "")
        self._click_popup_area(bar, "area-3")
        for page_number, area_uid in enumerate(
            ("", "area-1", "area-3", "", "area-3"), start=2
        ):
            bar.load_page(f"page-{page_number}", 1.0, 1.0, area_uid)
            self._open_and_assert_popup_area(bar, area_uid)
        bar.load_page("page-open-1", 1.0, 1.0, "area-1")
        self.assertTrue(bar.area_combo._popup.isVisible())
        self._open_and_assert_popup_area(bar, "area-1")
        bar.area_combo.hidePopup()
        self._open_and_assert_popup_area(bar, "area-1")

    def test_bid_rebuild_delete_and_recreate_rebind_popup_index(self):
        bar = self._make_bar(database_id="db-one.mdb", bid_uid="bid-same")
        bar.load_page("page-1", 1.0, 1.0, "")
        self._click_popup_area(bar, "area-3")
        old_item = bar.area_combo._area_items["area-3"]
        bar.load_bid_areas(
            BidRef("db-two.mdb", "bid-same"),
            areas=[
                BidArea("area-1", "bid-same", "", "Other Area 1", 0),
                BidArea("area-3", "bid-same", "", "Other Area 3", 1),
            ],
            selected_uid="area-3",
        )
        self.assertIsNot(bar.area_combo._area_items["area-3"], old_item)
        self._open_and_assert_popup_area(bar, "area-3")
        bar.load_bid_areas(
            BidRef("db-two.mdb", "bid-same"),
            areas=[BidArea("area-1", "bid-same", "", "Other Area 1", 0)],
            selected_uid="area-3",
        )
        self._open_and_assert_popup_area(bar, "")
        bar.load_bid_areas(
            BidRef("db-two.mdb", "bid-same"),
            areas=[
                BidArea("area-1", "bid-same", "", "Other Area 1", 0),
                BidArea("area-3", "bid-same", "", "Recreated Area 3", 1),
            ],
            selected_uid="area-3",
        )
        self._open_and_assert_popup_area(bar, "area-3")

    def test_targeted_page_area_projection_updates_open_popup(self):
        bar = self._make_bar()
        bar.load_page("page-1", 1.0, 1.0, "")
        self._click_popup_area(bar, "area-3")
        bar.area_combo.showPopup()
        self.app.processEvents()
        page = SimpleNamespace(scale_factor1=1.0, scale_factor2=1.0)
        coordinator = SimpleNamespace(
            _page_settings_bar=bar,
            project_data=SimpleNamespace(
                get_page=lambda page_uid: page if page_uid == "page-2" else None,
                get_page_area_selections=lambda: {"page-2": "area-1"},
                get_area_uids_with_takeoff_for_page=lambda _page_uid: {"area-1"},
            ),
            ui_state_manager=SimpleNamespace(selected_area_uid=""),
        )
        UIEventCoordinator._update_page_settings_bar(coordinator, "page-2")
        self.assertTrue(bar.area_combo._popup.isVisible())
        self._open_and_assert_popup_area(bar, "area-1")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "area-1")

    def test_page_scale_combo_does_not_reproduce_stale_popup_current_item(self):
        bar = self._make_bar()
        bar.load_page("page-1", 0.125, 12.0, "")
        first_index = bar.scale_combo.currentIndex()
        bar.scale_combo.showPopup()
        self.app.processEvents()
        self.assertEqual(bar.scale_combo._tree.currentIndex().row(), first_index)
        bar.scale_combo.hidePopup()
        bar.load_page("page-2", 0.25, 12.0, "")
        second_index = bar.scale_combo.currentIndex()
        self.assertNotEqual(second_index, first_index)
        bar.scale_combo.showPopup()
        self.app.processEvents()
        self.assertEqual(bar.scale_combo._tree.currentIndex().row(), second_index)
