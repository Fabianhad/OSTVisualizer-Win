import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.takeoff_domain_service import (
    common_reassign_geometry_type,
    condition_reassign_geometry_type,
    takeoffs_can_reassign_to_condition,
)
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_SQUARE_INCHES,
)
from ost_visualizer.domain.services.takeoff_domain_service import (
    is_takeoff_relevant_for_area_usage,
)


class TakeoffReassignmentPolicyTests(unittest.TestCase):
    def test_condition_reassignment_preserves_geometry_compatibility_policy(self):
        conditions = {
            "linear-a": Condition(uid="linear-a", condition_type=Condition.TYPE_LINEAR),
            "linear-b": Condition(uid="linear-b", condition_type=Condition.TYPE_LINEAR),
            "area-a": Condition(uid="area-a", condition_type=Condition.TYPE_AREA),
            "area-b": Condition(uid="area-b", condition_type=Condition.TYPE_AREA),
            "count": Condition(uid="count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        linear = Takeoff(uid="linear", condition_uid="linear-a")
        area = Takeoff(uid="area", condition_uid="area-a")
        hole = Takeoff(uid="hole", condition_uid="area-a", parent_uid="area")
        count = Takeoff(uid="count", condition_uid="count")
        attachment = Takeoff(uid="attachment", condition_uid="attachment")
        self.assertTrue(
            takeoffs_can_reassign_to_condition([linear], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([area, hole], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([area], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([count], conditions, "attachment")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([attachment], conditions, "count")
        )
        self.assertIsNone(common_reassign_geometry_type([linear, area], conditions))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear, area], conditions, "linear-b")
        )
        self.assertFalse(takeoffs_can_reassign_to_condition([], conditions, "linear-b"))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "missing")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition(
                [Takeoff("unknown", "missing")], conditions, "linear-b"
            )
        )
        self.assertEqual(
            condition_reassign_geometry_type(conditions["attachment"]),
            Condition.TYPE_COUNT,
        )


class TakeoffLifecycleQuantityTests(unittest.TestCase):
    def setUp(self):
        self.conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "backout": Condition(
                uid="backout",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "attachment": Condition(
                uid="attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                width=2,
                depth=2,
                calc_type1=CALC_COUNT,
            ),
        }
        self.takeoffs = [
            Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            ),
            Takeoff(
                uid="hole",
                condition_uid="backout",
                page_uid="page",
                parent_uid="parent",
                position=[1, 1, 3, 1, 3, 3, 1, 3],
            ),
            Takeoff(
                uid="point",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5, 5],
            ),
        ]

    def test_attachment_assignment_participates_in_bid_area_usage(self):
        attachment = self.takeoffs[-1]
        attachment.area_uid = "attachment-area"
        self.assertTrue(is_takeoff_relevant_for_area_usage(attachment, self.conditions))
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(self.takeoffs[1], self.conditions)
        )
        self.conditions["attachment"].layer_visible = False
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(attachment, self.conditions)
        )
        self.conditions["attachment"].layer_visible = True
        attachment.position = []
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(attachment, self.conditions)
        )
        self.assertFalse(
            is_takeoff_relevant_for_area_usage(
                Takeoff("orphan", "missing", position=[1, 2]), self.conditions
            )
        )


def _tk(uid, condition_uid="c", parent_uid="0", position=None, page_uid="p"):
    return Takeoff(
        uid=uid,
        condition_uid=condition_uid,
        parent_uid=parent_uid,
        position=list(position or []),
        page_uid=page_uid,
    )


def _cond(uid, condition_type, layer_visible=True):
    return Condition(uid=uid, condition_type=condition_type, layer_visible=layer_visible)


class TakeoffDescendantExpansionTests(unittest.TestCase):
    def test_selection_expands_to_every_descendant_but_not_siblings_or_ancestors(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            expand_takeoff_uids_with_descendants,
        )

        takeoffs = [
            _tk("root"),
            _tk("a", parent_uid="root"),
            _tk("a1", parent_uid="a"),
            _tk("a1x", parent_uid="a1"),
            _tk("b", parent_uid="root"),
            _tk("other"),
        ]
        self.assertEqual(
            expand_takeoff_uids_with_descendants(takeoffs, ["a"]), {"a", "a1", "a1x"}
        )
        self.assertEqual(
            expand_takeoff_uids_with_descendants(takeoffs, ["a1x", "b"]), {"a1x", "b"}
        )
        self.assertEqual(
            expand_takeoff_uids_with_descendants(takeoffs, ["root"]),
            {"root", "a", "a1", "a1x", "b"},
        )
        self.assertEqual(expand_takeoff_uids_with_descendants(takeoffs, []), set())

    def test_unknown_selected_uids_are_kept_and_uids_are_compared_as_text(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            expand_takeoff_uids_with_descendants,
        )

        takeoffs = [_tk(2, parent_uid=1), _tk(3, parent_uid=2)]
        result = expand_takeoff_uids_with_descendants(iter(takeoffs), iter([1, "ghost"]))
        self.assertEqual(result, {"1", "2", "3", "ghost"})

    def test_cyclic_parentage_terminates_with_each_member_once(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            expand_takeoff_uids_with_descendants,
        )

        takeoffs = [_tk("a", parent_uid="b"), _tk("b", parent_uid="a"), _tk("c", parent_uid="b")]
        self.assertEqual(
            expand_takeoff_uids_with_descendants(takeoffs, ["a"]), {"a", "b", "c"}
        )

    def test_the_input_collections_are_not_modified(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            expand_takeoff_uids_with_descendants,
        )

        selected = ["a"]
        takeoffs = [_tk("a"), _tk("b", parent_uid="a")]
        expand_takeoff_uids_with_descendants(takeoffs, selected)
        self.assertEqual(selected, ["a"])
        self.assertEqual([t.parent_uid for t in takeoffs], ["0", "a"])


