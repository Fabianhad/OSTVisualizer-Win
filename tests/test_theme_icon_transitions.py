import gc
import os
import weakref
import unittest
from collections import Counter
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.utils import themed_icon
from ost_visualizer.presentation.utils.annotation_style_controls import (
    apply_annotation_tool_icon_color,
)
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle


class PaletteWindow(MainWindow):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)


class ThemeIconTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.palette = self.app.palette()
        self.registry = dict(themed_icon._REGISTRY)
        self.cache = dict(themed_icon._ICON_CACHE)
        themed_icon._REGISTRY.clear()
        themed_icon._ICON_CACHE.clear()
        self.window = PaletteWindow()

    def tearDown(self):
        delete(self.window)
        themed_icon._REGISTRY.clear()
        self.app.setPalette(self.palette)
        themed_icon._REGISTRY.update(self.registry)
        themed_icon._ICON_CACHE.clear()
        themed_icon._ICON_CACHE.update(self.cache)

    def transition(self, foreground):
        palette = QtGui.QPalette(self.palette)
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(foreground))
        palette.setColor(
            QtGui.QPalette.ColorRole.Window,
            QtGui.QColor("#202020" if foreground == "#ffffff" else "#ffffff"),
        )
        self.app.setPalette(palette)
        # Deliver the production palette notification synchronously, without sleeps.
        self.app.sendEvent(self.window, QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
        self.assertEqual(themed_icon.current_text_hex(), foreground)

    def color(self, icon, mode=QtGui.QIcon.Mode.Normal, state=QtGui.QIcon.State.Off):
        image = icon.pixmap(QtCore.QSize(24, 24), mode, state).toImage()
        colors = Counter(
            image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() == 255
        )
        self.assertTrue(colors)
        return colors.most_common(1)[0][0]

    def test_existing_toolbar_actions_keep_tool_color_across_both_theme_cycles(self):
        toolbar = QtWidgets.QToolBar(self.window)
        ordinary = QtGui.QAction(toolbar)
        tool = QtGui.QAction(toolbar)
        button = QtWidgets.QToolButton(toolbar)
        button.setDefaultAction(tool)
        toolbar.addAction(ordinary)
        toolbar.addWidget(button)
        tool.setCheckable(True)
        tool.setChecked(True)
        spec = PLAN_ANNOTATION_TOOL_SPECS[0]
        expected = "#297ac4"
        for cycle in (
            ("#ffffff", "#000000", "#ffffff"),
            ("#000000", "#ffffff", "#000000"),
        ):
            with self.subTest(cycle=cycle):
                self.transition(cycle[0])
                IconManager.apply(ordinary, IconId.OPEN_FILES)
                IconManager.apply(tool, spec.icon_id)
                with patch(
                    "ost_visualizer.presentation.utils.annotation_style_controls.get_annotation_style_for_tool",
                    return_value=AnnotationStyle(color=expected),
                ):
                    apply_annotation_tool_icon_color({spec.action_key: tool})
                actions = toolbar.actions()
                observed = [
                    (cycle[0], self.color(ordinary.icon()), self.color(tool.icon()))
                ]
                for foreground in cycle[1:]:
                    self.transition(foreground)
                    observed.append(
                        (
                            foreground,
                            self.color(ordinary.icon()),
                            self.color(tool.icon()),
                        )
                    )
                self.assertEqual(observed, [(fg, fg, expected) for fg in cycle])
                self.assertEqual(self.color(button.icon()), expected)
                self.assertEqual(toolbar.actions(), actions)
                self.assertTrue(tool.isChecked())
                self.assertTrue(tool.isEnabled())

    def test_existing_project_tree_icon_follows_palette_without_rebuilding_item(self):
        self.transition("#ffffff")
        tree = QtWidgets.QTreeWidget(self.window)
        item = QtWidgets.QTreeWidgetItem(tree, ["Database"])
        ProjectView._apply_item_icon(item, IconId.PROJECT_TREE_DATABASE)
        self.assertEqual(self.color(item.icon(0)), "#ffffff")
        for foreground in ("#000000", "#ffffff"):
            with self.subTest(foreground=foreground):
                self.transition(foreground)
                self.assertEqual(self.color(item.icon(0)), foreground)
                self.assertIs(tree.topLevelItem(0), item)

    def test_latest_binding_wins_without_duplicate_registry_entries(self):
        button = QtWidgets.QToolButton(self.window)
        IconManager.apply(button, IconId.ADD)
        IconManager.apply(button, IconId.DELETE)
        self.assertEqual(len(themed_icon._REGISTRY), 1)
        IconManager.apply_colored(button, IconId.DELETE, "#c83b62")
        IconManager.apply_colored(button, IconId.DELETE, "#315ab9")
        self.assertEqual(len(themed_icon._REGISTRY), 1)
        for foreground in ("#ffffff", "#000000", "#ffffff"):
            self.transition(foreground)
            self.assertEqual(self.color(button.icon()), "#315ab9")
        IconManager.apply(button, IconId.ADD)
        self.transition("#000000")
        self.assertEqual(self.color(button.icon()), "#000000")
        self.assertEqual(len(themed_icon._REGISTRY), 1)

    def test_shared_svg_colors_and_disabled_modes_remain_independent(self):
        themed = QtGui.QAction(self.window)
        colored = QtGui.QAction(self.window)
        disabled = QtWidgets.QToolButton(self.window)
        IconManager.apply(themed, IconId.PAN_TOOL)
        IconManager.apply_colored(colored, IconId.PAN_TOOL, "#ad3574")
        IconManager.apply(disabled, IconId.PAN_TOOL)
        IconManager.apply_colored(disabled, IconId.PAN_TOOL, "#ad3574")
        disabled.setEnabled(False)
        untouched = IconManager.colored_icon(IconId.PAN_TOOL, "#28ad61")
        for foreground in ("#ffffff", "#000000", "#ffffff"):
            self.transition(foreground)
            self.assertEqual(self.color(themed.icon()), foreground)
            self.assertEqual(self.color(colored.icon()), "#ad3574")
            self.assertEqual(self.color(untouched), "#28ad61")
            self.assertFalse(disabled.isEnabled())
            reference = IconManager.colored_icon(IconId.PAN_TOOL, "#ad3574")
            for mode in QtGui.QIcon.Mode:
                for state in QtGui.QIcon.State:
                    expected = reference.pixmap(
                        QtCore.QSize(24, 24), mode, state
                    ).toImage()
                    actual = (
                        disabled.icon()
                        .pixmap(QtCore.QSize(24, 24), mode, state)
                        .toImage()
                    )
                    self.assertEqual(actual, expected)
            self.assertNotEqual(
                reference.pixmap(24, 24, QtGui.QIcon.Mode.Normal).toImage(),
                reference.pixmap(24, 24, QtGui.QIcon.Mode.Disabled).toImage(),
            )

    def test_tree_bindings_survive_python_scope_and_release_deleted_items(self):
        tree = QtWidgets.QTreeWidget(self.window)
        tree.setColumnCount(2)
        item = QtWidgets.QTreeWidgetItem(tree, ["Folder", "Bid"])
        IconManager.apply_to_item(item, 0, IconId.FOLDER)
        IconManager.apply_to_item(item, 1, IconId.PROJECT_TREE_BID)
        reference = weakref.ref(item)
        del item
        gc.collect()
        self.assertIsNotNone(reference())
        self.transition("#000000")
        self.assertEqual(self.color(tree.topLevelItem(0).icon(0)), "#000000")
        self.assertEqual(self.color(tree.topLevelItem(0).icon(1)), "#000000")
        retained = tree.topLevelItem(0)
        tree.clear()
        self.transition("#ffffff")
        self.assertEqual(themed_icon._REGISTRY, {})
        del retained
        gc.collect()
        self.assertIsNone(reference())

    def test_cached_source_render_matches_fresh_render_after_return_to_dark(self):
        self.transition("#ffffff")
        first = IconManager.icon(IconId.PAN_TOOL)
        same = IconManager.icon(IconId.PAN_TOOL)
        self.assertEqual(first.cacheKey(), same.cacheKey())
        first_pixels = first.pixmap(24, 24).toImage()
        self.transition("#000000")
        light = IconManager.icon(IconId.PAN_TOOL)
        self.assertEqual(self.color(light), "#000000")
        self.assertEqual(self.color(first), "#ffffff")
        self.transition("#ffffff")
        dark_again = IconManager.icon(IconId.PAN_TOOL)
        self.assertEqual(dark_again.pixmap(24, 24).toImage(), first_pixels)

    def test_actual_main_toolbar_keeps_all_annotation_colors_after_theme_changes(self):
        from tests.test_cross_surface_presentation import SceneControlPresentationTests
        from ost_visualizer.presentation.utils.annotation_defaults import (
            get_annotation_style_for_tool,
        )

        self.transition("#ffffff")
        bundle, _zoom = SceneControlPresentationTests._main_components(self)
        actions = bundle.plan_tool_actions
        original_actions = dict(actions)
        for foreground in ("#000000", "#ffffff"):
            self.transition(foreground)
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                with self.subTest(tool=spec.action_key, foreground=foreground):
                    expected = get_annotation_style_for_tool(spec.annotation_type).color
                    self.assertEqual(
                        self.color(actions[spec.action_key].icon()), expected
                    )
                    self.assertIs(
                        actions[spec.action_key], original_actions[spec.action_key]
                    )

    def test_tree_icon_refresh_preserves_state_without_edit_notifications(self):
        tree = QtWidgets.QTreeWidget(self.window)
        item = QtWidgets.QTreeWidgetItem(tree, ["Folder"])
        QtWidgets.QTreeWidgetItem(item, ["Page"])
        item.setExpanded(True)
        item.setSelected(True)
        item.setCheckState(0, QtCore.Qt.CheckState.Checked)
        IconManager.apply_to_item(item, 0, IconId.FOLDER)
        edits = []
        tree.itemChanged.connect(
            lambda changed, column: edits.append((changed, column))
        )
        for foreground in ("#ffffff", "#000000", "#ffffff"):
            self.transition(foreground)
        self.assertEqual(edits, [])
        self.assertTrue(item.isExpanded())
        self.assertTrue(item.isSelected())
        self.assertEqual(item.checkState(0), QtCore.Qt.CheckState.Checked)
