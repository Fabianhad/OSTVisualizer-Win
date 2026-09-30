import unittest
from unittest.mock import create_autospec, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.elevation_callout import ElevationCalloutSettings
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.renderers.threejs.two_d_takeoff_processor import (
    process_takeoffs_2d_for_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _TakeoffService as _export_support__TakeoffService,
)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_two_d_takeoff_export_includes_visibility_metadata_and_rings(self):
        condition = Condition(
            uid="condition-1",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            layer_uid="layer-1",
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            area_uid="area-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _export_support__TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "rotation": 0,
                "flip_x": False,
                "flip_y": False,
                "width": 72.0,
                "height": 72.0,
                "view_scale": 1.0,
            },
            include_elevation_callouts=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            grayscale_enabled=False,
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["takeoff_uid"], "takeoff-1")
        self.assertEqual(entry["page_uid"], "page-1")
        self.assertEqual(entry["condition_uid"], "condition-1")
        self.assertEqual(entry["area_uid"], "area-1")
        self.assertEqual(entry["layer_uid"], "layer-1")
        self.assertEqual(entry["kind"], "area")
        self.assertEqual(entry["color"], "#996633")
        self.assertTrue(entry["visible"])
        self.assertFalse(entry["is_negative"])
        self.assertEqual(len(entry["rings"]), 1)
        self.assertGreaterEqual(len(entry["rings"][0]), 3)
        self.assertEqual(callouts, [])

    def test_two_d_takeoff_export_resolves_callout_in_same_geometry_pass(self):
        condition = Condition(
            uid="condition-1",
            name="F9 @T 410' 3\"",
            condition_type=Condition.TYPE_AREA,
            thickness=48.0,
            z_value=4923.0,
            is_top=True,
            layer_uid="layer-1",
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-2",
            area_uid="area-1",
            position=[0.0, 0.0, 100.0, 0.0, 100.0, 125.0, 0.0, 125.0],
        )
        takeoff_service = _export_support__TakeoffService()
        with patch.object(
            takeoff_service,
            "group_area_takeoffs_with_holes",
            wraps=takeoff_service.group_area_takeoffs_with_holes,
        ) as group_takeoffs:
            entries, callouts = process_takeoffs_2d_for_threejs(
                {"condition-1": condition},
                [takeoff],
                ColorService(),
                takeoff_service,
                {
                    "scale_factor1": 1.0,
                    "scale_factor2": 1.0,
                    "width": 500.0,
                    "height": 500.0,
                },
                include_elevation_callouts=True,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                elevation_callout_color="#abcdef",
            )
        group_takeoffs.assert_called_once_with([takeoff], {"condition-1": condition})
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(callouts), 1)
        ring = entries[0]["rings"][0]
        center_x = (
            min(point[0] for point in ring) + max(point[0] for point in ring)
        ) / 2.0
        center_y = (
            min(point[1] for point in ring) + max(point[1] for point in ring)
        ) / 2.0
        self.assertEqual(
            callouts[0],
            {
                "page_uid": "page-2",
                "condition_uid": "condition-1",
                "area_uid": "area-1",
                "layer_uid": "layer-1",
                "x": center_x,
                "y": center_y,
                "lines": ["F9", "410' - 3\"", "406' - 3\"", "12.86 CY"],
                "color": "#abcdef",
            },
        )

    def test_two_d_takeoff_export_uses_configured_callout_content(self):
        condition = Condition(
            uid="condition-1",
            name="F9 @T 410' 3\"",
            condition_type=Condition.TYPE_AREA,
            thickness=48.0,
            z_value=4923.0,
            is_top=True,
            layer_uid="layer-1",
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-2",
            area_uid="area-1",
            position=[0.0, 0.0, 100.0, 0.0, 100.0, 125.0, 0.0, 125.0],
        )
        _entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _export_support__TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 500.0,
                "height": 500.0,
            },
            include_elevation_callouts=True,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            elevation_callout_settings=ElevationCalloutSettings(
                include_condition=False,
                include_top=True,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )
        self.assertEqual(callouts[0]["lines"], ["410' - 3\""])

    def test_two_d_takeoff_export_skips_callout_resolution_when_disabled(self):
        condition = Condition(
            uid="condition-1",
            name="F9 @T 10' 0\"",
            condition_type=Condition.TYPE_AREA,
            thickness=24.0,
            z_value=120.0,
            is_top=True,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 100.0, 0.0, 100.0, 100.0],
        )
        processor_module = (
            "ost_visualizer.presentation.visualization.renderers.threejs."
            "two_d_takeoff_processor"
        )
        with patch(f"{processor_module}.resolve_elevation_callout") as resolver:
            entries, callouts = process_takeoffs_2d_for_threejs(
                {condition.uid: condition},
                [takeoff],
                ColorService(),
                _export_support__TakeoffService(),
                {
                    "scale_factor1": 1.0,
                    "scale_factor2": 1.0,
                    "width": 500.0,
                    "height": 500.0,
                },
                include_elevation_callouts=False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
        self.assertEqual(len(entries), 1)
        self.assertEqual(callouts, [])
        resolver.assert_not_called()

    def test_two_d_takeoff_export_keeps_unassigned_area_empty(self):
        condition = Condition(
            uid="condition-1",
            name="Count",
            condition_type=Condition.TYPE_COUNT,
            color_fill=0,
            layer_uid="layer-1",
            width=1.0,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            area_uid="0",
            position=[1.0, 1.0],
        )
        entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _export_support__TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
            include_elevation_callouts=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertEqual(entries[0]["area_uid"], "")
        self.assertEqual(callouts, [])

    def test_split_display_modes_control_3d_and_2d_opacity_independently(self):
        condition = Condition(
            uid="condition-1",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            pattern=1,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        color_service = ColorService()
        takeoff_service = _export_support__TakeoffService()
        _, solid_color_map = color_service.get_color_mapping(
            {"condition-1": condition}, [takeoff], Config.DISPLAY_MODE_SOLID, False
        )
        _, transparent_color_map = color_service.get_color_mapping(
            {"condition-1": condition},
            [takeoff],
            Config.DISPLAY_MODE_TRANSPARENT,
            False,
        )
        _solid_hex, solid_opacity = color_service.get_color_for_takeoff(
            takeoff,
            condition,
            solid_color_map,
            Config.DISPLAY_MODE_SOLID,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        _transparent_hex, transparent_2d_opacity = (
            color_service.get_2d_color_for_takeoff(
                takeoff,
                condition,
                transparent_color_map,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
        )
        self.assertEqual(solid_opacity, 1.0)
        self.assertEqual(transparent_2d_opacity, 0.5)
        entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            color_service,
            takeoff_service,
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
            include_elevation_callouts=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            display_mode=Config.DISPLAY_MODE_TRANSPARENT,
            grayscale_enabled=False,
        )
        self.assertEqual(entries[0]["opacity"], 0.5)
        self.assertEqual(callouts, [])

    def test_original_2d_display_mode_uses_2d_pattern_opacity(self):
        condition = Condition(
            uid="condition-1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
            pattern=2,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff],
            ColorService(),
            _export_support__TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "width": 72.0,
                "height": 72.0,
            },
            include_elevation_callouts=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            display_mode=Config.DISPLAY_MODE_ORIGINAL,
            grayscale_enabled=False,
        )
        self.assertEqual(entries[0]["opacity"], 0.0)
        self.assertEqual(callouts, [])
