from ost_visualizer.infrastructure.visualization_provider import (
    _prepare_export_filename,
)
import unittest
from ost_visualizer.infrastructure.visualization_provider import (
    _ExportStrategyAdapter,
    _HtmlExportStrategyAdapter,
)
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.application.interfaces.i_html_renderer import IHtmlRenderer
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.visualization_provider import (
    _ExportStrategyAdapter,
    _HtmlExportStrategyAdapter,
    _HtmlRendererAdapter,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _TakeoffService as _export_support__TakeoffService,
)


class ExportFilenameTests(unittest.TestCase):
    def test_suggested_export_filename_replaces_windows_control_characters(self):
        self.assertEqual(
            _prepare_export_filename("pdf", "Bid\nOne", ["A1\tPlan"]),
            "Bid_One - A1_Plan.pdf",
        )


class ExportFilenameCompatibilityTests(unittest.TestCase):
    def test_export_filename_consolidation_preserves_html_and_mesh_policy(self):
        html = _HtmlExportStrategyAdapter(object())
        obj = _ExportStrategyAdapter("OBJ", "obj", object, None, None, None)
        cases = (
            ("Bid", ["Page"], "Bid - Page"),
            ("Bid", ["One", "Two"], "Bid - One + Two"),
            ("Bid", ["One", "Two", "Three"], "Bid - One + Two + 1 more"),
            ("Bid", ["A/B:*?<>|"], "Bid - A_B______"),
            ("Bid/Phase:*?<>|", ["Page"], "Bid_Phase______ - Page"),
            ("", ["Page"], " - Page"),
            ("Bid", [""], "Bid - "),
            ("Bíd", ["Páge"], "Bíd - Páge"),
            ("Bid", ["Same", "Same"], "Bid - Same + Same"),
        )
        for bid_name, page_names, stem in cases:
            with self.subTest(bid_name=bid_name, page_names=page_names):
                self.assertEqual(
                    html.prepare_filename(bid_name, page_names), stem + ".html"
                )
                self.assertEqual(
                    obj.prepare_filename(bid_name, page_names), stem + ".obj"
                )
        self.assertEqual(html.get_dialog_title(1), "Export page as HTML")
        self.assertEqual(obj.get_dialog_title(3), "Export 3 pages as OBJ")

    def test_export_filename_consolidation_preserves_long_name_fallbacks(self):
        html = _HtmlExportStrategyAdapter(object())
        obj = _ExportStrategyAdapter("OBJ", "obj", object, None, None, None)
        long_bid = "B" * 300
        self.assertEqual(len(html.prepare_filename(long_bid, ["Page"])), 255)
        self.assertEqual(len(obj.prepare_filename(long_bid, ["Page"])), 255)
        long_page = "P" * 300
        html_filename = html.prepare_filename("Bid", [long_page])
        obj_filename = obj.prepare_filename("Bid", [long_page])
        self.assertEqual(len(html_filename), 255)
        self.assertEqual(len(obj_filename), 255)
        self.assertTrue(html_filename.endswith("....html"))
        self.assertTrue(obj_filename.endswith("....obj"))
        self.assertEqual(
            html.prepare_filename("Bid", [long_page, long_page]),
            "Export_2_pages.html",
        )


class ThreejsExportLayerTests(unittest.TestCase):
    def test_html_renderer_adapter_reports_missing_output_as_failure(self):
        adapter = _HtmlRendererAdapter(
            SimpleNamespace(create=lambda: object()),
            ColorService(),
            _export_support__TakeoffService(),
        )
        renderer_module = "ost_visualizer.infrastructure.visualization_provider"
        with patch(
            f"{renderer_module}.visualize_with_threejs", return_value=None
        ) as renderer:
            result = adapter.render(
                {},
                [],
                "missing.html",
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                include_elevation_callouts=False,
            )
        self.assertFalse(result)
        renderer.assert_called_once()

    def test_html_renderer_adapter_does_not_hide_rendering_errors(self):
        adapter = _HtmlRendererAdapter(
            SimpleNamespace(create=lambda: object()),
            ColorService(),
            _export_support__TakeoffService(),
        )
        renderer_module = "ost_visualizer.infrastructure.visualization_provider"
        with patch(
            f"{renderer_module}.visualize_with_threejs",
            side_effect=RuntimeError("render failed"),
        ), self.assertRaisesRegex(RuntimeError, "render failed"):
            adapter.render(
                {},
                [],
                "missing.html",
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                include_elevation_callouts=False,
            )

    def test_export_strategy_filename_policy_handles_long_single_page_names(self):
        page_name = "P" * 300
        html_strategy = _HtmlExportStrategyAdapter(SimpleNamespace())
        mesh_strategy = _ExportStrategyAdapter("OBJ", "obj", object, None, None, None)
        html_filename = html_strategy.prepare_filename("Bid", [page_name])
        mesh_filename = mesh_strategy.prepare_filename("Bid", [page_name])
        self.assertEqual(len(html_filename), 255)
        self.assertEqual(len(mesh_filename), 255)
        self.assertTrue(html_filename.endswith("....html"))
        self.assertTrue(mesh_filename.endswith("....obj"))

    def test_html_strategy_passes_saved_callout_options_to_renderer(self):
        renderer = create_autospec(IHtmlRenderer, instance=True)
        renderer.render.return_value = True
        strategy = _HtmlExportStrategyAdapter(renderer)
        config = Config(
            html_elevation_callouts_enabled=False,
            elevation_callout_include_bottom=False,
            html_elevation_callout_color="#123456",
            inactive_object_color="#345678",
        )
        options = strategy.get_export_options(config)
        result = strategy.execute_export(
            {"condition-1": Condition(uid="condition-1", condition_type=1)},
            [Takeoff(uid="takeoff-1", condition_uid="condition-1")],
            "out.html",
            **options,
        )
        self.assertTrue(result)
        renderer.render.assert_called_once()
        options = renderer.render.call_args.kwargs
        self.assertFalse(options["include_elevation_callouts"])
        self.assertFalse(options["elevation_callout_settings"].include_bottom)
        self.assertEqual(options["elevation_callout_color"], "#123456")
        self.assertEqual(options["inactive_object_color"], "#345678")
