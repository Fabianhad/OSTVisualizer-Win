import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.pdf.renderers import pattern_renderer
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class PatternRendererConditionBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_pattern_spacing_rejects_invalid_converted_values(self):
        class InvalidCoordinateSystem:
            def __init__(self, converted, view_scale=1.0):
                self.converted = converted
                self.page_info = {"view_scale": view_scale}

            def ost_to_pdf_points(self, _value):
                return self.converted

        for converted, view_scale in (
            (-2.0, 1.0),
            (0.0, 1.0),
            (float("nan"), 1.0),
            (2.0, float("inf")),
        ):
            with self.subTest(converted=converted, view_scale=view_scale):
                self.assertEqual(
                    pattern_renderer._convert_spacing(
                        2.0, InvalidCoordinateSystem(converted, view_scale)
                    ),
                    72.0,
                )

    def test_fixed_diagonal_intersections_count_shared_vertices_once(self):
        square = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
        backward = pattern_renderer._find_backward_diagonal_intersections(0.0, square)
        forward = pattern_renderer._find_forward_diagonal_intersections(10.0, square)
        self.assertEqual(backward, [(0.0, 0.0), (10.0, 10.0)])
        self.assertEqual(forward, [(0.0, 10.0), (10.0, 0.0)])
