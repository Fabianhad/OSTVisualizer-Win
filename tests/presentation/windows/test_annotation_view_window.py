import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
    AnnotationViewWindow,
)
from PySide6 import QtCore, QtWidgets


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_annotation_window_uses_shared_annotation_tool_specs_only(self):
        self.assertEqual(
            _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs,
            PLAN_ANNOTATION_TOOL_SPECS,
        )
        self.assertEqual(
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
            [
                "dimension_tool",
                "text_annotation_tool",
                "highlight_annotation_tool",
                "arrow_annotation_tool",
                "line_annotation_tool",
                "rectangle_annotation_tool",
                "oval_annotation_tool",
                "polygon_annotation_tool",
                "cloud_annotation_tool",
                "ink_annotation_tool",
                "hotlink_tool",
                "named_view_tool",
            ],
        )
        self.assertEqual(
            [
                spec.annotation_type
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
            [
                "dimension",
                "text",
                "highlight",
                "arrow",
                "line",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
                "hotlink",
                "namedview",
            ],
        )
        self.assertNotIn(
            "place_tool",
            [
                spec.action_key
                for spec in _ANNOTATION_WINDOW_CONFIG.annotation_tool_specs
            ],
        )
