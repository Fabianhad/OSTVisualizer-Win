import math
import unittest
from dataclasses import FrozenInstanceError, replace
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
    MAX_CONDITION_BASE_NAME_CHARS,
    MAX_POLYGON_VERTICES,
    SQL_APPLY_UNAVAILABLE_MESSAGE,
    STATUS_PROPOSED,
    SUBJECT_CLOSING_SEGMENT,
    SUBJECT_OTHER,
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ConditionQuantityDelta,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
    _inside_or_on,
    _on_segment,
    _properly_cross,
    DATABASE_UNRESOLVED_MESSAGE,
    apply_block_for,
    apply_blocked_reason,
    assumption_impact,
    polygon_area,
    quantity_delta,
    resolved_condition_name,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
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

    def test_a_hole_filling_a_notch_of_the_outline_is_outside_it(self):
        u_slab = (0.0, 0.0, 30.0, 0.0, 30.0, 30.0, 20.0, 30.0)
        u_slab += (20.0, 10.0, 10.0, 10.0, 10.0, 30.0, 0.0, 30.0)
        notch = (10.0, 30.0, 20.0, 30.0, 20.0, 10.0, 10.0, 10.0)
        with self.assertRaises(ChangesetError) as raised:
            ProposedTakeoff("t1", "page-1", "c1", u_slab, (notch,)).validate()
        self.assertEqual(raised.exception.code, "invalid_geometry")
        in_the_base = (5.0, 2.0, 25.0, 2.0, 25.0, 8.0, 5.0, 8.0)
        ProposedTakeoff("t1", "page-1", "c1", u_slab, (in_the_base,)).validate()

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


def _circle(count, radius=1000.0):
    ring = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        ring.extend((radius * math.cos(angle), radius * math.sin(angle)))
    return tuple(ring)


def _validate_hole(outline, hole):
    ProposedTakeoff("t1", "page-1", "c1", outline, (hole,)).validate()


class ChangesetEntityTests(unittest.TestCase):
    def test_entities_are_frozen(self):
        condition = ProposedCondition("c1", "Slab", 8.0, None)
        takeoff = ProposedTakeoff("t1", "page-1", "c1", SQUARE)
        scale = ProposedScale("page-3", 0.25, 12.0, 0.125, 12.0)
        assumption = _assumption()
        changeset = _changeset()
        delta = ConditionQuantityDelta("c1", "Slab", 1, 1.0, None)
        with self.assertRaises(FrozenInstanceError):
            condition.base_name = "Other"
        with self.assertRaises(FrozenInstanceError):
            takeoff.page_uid = "page-2"
        with self.assertRaises(FrozenInstanceError):
            scale.sf1 = 1.0
        with self.assertRaises(FrozenInstanceError):
            assumption.status = ASSUMPTION_ACCEPTED
        with self.assertRaises(FrozenInstanceError):
            changeset.status = "applied"
        with self.assertRaises(FrozenInstanceError):
            delta.name = "Other"

    def test_a_new_changeset_starts_at_revision_zero(self):
        self.assertEqual(_changeset().revision, 0)

    def test_errors_carry_their_message_as_the_exception_text(self):
        error = ChangesetError("invalid_state", "This changeset has no scale")
        self.assertEqual(str(error), "This changeset has no scale")
        self.assertEqual(
            (error.code, error.message),
            ("invalid_state", "This changeset has no scale"),
        )

    def test_only_sql_server_bids_block_apply(self):
        access = DatabaseDescriptor.for_access("C:/jobs/a.mdb")
        sql = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="srv", database="Bids"), schema_version=1
        )
        self.assertEqual(apply_blocked_reason(access), "")
        self.assertEqual(apply_blocked_reason(sql), SQL_APPLY_UNAVAILABLE_MESSAGE)

    def test_a_database_that_cannot_be_resolved_blocks_apply(self):
        self.assertEqual(apply_blocked_reason(None), DATABASE_UNRESOLVED_MESSAGE)
        access = DatabaseDescriptor.for_access("C:/jobs/a.mdb")
        registered = {access.database_id: access}

        def failing_lookup(_database_id):
            raise LookupError("registry unavailable")

        self.assertEqual(apply_block_for(registered.get, access.database_id), "")
        for label, resolve, database_id in (
            ("unregistered id", registered.get, "sql:srv/unknown"),
            ("unregistered mdb path", registered.get, "C:/jobs/other.mdb"),
            ("missing descriptor", lambda _database_id: None, access.database_id),
            ("lookup raises", failing_lookup, access.database_id),
        ):
            with self.subTest(label):
                self.assertEqual(
                    apply_block_for(resolve, database_id), DATABASE_UNRESOLVED_MESSAGE
                )
        self.assertIn("not open", DATABASE_UNRESOLVED_MESSAGE)


