from dataclasses import replace
import unittest
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)


class FakePageSizeProvider:
    def __init__(self, sizes=None):
        self.sizes = dict(sizes or {})
        self.calls = []

    def get_page_size(self, file_path, page_index=0):
        self.calls.append((file_path, page_index))
        return self.sizes[(file_path, page_index)]


class PageLoadStrategyTests(unittest.TestCase):
    def _page(self, uid, **overrides):
        values = {
            "uid": uid,
            "name": uid,
            "width_pts": 612.0,
            "height_pts": 792.0,
        }
        values.update(overrides)
        return Page(**values)

    def test_pdf_load_strategy_uses_native_geometry_when_stored_dimensions_differ(
        self,
    ):
        size_provider = FakePageSizeProvider({("affected.pdf", 0): (2592.0, 1728.0)})
        strategy = PageLoadStrategyService(size_provider).determine_load_strategy(
            self._page(
                "p1",
                image_path="affected.pdf",
                width_pts=3024.0,
                height_pts=2160.0,
            )
        )
        self.assertEqual(strategy.pdf_width_pts, 2592.0)
        self.assertEqual(strategy.pdf_height_pts, 1728.0)
        self.assertTrue(strategy.load_main)
        self.assertTrue(strategy.needs_async_loading)
        self.assertTrue(strategy.show_canvas)
        self.assertEqual(
            strategy.placeholder_width,
            2592.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            strategy.placeholder_height,
            1728.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )

    def test_load_strategy_uses_canonical_pdf_and_raster_baselines(self):
        size_provider = FakePageSizeProvider(
            {("page.tif", 0): (612.0, 792.0), ("page.pdf", 0): (612.0, 792.0)}
        )
        pdf_strategy = PageLoadStrategyService(size_provider).determine_load_strategy(
            self._page("pdf", image_path="page.pdf")
        )
        raster_strategy = PageLoadStrategyService(
            size_provider
        ).determine_load_strategy(self._page("raster", image_path="page.tif"))
        overlay_pdf_strategy = PageLoadStrategyService(
            size_provider
        ).determine_load_strategy(
            self._page(
                "overlay",
                overlay_image_path="overlay.pdf",
                image_show_mode=1,
            )
        )
        self.assertEqual(
            pdf_strategy.main_scale,
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            pdf_strategy.view_scale,
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            raster_strategy.main_scale,
            RASTER_NATIVE_RENDER_SCALE,
        )
        self.assertEqual(
            overlay_pdf_strategy.view_scale,
            INTERACTIVE_PDF_RENDER_SCALE,
        )

    def test_pdf_load_strategy_reads_page_size_when_stored_dimensions_missing(self):
        size_provider = FakePageSizeProvider({("slow.pdf", 0): (3024.0, 2160.0)})
        strategy = PageLoadStrategyService(size_provider).determine_load_strategy(
            self._page(
                "p1",
                image_path="slow.pdf",
                width_pts=0.0,
                height_pts=0.0,
            )
        )
        self.assertEqual(strategy.pdf_width_pts, 3024.0)
        self.assertEqual(strategy.pdf_height_pts, 2160.0)
        self.assertFalse(strategy.show_canvas)
        self.assertTrue(strategy.needs_async_loading)
        self.assertEqual(size_provider.calls, [("slow.pdf", 0)])

    def test_overlay_only_raster_without_main_image_still_loads(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider({("overlay.tif", 0): (1224.0, 1584.0)})
        ).determine_load_strategy(
            self._page(
                "p1",
                image_path=None,
                overlay_image_path="overlay.tif",
                image_show_mode=1,
            )
        )
        self.assertTrue(strategy.needs_async_loading)
        self.assertTrue(strategy.load_overlay)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_composite)
        self.assertEqual(strategy.view_scale, 2.0)
        self.assertEqual(
            (strategy.placeholder_width, strategy.placeholder_height), (1224, 1584)
        )

    def test_overlay_only_mode_without_overlay_does_not_load_hidden_main(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider({("main.pdf", 0): (612, 792)})
        ).determine_load_strategy(
            self._page(
                "p1",
                image_path="main.pdf",
                overlay_image_path=None,
                image_show_mode=1,
            )
        )
        self.assertFalse(strategy.needs_async_loading)
        self.assertFalse(strategy.load_overlay)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_composite)

    def test_show_both_strategy_uses_composite_layer(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider({("base.pdf", 0): (612, 792)})
        ).determine_load_strategy(
            Page(
                uid="p1",
                name="P1",
                image_path="base.pdf",
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_BOTH,
                width_pts=612.0,
                height_pts=792.0,
            )
        )
        self.assertTrue(strategy.load_composite)
        self.assertTrue(strategy.needs_async_loading)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_overlay)

    def test_pdf_placeholder_rotation_preserves_canonical_source_geometry(self):
        provider = FakePageSizeProvider({("rotated.PDF", 2): (900, 600)})
        service = PageLoadStrategyService(provider)
        for rotation, expected in (
            (0, (900, 600)),
            (90, (600, 900)),
            (180, (900, 600)),
            (270, (600, 900)),
        ):
            with self.subTest(rotation=rotation):
                page = self._page(
                    "p1", image_path="rotated.PDF", page_index=2, rotation=rotation
                )
                original = replace(page)
                strategy = service.determine_load_strategy(page)
                self.assertEqual(
                    (strategy.pdf_width_pts, strategy.pdf_height_pts), (900, 600)
                )
                self.assertEqual(
                    (strategy.placeholder_width, strategy.placeholder_height),
                    tuple(value * INTERACTIVE_PDF_RENDER_SCALE for value in expected),
                )
                self.assertEqual(page, original)
        self.assertEqual(provider.calls, [("rotated.PDF", 2)] * 4)

    def test_incomplete_pdf_metadata_uses_complete_stored_or_default_geometry(self):
        for actual in ((0, 0), (900, 0), (0, 600), (-1, 600)):
            for stored, expected in (
                ((800, 500), (800, 500)),
                ((0, 0), (612, 792)),
                ((800, 0), (800, 792)),
            ):
                with self.subTest(actual=actual, stored=stored):
                    provider = FakePageSizeProvider({("missing.pdf", 0): actual})
                    strategy = PageLoadStrategyService(
                        provider
                    ).determine_load_strategy(
                        self._page(
                            "p1",
                            image_path="missing.pdf",
                            width_pts=stored[0],
                            height_pts=stored[1],
                        )
                    )
                    self.assertEqual(
                        (strategy.pdf_width_pts, strategy.pdf_height_pts), expected
                    )
                    self.assertEqual(
                        (strategy.placeholder_width, strategy.placeholder_height),
                        tuple(
                            value * INTERACTIVE_PDF_RENDER_SCALE for value in expected
                        ),
                    )

    def test_raster_placeholder_uses_both_native_pixel_dimensions(self):
        provider = FakePageSizeProvider({("scan.tif", 4): (2400, 1700)})
        strategy = PageLoadStrategyService(provider).determine_load_strategy(
            self._page(
                "p1", image_path="scan.tif", page_index=4, width_pts=600, height_pts=400
            )
        )
        self.assertEqual(
            strategy,
            LoadStrategy(
                True,
                4,
                True,
                600,
                400,
                2400 * RASTER_NATIVE_RENDER_SCALE,
                1700 * RASTER_NATIVE_RENDER_SCALE,
                RASTER_NATIVE_RENDER_SCALE,
                load_main=True,
            ),
        )
        self.assertTrue(provider.calls)
        self.assertEqual(set(provider.calls), {("scan.tif", 4)})

    def test_missing_raster_metadata_uses_logical_fallback(self):
        provider = FakePageSizeProvider({("scan.tif", 0): (0, 0)})
        strategy = PageLoadStrategyService(provider).determine_load_strategy(
            self._page("p1", image_path="scan.tif", width_pts=800, height_pts=500)
        )
        self.assertEqual(strategy.view_scale, RASTER_NATIVE_RENDER_SCALE)
        self.assertEqual(
            (strategy.placeholder_width, strategy.placeholder_height),
            (800 * RASTER_NATIVE_RENDER_SCALE, 500 * RASTER_NATIVE_RENDER_SCALE),
        )
        self.assertTrue(strategy.needs_async_loading)

    def test_hidden_layer_disables_loading_without_discarding_source_geometry(self):
        provider = FakePageSizeProvider({("base.pdf", 0): (900, 600)})
        service = PageLoadStrategyService(provider)
        page = self._page(
            "p1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=SHOW_BOTH,
        )
        visible = service.determine_load_strategy(page)
        hidden = service.determine_load_strategy(replace(page, layer_visible=False))
        self.assertTrue(visible.needs_async_loading)
        self.assertEqual(hidden, replace(visible, needs_async_loading=False))

    def test_empty_page_has_canvas_without_metadata_reads_or_async_loading(self):
        provider = FakePageSizeProvider()
        strategy = PageLoadStrategyService(provider).determine_load_strategy(
            self._page("p1", width_pts=0, height_pts=0)
        )
        scale = INTERACTIVE_PDF_RENDER_SCALE
        self.assertEqual(
            strategy,
            LoadStrategy(
                False,
                scale,
                True,
                612,
                792,
                612 * scale,
                792 * scale,
                RASTER_NATIVE_RENDER_SCALE,
            ),
        )
        self.assertEqual(provider.calls, [])

    def test_pending_data_retains_page_owner_and_captures_display_values(self):
        provider = FakePageSizeProvider()
        service = PageLoadStrategyService(provider)
        for mode, overlay, expected_overlay in (
            (SHOW_ORIGINAL, "overlay.pdf", False),
            (SHOW_OVERLAY, "overlay.pdf", True),
            (SHOW_BOTH, "overlay.pdf", True),
            (SHOW_BOTH, None, False),
        ):
            with self.subTest(mode=mode, overlay=overlay):
                page = self._page(
                    "p1", rotation=270, overlay_image_path=overlay, image_show_mode=mode
                )
                strategy = LoadStrategy(False, 3.5, True, 1, 2, 3, 4, 1)
                pending = service.create_pending_page_data(page, strategy, 900, 600)
                self.assertEqual(
                    pending,
                    {
                        "page": page,
                        "rotation": 270,
                        "show_mode": mode,
                        "show_overlay": expected_overlay,
                        "pdf_width_pts": 900,
                        "pdf_height_pts": 600,
                        "view_scale": 3.5,
                    },
                )
                self.assertIs(pending["page"], page)
                page.rotation = 90
                strategy.view_scale = 8
                self.assertEqual(pending["rotation"], 270)
                self.assertEqual(pending["view_scale"], 3.5)
        self.assertEqual(provider.calls, [])
