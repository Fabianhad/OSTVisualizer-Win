import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.native_page_plane import (
    NATIVE_PLAN_TEXTURE_MAX_DIMENSION,
    NativePageImagePlaneProvider,
    native_plan_texture_render_scale,
    qimage_to_rgba_bytes,
)
from PySide6 import QtGui
from tests.presentation.visualization.native_plane_support import (
    FakeProjectData as _native_plane_support_FakeProjectData,
)


class NativePageImagePlaneTests(unittest.TestCase):
    def test_matching_native_consumers_share_overlay_only_composition(self):
        from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
        from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
            CompositeRenderer,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "overlay.tif")
            image = QtGui.QImage(32, 32, QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor("blue"))
            self.assertTrue(image.save(path))
            page = Page(
                uid="page-1",
                name="Sheet",
                image_path="",
                overlay_image_path=path,
                image_show_mode=1,
                width_pts=64,
                height_pts=64,
                scale_factor1=1,
                scale_factor2=72,
                overlay_rect=(0, 0, 32, 32),
            )
            data = _native_plane_support_FakeProjectData(page)
            cache = PageCache()
            try:
                providers = [
                    NativePageImagePlaneProvider(
                        data,
                        SimpleNamespace(active_page_uid=page.uid),
                        cache,
                        PageVisualizationMetadataService(data),
                    )
                    for _ in range(2)
                ]
                with patch.object(
                    CompositeRenderer,
                    "_draw_overlay_image",
                    autospec=True,
                    side_effect=CompositeRenderer._draw_overlay_image,
                ) as draw:
                    first, second = [
                        p.build_for_scene([page.uid], {page.uid: 0}) for p in providers
                    ]
                    self.assertIsNotNone(first)
                    self.assertEqual(first.pixels_rgba, second.pixels_rgba)
                    self.assertEqual(draw.call_count, 1)
                    page.overlay_rect = (32, 32, 64, 64)
                    moved = [
                        p.build_for_scene([page.uid], {page.uid: 0}) for p in providers
                    ]
                    self.assertEqual(moved[0].pixels_rgba, moved[1].pixels_rgba)
                    self.assertNotEqual(moved[0].pixels_rgba, first.pixels_rgba)
                    self.assertEqual(draw.call_count, 2)
                    # Explicit same-path source revision must invalidate the derived canvas.
                    from ost_visualizer.presentation.visualization.utils.source_signature import (
                        invalidate_source_files,
                    )

                    previous = os.stat(path)
                    image.fill(QtGui.QColor("red"))
                    self.assertTrue(image.save(path))
                    self.assertEqual(os.stat(path).st_size, previous.st_size)
                    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
                    invalidate_source_files([path])
                    replaced = [
                        p.build_for_scene([page.uid], {page.uid: 0}) for p in providers
                    ]
                    self.assertEqual(replaced[0].pixels_rgba, replaced[1].pixels_rgba)
                    self.assertNotEqual(replaced[0].pixels_rgba, moved[0].pixels_rgba)
                    self.assertEqual(draw.call_count, 3)
            finally:
                cache.clear()