class ConditionBaseNameTests(unittest.TestCase):
    def test_a_name_without_elevation_is_only_the_cleaned_base(self):
        self.assertEqual(
            resolved_condition_name(ProposedCondition("c1", " Slab  8in ", 8.0, None)),
            "Slab 8in",
        )

    def test_whitespace_controls_become_single_spaces(self):
        for separator in ("\t", "\n", "\r", "\x0b", "\x0c"):
            with self.subTest(separator=repr(separator)):
                self.assertEqual(
                    resolved_condition_name(
                        ProposedCondition("c1", f"Slab{separator}8in", 8.0, None)
                    ),
                    "Slab 8in",
                )
        self.assertEqual(
            resolved_condition_name(ProposedCondition("c1", "Slab\x008in", 8.0, None)),
            "Slab8in",
        )

    def test_base_names_are_cut_at_eighty_characters(self):
        self.assertEqual(MAX_CONDITION_BASE_NAME_CHARS, 80)
        for text, expected in (
            ("x" * 80, "x" * 80),
            ("x" * 81, "x" * 80),
            ("x" * 79 + " yz", "x" * 79),
        ):
            with self.subTest(length=len(text)):
                self.assertEqual(
                    resolved_condition_name(ProposedCondition("c1", text, 8.0, None)),
                    expected,
                )


class RingValidationTests(unittest.TestCase):
    def test_odd_or_short_coordinate_lists_are_refused_even_with_area(self):
        for label, ring in {
            "seven coordinates": (0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0),
            "two points": (0.0, 0.0, 10.0, 10.0),
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError) as raised:
                    ProposedTakeoff("t1", "page-1", "c1", ring).validate()
                self.assertEqual(
                    (raised.exception.code, raised.exception.message),
                    ("invalid_geometry", "A polygon needs at least three points"),
                )

    def test_non_finite_or_non_numeric_coordinates_are_refused(self):
        for label, value in {
            "nan": float("nan"),
            "infinity": float("inf"),
            "text": "1",
        }.items():
            with self.subTest(label=label):
                ring = (0.0, 0.0, 10.0, 0.0, value, 10.0)
                with self.assertRaises(ChangesetError) as raised:
                    ProposedTakeoff("t1", "page-1", "c1", ring).validate()
                self.assertEqual(
                    (raised.exception.code, raised.exception.message),
                    ("invalid_geometry", "Polygon coordinates must be finite"),
                )

    def test_an_overflowing_area_is_refused(self):
        ring = (0.0, 0.0, 1e300, 0.0, 1e300, 1e300, 0.0, 1e300)
        with self.assertRaises(ChangesetError) as raised:
            ProposedTakeoff("t1", "page-1", "c1", ring).validate()
        self.assertEqual(raised.exception.message, "The polygon area is too large")

    def test_the_area_floor_is_one_billionth_square_point(self):
        tiny = (0.0, 0.0, 1.0, 0.0, 0.0, 2e-9)
        self.assertEqual(polygon_area(tiny), 1e-9)
        with self.assertRaises(ChangesetError) as raised:
            ProposedTakeoff("t1", "page-1", "c1", tiny).validate()
        self.assertEqual(raised.exception.message, "A polygon must enclose an area")
        for ring in (
            (0.0, 0.0, 1.0, 0.0, 0.0, 4e-9),
            (0.0, 0.0, 1.0, 0.0, 0.0, 1.0),
        ):
            with self.subTest(ring=ring):
                ProposedTakeoff("t1", "page-1", "c1", ring).validate()

    def test_validate_allows_two_thousand_vertices_per_ring(self):
        ProposedTakeoff("t1", "page-1", "c1", _circle(2000)).validate()
        ProposedTakeoff(
            "t1", "page-1", "c1", _circle(4, 5000.0), (_circle(2000),)
        ).validate()
        for label, takeoff in {
            "outline": ProposedTakeoff("t1", "page-1", "c1", _circle(2001)),
            "hole": ProposedTakeoff(
                "t1", "page-1", "c1", _circle(4, 5000.0), (_circle(2001),)
            ),
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError) as raised:
                    takeoff.validate()
                self.assertEqual(raised.exception.code, "changeset_too_large")


