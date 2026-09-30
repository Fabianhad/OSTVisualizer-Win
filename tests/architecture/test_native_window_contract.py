import inspect
import unittest
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer


class NativeWindowConstructionContractTests(unittest.TestCase):
    def test_opengl_viewer_sets_native_ancestor_guard_before_native_window(self):
        source = inspect.getsource(OpenGLViewer.__init__)
        guard_index = source.index("WA_DontCreateNativeAncestors")
        native_index = source.index("WA_NativeWindow")
        self.assertLess(guard_index, native_index)
