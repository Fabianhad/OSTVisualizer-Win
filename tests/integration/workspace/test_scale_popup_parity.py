import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.components.resizable_combo import ResizableComboBox
from ost_visualizer.presentation.config import (
    TAB_INDEX_TAKEOFF,
    VIEWER_SCALE_COMBO_WIDTH,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from PySide6 import QtCore, QtWidgets
from tests.presentation.windows.detached_controls_support import (
    FakeDetachedPageData as _detached_support_FakeDetachedPageData,
    FakeToolbarPlanView as _detached_support_FakeToolbarPlanView,
    FakeWindowIconProvider as _detached_support_FakeWindowIconProvider,
    _detached_toolbar_renderers as _detached_support__detached_toolbar_renderers,
)
from tests.presentation.windows.detached_access_support import (
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

    def _make_toolbar_window(self, window_cls, *, include_write_coordinator=True):
        window_options = {}
        if include_write_coordinator:
            window_options["annotation_write_coordinator"] = SimpleNamespace()
        with patch(
            "ost_visualizer.presentation.windows.components.window.TakeoffPlanView",
            _detached_support_FakeToolbarPlanView,
        ), patch.object(
            DetachedPageViewWindow, "load_view", lambda *_args, **_kwargs: None
        ):
            window = window_cls(
                _detached_support_FakeWindowIconProvider(),
                AnnotationView(
                    uid="view-1",
                    bid_uid="bid-1",
                    target_page_uid="page-1",
                    file_path="bid.mdb",
                ),
                EventBus(),
                _detached_support_FakeDetachedPageData(),
                SimpleNamespace(),
                _detached_support__detached_toolbar_renderers(),
                **window_options,
            )
            window.set_access_state(_detached_support__full_plan_surface_access())
            return window

    def test_annotation_scale_uses_main_resizable_combo_contract(self):
        main_bar = PageSettingsBar(
            _detached_support_FakeWindowIconProvider(),
            EventBus(),
            lambda _file_path: None,
            SimpleNamespace(is_allowed=lambda _feature: True),
            SimpleNamespace(),
            get_page_fn=lambda _uid: None,
        )
        window = self._make_toolbar_window(AnnotationViewWindow)
        try:
            self.assertIs(type(window._scale_combo), type(main_bar.scale_combo))
            self.assertIsInstance(window._scale_combo, ResizableComboBox)
            self.assertEqual(window._scale_combo.width(), VIEWER_SCALE_COMBO_WIDTH)
            self.assertEqual(
                window._scale_combo.minimumSize(), main_bar.scale_combo.minimumSize()
            )
            self.assertEqual(
                window._scale_combo.maximumSize(), main_bar.scale_combo.maximumSize()
            )
            self.assertEqual(
                window._scale_combo._popup.minimumSize(),
                main_bar.scale_combo._popup.minimumSize(),
            )
            self.assertIsNotNone(
                window._scale_combo._popup.findChild(QtWidgets.QSizeGrip)
            )
        finally:
            window.cleanup()
            window.deleteLater()
            main_bar.scale_combo.cleanup_popup()
            main_bar.area_combo.cleanup_popup()
            main_bar.deleteLater()