class PointOnBoundaryTests(unittest.TestCase):
    def test_segment_endpoints_and_tolerance_edges_are_on_the_segment(self):
        horizontal = ((2.0, 3.0), (7.0, 3.0))
        vertical = ((4.0, -6.0), (4.0, -1.0))
        for point, segment in (
            ((2.0, 3.0), horizontal),
            ((7.0, 3.0), horizontal),
            ((4.5, 3.0), horizontal),
            ((4.0, -6.0), vertical),
            ((4.0, -1.0), vertical),
            ((2.0 - 1e-9, 3.0), horizontal),
            ((7.0 + 1e-9, 3.0), horizontal),
            ((4.0, -6.0 - 1e-9), vertical),
            ((4.0, -1.0 + 1e-9), vertical),
        ):
            with self.subTest(point=point, segment=segment):
                self.assertTrue(_on_segment(point, *segment))
                self.assertTrue(_on_segment(point, *reversed(segment)))

    def test_points_past_the_tolerance_are_off_the_segment(self):
        horizontal = ((2.0, 3.0), (7.0, 3.0))
        vertical = ((4.0, -6.0), (4.0, -1.0))
        for point, segment in (
            ((1.5, 3.0), horizontal),
            ((7.5, 3.0), horizontal),
            ((4.0, -6.5), vertical),
            ((4.0, -0.5), vertical),
            ((4.5, 3.1), horizontal),
        ):
            with self.subTest(point=point, segment=segment):
                self.assertFalse(_on_segment(point, *segment))
                self.assertFalse(_on_segment(point, *reversed(segment)))

    def test_collinearity_tolerance_scales_with_the_squared_length(self):
        unit = ((0.0, 0.0), (1.0, 0.0))
        self.assertTrue(_on_segment((0.5, 1e-9), *unit))
        short_diagonal = ((0.0, 0.0), (1.0, 1.0))
        self.assertTrue(_on_segment((0.5 + 0.9e-9, 0.5 - 0.9e-9), *short_diagonal))
        self.assertFalse(_on_segment((0.5 + 1.5e-9, 0.5 - 1.5e-9), *short_diagonal))
        self.assertFalse(_on_segment((0.6, 0.4), *short_diagonal))
        long_diagonal = ((3.0, 5.0), (103.0, 105.0))
        self.assertTrue(_on_segment((53.0 + 5e-8, 55.0 - 5e-8), *long_diagonal))
        self.assertFalse(_on_segment((53.0 + 2e-7, 55.0 - 2e-7), *long_diagonal))
        far_short_diagonal = ((100.0, 100.0), (101.0, 101.0))
        self.assertFalse(_on_segment((100.5 + 1e-6, 100.5 - 1e-6), *far_short_diagonal))

    def test_only_segments_that_pass_through_each_other_cross_properly(self):
        self.assertTrue(
            _properly_cross((0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0))
        )
        self.assertTrue(_properly_cross((1.0, 2.0), (9.0, 5.0), (4.0, 7.0), (6.0, 1.0)))
        for label, segments in {
            "apart": ((0.0, 0.0), (4.0, 1.0), (5.0, 0.0), (6.0, 8.0)),
            "touching at an end": ((0.0, 0.0), (5.0, 5.0), (5.0, 5.0), (9.0, 1.0)),
            "end on the other segment": (
                (0.0, 0.0),
                (5.0, 5.0),
                (0.0, 10.0),
                (10.0, 0.0),
            ),
            "collinear overlap": ((0.0, 0.0), (6.0, 6.0), (3.0, 3.0), (9.0, 9.0)),
        }.items():
            with self.subTest(label=label):
                self.assertFalse(_properly_cross(*segments))

    def test_points_are_classified_against_slanted_edges(self):
        diamond = [(13.0, 5.0), (23.0, 15.0), (13.0, 25.0), (3.0, 15.0)]
        for point in ((13.0, 15.0), (7.0, 15.0), (19.0, 15.0), (13.0, 8.0)):
            with self.subTest(point=point):
                self.assertTrue(_inside_or_on(point, diamond))
        for point in (
            (6.0, 9.0),
            (20.0, 9.0),
            (20.0, 21.0),
            (6.0, 21.0),
            (2.0, 15.0),
            (24.0, 15.0),
        ):
            with self.subTest(point=point):
                self.assertFalse(_inside_or_on(point, diamond))


