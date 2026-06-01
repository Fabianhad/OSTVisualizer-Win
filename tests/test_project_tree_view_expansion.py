import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _EventBus:
    def publish(self, *_args, **_kwargs):
        pass


class ProjectTreeViewExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.view.deleteLater()
        self.app.processEvents()

    def setUp(self):
        self.view = ProjectView(None, _EventBus())

    def _loaded_file(self, source_bid_uids, deleted_bid_uids=()):
        return [
            LoadedFile(
                file_path="C:/jobs/test.mdb",
                display_name="test.mdb",
                projects=[
                    Project(
                        uid="project-1",
                        name="Source",
                        bids=[Bid(uid=uid, name=uid) for uid in source_bid_uids],
                    ),
                    Project(
                        uid=_DELETED_PROJECT_UID,
                        name="Deleted Bids",
                        bids=[Bid(uid=uid, name=uid) for uid in deleted_bid_uids],
                    ),
                ],
            )
        ]

    def _find_item(self, uid):
        found = None

        def walk(item):
            nonlocal found
            data = item.data(0, self.view._ITEM_ROLE)
            if data and data[1] == uid:
                found = item
                return
            for index in range(item.childCount()):
                walk(item.child(index))

        for index in range(self.view.top_tree.topLevelItemCount()):
            walk(self.view.top_tree.topLevelItem(index))
        return found

    def test_selection_restore_records_expanded_parent_nodes_for_rebuild(self):
        self.view.set_expanded_node_keys([])
        self.view.set_selected_node_state(
            {
                "kind": "bid",
                "file_path": "C:/jobs/test.mdb",
                "bid_uid": "bid-1",
                "project_uid": None,
            }
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        source_project = self._find_item("project-1")
        self.assertTrue(source_project.isExpanded())

    def test_blank_bid_status_displays_unassigned(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        bid_item = self._find_item("bid-1")
        self.assertEqual("(unassigned)", bid_item.text(2))
        self.assertIn(
            "project|C:/jobs/test.mdb|project-1",
            self.view.get_expanded_node_keys(),
        )
        self.view.build_complete_structure(self._loaded_file(["bid-2"], ["bid-1"]))
        source_project = self._find_item("project-1")
        self.assertTrue(source_project.isExpanded())

    def test_multi_select_bids_does_not_switch_active_bid(self):
        bid_selections = []
        multi_selections = []
        self.view.on_bid_selection = lambda bid_ref: bid_selections.append(bid_ref)
        self.view.on_multi_selection = lambda bids, projects: multi_selections.append(
            (list(bids), list(projects))
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        self.view.top_tree.setCurrentItem(bid_1)
        bid_1.setSelected(True)
        self.assertEqual([ref.bid_uid for ref in bid_selections], ["bid-1"])
        bid_2.setSelected(True)
        self.assertEqual([ref.bid_uid for ref in bid_selections], ["bid-1"])
        self.assertEqual(
            sorted(ref.bid_uid for ref in multi_selections[-1][0]),
            ["bid-1", "bid-2"],
        )


if __name__ == "__main__":
    unittest.main()
