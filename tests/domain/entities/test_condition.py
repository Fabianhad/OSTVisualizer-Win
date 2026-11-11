import unittest
from dataclasses import fields
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.tower_crane_spec import (
    NOT_A_COUNT_CONDITION_WARNING,
    TowerCraneSpec,
    resolve_tower_crane,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    tower_crane_catalog,
)

CATALOG = tower_crane_catalog()


class ConditionConditionBehaviorTests(unittest.TestCase):
    def test_condition_entity_does_not_expose_label_style_fields(self):
        condition_fields = {field.name for field in fields(Condition)}
        self.assertFalse(
            {
                "name_font_name",
                "name_font_color",
                "name_font_size",
                "name_font_bold",
                "name_font_italic",
                "name_font_underline",
            }
            & condition_fields
        )


class ConditionTypeTests(unittest.TestCase):
    def test_type_constants_are_the_stored_access_values(self):
        self.assertEqual(
            (
                Condition.TYPE_LINEAR,
                Condition.TYPE_AREA,
                Condition.TYPE_COUNT,
                Condition.TYPE_ATTACHMENT,
            ),
            (0, 1, 2, 3),
        )

    def test_exactly_one_type_predicate_is_true_per_known_type_and_none_for_unknown(
        self,
    ):
        predicates = ("is_linear", "is_area", "is_count", "is_attachment")
        for condition_type, expected in (
            (0, "is_linear"),
            (1, "is_area"),
            (2, "is_count"),
            (3, "is_attachment"),
            (4, None),
            (-1, None),
        ):
            with self.subTest(condition_type=condition_type):
                condition = Condition(uid="c", condition_type=condition_type)
                self.assertEqual(
                    [name for name in predicates if getattr(condition, name)],
                    [expected] if expected else [],
                )

    def test_default_condition_is_a_visible_unassigned_linear_condition(self):
        condition = Condition(uid="c")
        self.assertEqual(
            (
                condition.uid,
                condition.name,
                condition.condition_type,
                condition.cdn_type_uid,
                condition.cdn_type_name,
                condition.folder_uid,
                condition.layer_uid,
                condition.layer_visible,
                condition.display_size,
                condition.is_top,
                condition.notes,
            ),
            ("c", "", 0, None, "Unknown", None, None, True, 100.0, False, ""),
        )
        for numeric in (
            "thickness",
            "height",
            "width",
            "depth",
            "rise",
            "run",
            "shape",
            "color_fill",
            "z_value",
            "pattern",
            "spacing",
            "uom1",
            "uom2",
            "uom3",
            "calc_type1",
            "calc_type2",
            "calc_type3",
            "ref_no",
            "drop_value",
            "round_up",
            "grid_size1",
            "grid_size2",
            "gap",
        ):
            with self.subTest(field=numeric):
                self.assertEqual(getattr(condition, numeric), 0)
        for flag in (
            "drop_run",
            "round_quantity",
            "trim",
            "is_curved_segment",
            "grid",
            "display_dimension",
            "display_name",
            "display_grid_while_drawing",
        ):
            with self.subTest(field=flag):
                self.assertIs(getattr(condition, flag), False)


class ConditionTowerCraneTests(unittest.TestCase):
    def test_count_conditions_with_the_crane_tag_in_any_case_show_a_crane(self):
        default = resolve_tower_crane("[crane]", CATALOG).spec
        self.assertIsInstance(default, TowerCraneSpec)
        for notes in ("[crane]", "[CRANE]", "Footing 20x20 [ Crane ] by others"):
            with self.subTest(notes=notes):
                condition = Condition(
                    "c", condition_type=Condition.TYPE_COUNT, notes=notes
                )
                self.assertTrue(condition.has_tower_crane)
                self.assertEqual(condition.tower_crane_spec(CATALOG), default)
                self.assertEqual(condition.tower_crane_warnings(CATALOG), ())

    def test_the_tag_arguments_reach_the_condition(self):
        condition = Condition(
            "c", condition_type=Condition.TYPE_COUNT, notes="pad [crane mast=30]"
        )
        self.assertEqual(condition.tower_crane_spec(CATALOG).mast, 30)
        liebherr = Condition(
            "c", condition_type=Condition.TYPE_COUNT, notes="[crane model=liebherr]"
        )
        self.assertEqual(liebherr.tower_crane_spec(CATALOG).model, "liebherr")
        self.assertEqual(liebherr.tower_crane_spec(CATALOG).mast, 19)

    def test_other_types_missing_tags_and_loose_words_do_not(self):
        for condition_type in (
            Condition.TYPE_LINEAR,
            Condition.TYPE_AREA,
            Condition.TYPE_ATTACHMENT,
        ):
            with self.subTest(condition_type=condition_type):
                condition = Condition(
                    "c", condition_type=condition_type, notes="[crane]"
                )
                self.assertFalse(condition.has_tower_crane)
                self.assertIsNone(condition.tower_crane_spec(CATALOG))
                self.assertEqual(condition.tower_crane_notes(CATALOG), ())
                self.assertEqual(
                    condition.tower_crane_warnings(CATALOG),
                    (NOT_A_COUNT_CONDITION_WARNING,),
                )
        # The old "(CRANE)" tag no longer means anything.
        for notes in ("", None, "crane", "CRANE pad", "(CRANE)", "( crane )"):
            with self.subTest(notes=notes):
                condition = Condition(
                    "c", condition_type=Condition.TYPE_COUNT, notes=notes
                )
                self.assertFalse(condition.has_tower_crane)
                self.assertIsNone(condition.tower_crane_spec(CATALOG))
                self.assertEqual(condition.tower_crane_warnings(CATALOG), ())

    def test_tag_warnings_are_reported_but_the_crane_still_shows(self):
        condition = Condition(
            "c", condition_type=Condition.TYPE_COUNT, notes="[crane mast=abc]"
        )
        self.assertTrue(condition.has_tower_crane)
        self.assertEqual(
            condition.tower_crane_spec(CATALOG),
            resolve_tower_crane("[crane]", CATALOG).spec,
        )
        self.assertEqual(len(condition.tower_crane_warnings(CATALOG)), 1)
        self.assertIn("mast=abc", condition.tower_crane_warnings(CATALOG)[0])
