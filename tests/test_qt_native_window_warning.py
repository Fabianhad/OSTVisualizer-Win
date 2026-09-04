import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class QtNativeWindowWarningTests(unittest.TestCase):
    def test_native_child_does_not_create_native_splitter_ancestor(self):
        app = _app()
        window = QtWidgets.QMainWindow()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        host = QtWidgets.QWidget(splitter)
        layout = QtWidgets.QVBoxLayout(host)
        native_child = QtWidgets.QWidget(host)
        native_child.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_DontCreateNativeAncestors
        )
        native_child.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        layout.addWidget(native_child)
        splitter.addWidget(host)
        window.setCentralWidget(splitter)
        window.show()
        app.processEvents()
        self.assertTrue(
            native_child.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        )
        self.assertIsNone(splitter.windowHandle())
        window.close()
        app.processEvents()

    def test_opengl_viewer_sets_native_ancestor_guard_before_native_window(self):
        source = inspect.getsource(OpenGLViewer.__init__)
        guard_index = source.index("WA_DontCreateNativeAncestors")
        native_index = source.index("WA_NativeWindow")
        self.assertLess(guard_index, native_index)

    def test_opengl_viewer_keeps_production_stack_and_splitter_ancestors_alien(self):
        app = _app()
        window = QtWidgets.QMainWindow()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        viewer_container = QtWidgets.QWidget(splitter)
        container_layout = QtWidgets.QVBoxLayout(viewer_container)
        view_stack = QtWidgets.QStackedWidget(viewer_container)
        viewer_frame = QtWidgets.QFrame(view_stack)
        viewer_layout = QtWidgets.QVBoxLayout(viewer_frame)
        viewer = OpenGLViewer(
            viewer_frame,
            SimpleNamespace(get_rgb=lambda _color: (0, 0, 0)),
        )
        viewer_layout.addWidget(viewer)
        view_stack.addWidget(viewer_frame)
        container_layout.addWidget(view_stack)
        splitter.addWidget(viewer_container)
        window.setCentralWidget(splitter)
        try:
            with patch.object(OpenGLViewer, "_ensure_renderer", return_value=False):
                window.show()
                app.processEvents()
            self.assertTrue(
                viewer.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
            )
            self.assertIsNone(view_stack.windowHandle())
            self.assertIsNone(splitter.windowHandle())
        finally:
            viewer.cleanup()
            window.close()
            app.processEvents()

    def test_opengl_context_menu_uses_a_real_top_level_window_owner(self):
        app = _app()
        window = QtWidgets.QMainWindow()
        host = QtWidgets.QWidget(window)
        layout = QtWidgets.QVBoxLayout(host)
        viewer = OpenGLViewer(
            host,
            SimpleNamespace(get_rgb=lambda _color: (0, 0, 0)),
        )
        layout.addWidget(viewer)
        window.setCentralWidget(host)
        created_menus = []

        class TrackedMenu(QtWidgets.QMenu):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_menus.append(self)

            def exec(self, *args, **kwargs):
                return None

        try:
            with patch.object(OpenGLViewer, "_ensure_renderer", return_value=False):
                window.show()
                app.processEvents()
            with patch.object(QtWidgets, "QMenu", TrackedMenu):
                local_pos = QtCore.QPoint(2, 2)
                event = QtGui.QContextMenuEvent(
                    QtGui.QContextMenuEvent.Reason.Mouse,
                    local_pos,
                    viewer.mapToGlobal(local_pos),
                )
                viewer.contextMenuEvent(event)
            app.processEvents()
        finally:
            viewer.cleanup()
            window.close()
            app.processEvents()
        self.assertGreaterEqual(len(created_menus), 1)
        self.assertIs(created_menus[0].parent(), window)
        self.assertTrue(created_menus[0].parentWidget().isWindow())


if __name__ == "__main__":
    unittest.main()
