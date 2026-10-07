import unittest
from dataclasses import replace
from ost_visualizer.domain.entities.ai_changeset import (
    ASSUMPTION_ACCEPTED,
    ASSUMPTION_OPEN,
    ASSUMPTION_OVERRIDDEN,
    CHANGESET_EXPIRY_SECONDS,
    HIGH_IMPACT_CLOSING_SEGMENT_IN,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    KIND_SCALE,
    MAX_CHANGESET_NEW_CONDITIONS,
    MAX_CHANGESET_TAKEOFFS,
    MAX_CHANGESET_VERTICES,
    MAX_POLYGON_VERTICES,
    STATUS_PROPOSED,
    SUBJECT_CLOSING_SEGMENT,
    SUBJECT_OTHER,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
    assumption_impact,
    quantity_delta,
    resolved_condition_name,
)

SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)


def _changeset(**overrides):
    values = dict(
        uid="cs-1",
        database_id="C:/jobs/a.mdb",
        bid_uid="7",
        bid_key="a" * 32,
        kind=KIND_ELEMENTS,
        created_at=1000.0,
        status=STATUS_PROPOSED,
        conditions=(ProposedCondition("c1", "Slab 8in", 8.0, 1200.0),),
        takeoffs=(ProposedTakeoff("t1", "page-1", "c1", SQUARE),),
    )
    values.update(overrides)
    return AiChangeset(**values)


def _assumption(
    uid="a1", subject=SUBJECT_THICKNESS, status=ASSUMPTION_OPEN, value="8", length=None
):
    return ChangesetAssumption(
        uid=uid,
        subject=subject,
        target_key="c1",
        value=value,
        reason="not shown",
        sheet_ref="S-101",
        impact=assumption_impact(subject, length),
        status=status,
    )


class ChangesetCapTests(unittest.TestCase):
    def test_caps_match_the_plan(self):
        self.assertEqual(
            (
                MAX_CHANGESET_TAKEOFFS,
                MAX_CHANGESET_NEW_CONDITIONS,
                MAX_POLYGON_VERTICES,
                MAX_CHANGESET_VERTICES,
                CHANGESET_EXPIRY_SECONDS,
            ),
            (200, 25, 2000, 20000, 1800),
        )

    def test_a_changeset_inside_every_cap_validates(self):
        _changeset().validate_caps()

    def test_each_cap_is_enforced_at_its_boundary(self):
        polygon = SQUARE * 1
        takeoffs = tuple(
            ProposedTakeoff(f"t{index}", "page-1", "c1", polygon)
            for index in range(200)
        )
        _changeset(takeoffs=takeoffs).validate_caps()
        conditions = tuple(
            ProposedCondition(f"c{index}", "Slab", 8.0, 0.0) for index in range(25)
        )
        _changeset(conditions=conditions).validate_caps()
        vertices_2000 = tuple(float(value) for value in range(4000))
        _changeset(
            takeoffs=(ProposedTakeoff("t1", "page-1", "c1", vertices_2000),)
        ).validate_caps()
        cases = {
            "takeoffs": _changeset(
                takeoffs=takeoffs + (ProposedTakeoff("x", "page-1", "c1", polygon),)
            ),
            "conditions": _changeset(
                conditions=conditions + (ProposedCondition("x", "Slab", 8.0, 0.0),)
            ),
            "polygon vertices": _changeset(
                takeoffs=(
                    ProposedTakeoff("t1", "page-1", "c1", vertices_2000 + (1.0, 2.0)),
                )
            ),
            "hole vertices": _changeset(
                takeoffs=(
                    ProposedTakeoff(
                        "t1", "page-1", "c1", SQUARE, (vertices_2000 + (1.0, 2.0),)
                    ),
                )
            ),
            "changeset vertices": _changeset(
                takeoffs=tuple(
                    ProposedTakeoff(f"t{index}", "page-1", "c1", vertices_2000)
                    for index in range(9)
                )
                + (
                    ProposedTakeoff(
                        "t9", "page-1", "c1", vertices_2000[:3996], (SQUARE[:6],)
                    ),
                )
            ),
        }
        exactly_20000 = _changeset(
            takeoffs=tuple(
                ProposedTakeoff(f"t{index}", "page-1", "c1", vertices_2000)
                for index in range(10)
            )
        )
        self.assertEqual(exactly_20000.vertex_count, 20000)
        exactly_20000.validate_caps()
        self.assertEqual(cases["changeset vertices"].vertex_count, 20001)
        for label, changeset in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError) as raised:
                    changeset.validate_caps()
                self.assertEqual(raised.exception.code, "changeset_too_large")

    def test_vertex_counts_include_holes(self):
        takeoff = ProposedTakeoff("t1", "page-1", "c1", SQUARE, (SQUARE[:6],))
        self.assertEqual(takeoff.vertex_count, 7)
        self.assertEqual(_changeset(takeoffs=(takeoff, takeoff)).vertex_count, 14)

    def test_malformed_polygons_are_invalid_geometry(self):
        for label, polygon in {
            "odd coordinates": (0.0, 0.0, 1.0),
            "two points": (0.0, 0.0, 1.0, 1.0),
            "not finite": (0.0, 0.0, float("nan"), 0.0, 1.0, 1.0),
            "zero area": (0.0, 0.0, 1.0, 1.0, 2.0, 2.0),
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError) as raised:
                    ProposedTakeoff("t1", "page-1", "c1", polygon).validate()
                self.assertEqual(raised.exception.code, "invalid_geometry")


