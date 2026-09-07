import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryNode,
    ConditionSummaryValues,
    ConditionSummaryGrouping,
    SUMMARY_NODE_ROOT,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_CONDITION,
)
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab


class SummaryReactivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_inactive_summary_projects_folder_rename_delete_and_first_content(self):
        for change in ("rename", "delete", "first_content"):
            with self.subTest(change=change):
                tabs = QtWidgets.QTabWidget()
                summary = ConditionSummaryTab(
                    copy_allowed_fn=lambda: True, delete_allowed_fn=lambda: True
                )
                tabs.addTab(summary, "Summary")
                tabs.addTab(QtWidgets.QWidget(), "Other")

                def root(name, populated=True):
                    condition = ConditionSummaryNode(
                        kind=SUMMARY_NODE_CONDITION,
                        condition_uid="c1",
                        copyable=True,
                        deletable=True,
                        values=ConditionSummaryValues(
                            name="Current Condition", quantity1=3
                        ),
                    )
                    return ConditionSummaryNode(
                        kind=SUMMARY_NODE_ROOT,
                        children=(
                            [
                                ConditionSummaryNode(
                                    kind=SUMMARY_NODE_FOLDER,
                                    folder_uid="f1",
                                    label=name,
                                    children=[condition],
                                )
                            ]
                            if populated
                            else []
                        ),
                    )

                try:
                    summary.load_summary(
                        root("Old", change != "first_content"),
                        ConditionSummaryGrouping(),
                    )
                    tabs.resize(600, 350)
                    tabs.show()
                    self.app.processEvents()
                    if change != "first_content":
                        summary.tree.setCurrentItem(summary._condition_items["c1"][0])
                        self.assertTrue(summary.can_delete_current_row())
                    tabs.setCurrentIndex(1)
                    self.assertFalse(summary.isVisible())
                    with patch.object(
                        summary, "_rebuild_tree", wraps=summary._rebuild_tree
                    ) as rebuild:
                        summary.load_summary(
                            root("Renamed", change != "delete"),
                            ConditionSummaryGrouping(),
                        )
                        tabs.setCurrentIndex(0)
                        self.app.processEvents()
                        self.assertEqual(rebuild.call_count, 1)
                    if change == "rename":
                        self.assertIs(
                            summary.tree.currentItem(),
                            summary._condition_items["c1"][0],
                        )
                        self.assertTrue(summary.can_delete_current_row())
                        self.assertTrue(summary.tree.topLevelItem(0).isExpanded())
                        self.assertEqual(
                            summary.tree.topLevelItem(0).text(0), "Renamed"
                        )
                    elif change == "delete":
                        self.assertIsNone(summary.tree.currentItem())
                        self.assertFalse(summary.can_delete_current_row())
                        self.assertFalse(summary.can_copy_current_row())
                    else:
                        self.assertTrue(summary.tree.topLevelItem(0).isExpanded())
                        summary.tree.setCurrentItem(summary._condition_items["c1"][0])
                        self.assertTrue(summary.can_delete_current_row())
                        self.assertTrue(summary.can_copy_current_row())
                finally:
                    tabs.close()
                    delete(tabs)


if __name__ == "__main__":
    unittest.main()
