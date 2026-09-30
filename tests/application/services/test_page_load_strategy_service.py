from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.dtos.render_result_dto import RenderResult
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakePageSizeProvider,
)


class FakePageSizeProvider:
    def __init__(self, sizes=None):
        self.sizes = sizes or {}
        self.calls = []

    def get_page_size(self, file_path, page_index):
        self.calls.append((file_path, page_index))
        return self.sizes.get(file_path, (612.0, 792.0))


class FakeRenderingService:
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self.callbacks = {}
        self._counter = 0

    def _record(self, request_type, render_options):
        self._counter += 1
        request_id = f"{request_type}-{self._counter}"
        self.calls.append((request_type, request_id, render_options))
        self.callbacks[request_id] = render_options["callback"]
        return request_id

    def render_page_async(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        callback,
        priority=0,
        invert=False,
        bitonal=False,
        tint_rgb=None,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        render_options = {
            "file_path": file_path,
            "page_index": page_index,
            "scale": scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "invert": invert,
            "bitonal": bitonal,
            "tint_rgb": tint_rgb,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        return self._record("page", render_options)

    def render_overlay_async(
        self,
        page,
        show_mode,
        rotation,
        render_scale,
        callback,
        priority=0,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        render_options = {
            "page": page,
            "show_mode": show_mode,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "render_scale": render_scale,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        return self._record("overlay", render_options)

    def render_composite_async(
        self,
        page,
        bid_ref,
        render_scale,
        rotation,
        callback,
        priority=0,
    ):
        render_options = {
            "page": page,
            "bid_ref": bid_ref,
            "render_scale": render_scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
        }
        return self._record("composite", render_options)

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)

    def complete(self, request_id, success=True):
        callback = self.callbacks[request_id]
        callback(RenderResult(request_id, success, object(), None))


class FakeCache:
    def __init__(self, can_accept=True, can_accept_render=True, sizes=None):
        self.can_accept = can_accept
        self.can_accept_render = can_accept_render
        self.sizes = sizes or {}
        self.checks = 0
        self.render_checks = []

    def can_accept_prefetch(self):
        self.checks += 1
        return self.can_accept

    def can_accept_prefetch_render(self, width_pts, height_pts, scale):
        self.render_checks.append((width_pts, height_pts, scale))
        return self.can_accept_prefetch() and self.can_accept_render

    def get_page_size(self, file_path, page_index):
        return self.sizes.get((file_path, page_index), (612.0, 792.0))


class PageLoadStrategyTests(unittest.TestCase):
    def _coordinator(self, rendering_service=None, cache=None, size_provider=None):
        rendering_service = rendering_service or FakeRenderingService()
        cache = cache or FakeCache()
        size_provider = size_provider or FakePageSizeProvider()
        return PageRenderPrefetchCoordinator(
            rendering_service,
            PageLoadStrategyService(size_provider),
            cache,
        )

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
        size_provider = FakePageSizeProvider({"affected.pdf": (2592.0, 1728.0)})
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
        self.assertEqual(
            strategy.placeholder_width,
            2592.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            strategy.placeholder_height,
            1728.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )

    def test_load_strategy_uses_canonical_pdf_and_raster_baselines(self):
        size_provider = FakePageSizeProvider({"page.tif": (612.0, 792.0)})
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
        size_provider = FakePageSizeProvider({"slow.pdf": (3024.0, 2160.0)})
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
        self.assertEqual(size_provider.calls, [("slow.pdf", 0)])

    def test_overlay_only_raster_without_main_image_still_loads(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider({"overlay.tif": (1224.0, 1584.0)})
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

    def test_overlay_only_mode_without_overlay_does_not_load_hidden_main(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider()
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


class CompositePageStrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_show_both_strategy_uses_composite_layer(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider()
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
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_overlay)
