import unittest
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from ost_visualizer.presentation.components.resizable_combo import ResizableComboBox


class ResizableComboContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.combo = ResizableComboBox()
        self.addCleanup(delete, self.combo)

    def test_constructor_initializes_popup_model_before_model_replacement(self):
        self.assertIs(self.combo._tree.model(), self.combo.model())
        for labels in (("First", "Second"), ("Replacement", "Other")):
            with self.subTest(labels=labels):
                model = QtGui.QStandardItemModel(self.combo)
                for label in labels:
                    model.appendRow(QtGui.QStandardItem(label))
                self.combo.setModel(model)
                self.assertIs(self.combo.model(), model)
                self.assertIs(self.combo._tree.model(), model)
                activations = []
                self.combo.activated.connect(activations.append)
                self.combo._tree.clicked.emit(model.index(1, 0))
                self.assertEqual(self.combo.currentText(), labels[1])
                self.assertEqual(activations, [1])
                self.combo.activated.disconnect(activations.append)

    def test_popup_cleanup_is_idempotent_and_deletes_its_native_owner(self):
        popup = self.combo._popup
        destroyed = []
        popup.destroyed.connect(lambda: destroyed.append(True))
        self.combo.cleanup_popup()
        self.combo.cleanup_popup()
        self.assertIsNone(self.combo._tree)
        self.assertIsNone(self.combo._popup)
        QtCore.QCoreApplication.sendPostedEvents(
            popup, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertEqual(destroyed, [True])
