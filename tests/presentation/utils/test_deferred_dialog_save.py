import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.deferred_dialog_save import (
    DeferredDialogSaveController,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.dialogs.master_data_support import (
    _app as _master_data_support__app,
)


class DeferredDialogSaveControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_deferred_dialog_save_controller_flushes_scheduled_save(self):
        calls = []
        controller = DeferredDialogSaveController(lambda: calls.append("save") or True)
        try:
            controller.schedule()
            self.assertEqual(calls, [])
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()