class HoleContainmentTests(unittest.TestCase):
    def test_holes_flush_with_any_side_of_the_outline_are_inside(self):
        for label, hole in {
            "right": (380.0, 100.0, 480.0, 100.0, 480.0, 200.0, 380.0, 200.0),
            "top": (100.0, 260.0, 200.0, 260.0, 200.0, 360.0, 100.0, 360.0),
            "left": (0.0, 100.0, 100.0, 100.0, 100.0, 200.0, 0.0, 200.0),
            "bottom": (100.0, 0.0, 200.0, 0.0, 200.0, 100.0, 100.0, 100.0),
        }.items():
            with self.subTest(label=label):
                _validate_hole(SQUARE, hole)

    def test_a_hole_inside_the_bounding_box_of_a_slanted_edge_is_outside(self):
        triangle = (0.0, 0.0, 100.0, 0.0, 0.0, 100.0)
        with self.assertRaises(ChangesetError):
            _validate_hole(triangle, (70.0, 70.0, 90.0, 70.0, 90.0, 90.0))

    def test_an_edge_crossing_a_narrow_notch_is_refused(self):
        notched = (0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 80.0, 100.0)
        notched += (80.0, 55.0, 78.0, 55.0, 78.0, 100.0, 0.0, 100.0)
        crossing = (10.0, 10.0, 90.0, 10.0, 90.0, 60.0, 10.0, 60.0)
        with self.assertRaises(ChangesetError) as raised:
            _validate_hole(notched, crossing)
        self.assertEqual(raised.exception.code, "invalid_geometry")
        _validate_hole(notched, (10.0, 10.0, 90.0, 10.0, 90.0, 50.0, 10.0, 50.0))

    def test_a_vertex_in_a_notch_is_refused_even_when_its_edges_pass_corners(self):
        notched = (0.0, 0.0, 30.0, 0.0, 30.0, 20.0, 20.0, 20.0)
        notched += (20.0, 10.0, 10.0, 10.0, 10.0, 20.0, 0.0, 20.0)
        through_corners = (15.0, 11.0, 2.5, 8.5, 27.5, 8.5)
        with self.assertRaises(ChangesetError):
            _validate_hole(notched, through_corners)

    def test_touching_the_outline_at_one_point_is_not_crossing_it(self):
        l_slab = (0.0, 0.0, 480.0, 0.0, 480.0, 180.0, 240.0, 180.0)
        l_slab += (240.0, 360.0, 0.0, 360.0)
        _validate_hole(l_slab, (120.0, 240.0, 100.0, 100.0, 360.0, 120.0))
        _validate_hole(SQUARE, (240.0, 0.0, 300.0, 100.0, 180.0, 100.0))

    def test_a_hole_filling_a_notch_is_found_by_its_edge_midpoints(self):
        top_notch = (-30.0, -30.0, 30.0, -30.0, 30.0, 30.0, 10.0, 30.0)
        top_notch += (10.0, 21.0, -10.0, 21.0, -10.0, 30.0, -30.0, 30.0)
        right_notch = (-30.0, -30.0, 30.0, -30.0, 30.0, -10.0, 21.0, -10.0)
        right_notch += (21.0, 10.0, 30.0, 10.0, 30.0, 30.0, -30.0, 30.0)
        for label, outline, hole in (
            ("top", top_notch, (-10.0, 30.0, 10.0, 30.0, 10.0, 21.0, -10.0, 21.0)),
            ("right", right_notch, (30.0, -10.0, 30.0, 10.0, 21.0, 10.0, 21.0, -10.0)),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ChangesetError):
                    _validate_hole(outline, hole)


