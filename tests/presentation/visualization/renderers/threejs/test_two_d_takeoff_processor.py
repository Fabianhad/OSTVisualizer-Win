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
        self.assertEqual(entry["name"], "Slab")
        self.assertEqual(entry["opacity"], 1.0)
        # 1 OST unit is 1 inch at scale ratio 1, i.e. 72 pt, with no y flip.
        self.assertEqual(entry["rings"], [[[0.0, 0.0], [72.0, 0.0], [72.0, 72.0]]])
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
        # 100 x 125 OST units are 7200 x 9000 pt; the callout sits on the center
        # of the outer ring's bounds.
        self.assertEqual(
            entries[0]["rings"],
            [[[0.0, 0.0], [7200.0, 0.0], [7200.0, 9000.0], [0.0, 9000.0]]],
        )
        self.assertEqual(
            callouts[0],
            {
                "page_uid": "page-2",
                "condition_uid": "condition-1",
                "area_uid": "area-1",
                "layer_uid": "layer-1",
                "x": 3600.0,
                "y": 4500.0,
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
        with patch(
            f"{processor_module}.resolve_elevation_callout", autospec=True
        ) as resolver:
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
        assigned = Takeoff(
            uid="takeoff-2",
            condition_uid="condition-1",
            area_uid="area-1",
            position=[1.0, 1.0],
        )
        entries, callouts = process_takeoffs_2d_for_threejs(
            {"condition-1": condition},
            [takeoff, assigned],
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
        self.assertEqual(
            [(entry["takeoff_uid"], entry["area_uid"]) for entry in entries],
            [("takeoff-1", ""), ("takeoff-2", "area-1")],
        )
        self.assertEqual(entries[0]["kind"], "count")
        # Count footprint: 1 inch (72 pt) square centered on (72, 72).
        self.assertEqual(
            entries[0]["rings"],
            [[[36.0, 36.0], [108.0, 36.0], [108.0, 108.0], [36.0, 108.0]]],
        )
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
        solid_entries, _ = process_takeoffs_2d_for_threejs(
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
            display_mode=Config.DISPLAY_MODE_SOLID,
            grayscale_enabled=False,
        )
        self.assertEqual(solid_entries[0]["opacity"], 1.0)

    def test_original_2d_display_mode_uses_2d_pattern_opacity(self):
        # Solid fills stay opaque, line patterns are drawn as hatching so their
        # fill is transparent, and the transparent pattern is half opacity.
        for pattern, expected_opacity in ((1, 1.0), (2, 0.0), (8, 0.5)):
            with self.subTest(pattern=pattern):
                condition = Condition(
                    uid="condition-1",
                    condition_type=Condition.TYPE_AREA,
                    color_fill=0x336699,
                    pattern=pattern,
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
                self.assertEqual(entries[0]["opacity"], expected_opacity)
                self.assertEqual(callouts, [])


class _HoleTakeoffService(_export_support__TakeoffService):
    def __init__(self, holes_by_takeoff_uid):
        self.holes_by_takeoff_uid = holes_by_takeoff_uid

    def group_area_takeoffs_with_holes(self, takeoffs, _conditions):
        hole_uids = {
            hole.uid for holes in self.holes_by_takeoff_uid.values() for hole in holes
        }
        outer = [takeoff for takeoff in takeoffs if takeoff.uid not in hole_uids]
        return outer, self.holes_by_takeoff_uid


_UNIT_PAGE = {"scale_factor1": 1.0, "scale_factor2": 1.0, "width": 72.0, "height": 72.0}


class TwoDTakeoffRingTests(unittest.TestCase):
    def process(self, conditions, takeoffs, service=None, **overrides):
        options = {
            "include_elevation_callouts": False,
            "inactive_object_color": Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            "grayscale_enabled": False,
        }
        options.update(overrides)
        return process_takeoffs_2d_for_threejs(
            {condition.uid: condition for condition in conditions},
            takeoffs,
            ColorService(),
            service or _export_support__TakeoffService(),
            _UNIT_PAGE,
            **options,
        )

    def test_area_holes_become_inner_rings_after_the_outer_ring(self):
        condition = Condition(
            uid="condition-1", condition_type=Condition.TYPE_AREA, color_fill=0
        )
        outer = Takeoff(
            uid="outer",
            condition_uid="condition-1",
            position=[0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0],
        )
        hole = Takeoff(
            uid="hole",
            condition_uid="condition-1",
            parent_uid="outer",
            position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0],
        )
        too_short = Takeoff(
            uid="short",
            condition_uid="condition-1",
            parent_uid="outer",
            position=[1.0, 1.0, 2.0, 1.0],
        )
        entries, _ = self.process(
            [condition],
            [outer, hole, too_short],
            _HoleTakeoffService({"outer": [hole, too_short]}),
        )
        self.assertEqual([entry["takeoff_uid"] for entry in entries], ["outer"])
        self.assertEqual(
            entries[0]["rings"],
            [
                [[0.0, 0.0], [288.0, 0.0], [288.0, 288.0], [0.0, 288.0]],
                [[72.0, 72.0], [144.0, 72.0], [144.0, 144.0]],
            ],
        )

    def test_straight_linear_ring_is_a_thickness_wide_rectangle(self):
        condition = Condition(
            uid="condition-1", condition_type=Condition.TYPE_LINEAR, thickness=0.5
        )
        horizontal = Takeoff(
            uid="h", condition_uid="condition-1", position=[0.0, 0.0, 2.0, 0.0]
        )
        vertical = Takeoff(
            uid="v", condition_uid="condition-1", position=[0.0, 0.0, 0.0, 2.0]
        )
        entries, _ = self.process([condition], [horizontal, vertical])
        self.assertEqual([entry["kind"] for entry in entries], ["linear", "linear"])
        self.assertEqual(
            entries[0]["rings"],
            [[[0.0, 18.0], [0.0, -18.0], [144.0, -18.0], [144.0, 18.0]]],
        )
        self.assertEqual(
            entries[1]["rings"],
            [[[-18.0, 0.0], [18.0, 0.0], [18.0, 144.0], [-18.0, 144.0]]],
        )

    def test_linear_thickness_defaults_to_one_unit_and_has_a_visible_minimum(self):
        unset = Condition(uid="unset", condition_type=Condition.TYPE_LINEAR)
        hairline = Condition(
            uid="hairline", condition_type=Condition.TYPE_LINEAR, thickness=0.01
        )
        takeoffs = [
            Takeoff(
                uid="t-unset", condition_uid="unset", position=[0.0, 0.0, 2.0, 0.0]
            ),
            Takeoff(
                uid="t-hairline",
                condition_uid="hairline",
                position=[0.0, 0.0, 2.0, 0.0],
            ),
        ]
        entries, _ = self.process([unset, hairline], takeoffs)
        by_uid = {entry["takeoff_uid"]: entry["rings"] for entry in entries}
        # No thickness: 1 unit = 72 pt wide. 0.01 unit = 0.72 pt is widened to the
        # 2 pt rendering minimum.
        self.assertEqual(
            by_uid["t-unset"],
            [[[0.0, 36.0], [0.0, -36.0], [144.0, -36.0], [144.0, 36.0]]],
        )
        self.assertEqual(
            by_uid["t-hairline"],
            [[[0.0, 1.0], [0.0, -1.0], [144.0, -1.0], [144.0, 1.0]]],
        )

    def test_callout_quantity_excludes_holes_and_sits_on_the_outer_ring(self):
        condition = Condition(
            uid="condition-1",
            name="F9 @T 410' 3\"",
            condition_type=Condition.TYPE_AREA,
            thickness=48.0,
            z_value=4923.0,
            is_top=True,
        )
        outer = Takeoff(
            uid="outer",
            condition_uid="condition-1",
            position=[0.0, 0.0, 100.0, 0.0, 100.0, 125.0, 0.0, 125.0],
        )
        hole = Takeoff(
            uid="hole",
            condition_uid="condition-1",
            parent_uid="outer",
            position=[10.0, 10.0, 20.0, 10.0, 20.0, 20.0, 10.0, 20.0],
        )
        _, callouts = self.process(
            [condition],
            [outer, hole],
            _HoleTakeoffService({"outer": [hole]}),
            include_elevation_callouts=True,
        )
        self.assertEqual(len(callouts), 1)
        # (100 * 125 - 10 * 10) units^2 * 48 / 46656 cubic yards = 12.757 -> 12.76,
        # and the callout stays centered on the outer ring, not the hole.
        self.assertEqual(callouts[0]["lines"][-1], "12.76 CY")
        self.assertEqual((callouts[0]["x"], callouts[0]["y"]), (3600.0, 4500.0))

    def test_callout_without_any_selected_content_is_omitted_but_entry_is_kept(self):
        condition = Condition(
            uid="condition-1",
            name="F9 @T 10' 0\"",
            condition_type=Condition.TYPE_AREA,
            thickness=24.0,
            z_value=120.0,
            is_top=True,
        )
        takeoff = Takeoff(
            uid="t",
            condition_uid="condition-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        empty_settings = ElevationCalloutSettings(
            include_condition=False,
            include_top=False,
            include_bottom=False,
            include_cubic_yards=False,
        )
        entries, callouts = self.process(
            [condition],
            [takeoff],
            include_elevation_callouts=True,
            elevation_callout_settings=empty_settings,
        )
        self.assertEqual([entry["takeoff_uid"] for entry in entries], ["t"])
        self.assertEqual(callouts, [])
        _, default_callouts = self.process(
            [condition], [takeoff], include_elevation_callouts=True
        )
        self.assertEqual(len(default_callouts), 1)

    def test_takeoffs_without_condition_or_enough_position_are_omitted(self):
        area = Condition(uid="area", condition_type=Condition.TYPE_AREA)
        linear = Condition(uid="linear", condition_type=Condition.TYPE_LINEAR)
        takeoffs = [
            Takeoff(uid="orphan", condition_uid="foreign", position=[0, 0, 1, 0, 1, 1]),
            Takeoff(uid="two-points", condition_uid="area", position=[0, 0, 1, 0]),
            Takeoff(uid="one-point-line", condition_uid="linear", position=[0, 0]),
            Takeoff(uid="empty", condition_uid="area", position=[]),
            Takeoff(uid="ok", condition_uid="area", position=[0, 0, 1, 0, 1, 1]),
        ]
        entries, callouts = self.process([area, linear], takeoffs)
        self.assertEqual([entry["takeoff_uid"] for entry in entries], ["ok"])
        self.assertEqual(callouts, [])

    def test_entry_metadata_name_negative_flag_and_inactive_color(self):
        named = Condition(
            uid="named",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
        )
        unnamed = Condition(
            uid="unnamed", condition_type=Condition.TYPE_AREA, color_fill=0x336699
        )
        triangle = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0]
        takeoffs = [
            Takeoff(
                uid="t-named",
                condition_uid="named",
                page_uid="p1",
                area_uid="area-b",
                position=triangle,
                is_negative=True,
            ),
            Takeoff(
                uid="t-unnamed",
                condition_uid="unnamed",
                page_uid="p1",
                area_uid="area-a",
                position=triangle,
            ),
        ]
        entries, _ = self.process(
            [named, unnamed],
            takeoffs,
            page_area_selections={"p1": "area-a"},
            inactive_object_color="#010203",
        )
        by_uid = {entry["takeoff_uid"]: entry for entry in entries}
        self.assertEqual(by_uid["t-named"]["name"], "Slab")
        self.assertEqual(by_uid["t-unnamed"]["name"], "Takeoff t-unnamed")
        self.assertTrue(by_uid["t-named"]["is_negative"])
        self.assertFalse(by_uid["t-unnamed"]["is_negative"])
        # Only the takeoff outside the page's selected Area is recolored.
        self.assertEqual(by_uid["t-named"]["color"], "#010203")
        self.assertEqual(by_uid["t-unnamed"]["color"], "#996633")

    def test_grayscale_default_desaturates_entry_colors(self):
        condition = Condition(
            uid="condition-1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0x336699,
        )
        takeoff = Takeoff(
            uid="t",
            condition_uid="condition-1",
            position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
        )
        grayscale, _ = self.process([condition], [takeoff], grayscale_enabled=True)
        colored, _ = self.process([condition], [takeoff], grayscale_enabled=False)
        self.assertEqual(grayscale[0]["color"], "#6f6f6f")
        self.assertEqual(colored[0]["color"], "#996633")
