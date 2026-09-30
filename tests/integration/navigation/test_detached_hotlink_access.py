import logging
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.windows.detached_lifecycle_support import (
    FakeConstructedWindow as _detached_support_FakeConstructedWindow,
    FakeSignal as _detached_support_FakeSignal,
    TrackableSignal as _detached_support_TrackableSignal,
)
from tests.presentation.windows.detached_access_support import (
    FakePlanSurfaceAccessManager as _detached_support_FakePlanSurfaceAccessManager,
    _full_plan_surface_access as _detached_support__full_plan_surface_access,
)


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def _make_opening_manager(self, access_manager, on_construct=None):
        calls = []
        windows = []
        active_view = None
        view_count = 0
        bid_ref = BidRef("job.ost", "bid-1")
        named_view = BidAnnotation(
            uid="named-view-1",
            annotation_type=ANNOTATION_TYPE_NAMED_VIEW,
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )

        def create_view(bid_ref, target_page_uid, target_named_view_uid=None):
            nonlocal active_view, view_count
            view_count += 1
            active_view = AnnotationView(
                uid=f"view-{view_count}",
                bid_uid=bid_ref.bid_uid,
                file_path=bid_ref.file_path,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            return active_view

        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.icon_provider = object()
        manager.event_bus = object()
        manager.project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: None,
            get_current_bid_ref=lambda: bid_ref,
            get_current_bid_file_path=lambda: bid_ref.file_path,
            get_all_takeoffs=lambda: [],
            get_all_annotations=lambda: [named_view],
            find_hotlinks_targeting=lambda _uids: [],
        )
        manager.repository = SimpleNamespace(
            create_view=create_view,
            get_active_view=lambda: active_view,
            update_view=lambda _view: None,
        )
        manager.config_model = Config()
        manager._coord_factory = SimpleNamespace(create=lambda: object())
        manager._color_service = object()
        manager._infrastructure_provider = SimpleNamespace(
            create_plan_view_renderers=lambda _coord_system, _color_service: object()
        )

        def construct_window(**_options):
            window = _detached_support_FakeConstructedWindow(calls)
            windows.append(window)
            if on_construct is not None:
                on_construct(manager, window)
            return window

        manager._window_factory = construct_window
        manager._annotation_write_service = None
        manager._write_service = None
        manager._saved_window_state_provider = None
        manager.parent_window = None
        manager.logger = logging.getLogger("test.detached_opening_manager")
        manager._ui_access_manager = access_manager
        manager._access_listener_registered = False
        manager._remote_surface_id = "detached-plan:test"
        manager._window = None
        manager._window_undo_service = None
        manager._opening = False
        manager._lifecycle_generation = 0
        manager._remote_update_generation = 0
        manager._visibility_changed_callback = None
        manager._on_window_page_selected = lambda _page_uid: None
        manager._on_window_named_view_selected = lambda _page_uid, _named_view_uid: None
        manager._on_window_scale_changed = lambda _page_uid, _sf1, _sf2: None
        manager._collect_pages_with_takeoffs = lambda _bid_ref: set()
        manager._get_page_data = lambda view: PageViewDto(
            page=Page(uid=view.target_page_uid, name="Page"),
            bid_ref=view.bid_ref,
        )
        return manager, windows, calls, bid_ref

    def test_hotlink_open_uses_same_annotation_access_as_normal_open_and_reopen(self):
        access = _detached_support_FakePlanSurfaceAccessManager(
            _detached_support__full_plan_surface_access()
        )
        manager, windows, _calls, bid_ref = self._make_opening_manager(access)
        manager.open_view(bid_ref, "page-1")
        normal_enabled = windows[-1].annotation_tools_enabled
        manager.close_view()
        use_case = OpenAnnotationViewUseCase(manager, manager.project_data)
        event = AppEvents.HOTLINK_CLICKED(
            hotlink_uid="hotlink-1",
            bid_page_uid="page-1",
            target_view_uid="named-view-1",
        )
        use_case.execute_from_hotlink(event)
        first_hotlink_enabled = windows[-1].annotation_tools_enabled
        manager.close_view()
        use_case.execute_from_hotlink(event)
        reopened_hotlink_enabled = windows[-1].annotation_tools_enabled
        self.assertTrue(normal_enabled)
        self.assertEqual(first_hotlink_enabled, normal_enabled)
        self.assertEqual(reopened_hotlink_enabled, normal_enabled)
        self.assertEqual(len(windows), 3)
