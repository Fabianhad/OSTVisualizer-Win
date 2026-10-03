import unittest
from types import SimpleNamespace
from ost_visualizer.presentation.components.project_tree_view import _BidTreeWidget
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
from PySide6 import QtWidgets
from tests.presentation.managers.permission_support import (
    _FakeAccess as _permissions__FakeAccess,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_project_tree_drag_restore_and_move_use_structure_permission(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        access = _permissions__FakeAccess({Feature.EDIT_PROJECT_TREE_STRUCTURE})
        tree = _BidTreeWidget()
        tree.set_ui_access_manager(access)
        item = QtWidgets.QTreeWidgetItem(["Bid"])
        item.setData(0, tree._ITEM_ROLE, ("bid", "bid-1", "db.mdb"))
        tree.addTopLevelItem(item)
        tree._drag_items = [item]
        self.assertTrue(tree._move_bids_allowed())
        self.assertEqual(access.checked, [Feature.EDIT_PROJECT_TREE_STRUCTURE])
        # Negative control: dragging is refused once the structure permission is gone.
        access.allowed.clear()
        self.assertFalse(tree._move_bids_allowed())
        tree.deleteLater()
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = _permissions__FakeAccess(set())
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                restore_bids=lambda refs: calls.append(("restore", refs)),
                move_bids=lambda refs, target: calls.append(("move", refs, target)),
            )
        )
        MainWindow._restore_project_bids(window, ["bid-1"])
        MainWindow._move_project_bids(window, ["bid-1"], "project-2")
        self.assertEqual(calls, [])
        # Positive control: the same command runs once the structure permission
        # is granted, so the empty result above is a real denial.
        window.ui_access_manager = _permissions__FakeAccess(
            {Feature.EDIT_PROJECT_TREE_STRUCTURE}
        )
        MainWindow._restore_project_bids(window, ["bid-1"])
        self.assertEqual(calls, [("restore", ["bid-1"])])