class ChangesetLifecycleTests(unittest.TestCase):
    def test_expiry_is_thirty_minutes_after_proposal(self):
        changeset = _changeset()
        self.assertEqual(changeset.expires_at, 1000.0 + 1800.0)
        self.assertFalse(changeset.is_expired(2799.9))
        self.assertTrue(changeset.is_expired(2800.0))

    def test_touched_resources_are_the_pages_and_existing_conditions_it_depends_on(
        self,
    ):
        reused = _changeset(
            conditions=(),
            takeoffs=(ProposedTakeoff("t1", "page-2", "existing:42", SQUARE),),
        )
        self.assertEqual(reused.touched_resources, ("condition:42", "page:page-2"))
        self.assertEqual(_changeset().touched_resources, ("page:page-1",))
        scale = _changeset(
            kind=KIND_SCALE,
            conditions=(),
            takeoffs=(),
            scale=ProposedScale("page-3", 0.25, 12.0, 0.125, 12.0, 0.4),
        )
        self.assertEqual(
            scale.touched_resources, ("page:page-3", "page_takeoffs:page-3")
        )


class AssumptionGatingTests(unittest.TestCase):
    def test_scale_thickness_and_elevation_are_high_impact(self):
        self.assertEqual(assumption_impact(SUBJECT_THICKNESS), IMPACT_HIGH)
        self.assertEqual(assumption_impact(SUBJECT_TOP_ELEVATION), IMPACT_HIGH)
        self.assertEqual(assumption_impact("scale"), IMPACT_HIGH)
        self.assertEqual(assumption_impact(SUBJECT_OTHER), IMPACT_NORMAL)

    def test_closing_segments_over_twelve_inches_are_high_impact(self):
        self.assertEqual(HIGH_IMPACT_CLOSING_SEGMENT_IN, 12.0)
        self.assertEqual(
            assumption_impact(SUBJECT_CLOSING_SEGMENT, 12.0), IMPACT_NORMAL
        )
        self.assertEqual(assumption_impact(SUBJECT_CLOSING_SEGMENT, 12.01), IMPACT_HIGH)

    def test_only_open_high_impact_assumptions_block(self):
        blocked = _changeset(
            assumptions=(
                _assumption("a1", SUBJECT_THICKNESS),
                _assumption("a2", SUBJECT_OTHER),
                _assumption("a3", SUBJECT_TOP_ELEVATION, ASSUMPTION_ACCEPTED),
            )
        )
        self.assertEqual([item.uid for item in blocked.blocking_assumptions], ["a1"])
        resolved = replace(
            blocked,
            assumptions=tuple(
                (
                    replace(item, status=ASSUMPTION_OVERRIDDEN, override_value="10")
                    if item.uid == "a1"
                    else item
                )
                for item in blocked.assumptions
            ),
        )
        self.assertEqual(resolved.blocking_assumptions, ())

    def test_resolved_values_follow_overrides(self):
        changeset = _changeset(
            conditions=(ProposedCondition("c1", "Slab", None, None),),
            assumptions=(
                replace(
                    _assumption("a1", SUBJECT_THICKNESS),
                    status=ASSUMPTION_OVERRIDDEN,
                    override_value="10",
                ),
                replace(
                    _assumption("a2", SUBJECT_TOP_ELEVATION, value="1200"),
                    status=ASSUMPTION_ACCEPTED,
                ),
            ),
        )
        condition = changeset.resolved_conditions()[0]
        self.assertEqual(
            (condition.thickness_in, condition.top_elev_in), (10.0, 1200.0)
        )

    def test_unresolved_values_cannot_be_applied(self):
        changeset = _changeset(
            conditions=(ProposedCondition("c1", "Slab", None, 1200.0),),
            assumptions=(_assumption("a1", SUBJECT_THICKNESS),),
        )
        with self.assertRaises(ChangesetError) as raised:
            changeset.resolved_conditions()
        self.assertEqual(raised.exception.code, "assumption_unresolved")


