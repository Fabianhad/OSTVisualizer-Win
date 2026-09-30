import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog as MasterLayersDialog,
    LayersDialogMode,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterLayersDialog as _master_data_support_MasterLayersDialog,
    _app as _master_data_support__app,
)


class LayerCheckboxParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="bid-1",
            name=name,
            show=show,
            sequence=sequence,
        )

    def _click_checkbox(self, checkbox: QtWidgets.QCheckBox) -> None:
        QTest.mouseClick(checkbox, QtCore.Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def test_layers_dialog_and_sidebar_checkbox_state_stay_synchronized(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])

        def update_show(layer_uid, show):
            sidebar.set_layer_visible(layer_uid, show)
            return True

        dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            sidebar.show()
            self.app.processEvents()
            self._click_checkbox(dialog._checkboxes[0])
            self.assertFalse(dialog._checkboxes[0].isChecked())
            self.assertFalse(dialog._layers[0].show)
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            layer = next(
                layer for layer in sidebar.get_layers() if layer.uid == "layer-1"
            )
            self.assertFalse(layer.show)
            self._click_checkbox(dialog._checkboxes[0])
            self.assertTrue(dialog._checkboxes[0].isChecked())
            self.assertTrue(dialog._layers[0].show)
            self.assertTrue(sidebar._checkboxes[0].isChecked())
            layer = next(
                layer for layer in sidebar.get_layers() if layer.uid == "layer-1"
            )
            self.assertTrue(layer.show)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
            sidebar.close()
            sidebar.deleteLater()
