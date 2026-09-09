import gc
import unittest
import weakref
import shiboken6
from PySide6 import QtGui, QtWidgets
from ost_visualizer.presentation.utils import themed_icon


class ThemedIconLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self._registry = list(themed_icon._REGISTRY)
        themed_icon._REGISTRY.clear()

    def tearDown(self):
        themed_icon._REGISTRY.clear()
        themed_icon._REGISTRY.extend(self._registry)

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
        self.assertEqual(themed_icon._REGISTRY, [])

    def test_live_themed_icon_target_remains_registered_for_rebuild(self):
        button = QtWidgets.QToolButton()
        try:
            themed_icon.apply_themed_icon(
                button,
                "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            )
            themed_icon.rebuild_all_icons()
            self.assertEqual(len(themed_icon._REGISTRY), 1)
            target_ref, svg_name = themed_icon._REGISTRY[0]
            self.assertIs(target_ref(), button)
            self.assertEqual(
                svg_name,
                "pan_tool_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
            )
        finally:
            shiboken6.delete(button)


if __name__ == "__main__":
    unittest.main()
