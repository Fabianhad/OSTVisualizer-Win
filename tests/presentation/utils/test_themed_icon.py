import gc
import unittest
import weakref
from unittest import mock
import shiboken6
from ost_visualizer.presentation.utils import themed_icon
from PySide6 import QtGui, QtWidgets


class ThemedIconLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self._registry = dict(themed_icon._REGISTRY)
        themed_icon._REGISTRY.clear()

    def tearDown(self):
        themed_icon._REGISTRY.clear()
        themed_icon._REGISTRY.update(self._registry)

    def test_themed_icon_registry_does_not_own_destroyed_target_wrappers(self):
        target_refs = []
        for _ in range(100):
            for target in (QtWidgets.QToolButton(), QtGui.QAction()):
                themed_icon.apply_themed_icon(
                    target,
                    "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
                )
                target_refs.append(weakref.ref(target))
                shiboken6.delete(target)
        del target
        gc.collect()
        self.assertTrue(all(target_ref() is None for target_ref in target_refs))
        themed_icon.rebuild_all_icons()
        self.assertEqual(themed_icon._REGISTRY, {})

    def test_live_themed_icon_target_remains_registered_for_rebuild(self):
        button = QtWidgets.QToolButton()
        try:
            themed_icon.apply_themed_icon(
                button,
                "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            )
            themed_icon.rebuild_all_icons()
            self.assertEqual(len(themed_icon._REGISTRY), 1)
            binding = next(iter(themed_icon._REGISTRY.values()))
            self.assertIs(binding.target_ref(), button)
            self.assertEqual(
                binding.svg_name,
                "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            )
        finally:
            shiboken6.delete(button)

    @staticmethod
    def _opaque_pixel_name(icon):
        image = icon.pixmap(24, 24).toImage()
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.alpha() == 255:
                    return color.name()
        return None

    def test_rebuild_recolors_theme_bindings_and_keeps_explicit_colors(self):
        svg = "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
        themed = QtWidgets.QToolButton()
        explicit = QtGui.QAction()
        try:
            with mock.patch.object(
                themed_icon, "current_text_hex", return_value="#112233"
            ):
                themed_icon.apply_themed_icon(themed, svg)
                themed_icon.apply_colored_icon(explicit, svg, "#00aa00")
            self.assertEqual(self._opaque_pixel_name(themed.icon()), "#112233")
            self.assertEqual(self._opaque_pixel_name(explicit.icon()), "#00aa00")
            with mock.patch.object(
                themed_icon, "current_text_hex", return_value="#aa0000"
            ):
                themed_icon.rebuild_all_icons()
            self.assertEqual(self._opaque_pixel_name(themed.icon()), "#aa0000")
            self.assertEqual(self._opaque_pixel_name(explicit.icon()), "#00aa00")
        finally:
            shiboken6.delete(themed)
            shiboken6.delete(explicit)

    def test_reapplying_to_a_target_replaces_its_binding(self):
        button = QtWidgets.QToolButton()
        try:
            svg = "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            themed_icon.apply_themed_icon(button, svg)
            themed_icon.apply_colored_icon(button, svg, "#00aa00")
            self.assertEqual(len(themed_icon._REGISTRY), 1)
            binding = next(iter(themed_icon._REGISTRY.values()))
            self.assertEqual(binding.hex_color, "#00aa00")
        finally:
            shiboken6.delete(button)

    def test_tree_item_columns_are_registered_separately(self):
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(2)
        item = QtWidgets.QTreeWidgetItem(tree, ["a", "b"])
        svg = "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
        try:
            themed_icon.apply_themed_item_icon(item, 0, svg)
            themed_icon.apply_themed_item_icon(item, 1, svg)
            self.assertEqual(
                sorted(binding.column for binding in themed_icon._REGISTRY.values()),
                [0, 1],
            )
            self.assertFalse(item.icon(0).isNull())
            self.assertFalse(item.icon(1).isNull())
        finally:
            tree.deleteLater()


if __name__ == "__main__":
    unittest.main()
