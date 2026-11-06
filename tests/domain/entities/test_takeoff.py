import unittest
from itertools import permutations
from dataclasses import replace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import (
    Takeoff,
    find_takeoff_parent_cycle_uids,
)


class TakeoffParentTests(unittest.TestCase):
    def test_takeoff_root_parent_sentinels_are_canonical(self):
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="0").is_hole)
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="").is_hole)
        self.assertTrue(Takeoff(uid="1", condition_uid="c1", parent_uid="None").is_hole)
        self.assertTrue(Takeoff(uid="2", condition_uid="c1", parent_uid="1").is_hole)


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_takeoff_contract_rejects_missing_declared_field(self):
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        self.assertTrue(takeoff.has_valid_contract())
        del takeoff.uid
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_bool_as_numeric_storage(self):
        takeoff = Takeoff(
            uid="4485",
            condition_uid="10",
            page_uid="20",
            rotation=True,
        )
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_non_finite_numeric_storage(self):
        original = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        self.assertTrue(original.has_valid_contract())
        for changes in (
            {"position": [1.0, float("nan"), 3.0, 4.0]},
            {"position": [1.0, float("inf"), 3.0, 4.0]},
            {"rotation": float("-inf")},
            {"rotation": 10**1000},
        ):
            with self.subTest(changes=changes):
                takeoff = replace(original, **changes)
                self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_parent_cycle_detection_is_order_independent(self):
        items = (("32", "31"), ("30", "0"), ("31", "32"), ("33", "32"))
        for order in permutations(items):
            with self.subTest(order=order):
                self.assertEqual(
                    find_takeoff_parent_cycle_uids(dict(order)), {"31", "32"}
                )
        self.assertEqual(find_takeoff_parent_cycle_uids({"one": "one"}), {"one"})
        self.assertEqual(
            find_takeoff_parent_cycle_uids({"child": "parent", "parent": "0"}), set()
        )


class TakeoffEntityContractTests(unittest.TestCase):
    def valid(self, **changes):
        base = dict(uid="1", condition_uid="c", page_uid="p")
        base.update(changes)
        return Takeoff(**base)

    def test_constants_and_defaults_describe_a_root_unassigned_straight_takeoff(self):
        from ost_visualizer.domain.entities.area import UNASSIGNED_AREA_UID

        self.assertEqual((Takeoff.CURVE_DISABLED, Takeoff.CURVE_ENABLED), (-1, 0))
        takeoff = Takeoff(uid="1", condition_uid="c")
        self.assertEqual(
            (
                takeoff.page_uid,
                takeoff.area_uid,
                takeoff.position,
                takeoff.rotation,
                takeoff.curve,
                takeoff.parent_uid,
                takeoff.is_negative,
            ),
            ("", UNASSIGNED_AREA_UID, [], 0.0, -1, "0", False),
        )
        for name in (
            "dimension_font_name",
            "dimension_font_color",
            "dimension_font_size",
            "name_font_name",
            "name_font_color",
            "name_font_size",
        ):
            self.assertIsNone(getattr(takeoff, name), name)
        for name in (
            "dimension_font_bold",
            "dimension_font_italic",
            "dimension_font_underline",
            "name_font_bold",
            "name_font_italic",
            "name_font_underline",
        ):
            self.assertIs(getattr(takeoff, name), False, name)
        other = Takeoff(uid="2", condition_uid="c")
        takeoff.position.append(1.0)
        self.assertEqual(other.position, [])

    def test_a_complete_takeoff_with_every_optional_value_is_valid(self):
        self.assertTrue(self.valid().has_valid_contract())
        full = self.valid(
            area_uid="",
            position=[1, 2.5, -3, 4.0],
            rotation=90,
            curve=0,
            parent_uid="",
            is_negative=True,
            dimension_font_name="Arial",
            dimension_font_color=255,
            dimension_font_size=12,
            dimension_font_bold=True,
            dimension_font_italic=True,
            dimension_font_underline=True,
            name_font_name="Arial",
            name_font_color=0,
            name_font_size=9,
            name_font_bold=True,
            name_font_italic=True,
            name_font_underline=True,
        )
        self.assertTrue(full.has_valid_contract())

    def test_each_invalid_field_value_breaks_the_contract_independently(self):
        invalid = {
            "uid": ["", 5, None],
            "condition_uid": ["", 5, None],
            "page_uid": ["", 5, None],
            "area_uid": [5, None],
            "position": [(1, 2, 3, 4), "1234", [1, "2"], [1, None], [True, 2]],
            "rotation": ["90", None, True, float("nan"), 10**1000],
            "curve": [1.0, True, "0", None],
            "parent_uid": [0, None],
            "is_negative": [1, 0, None, "False"],
            "dimension_font_name": [5, b"Arial"],
            "dimension_font_color": ["1", 1.0, True],
            "dimension_font_size": ["1", 1.0, True],
            "dimension_font_bold": [1, None, "x"],
            "dimension_font_italic": [1, None, "x"],
            "dimension_font_underline": [1, None, "x"],
            "name_font_name": [5, b"Arial"],
            "name_font_color": ["1", 1.0, True],
            "name_font_size": ["1", 1.0, True],
            "name_font_bold": [1, None, "x"],
            "name_font_italic": [1, None, "x"],
            "name_font_underline": [1, None, "x"],
        }
        for field_name, values in invalid.items():
            for value in values:
                with self.subTest(field=field_name, value=value):
                    takeoff = self.valid()
                    setattr(takeoff, field_name, value)
                    self.assertIs(takeoff.has_valid_contract(), False)

    def test_numeric_storage_accepts_int_and_float_but_not_other_number_types(self):
        from decimal import Decimal
        from fractions import Fraction

        self.assertTrue(self.valid(position=[1, 2.0, 3, 4], rotation=1).has_valid_contract())
        for bad in (Decimal("1"), Fraction(1, 2), complex(1, 0)):
            with self.subTest(bad=bad):
                self.assertFalse(self.valid(position=[bad, 2, 3, 4]).has_valid_contract())
                self.assertFalse(self.valid(rotation=bad).has_valid_contract())

    def test_visibility_follows_the_conditions_layer_and_defaults_to_visible(self):
        hidden = Condition(uid="c", layer_visible=False)
        shown = Condition(uid="c", layer_visible=True)
        takeoff = self.valid()
        self.assertIs(takeoff.is_visible({"c": hidden}), False)
        self.assertIs(takeoff.is_visible({"c": shown}), True)
        self.assertIs(takeoff.is_visible({}), True)
        self.assertIs(takeoff.is_visible({"other": hidden}), True)
        self.assertIs(self.valid(condition_uid="").is_visible({"": hidden}), True)

    def test_get_condition_returns_the_exact_mapped_condition_or_none(self):
        condition = Condition(uid="c")
        self.assertIs(self.valid().get_condition({"c": condition}), condition)
        self.assertIsNone(self.valid().get_condition({"x": condition}))

    def test_has_valid_position_needs_at_least_two_points(self):
        for length, expected in ((0, False), (2, False), (3, False), (4, True), (5, True)):
            with self.subTest(length=length):
                self.assertIs(
                    self.valid(position=[0.0] * length).has_valid_position, expected
                )

    def test_root_parent_sentinels_are_only_blank_and_zero(self):
        for parent, expected in (("0", False), ("", False), ("00", True), (" ", True), ("7", True)):
            with self.subTest(parent=parent):
                self.assertIs(self.valid(parent_uid=parent).is_hole, expected)