class QuantityDeltaTests(unittest.TestCase):
    def test_area_and_volume_per_condition_subtract_holes(self):
        hole = (120.0, 120.0, 240.0, 120.0, 240.0, 240.0, 120.0, 240.0)
        changeset = _changeset(
            takeoffs=(
                ProposedTakeoff("t1", "page-1", "c1", SQUARE, (hole,)),
                ProposedTakeoff("t2", "page-1", "c1", tuple(reversed(SQUARE))),
            )
        )
        (delta,) = quantity_delta(changeset)
        self.assertEqual(
            (delta.key, delta.name, delta.takeoff_count),
            ("c1", "Slab 8in @T 100' - 0\"", 2),
        )
        self.assertAlmostEqual(delta.area_sf, 1200.0 - 100.0 + 1200.0)
        self.assertAlmostEqual(delta.volume_cy, 2300.0 * 8.0 / 12.0 / 27.0)

    def test_unresolved_thickness_has_no_volume_until_an_assumption_resolves_it(self):
        changeset = _changeset(
            conditions=(ProposedCondition("c1", "Slab", None, None),)
        )
        self.assertIsNone(quantity_delta(changeset)[0].volume_cy)
        resolved = replace(
            changeset,
            assumptions=(
                replace(
                    _assumption(), status=ASSUMPTION_OVERRIDDEN, override_value="6"
                ),
            ),
        )
        self.assertAlmostEqual(
            quantity_delta(resolved)[0].volume_cy, 1200.0 * 0.5 / 27.0
        )

    def test_existing_conditions_are_listed_by_uid(self):
        changeset = _changeset(
            conditions=(),
            takeoffs=(ProposedTakeoff("t1", "page-1", "existing:42", SQUARE),),
        )
        (delta,) = quantity_delta(changeset)
        self.assertEqual(
            (delta.key, delta.name, delta.volume_cy),
            ("existing:42", "existing:42", None),
        )


