import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.page_view_dto import PageViewDto
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.dialogs.select_named_view_dialog import (
    SelectNamedViewDialog,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from PySide6 import QtCore, QtWidgets
from tests.presentation.windows.detached_annotation_support import (
    FakeAnnotationWriteService as _detached_support_FakeAnnotationWriteService,
    FakeDetachedPlanView as _detached_support_FakeDetachedPlanView,
)
from tests.presentation.windows.detached_controls_support import (
    FakeDetachedPageData as _detached_support_FakeDetachedPageData,
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

    def test_repeated_detached_hotlink_cancellation_releases_picker_widgets(self):
        write_service = _detached_support_FakeAnnotationWriteService()
        plan_view = _detached_support_FakeDetachedPlanView()
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        window._config = SimpleNamespace(allow_annotation_editing=True)
        window._access_state = _detached_support__full_plan_surface_access()
        window.page_data = _detached_support_FakeDetachedPageData()
        window._is_closing = False
        window._file_path = None
        window._project_write_svc = None
        window._ann_write_svc = write_service
        window._undo_svc = None
        window.plan_view = plan_view
        window.view = SimpleNamespace(bid_ref=BidRef("bid.mdb", "7"))
        window._named_views = [("nv1", "p1", "Page 1", "Lobby")]
        owner = QtWidgets.QWidget()

        def make_rejected_dialog(named_views, parent=None):
            del parent
            dialog = SelectNamedViewDialog(named_views, parent=owner)
            dialog.exec = lambda: QtWidgets.QDialog.DialogCode.Rejected
            return dialog

        try:
            with patch(
                "ost_visualizer.presentation.windows.components.window."
                "SelectNamedViewDialog",
                side_effect=make_rejected_dialog,
            ):
                for _ in range(100):
                    window._on_hotlink_placement_requested([5.0, 6.0], "p1")
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(owner.findChildren(SelectNamedViewDialog), [])
        finally:
            owner.deleteLater()
