import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar


class ConditionFolderContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pending_folder_editor_does_not_survive_owner_transition(self):
        for transition in (
            "current",
            "hide",
            "close",
            "reopen",
            "disable",
            "reenable",
            "access",
            "clear",
            "repeat",
        ):
            with self.subTest(transition=transition):
                sidebar = ConditionsSidebar(None)
                try:
                    sidebar.load_conditions({}, {}, "Project")
                    sidebar.set_create_folder_enabled(True)
                    sidebar.show()
                    self.app.processEvents()
                    sidebar.set_pending_folder_edit("new")
                    if transition == "repeat":
                        sidebar.set_pending_folder_edit("new")
                    elif transition in ("hide", "reopen"):
                        sidebar.hide()
                        if transition == "reopen":
                            sidebar.show()
                    elif transition == "close":
                        sidebar.close()
                    elif transition in ("disable", "reenable"):
                        sidebar.setEnabled(False)
                        if transition == "reenable":
                            sidebar.setEnabled(True)
                    elif transition == "access":
                        sidebar.set_create_folder_enabled(False)
                    elif transition == "clear":
                        sidebar.clear()
                        sidebar.set_create_folder_enabled(True)
                    with patch.object(
                        sidebar.tree, "editItem", wraps=sidebar.tree.editItem
                    ) as edit:
                        sidebar.load_conditions(
                            {},
                            {"new": BidConditionFolder(uid="new", name="New")},
                            "Project",
                        )
                        self.assertEqual(
                            edit.call_count, int(transition in ("current", "repeat"))
                        )
                        if transition not in ("current", "repeat"):
                            self.assertIsNone(sidebar._editing_folder)
                finally:
                    sidebar.close()
                    delete(sidebar)


if __name__ == "__main__":
    unittest.main()
