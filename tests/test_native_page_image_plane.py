import os
import tempfile
import unittest
from types import SimpleNamespace
from PySide6 import QtGui
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    native_page_plane_transform,
    threejs_page_plane_transform,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.native_page_plane import (
    NATIVE_PLAN_TEXTURE_MAX_DIMENSION,
    NativePageImagePlaneProvider,
    native_plan_texture_render_scale,
    qimage_to_rgba_bytes,
)


class FakeProjectData:
    def __init__(self, page):
        self.page = page

    def get_page(self, page_uid):
        return self.page if page_uid == self.page.uid else None

    def get_selected_page_uids(self):
        return [self.page.uid]

    def get_last_selected_page_uid(self):
        return self.page.uid

    def get_image_layer_uid(self):
        return "image"


class FakePageCache:
    def __init__(self, image):
        self.image = image
        self.calls = []

    def get_page(self, file_path, page_index=0, scale=1.0, rotation=0):
        self.calls.append((file_path, page_index, scale, rotation))
        return self.image


class NativePageImagePlaneTests(unittest.TestCase):
    def test_unchecked_active_page_falls_back_to_first_checked_page(self):
        provider = NativePageImagePlaneProvider(
            SimpleNamespace(get_selected_page_uids=lambda: ["page-b"]),
            SimpleNamespace(active_page_uid="page-a"),
            None,
            None,
        )
        self.assertEqual(provider._active_page_uid(), "page-b")

    def test_native_and_threejs_plane_transforms_share_floor_offset(self):
        native = native_page_plane_transform(20.0, 10.0, (-5, 5, -2, 2, 3, 8))
        threejs = threejs_page_plane_transform(
            20.0, 10.0, {"min": [-5.0, 3.0, -10.0], "max": [5.0, 8.0, 0.0]}
        )
        self.assertEqual(native.plane_x, -10.0)
        self.assertEqual(native.plane_y, 5.0)
        self.assertAlmostEqual(native.plane_z, 3.0 - PAGE_PLANE_FLOOR_OFFSET)
        self.assertTrue(native.flip_u)
        self.assertFalse(native.flip_v)
        self.assertEqual(threejs.plane_x, -10.0)
        self.assertEqual(threejs.plane_z, -5.0)
        self.assertAlmostEqual(threejs.plane_y, 3.0 - PAGE_PLANE_FLOOR_OFFSET)
        self.assertTrue(threejs.flip_u)
        self.assertTrue(threejs.flip_v)

    def test_render_scale_is_bounded_for_large_pages(self):
        scale = native_plan_texture_render_scale(9000.0, 6000.0)
        self.assertLess(scale, 1.0)
        self.assertLessEqual(9000.0 * scale, NATIVE_PLAN_TEXTURE_MAX_DIMENSION)

    def test_qimage_to_rgba_bytes_returns_packed_rgba(self):
        image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_RGBA8888)
        image.setPixelColor(0, 0, QtGui.QColor(10, 20, 30, 40))
        image.setPixelColor(1, 0, QtGui.QColor(50, 60, 70, 80))
        pixels, width, height = qimage_to_rgba_bytes(image)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(pixels, bytes([10, 20, 30, 40, 50, 60, 70, 80]))

    def test_provider_builds_active_page_plane_from_existing_page_cache(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            source_path = handle.name
        self.addCleanup(lambda: os.path.exists(source_path) and os.remove(source_path))
        page = Page(
            uid="page-1",
            name="A1",
            image_path=source_path,
            width_pts=720.0,
            height_pts=360.0,
            scale_factor1=1.0,
            scale_factor2=2.0,
            page_index=2,
            layer_visible=False,
        )
        image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_RGBA8888)
        image.fill(QtGui.QColor(1, 2, 3, 4))
        cache = FakePageCache(image)
        provider = NativePageImagePlaneProvider(
            project_data := FakeProjectData(page),
            SimpleNamespace(active_page_uid="page-1"),
            cache,
            PageVisualizationMetadataService(project_data),
        )
        data = provider.build_for_bounds((-5, 5, -2, 2, 3, 8))
        self.assertIsNotNone(data)
        self.assertEqual(data.page_uid, "page-1")
        self.assertEqual(data.width_px, 2)
        self.assertEqual(data.height_px, 1)
        self.assertEqual(data.page_width, 20.0)
        self.assertEqual(data.page_height, 10.0)
        self.assertEqual(data.plane_x, -10.0)
        self.assertEqual(data.plane_y, 5.0)
        self.assertAlmostEqual(data.plane_z, 2.99)
        self.assertFalse(data.visible)
        self.assertEqual(cache.calls[0][1], 2)


if __name__ == "__main__":
    unittest.main()
