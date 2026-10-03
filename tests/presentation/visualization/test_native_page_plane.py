import os
import tempfile
import unittest
from types import SimpleNamespace
from ost_visualizer.application.render_quality import (
    CONSTRAINED_RENDER_SCALE_FLOOR,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    native_page_plane_transform,
    threejs_page_plane_transform,
)
from ost_visualizer.presentation.visualization.native_page_plane import (
    NATIVE_PLAN_TEXTURE_MAX_DIMENSION,
    NativePageImagePlaneProvider,
    native_plan_texture_render_scale,
    qimage_to_rgba_bytes,
)
from PySide6 import QtGui
from tests.presentation.visualization.native_plane_support import (
    FakePageCache as _native_plane_support_FakePageCache,
    FakeProjectData as _native_plane_support_FakeProjectData,
)

_BID_REF = object()


class _FakeCompositeRenderer:
    def __init__(self, image):
        self.image = image
        self.calls = []

    def render_composite(self, page, bid_ref, render_scale, raster_rotation):
        self.calls.append(("composite", page, render_scale, (bid_ref, raster_rotation)))
        return self.image

    def render_overlay_only(self, page, render_scale, *, tint_rgb=None):
        self.calls.append(("overlay", page, render_scale, {"tint_rgb": tint_rgb}))
        return self.image


class _BidRefProjectData(_native_plane_support_FakeProjectData):
    def get_current_bid_ref(self):
        return _BID_REF


