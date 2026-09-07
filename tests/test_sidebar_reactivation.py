import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.project_tree_view import ProjectView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar


class SidebarReactivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_hidden_condition_refresh_preserves_valid_selection_and_current_row(self):
        for change in ("rename", "delete_current", "delete_all"):
            with self.subTest(change=change):
                sidebar = ConditionsSidebar(None)
                try:
                    conditions = {
                        uid: Condition(uid=uid, name=uid, ref_no=int(uid))
                        for uid in ("3", "5", "7")
                    }
                    sidebar.load_conditions(conditions, {}, "Project")
                    sidebar.resize(500, 300)
                    sidebar.show()
                    self.app.processEvents()
                    sidebar.tree.setCurrentItem(sidebar._condition_items["3"])
                    sidebar._condition_items["5"].setSelected(True)
                    sidebar.tree.setCurrentItem(
                        sidebar._condition_items["5"],
                        0,
                        QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                    sidebar.hide()
                    surviving = (
                        ("3", "5", "7")
                        if change == "rename"
                        else (("3", "7") if change == "delete_current" else ("7",))
                    )
                    refreshed = {
                        uid: Condition(uid=uid, name="Updated " + uid, ref_no=int(uid))
                        for uid in surviving
                    }
                    with patch.object(
                        sidebar, "_rebuild_tree", wraps=sidebar._rebuild_tree
                    ) as rebuild:
                        sidebar.load_conditions(refreshed, {}, "Project")
                        sidebar.show()
                        self.app.processEvents()
                        self.assertEqual(rebuild.call_count, 1)
                    expected = (
                        {"3", "5"}
                        if change == "rename"
                        else ({"3"} if change == "delete_current" else set())
                    )
                    self.assertEqual(
                        set(sidebar.get_selected_condition_uids()), expected
                    )
                    current = sidebar.tree.currentItem()
                    if change == "rename":
                        self.assertIs(current, sidebar._condition_items["5"])
                        self.assertEqual(current.text(1), "Updated 5")
                    else:
                        self.assertIsNone(current)
                    self.assertIs(sidebar._conditions, refreshed)
                finally:
                    sidebar.close()
                    delete(sidebar)

    def test_hidden_refresh_keeps_folder_current_without_losing_condition_selection(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        try:
            sidebar.load_conditions(
                {"same": Condition(uid="same", name="Condition")},
                {"same": BidConditionFolder(uid="same", name="Folder")},
                "Project",
            )
            sidebar.show()
            self.app.processEvents()
            sidebar.tree.setCurrentItem(sidebar._condition_items["same"])
            sidebar._folder_items["same"].setSelected(True)
            sidebar.tree.setCurrentItem(
                sidebar._folder_items["same"],
                0,
                QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
            )
            sidebar.hide()
            sidebar.load_conditions(
                {"same": Condition(uid="same", name="New Condition")},
                {"same": BidConditionFolder(uid="same", name="New Folder")},
                "Project",
            )
            sidebar.show()
            self.app.processEvents()
            self.assertEqual(sidebar.get_selected_condition_uids(), ["same"])
            self.assertTrue(sidebar._folder_items["same"].isSelected())
            self.assertIs(sidebar.tree.currentItem(), sidebar._folder_items["same"])
            self.assertEqual(sidebar.tree.currentItem().text(0), "New Folder")
        finally:
            sidebar.close()
            delete(sidebar)

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

    def test_project_tree_hidden_refresh_preserves_logical_viewport(self):
        for change in ("rename", "insert", "delete_before"):
            with self.subTest(change=change):
                view = ProjectView(None, SimpleNamespace(publish=lambda *args: None))

                def files(ids, prefix="Bid"):
                    return [
                        LoadedFile(
                            file_path="C:/test.mdb",
                            display_name="test",
                            projects=[
                                Project(
                                    uid="p",
                                    name="Project",
                                    bids=[
                                        Bid(
                                            uid=str(i),
                                            name=f"{prefix} {i:03}",
                                            bid_no=i,
                                        )
                                        for i in ids
                                    ],
                                )
                            ],
                        )
                    ]

                try:
                    view.resize(600, 300)
                    view.build_complete_structure(files(range(80)))
                    view.show()
                    self.app.processEvents()
                    view.restore_bid_selection(
                        BidRef(file_path="C:/test.mdb", bid_uid="5")
                    )
                    view.top_tree.verticalScrollBar().setValue(30)
                    self.app.processEvents()
                    top = view.top_tree.itemAt(1, 1)
                    anchor = view._get_node_key(top)
                    self.assertNotEqual(view._get_item_info(top)[1], "5")
                    view.hide()
                    ids = list(range(80))
                    if change == "insert":
                        ids = list(range(-10, 0)) + ids
                    elif change == "delete_before":
                        ids = [i for i in ids if i not in (10, 11, 12)]
                    with patch.object(
                        view,
                        "_build_multi_file_structure",
                        wraps=view._build_multi_file_structure,
                    ) as rebuild:
                        view.build_complete_structure(files(ids, "Renamed"))
                        view.show()
                        self.app.processEvents()
                        self.assertEqual(rebuild.call_count, 1)
                    self.assertEqual(
                        view._get_node_key(view.top_tree.itemAt(1, 1)), anchor
                    )
                    self.assertEqual(view.current_bid_ref.bid_uid, "5")
                    self.assertEqual(view.top_tree.currentItem().text(1), "Renamed 005")
                finally:
                    view.close()
                    view.cleanup()
                    delete(view)


if __name__ == "__main__":
    unittest.main()
