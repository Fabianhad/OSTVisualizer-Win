import unittest
from pathlib import Path
from PySide6 import QtWidgets
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    apply_tree_indentation,
)
from ost_visualizer.presentation.components.tree_popup_combo import (
    TreePopupComboBoxBase,
)
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.dialogs.cover_sheet.components import PlanTreeWidget


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TreeIndentationTests(unittest.TestCase):
    def test_shared_tree_indentation_applies_to_tree_widgets_and_views(self):
        _app()
        tree_widget = QtWidgets.QTreeWidget()
        tree_view = QtWidgets.QTreeView()
        try:
            apply_tree_indentation(tree_widget)
            apply_tree_indentation(tree_view)
            self.assertEqual(tree_widget.indentation(), CONDITION_TREE_INDENTATION)
            self.assertEqual(tree_view.indentation(), CONDITION_TREE_INDENTATION)
        finally:
            tree_widget.deleteLater()
            tree_view.deleteLater()

    def test_representative_app_trees_use_shared_indentation(self):
        _app()
        widgets = [
            TreePopupComboBoxBase(),
            BidLayersSidebar(None),
            ProjectView(None, event_bus=object()),
            PlanTreeWidget(),
        ]
        try:
            self.assertEqual(widgets[0]._tree.indentation(), CONDITION_TREE_INDENTATION)
            self.assertEqual(
                widgets[1]._table.indentation(), CONDITION_TREE_INDENTATION
            )
            self.assertEqual(
                widgets[2].top_tree.indentation(), CONDITION_TREE_INDENTATION
            )
            self.assertEqual(widgets[3].indentation(), CONDITION_TREE_INDENTATION)
        finally:
            for widget in widgets:
                widget.deleteLater()

    def test_presentation_tree_construction_sites_use_shared_indentation_helper(self):
        root = Path(__file__).resolve().parents[1]
        presentation_root = root / "ost_visualizer" / "presentation"
        tree_files = sorted(
            path
            for path in presentation_root.rglob("*.py")
            if path.name != "condition_tree_style.py"
            and (
                "QtWidgets.QTreeWidget(" in path.read_text(encoding="utf-8")
                or "QtWidgets.QTreeView(" in path.read_text(encoding="utf-8")
                or "(QtWidgets.QTreeWidget)" in path.read_text(encoding="utf-8")
                or "(QtWidgets.QTreeView)" in path.read_text(encoding="utf-8")
            )
        )
        missing = [
            str(path.relative_to(root))
            for path in tree_files
            if "apply_tree_indentation" not in path.read_text(encoding="utf-8")
            and "apply_condition_tree_style" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
