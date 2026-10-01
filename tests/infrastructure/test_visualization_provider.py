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
from ost_visualizer.domain.entities.elevation_callout import ElevationCalloutSettings
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
        self.assertEqual(
            _prepare_export_filename("pdf", "B\x00\x1fB", ["P\r\x01P"]),
            "B__B - P__P.pdf",
        )
        self.assertEqual(
            _prepare_export_filename("pdf", 'Bid\\"Q"', [" P\u00a0 "]),
            "Bid__Q_ -  P\u00a0 .pdf",
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
            ("Bid", ['A\\B"C'], "Bid - A_B_C"),
            ("Bid", ["Tab\tNew\nLine\x1f"], "Bid - Tab_New_Line_"),
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
        self.assertEqual(
            html.prepare_filename(long_bid, ["Page"]),
            "B" * 240 + "... - Page.html",
        )
        self.assertEqual(
            obj.prepare_filename(long_bid, ["Page"]),
            "B" * 241 + "... - Page.obj",
        )
        long_page = "P" * 300
        self.assertEqual(
            html.prepare_filename("Bid", [long_page]),
            "P" * 247 + "....html",
        )
        self.assertEqual(
            obj.prepare_filename("Bid", [long_page]),
            "P" * 248 + "....obj",
        )
        self.assertEqual(
            html.prepare_filename("Bid", [long_page, long_page]),
            "Export_2_pages.html",
        )
        self.assertEqual(
            obj.prepare_filename("Bid", [long_page, long_page, long_page]),
            "Export_3_pages.obj",
        )

    def test_export_filename_length_boundary_is_255_characters(self):
        html = _HtmlExportStrategyAdapter(object())
        suffix = " - Page.html"
        exact_bid = "B" * (255 - len(suffix))
        self.assertEqual(html.prepare_filename(exact_bid, ["Page"]), exact_bid + suffix)
        over_bid = "B" * (256 - len(suffix))
        truncated = html.prepare_filename(over_bid, ["Page"])
        self.assertEqual(len(truncated), 255)
        self.assertEqual(truncated, "B" * (len(over_bid) - 1 - 3) + "..." + suffix)
        short_bid = "B" * 10
        long_page = "P" * 300
        self.assertEqual(
            html.prepare_filename(short_bid, [long_page]),
            "P" * 247 + "....html",
        )


class ThreejsExportLayerTests(unittest.TestCase):
    _RENDERER = (
        "ost_visualizer.infrastructure.visualization_provider.visualize_with_threejs"
    )

    def _adapter(self):
        self.coordinate_system = object()
        self.color_service = ColorService()
        self.takeoff_service = _export_support__TakeoffService()
        return _HtmlRendererAdapter(
            SimpleNamespace(create=lambda: self.coordinate_system),
            self.color_service,
            self.takeoff_service,
        )

    def test_html_renderer_adapter_reports_missing_output_as_failure(self):
        adapter = self._adapter()
        conditions = {"condition-1": Condition(uid="condition-1", condition_type=1)}
        takeoffs = [Takeoff(uid="takeoff-1", condition_uid="condition-1")]
        with patch(self._RENDERER, return_value=None) as renderer:
            result = adapter.render(
                conditions,
                takeoffs,
                "missing.html",
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                include_elevation_callouts=False,
            )
        self.assertIs(result, False)
        renderer.assert_called_once()
        self.assertEqual(
            renderer.call_args.args,
            (
                conditions,
                takeoffs,
                self.coordinate_system,
                self.color_service,
                self.takeoff_service,
            ),
        )
        self.assertEqual(renderer.call_args.kwargs["output_path"], "missing.html")

    def test_html_renderer_adapter_reports_written_output_as_success(self):
        adapter = self._adapter()
        with patch(self._RENDERER, return_value="out.html") as renderer:
            result = adapter.render(
                {},
                [],
                "out.html",
                title="Bid - Page",
                display_mode_3d=Config.DISPLAY_MODE_TRANSPARENT,
                display_mode_2d=Config.DISPLAY_MODE_ORIGINAL,
                display_modes_synced=False,
                grayscale_enabled=False,
                inactive_object_color="#345678",
                include_elevation_callouts=True,
                elevation_callout_color="#123456",
            )
        self.assertIs(result, True)
        kwargs = renderer.call_args.kwargs
        self.assertEqual(kwargs["title"], "Bid - Page")
        self.assertEqual(kwargs["output_path"], "out.html")
        self.assertIs(kwargs["auto_open"], False)
        self.assertEqual(kwargs["display_mode_3d"], Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(kwargs["display_mode_2d"], Config.DISPLAY_MODE_ORIGINAL)
        self.assertIs(kwargs["display_modes_synced"], False)
        self.assertIs(kwargs["grayscale_enabled"], False)
        self.assertEqual(kwargs["inactive_object_color"], "#345678")
        self.assertIs(kwargs["include_elevation_callouts"], True)
        self.assertEqual(kwargs["elevation_callout_color"], "#123456")

    def test_html_renderer_adapter_does_not_hide_rendering_errors(self):
        adapter = self._adapter()
        with patch(
            self._RENDERER,
            side_effect=RuntimeError("render failed"),
        ) as renderer, self.assertRaisesRegex(RuntimeError, "render failed"):
            adapter.render(
                {},
                [],
                "missing.html",
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                include_elevation_callouts=False,
            )
        renderer.assert_called_once()

    def test_html_strategy_passes_saved_callout_options_to_renderer(self):
        renderer = create_autospec(IHtmlRenderer, instance=True)
        renderer.render.return_value = True
        strategy = _HtmlExportStrategyAdapter(renderer)
        config = Config(
            display_mode_3d=Config.DISPLAY_MODE_TRANSPARENT,
            display_mode_2d=Config.DISPLAY_MODE_SOLID,
            display_modes_synced=False,
            grayscale_enabled=True,
            html_elevation_callouts_enabled=False,
            elevation_callout_include_condition=False,
            elevation_callout_include_top=True,
            elevation_callout_include_bottom=False,
            elevation_callout_include_cubic_yards=False,
            html_elevation_callout_color="#123456",
            inactive_object_color="#345678",
        )
        conditions = {"condition-1": Condition(uid="condition-1", condition_type=1)}
        takeoffs = [Takeoff(uid="takeoff-1", condition_uid="condition-1")]
        options = strategy.get_export_options(config)
        result = strategy.execute_export(conditions, takeoffs, "out.html", **options)
        self.assertIs(result, True)
        renderer.render.assert_called_once()
        self.assertEqual(
            renderer.render.call_args.args, (conditions, takeoffs, "out.html")
        )
        options = renderer.render.call_args.kwargs
        self.assertIs(options["include_elevation_callouts"], False)
        self.assertEqual(
            options["elevation_callout_settings"],
            ElevationCalloutSettings(
                include_condition=False,
                include_top=True,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )
        self.assertEqual(options["elevation_callout_color"], "#123456")
        self.assertEqual(options["inactive_object_color"], "#345678")
        self.assertEqual(options["display_mode_3d"], Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(options["display_mode_2d"], Config.DISPLAY_MODE_SOLID)
        self.assertIs(options["display_modes_synced"], False)
        self.assertIs(options["grayscale_enabled"], True)
        self.assertIs(options["auto_open"], False)

    def test_html_strategy_exports_only_supported_condition_types(self):
        renderer = create_autospec(IHtmlRenderer, instance=True)
        renderer.render.return_value = True
        strategy = _HtmlExportStrategyAdapter(renderer)
        options = strategy.get_export_options(Config())
        conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "count": Condition(uid="count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
            "unsupported": Condition(uid="unsupported", condition_type=99),
        }
        takeoffs = [
            Takeoff(uid=f"takeoff-{uid}", condition_uid=uid)
            for uid in (*conditions, "missing-condition")
        ]
        self.assertTrue(
            strategy.execute_export(conditions, takeoffs, "out.html", **options)
        )
        exported = renderer.render.call_args.args[1]
        self.assertEqual(
            [takeoff.condition_uid for takeoff in exported],
            ["linear", "area", "count", "attachment"],
        )
        renderer.render.reset_mock()
        unsupported_only = [takeoffs[4], takeoffs[5]]
        self.assertIs(
            strategy.execute_export(
                conditions, unsupported_only, "out.html", **options
            ),
            False,
        )
        renderer.render.assert_not_called()
