import os
import unittest
from unittest.mock import patch
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from tests.presentation.dialogs.master_data_support import (
    _app as _master_data_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class LayersSidebarReactivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_hidden_layer_refresh_preserves_logical_scroll_region(self):
        for change in ("rename", "insert_before", "reorder", "delete_current", "empty"):
            with self.subTest(change=change):
                sidebar = BidLayersSidebar(None)

                def layers(ids):
                    return [
                        BidLayer(
                            uid=str(uid),
                            bid_uid="bid",
                            name=f"Layer {uid}",
                            show=True,
                            sequence=rank,
                        )
                        for rank, uid in enumerate(ids)
                    ]

                try:
                    sidebar.resize(300, 250)
                    sidebar.load_layers(layers(range(80)))
                    sidebar.show()
                    self.app.processEvents()
                    sidebar.table.setCurrentItem(sidebar.table.topLevelItem(40))
                    sidebar.table.verticalScrollBar().setValue(30)
                    self.app.processEvents()
                    top = sidebar.table.itemAt(1, 1)
                    anchor_uid = sidebar.get_layers()[
                        sidebar.table.indexOfTopLevelItem(top)
                    ].uid
                    sidebar.hide()
                    ids = list(range(80))
                    if change == "insert_before":
                        ids = list(range(100, 110)) + ids
                    elif change == "reorder":
                        ids = ids[10:] + ids[:10]
                    elif change == "delete_current":
                        ids.remove(40)
                    elif change == "empty":
                        ids = []
                    refreshed = layers(ids)
                    for layer in refreshed:
                        layer.name = "Updated " + layer.uid
                    with patch.object(
                        sidebar, "load_layers", wraps=sidebar.load_layers
                    ) as reload:
                        sidebar.load_layers(refreshed)
                        sidebar.show()
                        self.app.processEvents()
                        self.assertEqual(reload.call_count, 1)
                    if change == "empty":
                        self.assertEqual(sidebar.table.topLevelItemCount(), 0)
                        self.assertFalse(sidebar._delete_btn.isEnabled())
                    else:
                        top = sidebar.table.itemAt(1, 1)
                        self.assertIsNotNone(top)
                        self.assertEqual(
                            sidebar.get_layers()[
                                sidebar.table.indexOfTopLevelItem(top)
                            ].uid,
                            anchor_uid,
                        )
                        self.assertEqual(top.text(1), "Updated " + anchor_uid)
                    if change in ("delete_current", "empty"):
                        self.assertIsNone(sidebar._selected_uid)
                        self.assertEqual(sidebar.table.selectedItems(), [])
                    else:
                        self.assertEqual(sidebar._selected_uid, "40")
                finally:
                    sidebar.close()
                    delete(sidebar)

    def test_explicit_new_layer_selection_still_reveals_its_result(self):
        sidebar = BidLayersSidebar(None)
        try:
            layers = [
                BidLayer(uid=str(i), bid_uid="bid", name=str(i), show=True, sequence=i)
                for i in range(80)
            ]
            sidebar.resize(300, 250)
            sidebar.load_layers(layers)
            sidebar.show()
            self.app.processEvents()
            sidebar.table.verticalScrollBar().setValue(30)
            sidebar.hide()
            sidebar.set_pending_selection("new")
            sidebar.load_layers(
                layers
                + [
                    BidLayer(
                        uid="new", bid_uid="bid", name="New", show=True, sequence=80
                    )
                ]
            )
            self.app.processEvents()
            sidebar.show()
            self.app.processEvents()
            current = sidebar.table.currentItem()
            self.assertEqual(sidebar._selected_uid, "new")
            self.assertTrue(
                sidebar.table.viewport()
                .rect()
                .intersects(sidebar.table.visualItemRect(current))
            )
        finally:
            sidebar.close()
            delete(sidebar)


class LayersSidebarInteractionTests(unittest.TestCase):
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

    def test_layers_sidebar_checkbox_click_updates_visual_state_and_emits_once(self):
        sidebar = BidLayersSidebar(None)
        calls = []
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])
        sidebar.set_toggle_callback(lambda uid, show: calls.append((uid, show)))
        try:
            self._click_checkbox(sidebar._checkboxes[0])
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            self.assertEqual(calls, [("layer-1", False)])
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_can_add_first_layer_after_last_layer_disappears(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
        sidebar.set_interactive(True)
        sidebar.load_layers([])
        try:
            self.assertTrue(sidebar._add_btn.isEnabled())
            self.assertFalse(sidebar._select_all_btn.isEnabled())
            self.assertFalse(sidebar._unselect_all_btn.isEnabled())
            sidebar._add_btn.click()
            self.assertIsNotNone(sidebar._pending_new_item)
            self.assertEqual(sidebar._table.topLevelItemCount(), 1)
            self.assertEqual(sidebar._pending_new_after_sequence, 0)
        finally:
            sidebar.clear()
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_reload_cancels_pending_new_layer_editor(self):
        sidebar = BidLayersSidebar(None)
        layer = self._layer("layer-1", "Layer 1", 1)
        sidebar.load_layers([layer])
        sidebar.set_pending_selection(layer.uid)
        try:
            sidebar._on_add_clicked()
            self.assertIsNotNone(sidebar._pending_new_item)
            self.assertTrue(sidebar._pending_new_editor_connected)
            sidebar.load_layers([layer])
            self.assertIsNone(sidebar._pending_new_item)
            self.assertFalse(sidebar._pending_new_editor_connected)
            self.assertEqual(sidebar._selected_uid, layer.uid)
            self.assertEqual(sidebar._table.topLevelItemCount(), 1)
            sidebar._on_add_clicked()
            self.assertIsNotNone(sidebar._pending_new_item)
            self.assertEqual(sidebar._table.topLevelItemCount(), 2)
        finally:
            sidebar.clear()
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_inline_rename_rejects_blank_and_trims_name(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
        renamed = []
        sidebar.layer_renamed.connect(
            lambda layer_uid, name: renamed.append((layer_uid, name))
        )
        item = sidebar._table.topLevelItem(0)
        try:
            item.setText(1, "   ")
            self.assertEqual(item.text(1), "Layer 1")
            self.assertEqual(renamed, [])
            item.setText(1, "  Renamed Layer  ")
            self.assertEqual(renamed, [("layer-1", "Renamed Layer")])
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_inline_rename_reverts_after_access_loss(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
        renamed = []
        sidebar.layer_renamed.connect(
            lambda layer_uid, name: renamed.append((layer_uid, name))
        )
        item = sidebar._table.topLevelItem(0)
        try:
            sidebar.set_interactive(False)
            item.setText(1, "Unauthorized rename")
            self.assertEqual(renamed, [])
            self.assertEqual(item.text(1), "Layer 1")
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_access_loss_cancels_pending_new_layer_editor(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
        added = []
        sidebar.layer_added.connect(
            lambda name, sequence: added.append((name, sequence))
        )
        try:
            sidebar._on_add_clicked()
            self.assertIsNotNone(sidebar._pending_new_item)
            sidebar.set_interactive(False)
            self.assertIsNone(sidebar._pending_new_item)
            self.assertEqual(sidebar._table.topLevelItemCount(), 1)
            self.assertEqual(added, [])
        finally:
            sidebar.close()
            sidebar.deleteLater()