class TakeoffRenderablePositionTests(unittest.TestCase):
    def test_minimum_coordinate_counts_per_condition_type(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            has_renderable_takeoff_position,
        )

        for condition_type, minimum in (
            (Condition.TYPE_COUNT, 2),
            (Condition.TYPE_ATTACHMENT, 2),
            (Condition.TYPE_LINEAR, 4),
            (Condition.TYPE_AREA, 6),
        ):
            condition = _cond("c", condition_type)
            for length in range(0, 9):
                with self.subTest(type=condition_type, length=length):
                    takeoff = _tk("t", position=[0.0] * length)
                    self.assertIs(
                        has_renderable_takeoff_position(takeoff, condition),
                        length >= minimum,
                    )

    def test_unknown_condition_types_and_missing_positions_are_never_renderable(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            has_renderable_takeoff_position,
        )

        self.assertIs(
            has_renderable_takeoff_position(_tk("t", position=[0.0] * 10), _cond("c", 9)),
            False,
        )
        takeoff = _tk("t")
        takeoff.position = None
        for condition_type in range(4):
            self.assertIs(
                has_renderable_takeoff_position(takeoff, _cond("c", condition_type)), False
            )

    def test_area_usage_relevance_requires_condition_visibility_geometry_and_non_hole_area(self):
        conditions = {
            "area": _cond("area", Condition.TYPE_AREA),
            "hidden": _cond("hidden", Condition.TYPE_AREA, layer_visible=False),
            "line": _cond("line", Condition.TYPE_LINEAR),
        }
        square = [0, 0, 1, 0, 1, 1, 0, 1]
        relevant = is_takeoff_relevant_for_area_usage
        self.assertIs(relevant(_tk("t", "area", position=square), conditions), True)
        self.assertIs(relevant(_tk("t", "line", position=[0, 0, 1, 1]), conditions), True)
        # A backout (hole) under an area condition does not use bid area; a hole of
        # another geometry type still does.
        self.assertIs(
            relevant(_tk("t", "area", parent_uid="p0", position=square), conditions), False
        )
        self.assertIs(
            relevant(_tk("t", "line", parent_uid="p0", position=[0, 0, 1, 1]), conditions),
            True,
        )
        self.assertIs(relevant(_tk("t", "hidden", position=square), conditions), False)
        self.assertIs(relevant(_tk("t", "area", position=[0, 0, 1, 1]), conditions), False)
        self.assertIs(relevant(_tk("t", "missing", position=square), conditions), False)

    def test_is_takeoff_visible_delegates_to_the_entity(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            is_takeoff_visible,
        )

        conditions = {"c": _cond("c", 0, layer_visible=False)}
        self.assertIs(is_takeoff_visible(_tk("t"), conditions), False)
        self.assertIs(is_takeoff_visible(_tk("t", "other"), conditions), True)