class ResolutionTests(unittest.TestCase):
    def test_open_high_impact_assumptions_block_even_when_values_are_given(self):
        changeset = _changeset(assumptions=(_assumption("a1", SUBJECT_THICKNESS),))
        with self.assertRaises(ChangesetError) as raised:
            changeset.resolved_conditions()
        self.assertEqual(
            (raised.exception.code, raised.exception.message),
            (
                "assumption_unresolved",
                "High-impact assumptions must be accepted or overridden first",
            ),
        )

    def test_thickness_must_be_above_zero_and_at_most_120_inches(self):
        for thickness, accepted in (
            (0.0, False),
            (0.5, True),
            (120.0, True),
            (120.0001, False),
        ):
            with self.subTest(thickness=thickness):
                changeset = _changeset(
                    conditions=(ProposedCondition("c1", "Slab", thickness, None),)
                )
                if accepted:
                    (condition,) = changeset.resolved_conditions()
                    self.assertEqual(condition.thickness_in, thickness)
                else:
                    with self.assertRaises(ChangesetError) as raised:
                        changeset.resolved_conditions()
                    self.assertEqual(raised.exception.code, "assumption_unresolved")

    def test_a_thickness_override_that_is_not_a_finite_number_is_unresolved(self):
        for text in ("eight", "nan", "inf"):
            with self.subTest(text=text):
                changeset = _changeset(
                    assumptions=(
                        replace(
                            _assumption(),
                            status=ASSUMPTION_OVERRIDDEN,
                            override_value=text,
                        ),
                    )
                )
                self.assertIsNone(quantity_delta(changeset)[0].volume_cy)
                with self.assertRaises(ChangesetError) as raised:
                    changeset.resolved_conditions()
                self.assertEqual(raised.exception.code, "assumption_unresolved")

    def test_effective_values_follow_the_assumption_status(self):
        open_item = _assumption(value="8")
        self.assertIsNone(open_item.effective_value)
        self.assertEqual(
            replace(open_item, status=ASSUMPTION_ACCEPTED).effective_value, "8"
        )
        self.assertEqual(
            replace(
                open_item, status=ASSUMPTION_OVERRIDDEN, override_value="10"
            ).effective_value,
            "10",
        )

    def test_a_later_resolved_assumption_supplies_the_value(self):
        changeset = _changeset(
            assumptions=(
                _assumption("a1", SUBJECT_OTHER, value="1"),
                replace(
                    _assumption("a2", SUBJECT_OTHER, value="2"),
                    status=ASSUMPTION_ACCEPTED,
                ),
            )
        )
        self.assertEqual(changeset.assumption_value("c1", SUBJECT_OTHER), "2")
        self.assertIsNone(changeset.assumption_value("c1", SUBJECT_THICKNESS))

    def test_resolved_scale_needs_a_scale_and_no_open_high_impact_assumptions(self):
        scale = ProposedScale("page-3", 0.25, 12.0, 0.125, 12.0, 0.4)
        without = _changeset(kind=KIND_SCALE, conditions=(), takeoffs=())
        with self.assertRaises(ChangesetError) as raised:
            without.resolved_scale()
        self.assertEqual(
            (raised.exception.code, raised.exception.message),
            ("invalid_state", "This changeset has no scale"),
        )
        blocked = replace(
            without, scale=scale, assumptions=(_assumption("a1", SUBJECT_SCALE),)
        )
        with self.assertRaises(ChangesetError) as raised:
            blocked.resolved_scale()
        self.assertEqual(raised.exception.code, "assumption_unresolved")
        accepted = replace(
            blocked,
            assumptions=(replace(blocked.assumptions[0], status=ASSUMPTION_ACCEPTED),),
        )
        self.assertIs(accepted.resolved_scale(), scale)


if __name__ == "__main__":
    unittest.main()
