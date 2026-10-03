from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
    hex_to_rgb,
    int_to_hex,
    parse_hex_color,
)
from ost_visualizer.domain.entities.condition import Condition
import unittest
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff


class ColorServiceTests(unittest.TestCase):
    def test_numeric_rgb_sequence_is_not_treated_as_color_opacity_pair(self):
        self.assertEqual(
            ColorService().convert_to_rgba((255, 128, 0)),
            (1.0, 128 / 255.0, 0.0, 1.0),
        )

    def test_numeric_rgba_sequence_converts_to_hex_with_opacity(self):
        self.assertEqual(
            ColorService().as_hex_with_opacity((255, 128, 0, 0.25)),
            ("#ff8000", 0.25),
        )

    def test_condition_color_preserves_black_fill(self):
        condition = Condition(uid="condition-1", color_fill=0)
        self.assertEqual(ColorService().get_condition_color(condition), [0, 0, 0])

    def test_condition_color_uses_bgr_fill_and_defaults_missing_fill_to_red(self):
        service = ColorService()
        self.assertEqual(
            service.get_condition_color(Condition(uid="c", color_fill=0x336699)),
            [0x99, 0x66, 0x33],
        )
        # A missing fill (None) is the OST default 255, which is pure red.
        self.assertEqual(
            service.get_condition_color(Condition(uid="c", color_fill=None)),
            [255, 0, 0],
        )

    def test_convert_to_rgba_parses_strings_dicts_pairs_and_clamps(self):
        service = ColorService()
        cases = [
            ("#ff8000", (1.0, 128 / 255.0, 0.0, 1.0)),
            ("rgba(255, 128, 0, 0.5)", (1.0, 128 / 255.0, 0.0, 0.5)),
            ("rgb(0.2, 0.4, 0.6)", (0.2, 0.4, 0.6, 1.0)),
            ("rgb(2, 1, 0)", (2 / 255.0, 1 / 255.0, 0.0, 1.0)),
            ({"color": "#ff0000", "opacity": 2.0}, (1.0, 0.0, 0.0, 1.0)),
            ({"color": "#ff0000", "opacity": -1.0}, (1.0, 0.0, 0.0, 0.0)),
            ({"color": "rgba(255,0,0,0.5)", "opacity": 0.5}, (1.0, 0.0, 0.0, 0.25)),
            (("#00ff00", 0.3), (0.0, 1.0, 0.0, 0.3)),
            ((0.5, 0.25, 1.0), (0.5, 0.25, 1.0, 1.0)),
            ("#fff", (0.5, 0.5, 0.5, 1.0)),
            ({}, (128 / 255.0, 128 / 255.0, 128 / 255.0, 1.0)),
            (None, (128 / 255.0, 128 / 255.0, 128 / 255.0, 1.0)),
        ]
        for entry, expected in cases:
            with self.subTest(entry=entry):
                self.assertEqual(service.convert_to_rgba(entry), expected)

    def test_as_hex_with_opacity_normalizes_every_entry_shape(self):
        service = ColorService()
        cases = [
            ({"color": "#112233", "opacity": 0.5}, ("#112233", 0.5)),
            ({"color": "#112233", "opacity": 3}, ("#112233", 1.0)),
            ({"opacity": 0.5}, ("#808080", 0.5)),
            ("#abcdef", ("#abcdef", 1.0)),
            ("", ("#808080", 1.0)),
            (("#010203", 0.3), ("#010203", 0.3)),
            ((0.2, 0.4, 0.6), ("#336699", 1.0)),
            ((0.5, 0.5, 0.5), ("#808080", 1.0)),
            (None, ("#808080", 1.0)),
        ]
        for entry, expected in cases:
            with self.subTest(entry=entry):
                self.assertEqual(service.as_hex_with_opacity(entry), expected)

    def test_hex_helpers_round_trip_bgr_integers(self):
        service = ColorService()
        self.assertEqual(int_to_hex(0x336699), "#996633")
        self.assertEqual(service.int_to_hex(0xFFFFFF), "#ffffff")
        self.assertEqual(int_to_hex(0), "#000000")
        self.assertEqual(hex_to_rgb("#336699"), (51 / 255.0, 102 / 255.0, 153 / 255.0))
        self.assertEqual(service.hex_to_rgb_int("#336699"), [51, 102, 153])
        self.assertEqual(parse_hex_color("#336699"), hex_to_rgb("#336699"))
        self.assertEqual(parse_hex_color("336699"), hex_to_rgb("#336699"))
        self.assertEqual(parse_hex_color("#12345"), (0.5, 0.5, 0.5))
        self.assertEqual(service.parse_hex_color("#ff0000"), (1.0, 0.0, 0.0))

    def test_inactive_area_takeoff_requires_a_different_selected_area(self):
        service = ColorService()
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-b"
        )
        self.assertTrue(service.is_inactive_area_takeoff(takeoff, {"p1": "area-a"}))
        for selections in (
            None,
            {},
            {"p1": "area-b"},
            {"p1": None},
            {"other-page": "area-a"},
        ):
            with self.subTest(selections=selections):
                self.assertFalse(service.is_inactive_area_takeoff(takeoff, selections))


