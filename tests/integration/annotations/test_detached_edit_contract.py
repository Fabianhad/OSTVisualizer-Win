import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.windows.annotation_view_window import (
    _ANNOTATION_WINDOW_CONFIG,
)
from ost_visualizer.presentation.windows.view_window import _VIEW_WINDOW_CONFIG
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)


class DetachedInlineEditContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_detached_window_configs_control_inline_text_edit_capability(self):
        self.assertTrue(_ANNOTATION_WINDOW_CONFIG.allow_annotation_editing)
        self.assertFalse(_VIEW_WINDOW_CONFIG.allow_annotation_editing)
