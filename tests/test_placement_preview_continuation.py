import unittest
from unittest.mock import patch
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete


class PreviewSurface(QtWidgets.QGraphicsView, PlacementModeMixin):
    def __init__(self):
        super().__init__()
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self._place_preview_items = []
        self._place_flashing = False
        self._backout_orig_parent_path = None

    def add_preview(self):
        item = QtWidgets.QGraphicsPathItem()
        path = QtGui.QPainterPath()
        path.addRect(0, 0, 10, 10)
        item.setPath(path)
        item.setBrush(QtGui.QBrush(QtGui.QColor("blue")))
        self._scene.addItem(item)
        self._place_preview_items.append(item)
        return item


class PlacementPreviewContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_old_preview_timer_cannot_consume_new_preview_flash(self):
        view = PreviewSurface()
        callbacks = []
        old = view.add_preview()
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
            ):
                view._flash_invalid_preview(QtGui.QColor("green"))
                view.clear_place_preview()
                current = view.add_preview()
                view._flash_invalid_preview(QtGui.QColor("green"))
            callbacks[0]()
            callbacks[1]()
            self.assertEqual(current.brush().color(), QtGui.QColor(200, 0, 0))
            self.assertEqual(old.brush().color(), QtGui.QColor("green"))
            self.assertFalse(view._place_flashing)
        finally:
            delete(old)
            delete(view)

    def test_current_preview_timer_restores_color(self):
        view = PreviewSurface()
        callbacks = []
        item = view.add_preview()
        try:
            with patch.object(
                QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
            ):
                view._flash_invalid_preview(QtGui.QColor("green"))
            callbacks[0]()
            self.assertEqual(item.brush().color(), QtGui.QColor(200, 0, 0))
            self.assertFalse(view._place_flashing)
        finally:
            delete(view)

    def test_destroyed_preview_owner_ignores_queued_timer(self):
        view = PreviewSurface()
        item = view.add_preview()
        callbacks = []
        with patch.object(
            QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
        ):
            view._flash_invalid_preview(QtGui.QColor("green"))
        delete(view)
        callbacks[0]()
