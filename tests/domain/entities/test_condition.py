import unittest
from dataclasses import fields
from ost_visualizer.domain.entities.condition import Condition


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
