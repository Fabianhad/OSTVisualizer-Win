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

    def test_annotation_window_config_is_editable_select_window_with_scale(self):
        config = _ANNOTATION_WINDOW_CONFIG
        self.assertEqual(config.window_title, "Annotation Window")
        self.assertTrue(config.show_scale_combo)
        self.assertTrue(config.show_select_tool)
        self.assertEqual(config.default_cursor_mode, "select")
        self.assertTrue(config.allow_annotation_editing)
        self.assertEqual(config.dropdown_state_key, "annotation")