class TakeoffRelationshipHelperTests(unittest.TestCase):
    def test_page_mismatches_report_children_on_another_page_than_a_known_parent(self):
        from ost_visualizer.domain.entities.takeoff import (
            find_takeoff_parent_page_mismatches,
        )

        parents = {"child": "parent", "ok": "parent", "root": "0", "blank": "", "orphan": "gone", "nopage": "parent"}
        pages = {"parent": "p1", "child": "p2", "ok": "p1", "root": "p9", "blank": "p9", "orphan": "p3"}
        self.assertEqual(
            find_takeoff_parent_page_mismatches(parents, pages), {"child", "nopage"}
        )
        self.assertEqual(find_takeoff_parent_page_mismatches({}, {}), set())
        self.assertEqual(
            find_takeoff_parent_page_mismatches({"a": "b"}, {"a": "p", "b": "p"}), set()
        )

    def test_cycles_ignore_root_parents_and_report_only_members_of_the_loop(self):
        self.assertEqual(find_takeoff_parent_cycle_uids({}), set())
        self.assertEqual(find_takeoff_parent_cycle_uids({"a": "", "b": "0"}), set())
        # Chain feeding a three-cycle: only the cycle members are reported.
        parents = {"t": "a", "a": "b", "b": "c", "c": "a", "x": "0", "y": "x"}
        self.assertEqual(find_takeoff_parent_cycle_uids(parents), {"a", "b", "c"})
        # Two independent cycles and a shared tail are all found regardless of visiting order.
        parents = {"a": "b", "b": "a", "c": "d", "d": "c", "e": "a"}
        self.assertEqual(find_takeoff_parent_cycle_uids(parents), {"a", "b", "c", "d"})
        self.assertEqual(find_takeoff_parent_cycle_uids({1: 2, 2: 1}), {"1", "2"})

    def test_page_mismatch_never_treats_a_root_sentinel_as_a_parent_even_if_a_page_has_that_uid(self):
        from ost_visualizer.domain.entities.takeoff import (
            find_takeoff_parent_page_mismatches,
        )

        self.assertEqual(
            find_takeoff_parent_page_mismatches(
                {"a": "0", "b": ""}, {"a": "p1", "b": "p1", "0": "p2", "": "p3"}
            ),
            set(),
        )

    def test_contract_is_a_real_false_when_a_declared_field_is_missing(self):
        takeoff = Takeoff(uid="1", condition_uid="c", page_uid="p")
        del takeoff.curve
        self.assertIs(takeoff.has_valid_contract(), False)
