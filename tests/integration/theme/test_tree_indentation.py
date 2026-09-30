import unittest
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.components.tree_popup_combo import (
    TreePopupComboBoxBase,
)
from ost_visualizer.presentation.dialogs.cover_sheet.components import PlanTreeWidget
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    apply_tree_indentation,
)
from PySide6 import QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TreeWidgetIndentationParityTests(unittest.TestCase):
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