class TakeoffGroupingTests(unittest.TestCase):
    def test_takeoffs_group_by_condition_type_with_empty_buckets_and_unknowns_dropped(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            group_takeoffs_by_type,
        )

        conditions = {
            "l": _cond("l", 0),
            "a": _cond("a", 1),
            "n": _cond("n", 2),
            "x": _cond("x", 3),
            "weird": _cond("weird", 7),
        }
        takeoffs = [
            _tk("1", "a"),
            _tk("2", "l"),
            _tk("3", "a"),
            _tk("4", "missing"),
            _tk("5", "weird"),
            _tk("6", "x"),
        ]
        grouped = group_takeoffs_by_type(conditions, takeoffs)
        self.assertEqual(sorted(grouped), [0, 1, 2, 3])
        self.assertEqual({k: [t.uid for t in v] for k, v in grouped.items()},
                         {0: ["2"], 1: ["1", "3"], 2: [], 3: ["6"]})
        empty = group_takeoffs_by_type(conditions, [])
        self.assertEqual(empty, {0: [], 1: [], 2: [], 3: []})
        self.assertIsNot(empty[0], empty[1])

    def test_area_holes_are_grouped_under_their_area_parent(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            group_area_takeoffs_with_holes,
        )

        conditions = {"area": _cond("area", 1), "line": _cond("line", 0)}
        parent = _tk("parent", "area")
        hole1 = _tk("hole1", "area", parent_uid="parent")
        hole2 = _tk("hole2", "area", parent_uid="parent")
        other = _tk("other", "area")
        line = _tk("line1", "line")
        lone_hole = _tk("lone", "area", parent_uid="gone")
        unknown = _tk("unknown", "missing")
        roots, holes = group_area_takeoffs_with_holes(
            [parent, hole1, line, other, hole2, lone_hole, unknown], conditions
        )
        # Non-area takeoffs (including unknown conditions) come first, then area
        # takeoffs that are not claimed as a hole of an area parent.
        self.assertEqual([t.uid for t in roots], ["line1", "unknown", "parent", "other", "lone"])
        self.assertEqual({k: [t.uid for t in v] for k, v in holes.items()}, {"parent": ["hole1", "hole2"]})

    def test_without_any_area_takeoff_the_input_list_is_returned_unchanged(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            group_area_takeoffs_with_holes,
        )

        conditions = {"line": _cond("line", 0)}
        takeoffs = [_tk("1", "line"), _tk("2", "missing")]
        roots, holes = group_area_takeoffs_with_holes(takeoffs, conditions)
        self.assertIs(roots, takeoffs)
        self.assertEqual(holes, {})
        self.assertEqual(group_area_takeoffs_with_holes([], conditions), ([], {}))

    def test_a_hole_under_a_non_area_parent_stays_a_top_level_takeoff(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            group_area_takeoffs_with_holes,
        )

        conditions = {"area": _cond("area", 1), "line": _cond("line", 0)}
        line = _tk("line1", "line")
        stray = _tk("stray", "area", parent_uid="line1")
        roots, holes = group_area_takeoffs_with_holes([line, stray], conditions)
        self.assertEqual([t.uid for t in roots], ["line1", "stray"])
        self.assertEqual(holes, {})


class TakeoffReassignEdgeTests(unittest.TestCase):
    def test_reassignment_types_map_every_condition_type_and_reject_unknown(self):
        for condition_type, expected in (
            (Condition.TYPE_LINEAR, Condition.TYPE_LINEAR),
            (Condition.TYPE_AREA, Condition.TYPE_AREA),
            (Condition.TYPE_COUNT, Condition.TYPE_COUNT),
            (Condition.TYPE_ATTACHMENT, Condition.TYPE_COUNT),
            (9, None),
        ):
            with self.subTest(type=condition_type):
                self.assertEqual(
                    condition_reassign_geometry_type(_cond("c", condition_type)), expected
                )

    def test_common_type_requires_every_takeoff_to_agree_and_resolve(self):
        conditions = {
            "l1": _cond("l1", 0),
            "l2": _cond("l2", 0),
            "a": _cond("a", 1),
            "weird": _cond("weird", 7),
        }
        self.assertEqual(
            common_reassign_geometry_type([_tk("1", "l1"), _tk("2", "l2")], conditions), 0
        )
        self.assertIsNone(common_reassign_geometry_type([], conditions))
        self.assertIsNone(
            common_reassign_geometry_type([_tk("1", "l1"), _tk("2", "a")], conditions)
        )
        self.assertIsNone(
            common_reassign_geometry_type([_tk("1", "a"), _tk("2", "l1")], conditions)
        )
        self.assertIsNone(
            common_reassign_geometry_type([_tk("1", "l1"), _tk("2", "weird")], conditions)
        )
        self.assertIsNone(
            common_reassign_geometry_type([_tk("1", "l1"), _tk("2", "gone")], conditions)
        )

    def test_matching_and_can_reassign_return_real_booleans(self):
        from ost_visualizer.domain.services.takeoff_domain_service import (
            condition_matches_reassign_geometry,
        )

        conditions = {"l": _cond("l", 0), "l2": _cond("l2", 0), "a": _cond("a", 1), "weird": _cond("weird", 7)}
        self.assertIs(condition_matches_reassign_geometry(conditions["l"], 0), True)
        self.assertIs(condition_matches_reassign_geometry(conditions["a"], 0), False)
        linear = [_tk("1", "l")]
        self.assertIs(takeoffs_can_reassign_to_condition(linear, conditions, "l2"), True)
        self.assertIs(takeoffs_can_reassign_to_condition(linear, conditions, "a"), False)
        self.assertIs(takeoffs_can_reassign_to_condition(linear, conditions, "missing"), False)
        # Without a common source type nothing is assignable, even to an unknown-type target.
        self.assertIs(takeoffs_can_reassign_to_condition([], conditions, "weird"), False)
        self.assertIs(
            takeoffs_can_reassign_to_condition([_tk("1", "gone")], conditions, "l"), False
        )

    def test_target_uid_is_looked_up_as_text(self):
        conditions = {"7": _cond("7", 0), "l": _cond("l", 0)}
        self.assertIs(takeoffs_can_reassign_to_condition([_tk("1", "l")], conditions, 7), True)