class ColorMappingTests(unittest.TestCase):
    def setUp(self):
        self.conditions = {
            "c1": Condition(
                uid="c1",
                name="Slab",
                cdn_type_name="Concrete",
                color_fill=0x336699,
                pattern=1,
                z_value=1,
            ),
            "c2": Condition(
                uid="c2",
                name="Slab",
                cdn_type_name="Concrete",
                color_fill=0x336699,
                pattern=2,
                z_value=1,
            ),
            "c3": Condition(
                uid="c3", name="Wall", cdn_type_name="", color_fill=0, pattern=8
            ),
            "c4": Condition(uid="c4", name="Unused", color_fill=0xFFFFFF),
        }
        self.takeoffs = [
            Takeoff(uid="t1", condition_uid="c1"),
            Takeoff(uid="t2", condition_uid="c2"),
            Takeoff(uid="t3", condition_uid="c3"),
            Takeoff(uid="t4", condition_uid="foreign"),
        ]

    def mapping(self, display_mode, grayscale=False, **kwargs):
        return ColorService().get_color_mapping(
            self.conditions, self.takeoffs, display_mode, grayscale, **kwargs
        )

    def test_solid_mapping_covers_only_used_conditions_with_full_opacity(self):
        result = self.mapping(Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            result.condition_color_map,
            {
                "c1": ColorWithOpacity("#996633", 1.0),
                "c2": ColorWithOpacity("#996633", 1.0),
                "c3": ColorWithOpacity("#000000", 1.0),
            },
        )

    def test_hierarchy_groups_identical_conditions_by_type_name(self):
        hierarchy = self.mapping(Config.DISPLAY_MODE_SOLID).hierarchy_map
        self.assertEqual(list(hierarchy), ["Concrete", "Unknown"])
        (slab,) = hierarchy["Concrete"]
        # c1 and c2 share name, z value and color, so they form one legend entry.
        self.assertIn(slab["uid"], {"c1", "c2"})
        self.assertEqual(
            {key: value for key, value in slab.items() if key != "uid"},
            {"name": "Slab", "z_value": 1, "color": "#996633", "count": 2},
        )
        self.assertEqual(
            hierarchy["Unknown"],
            [
                {
                    "uid": "c3",
                    "name": "Wall",
                    "z_value": 0,
                    "color": "#000000",
                    "count": 1,
                }
            ],
        )

    def test_transparent_mode_halves_opacity(self):
        result = self.mapping(Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(
            {uid: entry.opacity for uid, entry in result.condition_color_map.items()},
            {"c1": 0.5, "c2": 0.5, "c3": 0.5},
        )
        self.assertEqual(result.condition_color_map["c1"].hex, "#996633")

    def test_original_mode_takes_opacity_from_the_2d_pattern(self):
        result = self.mapping(Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(
            {uid: entry.opacity for uid, entry in result.condition_color_map.items()},
            {"c1": 1.0, "c2": 0.0, "c3": 0.5},
        )

    def test_grayscale_desaturates_colors_and_legend_but_keeps_opacity(self):
        result = self.mapping(Config.DISPLAY_MODE_TRANSPARENT, grayscale=True)
        # 0.299 * 0.6 + 0.587 * 0.4 + 0.114 * 0.2 = 0.437 -> 111 -> 0x6f
        self.assertEqual(
            result.condition_color_map,
            {
                "c1": ColorWithOpacity("#6f6f6f", 0.5),
                "c2": ColorWithOpacity("#6f6f6f", 0.5),
                "c3": ColorWithOpacity("#000000", 0.5),
            },
        )
        self.assertEqual(
            [entry["color"] for entry in result.hierarchy_map["Concrete"]],
            ["#6f6f6f"],
        )

    def test_extra_condition_uids_add_known_conditions_only(self):
        result = self.mapping(
            Config.DISPLAY_MODE_SOLID, extra_condition_uids={"c4", "unknown"}
        )
        self.assertEqual(set(result.condition_color_map), {"c1", "c2", "c3", "c4"})
        self.assertEqual(
            result.condition_color_map["c4"], ColorWithOpacity("#ffffff", 1.0)
        )


class ColorServiceOpacityTests(unittest.TestCase):
    def setUp(self):
        self.service = ColorService()
        self.takeoff = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-b"
        )
        self.color_map = {"c1": {"color": "#abcdef", "opacity": 0.37}}

    def colors_for(self, selections, condition=None, mode=Config.DISPLAY_MODE_SOLID):
        condition = condition or Condition(uid="c1")
        result_2d = self.service.get_2d_color_for_takeoff(
            self.takeoff,
            condition,
            self.color_map,
            selections,
            inactive_object_color="#123456",
        )
        result_3d = self.service.get_color_for_takeoff(
            self.takeoff,
            condition,
            self.color_map,
            mode,
            selections,
            inactive_object_color="#123456",
        )
        return result_2d, result_3d

    def test_inactive_color_substitution_preserves_opacity(self):
        result_2d, result_3d = self.colors_for({"p1": "area-a"})
        self.assertEqual((result_2d.hex, result_2d.opacity), ("#123456", 0.37))
        self.assertEqual((result_3d.hex, result_3d.opacity), ("#123456", 0.37))

    def test_active_or_unrestricted_takeoffs_keep_their_color(self):
        for selections in (None, {}, {"p1": "area-b"}, {"p1": None}, {"p2": "a"}):
            with self.subTest(selections=selections):
                for result in self.colors_for(selections):
                    self.assertEqual((result.hex, result.opacity), ("#abcdef", 0.37))

    def test_missing_color_map_entry_falls_back_to_opaque_gray(self):
        self.color_map = {}
        for result in self.colors_for(None):
            self.assertEqual((result.hex, result.opacity), ("#808080", 1.0))

    def test_original_mode_3d_opacity_comes_from_the_pattern_not_the_color_map(self):
        # 3D only distinguishes solid (opaque) from every other pattern (half
        # transparent); a missing pattern (0) is treated as solid.
        for pattern, expected in ((1, 1.0), (2, 0.5), (8, 0.5), (0, 1.0)):
            with self.subTest(pattern=pattern):
                condition = Condition(uid="c1", pattern=pattern)
                result_2d, result_3d = self.colors_for(
                    None, condition, Config.DISPLAY_MODE_ORIGINAL
                )
                self.assertEqual(
                    (result_3d.hex, result_3d.opacity), ("#abcdef", expected)
                )
                # The 2D color query never applies the 3D pattern rule.
                self.assertEqual(result_2d.opacity, 0.37)

    def test_non_original_modes_ignore_the_pattern_for_3d_opacity(self):
        condition = Condition(uid="c1", pattern=2)
        for mode in (Config.DISPLAY_MODE_SOLID, Config.DISPLAY_MODE_TRANSPARENT):
            with self.subTest(mode=mode):
                _, result_3d = self.colors_for(None, condition, mode)
                self.assertEqual(result_3d.opacity, 0.37)

    def test_original_mode_inactive_takeoff_keeps_pattern_opacity(self):
        condition = Condition(uid="c1", pattern=2)
        _, result_3d = self.colors_for(
            {"p1": "area-a"}, condition, Config.DISPLAY_MODE_ORIGINAL
        )
        self.assertEqual((result_3d.hex, result_3d.opacity), ("#123456", 0.5))
