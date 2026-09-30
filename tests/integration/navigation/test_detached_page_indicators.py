import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_combo import (
    _ITEM_ROLE_PRECHECK_ICON,
    SinglePageComboBox,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.view_window import ViewWindow
from PySide6 import QtCore, QtWidgets


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    @staticmethod
    def _indicator_is_active(combo, page_uid):
        icon = combo._page_items[page_uid].data(_ITEM_ROLE_PRECHECK_ICON)
        return icon.cacheKey() == combo._draft_icon_active.cacheKey()

    @staticmethod
    def _indicator_bid():
        return Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="Duplicate"),
                Page(uid="p2", name="Duplicate"),
            ],
        )

    def _make_indicator_manager(
        self,
        window_cls,
        *,
        target_page_uid,
        pages_with_takeoffs,
    ):
        bid_ref = BidRef("memory-test.mdb", "bid-1")
        combo = SinglePageComboBox()
        combo.load_bid(
            self._indicator_bid(),
            pages_with_takeoffs=set(pages_with_takeoffs),
        )
        combo.set_current_page_uid(target_page_uid)
        window = window_cls.__new__(window_cls)
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._geometry_edit_lease_handle = None
        window._geometry_edit_lease_request_id = ""
        window._geometry_edit_lease_selection = set()
        window._pages_with_takeoffs = set(pages_with_takeoffs)
        window._page_combo = combo
        view = AnnotationView(
            uid=f"{window_cls.__name__}-view",
            bid_uid=bid_ref.bid_uid,
            file_path=bid_ref.file_path,
            target_page_uid=target_page_uid,
        )
        refreshes = []
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager._window = window
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            has_takeoffs_for_pages=(
                lambda page_uids: page_uids[0] in pages_with_takeoffs
            ),
        )
        manager._get_page_data = lambda _view: PageViewDto(
            page=Page(uid=target_page_uid, name="Displayed"),
            bid_ref=bid_ref,
        )
        manager._apply_window_page = lambda _view, _page_data: refreshes.append(
            target_page_uid
        )
        return manager, window, combo, refreshes

    def test_detached_indicator_updates_real_model_role_by_page_uid(self):
        _manager, window, combo, _refreshes = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p1",
            pages_with_takeoffs=set(),
        )
        changed_rows = []
        combo._model.dataChanged.connect(
            lambda top_left, _bottom_right, _roles: changed_rows.append(
                top_left.data(QtCore.Qt.ItemDataRole.UserRole + 1)
            )
        )
        try:
            default_p1 = combo._page_items["p1"].data(_ITEM_ROLE_PRECHECK_ICON)
            default_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            window.set_page_has_takeoffs("p2", True)
            active_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            self.assertNotEqual(active_p2.cacheKey(), default_p2.cacheKey())
            self.assertEqual(
                combo._page_items["p1"].data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(),
                default_p1.cacheKey(),
            )
            self.assertEqual(window._pages_with_takeoffs, {"p2"})
            self.assertEqual(changed_rows, ["p2"])
            window.set_page_has_takeoffs("p2", False)
            restored_p2 = combo._page_items["p2"].data(_ITEM_ROLE_PRECHECK_ICON)
            self.assertEqual(restored_p2.cacheKey(), default_p2.cacheKey())
            self.assertEqual(window._pages_with_takeoffs, set())
            self.assertEqual(changed_rows, ["p2", "p2"])
        finally:
            combo.cleanup()
            combo.deleteLater()

    def test_takeoff_count_edits_change_detached_role_only_at_zero_boundary(self):
        pages_with_takeoffs = set()
        manager, _window, combo, refreshes = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p2",
            pages_with_takeoffs=pages_with_takeoffs,
        )
        role_changes = []
        combo._model.dataChanged.connect(
            lambda *_args: role_changes.append(self._indicator_is_active(combo, "p1"))
        )
        try:
            pages_with_takeoffs.add("p1")
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t2"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t2"])
            self.assertEqual(role_changes, [True])
            pages_with_takeoffs.clear()
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["t1"])
            self.assertEqual(role_changes, [True, False])
            pages_with_takeoffs.add("p1")
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["undo-t1"])
            pages_with_takeoffs.clear()
            manager._on_takeoffs_changed(page_uid="p1", takeoff_uids=["redo-t1"])
            self.assertEqual(role_changes, [True, False, True, False])
            self.assertEqual(refreshes, [])
        finally:
            combo.cleanup()
            combo.deleteLater()

    def test_takeoff_event_fans_out_to_annotation_and_view_models(self):
        pages_with_takeoffs = set()
        (
            annotation_manager,
            _annotation_window,
            annotation_combo,
            annotation_refreshes,
        ) = self._make_indicator_manager(
            AnnotationViewWindow,
            target_page_uid="p1",
            pages_with_takeoffs=pages_with_takeoffs,
        )
        view_manager, _view_window, view_combo, view_refreshes = (
            self._make_indicator_manager(
                ViewWindow,
                target_page_uid="p2",
                pages_with_takeoffs=pages_with_takeoffs,
            )
        )
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.TAKEOFFS_CHANGED, annotation_manager._on_takeoffs_changed
        )
        event_bus.subscribe(
            AppEvents.TAKEOFFS_CHANGED, view_manager._on_takeoffs_changed
        )
        try:
            pages_with_takeoffs.add("p1")
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["t1"],
            )
            self.assertTrue(self._indicator_is_active(annotation_combo, "p1"))
            self.assertTrue(self._indicator_is_active(view_combo, "p1"))
            self.assertEqual(annotation_refreshes, ["p1"])
            self.assertEqual(view_refreshes, [])
            pages_with_takeoffs.clear()
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["t1"],
            )
            self.assertFalse(self._indicator_is_active(annotation_combo, "p1"))
            self.assertFalse(self._indicator_is_active(view_combo, "p1"))
            view_manager._window = None
            pages_with_takeoffs.add("p1")
            event_bus.publish(
                AppEvents.TAKEOFFS_CHANGED,
                page_uid="p1",
                takeoff_uids=["undo-t1"],
            )
            self.assertTrue(self._indicator_is_active(annotation_combo, "p1"))
            self.assertFalse(self._indicator_is_active(view_combo, "p1"))
        finally:
            for combo in (annotation_combo, view_combo):
                combo.cleanup()
                combo.deleteLater()

    def test_reopened_detached_combo_reads_current_canonical_indicator_state(self):
        bid_ref = BidRef("memory-test.mdb", "bid-1")
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_takeoffs=lambda: [
                SimpleNamespace(page_uid="p1"),
                SimpleNamespace(page_uid="p1"),
            ],
        )
        current = manager._collect_pages_with_takeoffs(bid_ref)
        combo = SinglePageComboBox()
        try:
            combo.load_bid(self._indicator_bid(), pages_with_takeoffs=current)
            self.assertTrue(self._indicator_is_active(combo, "p1"))
            self.assertFalse(self._indicator_is_active(combo, "p2"))
        finally:
            combo.cleanup()
            combo.deleteLater()