def _rgba_image(width, height, *colors):
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGBA8888)
    for index in range(width * height):
        image.setPixelColor(index % width, index // width, colors[index % len(colors)])
    return image


class NativePageImagePlaneTests(unittest.TestCase):
    def make_source_file(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            path = handle.name
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def build(
        self,
        page,
        image,
        *,
        cache=None,
        composite=None,
        scene_page_uids=None,
        elevations=None,
    ):
        project_data = _BidRefProjectData(page)
        cache = cache or _native_plane_support_FakePageCache(image)
        provider = NativePageImagePlaneProvider(
            project_data,
            SimpleNamespace(active_page_uid=page.uid),
            cache,
            PageVisualizationMetadataService(project_data),
        )
        if composite is not None:
            provider._composite_renderer = composite
        return provider.build_for_scene(
            scene_page_uids if scene_page_uids is not None else [page.uid],
            elevations if elevations is not None else {page.uid: 0.0},
        )

    def test_unchecked_active_page_falls_back_to_first_checked_page(self):
        provider = NativePageImagePlaneProvider(
            SimpleNamespace(get_selected_page_uids=lambda: ["page-b"]),
            SimpleNamespace(active_page_uid="page-a"),
            None,
            None,
        )
        self.assertEqual(provider._rendered_page_uid(["page-b"]), "page-b")

    def test_fallback_page_is_stable_for_equivalent_checked_page_orderings(self):
        ui_state = SimpleNamespace(active_page_uid="unchecked-page")
        first = NativePageImagePlaneProvider(
            SimpleNamespace(get_selected_page_uids=lambda: ["page-b", "page-a"]),
            ui_state,
            None,
            None,
        )
        second = NativePageImagePlaneProvider(
            SimpleNamespace(get_selected_page_uids=lambda: ["page-a", "page-b"]),
            ui_state,
            None,
            None,
        )
        self.assertEqual(first._rendered_page_uid(["page-b", "page-a"]), "page-a")
        self.assertEqual(second._rendered_page_uid(["page-a", "page-b"]), "page-a")

    def test_render_scale_is_bounded_for_large_pages(self):
        scale = native_plan_texture_render_scale(9000.0, 6000.0)
        self.assertLess(scale, RASTER_NATIVE_RENDER_SCALE)
        self.assertLessEqual(9000.0 * scale, NATIVE_PLAN_TEXTURE_MAX_DIMENSION)
        # The longest side lands exactly on the texture dimension limit.
        self.assertAlmostEqual(scale, 4096.0 / 9000.0, places=12)
        self.assertAlmostEqual(9000.0 * scale, 4096.0, places=9)

    def test_render_scale_is_native_for_pages_within_limits_and_invalid_sizes(self):
        self.assertEqual(
            native_plan_texture_render_scale(720.0, 360.0),
            RASTER_NATIVE_RENDER_SCALE,
        )
        for size in ((0.0, 100.0), (100.0, 0.0), (-5.0, 100.0), (None, None)):
            with self.subTest(size=size):
                self.assertEqual(
                    native_plan_texture_render_scale(*size),
                    RASTER_NATIVE_RENDER_SCALE,
                )

    def test_render_scale_uses_shared_floor_for_extreme_pages(self):
        self.assertEqual(
            native_plan_texture_render_scale(1_000_000_000.0, 1_000_000_000.0),
            CONSTRAINED_RENDER_SCALE_FLOOR,
        )

    def test_qimage_to_rgba_bytes_returns_packed_rgba(self):
        image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_RGBA8888)
        image.setPixelColor(0, 0, QtGui.QColor(10, 20, 30, 40))
        image.setPixelColor(1, 0, QtGui.QColor(50, 60, 70, 80))
        pixels, width, height = qimage_to_rgba_bytes(image)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(pixels, bytes([10, 20, 30, 40, 50, 60, 70, 80]))

    def test_qimage_to_rgba_bytes_converts_other_formats_to_rgba_byte_order(self):
        image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_ARGB32)
        image.setPixelColor(0, 0, QtGui.QColor(1, 2, 3, 255))
        image.setPixelColor(1, 0, QtGui.QColor(4, 5, 6, 128))
        pixels, width, height = qimage_to_rgba_bytes(image)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(pixels, bytes([1, 2, 3, 255, 4, 5, 6, 128]))

    def test_qimage_to_rgba_bytes_rejects_missing_and_null_images(self):
        self.assertIsNone(qimage_to_rgba_bytes(None))
        self.assertIsNone(qimage_to_rgba_bytes(QtGui.QImage()))

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
        cache = _native_plane_support_FakePageCache(image)
        provider = NativePageImagePlaneProvider(
            project_data := _native_plane_support_FakeProjectData(page),
            SimpleNamespace(active_page_uid="page-1"),
            cache,
            PageVisualizationMetadataService(project_data),
        )
        data = provider.build_for_scene(["page-1"], {"page-1": 3.0})
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
        self.assertEqual(data.pixels_rgba, bytes([1, 2, 3, 4] * 2))
        self.assertEqual((data.opacity, data.flip_u, data.flip_v), (1.0, True, False))
        # Plan texture is rendered unrotated from the page's source at the
        # native scale (720 x 360 pt is well inside the texture limits).
        self.assertEqual(cache.calls, [(source_path, 2, 1.0, 0)])

    def test_active_2d_page_cannot_supply_another_checked_pages_elevation(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            source_path = handle.name
        self.addCleanup(lambda: os.path.exists(source_path) and os.remove(source_path))
        page_a = Page(
            uid="page-a",
            name="A",
            image_path=source_path,
            width_pts=720.0,
            height_pts=360.0,
        )
        page_b = Page(
            uid="page-b",
            name="B",
            image_path=source_path,
            width_pts=720.0,
            height_pts=360.0,
        )
        project_data = _native_plane_support_FakeProjectData(
            [page_a, page_b],
            selected_page_uids=["page-b"],
        )
        ui_state = SimpleNamespace(active_page_uid="page-a")
        image = QtGui.QImage(1, 1, QtGui.QImage.Format.Format_RGBA8888)
        image.fill(QtGui.QColor(1, 2, 3, 4))
        provider = NativePageImagePlaneProvider(
            project_data,
            ui_state,
            _native_plane_support_FakePageCache(image),
            PageVisualizationMetadataService(project_data),
        )
        plane = provider.build_for_scene(
            ["page-b"],
            {"page-a": 10.0, "page-b": -100.0},
        )
        self.assertEqual(plane.page_uid, "page-b")
        self.assertAlmostEqual(plane.plane_z, -100.0 - PAGE_PLANE_FLOOR_OFFSET)

    def test_active_checked_page_switch_uses_matching_page_elevation(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            source_path = handle.name
        self.addCleanup(lambda: os.path.exists(source_path) and os.remove(source_path))
        pages = [
            Page(
                uid=uid,
                name=uid,
                image_path=source_path,
                width_pts=720.0,
                height_pts=360.0,
            )
            for uid in ("page-a", "page-b")
        ]
        project_data = _native_plane_support_FakeProjectData(
            pages,
            selected_page_uids=["page-b", "page-a"],
        )
        ui_state = SimpleNamespace(active_page_uid="page-a")
        image = QtGui.QImage(1, 1, QtGui.QImage.Format.Format_RGBA8888)
        image.fill(QtGui.QColor(1, 2, 3, 4))
        provider = NativePageImagePlaneProvider(
            project_data,
            ui_state,
            _native_plane_support_FakePageCache(image),
            PageVisualizationMetadataService(project_data),
        )
        elevations = {"page-a": 10.0, "page-b": -100.0}
        page_a_plane = provider.build_for_scene(["page-b", "page-a"], elevations)
        ui_state.active_page_uid = "page-b"
        page_b_plane = provider.build_for_scene(["page-b", "page-a"], elevations)
        project_data.selected_page_uids = ["page-a", "page-b"]
        reordered_page_b_plane = provider.build_for_scene(
            ["page-a", "page-b"], elevations
        )
        self.assertEqual(
            (page_a_plane.page_uid, page_a_plane.plane_z),
            ("page-a", 10.0 - PAGE_PLANE_FLOOR_OFFSET),
        )
        self.assertEqual(
            (page_b_plane.page_uid, page_b_plane.plane_z),
            ("page-b", -100.0 - PAGE_PLANE_FLOOR_OFFSET),
        )
        self.assertEqual(reordered_page_b_plane, page_b_plane)

    def test_visible_page_layer_makes_plane_visible(self):
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=72.0,
            height_pts=72.0,
        )
        data = self.build(page, _rgba_image(1, 1, QtGui.QColor(1, 2, 3, 4)))
        self.assertTrue(data.visible)

    def test_rotation_flip_and_effects_are_applied_to_the_unrotated_render(self):
        a, b = QtGui.QColor(10, 20, 30, 255), QtGui.QColor(200, 150, 100, 255)
        c, d = QtGui.QColor(1, 2, 3, 255), QtGui.QColor(4, 5, 6, 255)
        grid = _rgba_image(2, 2, a, b, c, d)

        def rgba(*colors):
            return b"".join(bytes(color.getRgb()) for color in colors)

        cases = [
            ({"flip_x": True}, rgba(b, a, d, c)),
            ({"flip_y": True}, rgba(c, d, a, b)),
            ({"flip_x": True, "flip_y": True}, rgba(d, c, b, a)),
            ({"rotation": 90}, rgba(b, d, a, c)),
            (
                {"invert": True},
                rgba(
                    QtGui.QColor(245, 235, 225, 255),
                    QtGui.QColor(55, 105, 155, 255),
                    QtGui.QColor(254, 253, 252, 255),
                    QtGui.QColor(251, 250, 249, 255),
                ),
            ),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                page = Page(
                    uid="page-1",
                    name="A1",
                    image_path=self.make_source_file(),
                    width_pts=72.0,
                    height_pts=72.0,
                    **overrides,
                )
                cache = _native_plane_support_FakePageCache(grid)
                data = self.build(page, grid, cache=cache)
                self.assertEqual((data.width_px, data.height_px), (2, 2))
                self.assertEqual(data.pixels_rgba, expected)
                # The page is always rendered unrotated and unflipped.
                self.assertEqual(cache.calls[0][3], 0)

    def test_rotation_by_a_quarter_turn_swaps_texture_dimensions(self):
        a, b = QtGui.QColor(10, 20, 30, 255), QtGui.QColor(200, 150, 100, 255)
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=72.0,
            height_pts=36.0,
            rotation=90,
        )
        data = self.build(page, _rgba_image(2, 1, a, b))
        self.assertEqual((data.width_px, data.height_px), (1, 2))
        # Counter-clockwise quarter turn: the right pixel ends up on top.
        self.assertEqual(data.pixels_rgba, bytes(b.getRgb()) + bytes(a.getRgb()))

    def test_large_page_is_rendered_at_the_bounded_texture_scale(self):
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=9000.0,
            height_pts=6000.0,
        )
        cache = _native_plane_support_FakePageCache(
            _rgba_image(1, 1, QtGui.QColor(1, 2, 3, 4))
        )
        data = self.build(page, cache.image, cache=cache)
        self.assertIsNotNone(data)
        self.assertAlmostEqual(cache.calls[0][2], 4096.0 / 9000.0, places=12)

    def test_bitonal_effect_clamps_paper_white_in_the_texture(self):
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=72.0,
            height_pts=72.0,
            bitonal=True,
        )
        white = QtGui.QColor(255, 255, 255, 255)
        data = self.build(page, _rgba_image(1, 1, white))
        self.assertEqual(data.pixels_rgba, bytes([220, 220, 220, 255]))

    def test_pages_without_usable_source_or_size_supply_no_plane(self):
        source = self.make_source_file()
        missing = source + ".missing"
        image = _rgba_image(1, 1, QtGui.QColor(1, 2, 3, 4))
        cases = {
            "no image path": Page(
                uid="page-1", name="A", image_path="", width_pts=72.0, height_pts=72.0
            ),
            "image file missing": Page(
                uid="page-1",
                name="A",
                image_path=missing,
                width_pts=72.0,
                height_pts=72.0,
            ),
            "overlay mode without overlay": Page(
                uid="page-1",
                name="A",
                image_path=source,
                width_pts=72.0,
                height_pts=72.0,
                image_show_mode=1,
            ),
            "zero page size": Page(
                uid="page-1", name="A", image_path=source, width_pts=0.0, height_pts=0.0
            ),
        }
        for name, page in cases.items():
            with self.subTest(name):
                cache = _native_plane_support_FakePageCache(image)
                self.assertIsNone(self.build(page, image, cache=cache))
                self.assertEqual(cache.calls, [])
        positive = Page(
            uid="page-1", name="A", image_path=source, width_pts=72.0, height_pts=72.0
        )
        self.assertIsNotNone(self.build(positive, image))

    def test_null_rendered_image_supplies_no_plane(self):
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=72.0,
            height_pts=72.0,
        )
        self.assertIsNone(self.build(page, QtGui.QImage()))

    def test_page_without_floor_elevation_or_project_record_supplies_no_plane(self):
        page = Page(
            uid="page-1",
            name="A1",
            image_path=self.make_source_file(),
            width_pts=72.0,
            height_pts=72.0,
        )
        image = _rgba_image(1, 1, QtGui.QColor(1, 2, 3, 4))
        self.assertIsNone(self.build(page, image, elevations={"other": 1.0}))
        self.assertIsNone(
            self.build(
                page, image, scene_page_uids=["unknown"], elevations={"unknown": 0.0}
            )
        )
        self.assertIsNotNone(self.build(page, image, elevations={"page-1": 0.0}))

    def test_display_mode_routes_to_composite_overlay_or_original_render(self):
        original = self.make_source_file()
        overlay = self.make_source_file()
        grid = _rgba_image(1, 1, QtGui.QColor(1, 2, 3, 255))

        def page_for(mode, *, image_path=original, overlay_path=overlay):
            return Page(
                uid="page-1",
                name="A1",
                image_path=image_path,
                overlay_image_path=overlay_path,
                width_pts=72.0,
                height_pts=72.0,
                image_show_mode=mode,
                rotation=90,
                flip_x=True,
                page_index=4,
            )

        def routed(page):
            cache = _native_plane_support_FakePageCache(grid)
            composite = _FakeCompositeRenderer(grid)
            data = self.build(page, grid, cache=cache, composite=composite)
            self.assertIsNotNone(data)
            return cache.calls, composite.calls

        cache_calls, composite_calls = routed(page_for(0))
        self.assertEqual(cache_calls, [(original, 4, 1.0, 0)])
        self.assertEqual(composite_calls, [])
        cache_calls, composite_calls = routed(page_for(1))
        self.assertEqual(cache_calls, [])
        self.assertEqual(len(composite_calls), 1)
        kind, rendered_page, scale, extra = composite_calls[0]
        self.assertEqual((kind, scale, extra), ("overlay", 1.0, {"tint_rgb": None}))
        self.assertEqual(
            (rendered_page.rotation, rendered_page.flip_x, rendered_page.flip_y),
            (0, False, False),
        )
        cache_calls, composite_calls = routed(page_for(2))
        self.assertEqual(cache_calls, [])
        kind, rendered_page, scale, extra = composite_calls[0]
        self.assertEqual((kind, scale, extra), ("composite", 1.0, (_BID_REF, 0)))
        self.assertEqual((rendered_page.rotation, rendered_page.flip_x), (0, False))
        # Both selected but only an overlay exists: tinted overlay-only render.
        cache_calls, composite_calls = routed(page_for(2, image_path=""))
        self.assertEqual(cache_calls, [])
        self.assertEqual(
            [(call[0], call[3]) for call in composite_calls],
            [("overlay", {"tint_rgb": (80, 80, 255)})],
        )
        # Both selected but no overlay exists: original page only.
        cache_calls, composite_calls = routed(page_for(2, overlay_path=None))
        self.assertEqual(cache_calls, [(original, 4, 1.0, 0)])
        self.assertEqual(composite_calls, [])

    def test_checked_page_without_geometry_does_not_create_origin_plane(self):
        provider = NativePageImagePlaneProvider(
            SimpleNamespace(get_selected_page_uids=lambda: ["page-a"]),
            SimpleNamespace(active_page_uid="page-a"),
            None,
            None,
        )
        self.assertIsNone(provider.build_for_scene(["page-a"], {}))
