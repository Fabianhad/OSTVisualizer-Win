import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.domain.entities.annotation_view import AnnotationView
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from ost_visualizer.presentation.windows.view_window import (
    _VIEW_WINDOW_CONFIG,
    ViewWindow,
)
from PySide6.QtWidgets import QApplication
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeProjectData,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from tests.presentation.windows.detached_controls_support import FakeWindowIconProvider


def _renderers():
    return SimpleNamespace(
        rendering_service=FakeRenderingService(),
        load_coordinator=FakeLoadCoordinator(),
        takeoff_renderer=FakeTakeoffRenderer(),
        annotation_renderer=FakeAnnotationRenderer(),
        linear_geometry=FakeLinearGeometry(),
        prefetch_coordinator=None,
    )


def _all_access_granted():
    return PlanSurfaceAccessState(
        can_select_plan_items=True,
        can_place_plan_items=True,
        can_edit_plan_items=True,
        can_place_annotations=True,
        can_continue_annotation_placement=True,
        can_edit_annotations=True,
        can_edit_annotation_text=True,
        can_edit_page_settings=True,
    )


class DetachedInlineEditContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def _open_window(self, window_class, **window_options):
        data = FakeProjectData()
        bid_ref = BidRef("bid.mdb", "1")
        view = AnnotationView(
            uid="detached",
            bid_uid=bid_ref.bid_uid,
            file_path=bid_ref.file_path,
            target_page_uid=data.page.uid,
        )
        window = window_class(
            FakeWindowIconProvider(),
            view,
            EventBus(),
            PageViewDto(page=data.page, bid_ref=bid_ref),
            FakeColorService(),
            _renderers(),
            bid=data.bid,
            **window_options,
        )
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.cleanup)
        return window

    def test_detached_window_configs_control_inline_text_edit_capability(self):
        self.assertTrue(_ANNOTATION_WINDOW_CONFIG.allow_annotation_editing)
        self.assertFalse(_VIEW_WINDOW_CONFIG.allow_annotation_editing)
        # Real windows built from those configs project the capability into
        # their real plan views, even when every access flag is granted.
        annotation_window = self._open_window(
            AnnotationViewWindow, annotation_write_coordinator=SimpleNamespace()
        )
        view_window = self._open_window(ViewWindow)
        annotation_window.set_access_state(_all_access_granted())
        view_window.set_access_state(_all_access_granted())
        annotation_plan = annotation_window.plan_view
        self.assertTrue(annotation_plan._can_begin_text_annotation_inline_edit())
        self.assertTrue(annotation_plan._selection_enabled)
        self.assertTrue(annotation_plan._editing_enabled)
        view_plan = view_window.plan_view
        self.assertFalse(view_plan._can_begin_text_annotation_inline_edit())
        self.assertFalse(view_plan._text_annotation_inline_edit_enabled)
        self.assertFalse(view_plan._selection_enabled)
        self.assertFalse(view_plan._editing_enabled)
