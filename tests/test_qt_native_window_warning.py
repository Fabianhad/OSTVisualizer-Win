import inspect
import unittest
from PySide6 import QtCore, QtWidgets
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


if __name__ == "__main__":
    unittest.main()
