import unittest
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class QtNativeWindowOwnershipTests(unittest.TestCase):
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