class ConditionNameTests(unittest.TestCase):
    def test_top_elevation_uses_the_at_t_suffix(self):
        self.assertEqual(
            resolved_condition_name(ProposedCondition("c1", "Slab 8in", 8.0, 1200.0)),
            "Slab 8in @T 100' - 0\"",
        )
        self.assertEqual(
            resolved_condition_name(ProposedCondition("c1", "Slab 8in", 8.0, -18.5)),
            "Slab 8in @T -1' - 6 1/2\"",
        )

    def test_base_names_are_cleaned_and_bounded(self):
        name = resolved_condition_name(
            ProposedCondition("c1", "Slab\n\u202e @T 5' " + "x" * 200, 8.0, 0.0)
        )
        self.assertNotIn("\n", name)
        self.assertNotIn("\u202e", name)
        self.assertEqual(name.count("@T"), 1)
        self.assertLessEqual(len(name), 120)


class GeometryAndRangeTests(unittest.TestCase):
    def test_holes_must_lie_inside_their_polygon(self):
        inside = (100.0, 100.0, 200.0, 100.0, 200.0, 200.0, 100.0, 200.0)
        ProposedTakeoff("t1", "page-1", "c1", SQUARE, (inside,)).validate()
        for label, hole in {
            "outside": (1000.0, 1000.0, 1100.0, 1000.0, 1100.0, 1100.0, 1000.0, 1100.0),
            "crossing": (400.0, 100.0, 600.0, 100.0, 600.0, 200.0, 400.0, 200.0),
            "larger": (-10.0, -10.0, 500.0, -10.0, 500.0, 400.0, -10.0, 400.0),
            "same as the outline": SQUARE,
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError) as raised:
                    ProposedTakeoff("t1", "page-1", "c1", SQUARE, (hole,)).validate()
                self.assertEqual(raised.exception.code, "invalid_geometry")
        l_slab = (
            0.0,
            0.0,
            480.0,
            0.0,
            480.0,
            180.0,
            240.0,
            180.0,
            240.0,
            360.0,
            0.0,
            360.0,
        )
        across_the_notch = (400.0, 100.0, 100.0, 300.0, 100.0, 100.0)
        with self.assertRaises(ChangesetError):
            ProposedTakeoff(
                "t1", "page-1", "c1", l_slab, (across_the_notch,)
            ).validate()
        in_one_arm = (300.0, 50.0, 450.0, 50.0, 450.0, 150.0)
        ProposedTakeoff("t1", "page-1", "c1", l_slab, (in_one_arm,)).validate()
        touching = (0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0)
        ProposedTakeoff("t1", "page-1", "c1", SQUARE, (touching,)).validate()

    def test_resolved_values_outside_the_proposal_limits_are_unresolved(self):
        for subject, value in (
            (SUBJECT_TOP_ELEVATION, "1e300"),
            (SUBJECT_TOP_ELEVATION, "100001"),
            (SUBJECT_THICKNESS, "121"),
        ):
            with self.subTest(subject=subject, value=value):
                changeset = _changeset(
                    conditions=(ProposedCondition("c1", "Slab", None, None),),
                    assumptions=(
                        _assumption(
                            "a1", SUBJECT_THICKNESS, ASSUMPTION_OVERRIDDEN, "8"
                        ),
                        _assumption(
                            "a2", SUBJECT_TOP_ELEVATION, ASSUMPTION_ACCEPTED, "0"
                        ),
                    ),
                )
                changeset = replace(
                    changeset,
                    assumptions=tuple(
                        (
                            replace(
                                item, override_value=value, status=ASSUMPTION_OVERRIDDEN
                            )
                            if item.subject == subject
                            else (
                                replace(item, override_value="8")
                                if item.status == ASSUMPTION_OVERRIDDEN
                                else item
                            )
                        )
                        for item in changeset.assumptions
                    ),
                )
                with self.assertRaises(ChangesetError) as raised:
                    changeset.resolved_conditions()
                self.assertEqual(raised.exception.code, "assumption_unresolved")
        within = _changeset(
            conditions=(ProposedCondition("c1", "Slab", 120.0, -100000.0),)
        )
        (condition,) = within.resolved_conditions()
        self.assertEqual(
            (condition.thickness_in, condition.top_elev_in), (120.0, -100000.0)
        )


if __name__ == "__main__":
    unittest.main()
