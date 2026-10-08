import dataclasses
import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AiTakeoffRequestError,
    PageSnapshot,
)
from ost_visualizer.application.dtos.pdf_metadata_dtos import (
    PdfPageInfoDto,
    PdfVectorSegmentDto,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_proposal_service import (
    MAX_CACHED_REGIONS,
    MAX_GAP_CLOSE_IN,
    MAX_REGIONS_RETURNED,
    AiTakeoffProposalService,
    RasterResult,
)
from ost_visualizer.domain.entities.ai_changeset import (
    ASSUMPTION_ACCEPTED,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    STATUS_PENDING_APPROVAL,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.ai_changeset import (
    DATABASE_UNRESOLVED_MESSAGE,
    apply_block_for,
    apply_blocked_reason,
)
from tests.application.services.test_ai_takeoff_read_service import (
    ACCESS_PATH,
    ServiceTestCase,
)

PRESETS = [
    (0.125, 12.0, '1/8" = 1\' 0"'),
    (0.25, 12.0, '1/4" = 1\' 0"'),
]
PAGE_HEIGHT = 792.0
K = 12.0 / 18.0


def _raw(x1, y1, x2, y2):
    return PdfVectorSegmentDto(x1, PAGE_HEIGHT - y1, x2, PAGE_HEIGHT - y2)


def _rect(x1, y1, x2, y2):
    return [
        _raw(x1, y1, x2, y1),
        _raw(x2, y1, x2, y2),
        _raw(x2, y2, x1, y2),
        _raw(x1, y2, x1, y1),
    ]


class ProposalTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.raster_calls = []
        self.raster_result = None
        self.requested = []
        self.store = AiChangesetStore(clock=lambda: 50.0)
        self.proposals = AiChangesetProposals(self.store)
        self.service_m1b = AiTakeoffProposalService(
            read_service=self.service,
            proposals=self.proposals,
            presets=PRESETS,
            raster_fill=self._raster,
            level_uids=lambda: {"L1"},
        )

    def _raster(self, segments, bbox, seed, pen_width_pts):
        self.raster_calls.append((bbox, seed, pen_width_pts))
        return self.raster_result

    def snapshot(self, uid="p1"):
        return self.service.page_snapshot(uid)

    def assert_error(self, code, call):
        with self.assertRaises(AiTakeoffRequestError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        return raised.exception


class ScaleProposalTests(ProposalTestCase):
    def test_a_measured_distance_matching_a_preset_proposes_it(self):
        result = self.service_m1b.propose_scale(
            "p1", [100, 100], [460, 100], real_in=479.0
        )
        data = result["data"]
        self.assertEqual(data["kind"], "scale")
        self.assertEqual(data["scale"]["sf1_sf2"], [0.125, 12.0])
        self.assertAlmostEqual(
            data["scale"]["error_pct"], abs(4 / 3 - 479 / 360) / (479 / 360) * 100
        )
        (assumption,) = data["assumptions"]
        self.assertEqual(
            (assumption["subject"], assumption["impact"]), ("scale", IMPACT_HIGH)
        )
        self.assertEqual(data["blocking_assumption_ids"], ["a1"])

    def test_a_distance_far_from_any_preset_proposes_a_custom_scale(self):
        data = self.service_m1b.propose_scale("p1", [0, 0], [100, 0], real_in=1000.0)[
            "data"
        ]
        self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 720.0])
        self.assertAlmostEqual(data["scale"]["error_pct"], 0.0)

    def test_a_named_preset_with_a_check_distance(self):
        data = self.service_m1b.propose_scale(
            "p1", [0, 0], [72, 0], preset='1/4" = 1\' 0"', real_in=48.0
        )["data"]
        self.assertEqual(data["scale"]["sf1_sf2"], [0.25, 12.0])
        self.assertAlmostEqual(data["scale"]["error_pct"], 0.0)

    def test_invalid_scale_requests(self):
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.propose_scale(
                "p1", [0, 0], [0.5, 0], real_in=10.0
            ),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.propose_scale("p1", [0, 0], [100, 0]),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.propose_scale(
                "p1", [0, 0], [100, 0], preset="1:0"
            ),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.propose_scale(
                "p1", [0, 0], [100, 0], real_in=-5.0
            ),
        )
        self.assert_error(
            "not_found",
            lambda: self.service_m1b.propose_scale(
                "nope", [0, 0], [100, 0], real_in=5.0
            ),
        )

    def test_degenerate_or_overflowing_scales_are_invalid_arguments(self):
        propose = self.service_m1b.propose_scale
        for label, call in (
            ("tiny real_in", lambda: propose("p1", [0, 0], [500, 0], real_in=1e-9)),
            ("huge real_in", lambda: propose("p1", [0, 0], [1, 0], real_in=1e308)),
            (
                "integer overflow",
                lambda: propose("p1", [0, 0], [100, 0], real_in=10**400),
            ),
            (
                "infinite distance",
                lambda: propose("p1", [1e308, 0], [-1e308, 0], real_in=1.0),
            ),
            (
                "infinite preset ratio",
                lambda: propose("p1", [0, 0], [100, 0], preset="1e-320:1e308"),
            ),
        ):
            with self.subTest(label):
                self.assert_error("invalid_argument", call)


class FindRegionTests(ProposalTestCase):
    def test_regions_come_back_in_ost_inches_with_ids_and_gaps(self):
        self.pdf.segments = [
            _raw(100, 100, 460, 100),
            _raw(460, 100, 460, 370),
            _raw(460, 370, 100, 370),
            _raw(100, 370, 100, 104.5),
        ]
        result = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 500, 400], gap_close_in=6.0
        )
        (region,) = result["data"]["regions"]
        self.assertTrue(region["id"].startswith("r"))
        self.assertEqual(region["method"], "vector")
        self.assertAlmostEqual(region["area_sf"], 360 * 270 * K * K / 144.0, places=2)
        (gap,) = region["gaps"]
        self.assertAlmostEqual(gap["length_in"], 4.5 * K)
        self.assertTrue(region["leak_risk"])
        xs = region["polygon_ost"][0::2]
        self.assertAlmostEqual(min(xs), 100 * K)

    def test_a_seed_selects_the_containing_region_and_raster_runs_only_as_fallback(
        self,
    ):
        self.pdf.segments = _rect(100, 100, 460, 370) + [_raw(280, 100, 280, 370)]
        result = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 500, 400], seed_pts=[150, 200]
        )
        (region,) = result["data"]["regions"]
        self.assertAlmostEqual(region["area_sf"], 180 * 270 * K * K / 144.0, places=2)
        self.assertEqual(self.raster_calls, [])
        self.raster_result = RasterResult(
            ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)), False
        )
        fallback = self.service_m1b.find_regions(
            self.snapshot(), [0, 0, 600, 700], seed_pts=[30, 600]
        )
        (region,) = fallback["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        self.assertEqual(len(self.raster_calls), 1)

    def test_scale_must_be_set_and_boxes_are_required(self):
        self.project.pages[1] = replace(self.project.pages[1], scale_factor1=0.0)
        self.assert_error(
            "scale_unset",
            lambda: self.service_m1b.find_regions(self.snapshot(), [0, 0, 10, 10]),
        )


class ElementProposalTests(ProposalTestCase):
    SQUARE = [0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0]

    def test_a_complete_slab_needs_no_assumptions(self):
        data = self.service_m1b.propose_element(
            "slab",
            "p1",
            polygon_ost=self.SQUARE,
            thickness_in=8.0,
            top_elev_in=1200.0,
            summary="F1 slab",
        )["data"]
        self.assertEqual(data["status"], "proposed")
        self.assertEqual(data["assumptions"], [])
        (condition,) = data["conditions"]
        self.assertEqual(condition["name"]["value"], "Slab 8in @T 100' - 0\"")
        self.assertTrue(condition["name"]["untrusted"])
        (delta,) = data["quantity_delta"]
        self.assertAlmostEqual(delta["area_sf"], 1200.0)
        self.assertAlmostEqual(delta["volume_cy"], 1200 * 8 / 12 / 27, places=4)
        self.assertEqual(data["summary"]["value"], "F1 slab")

    def test_missing_thickness_and_elevation_become_high_impact_assumptions(self):
        data = self.service_m1b.propose_element("slab", "p1", polygon_ost=self.SQUARE)[
            "data"
        ]
        subjects = {
            (a["subject"], a["impact"], a["status"]) for a in data["assumptions"]
        }
        self.assertEqual(
            subjects,
            {
                ("thickness", IMPACT_HIGH, "open"),
                ("top_elevation", IMPACT_HIGH, "open"),
            },
        )
        self.assertEqual(len(data["blocking_assumption_ids"]), 2)
        self.assertIsNone(data["quantity_delta"][0]["volume_cy"])

    def test_region_gaps_become_closing_segment_assumptions(self):
        self.pdf.segments = [
            _raw(100, 100, 460, 100),
            _raw(460, 100, 460, 370),
            _raw(460, 370, 100, 370),
            _raw(100, 370, 100, 120),
        ]
        region = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 500, 400], gap_close_in=20.0
        )["data"]["regions"][0]
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        (closing,) = data["assumptions"]
        self.assertEqual(closing["subject"], "closing_segment")
        self.assertEqual(closing["impact"], IMPACT_HIGH)
        self.assertIn("13.33", closing["value"]["value"])

    def test_invalid_elements(self):
        call = self.service_m1b.propose_element
        self.assert_error(
            "invalid_argument",
            lambda: call("wall", "p1", polygon_ost=self.SQUARE, thickness_in=8),
        )
        self.assert_error(
            "invalid_argument", lambda: call("slab", "p1", thickness_in=8)
        )
        self.assert_error(
            "invalid_argument",
            lambda: call("slab", "p1", polygon_ost=self.SQUARE, region_id="r1"),
        )
        self.assert_error(
            "not_found", lambda: call("slab", "p1", region_id="r404", thickness_in=8)
        )
        self.assert_error(
            "invalid_geometry",
            lambda: call("slab", "p1", polygon_ost=[0, 0, 1, 1, 2, 2], thickness_in=8),
        )
        self.assert_error(
            "invalid_argument",
            lambda: call("slab", "p1", polygon_ost=self.SQUARE, thickness_in=-1),
        )
        self.assert_error(
            "invalid_argument",
            lambda: call(
                "slab", "p1", polygon_ost=self.SQUARE, thickness_in=8, level_id="L9"
            ),
        )
        self.assert_error(
            "changeset_too_large",
            lambda: call(
                "slab",
                "p1",
                polygon_ost=[float(v) for v in range(4002)] + [0.0, 0.0],
                thickness_in=8,
            ),
        )
        call("slab", "p1", polygon_ost=self.SQUARE, thickness_in=8, level_id="L1")

    def test_malformed_argument_types_are_invalid_arguments(self):
        call = self.service_m1b.propose_element
        for label, arguments in (
            ("holes_ost not a list", {"holes_ost": 5}),
            ("level_id not text", {"level_id": [1]}),
            ("integer overflow", {"thickness_in": 10**400}),
        ):
            with self.subTest(label):
                self.assert_error(
                    "invalid_argument",
                    lambda: call(
                        "slab",
                        "p1",
                        polygon_ost=self.SQUARE,
                        **{"thickness_in": 8, **arguments},
                    ),
                )

    def test_an_area_too_large_to_compute_is_invalid_geometry(self):
        self.assert_error(
            "invalid_geometry",
            lambda: self.service_m1b.propose_element(
                "slab",
                "p1",
                polygon_ost=[0, 0, 1e200, 0, 1e200, 1e200, 0, 1e200],
                thickness_in=8,
            ),
        )

    def test_a_long_untrusted_name_is_cleaned(self):
        data = self.service_m1b.propose_element(
            "slab",
            "p1",
            polygon_ost=self.SQUARE,
            thickness_in=8,
            top_elev_in=0,
            name="Slab\n\u202e<b>x</b> @T 1'" + "y" * 300,
        )["data"]
        name = data["conditions"][0]["name"]["value"]
        self.assertNotIn("\n", name)
        self.assertEqual(name.count("@T"), 1)


class ChangesetLifecycleTests(ProposalTestCase):
    SQUARE = [0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0]

    def test_update_assumption_adds_and_revises_but_never_accepts(self):
        uid = self.service_m1b.propose_element("slab", "p1", polygon_ost=self.SQUARE)[
            "data"
        ]["changeset_id"]
        added = self.service_m1b.update_assumption(
            uid,
            "add",
            subject="other",
            target_key="c1",
            value="flat",
            reason="ramp not shown",
            sheet_ref="S-102",
        )["data"]
        self.assertEqual([a["status"] for a in added["assumptions"]], ["open"] * 3)
        self.store.accept_assumption(uid, "a1")
        revised = self.service_m1b.update_assumption(
            uid, "revise", assumption_id="a1", value="9", reason="S-101 note"
        )["data"]
        first = revised["assumptions"][0]
        self.assertEqual((first["value"]["value"], first["status"]), ("9", "open"))
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid, "accept", assumption_id="a1"
            ),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid,
                "add",
                subject="status",
                target_key="c1",
                value="accepted",
                reason="x",
            ),
        )
        self.assertNotEqual(
            self.store.get(uid).assumptions[0].status, ASSUMPTION_ACCEPTED
        )

    def test_the_scale_assumption_can_only_change_through_a_new_proposal(self):
        uid = self.service_m1b.propose_scale(
            "p1", [100, 100], [460, 100], real_in=479.0
        )["data"]["changeset_id"]
        before = self.store.get(uid)
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid, "revise", assumption_id="a1", value="1:999", reason="x"
            ),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid,
                "add",
                subject="scale",
                target_key="p1",
                value="1:999",
                reason="x",
            ),
        )
        self.assertEqual(self.store.get(uid), before)

    def test_apply_only_asks_for_approval_and_discard_closes(self):
        uid = self.service_m1b.propose_element(
            "slab", "p1", polygon_ost=self.SQUARE, thickness_in=8.0, top_elev_in=0.0
        )["data"]["changeset_id"]
        applied = self.service_m1b.apply_changeset(uid)
        self.assertEqual(applied["status"], STATUS_PENDING_APPROVAL)
        self.assertEqual(applied["data"]["status"], STATUS_PENDING_APPROVAL)
        self.assertIn("approve", applied["data"]["message"].lower())
        discarded = self.service_m1b.discard_changeset(uid)["data"]
        self.assertEqual(discarded["status"], "discarded")
        self.assert_error(
            "invalid_state", lambda: self.service_m1b.apply_changeset(uid)
        )
        self.assert_error("not_found", lambda: self.service_m1b.apply_changeset("nope"))

    def test_impacts_reported_for_normal_assumptions(self):
        uid = self.service_m1b.propose_element(
            "slab", "p1", polygon_ost=self.SQUARE, thickness_in=8, top_elev_in=0
        )["data"]["changeset_id"]
        data = self.service_m1b.update_assumption(
            uid, "add", subject="other", target_key="c1", value="x", reason="y"
        )["data"]
        self.assertEqual(data["assumptions"][0]["impact"], IMPACT_NORMAL)
        self.assertEqual(data["blocking_assumption_ids"], [])


class RegionScaleTests(ProposalTestCase):
    def test_a_region_found_at_another_scale_is_refused(self):
        self.pdf.segments = _rect(100, 100, 460, 370)
        result = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 500, 400], seed_pts=[150, 200]
        )
        (region,) = result["data"]["regions"]
        page = self.project.pages[1]
        self.project.pages[1] = replace(page, scale_factor1=page.scale_factor1 / 2.0)
        self.assert_error(
            "not_found",
            lambda: self.service_m1b.propose_element(
                "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
            ),
        )
        self.project.pages[1] = page
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        self.assertAlmostEqual(
            data["quantity_delta"][0]["area_sf"], region["area_sf"], places=3
        )


class SqlApplyTests(ProposalTestCase):
    def test_sql_bids_keep_proposals_but_cannot_be_applied(self):
        location = SqlServerDatabaseLocation(
            server="srv", database="ost", database_guid="g-1"
        )
        self.descriptors["sql:srv/ost"] = DatabaseDescriptor.for_sql_server(
            location, schema_version=1
        )
        self.project.bid_ref = BidRef("sql:srv/ost", "{BID-1}")
        service = AiTakeoffProposalService(
            read_service=self.service,
            proposals=self.proposals,
            presets=PRESETS,
            raster_fill=self._raster,
            apply_blocked=lambda database_id: apply_blocked_reason(
                self.descriptors.get(database_id)
            ),
        )
        proposed = service.propose_element(
            "slab",
            "p1",
            polygon_ost=ElementProposalTests.SQUARE,
            thickness_in=8.0,
            top_elev_in=0.0,
        )["data"]
        error = self.assert_error(
            "sql_apply_unavailable",
            lambda: service.apply_changeset(proposed["changeset_id"]),
        )
        self.assertIn("SQL Server", error.message)
        self.assertEqual(
            self.proposals.get(proposed["changeset_id"]).status, "proposed"
        )
        self.assertTrue(
            service.propose_scale("p1", [0, 0], [72, 0], real_in=96.0)["success"]
        )
        self.project.bid_ref = BidRef(ACCESS_PATH, "{BID-1}")
        access = service.propose_element(
            "slab",
            "p1",
            polygon_ost=ElementProposalTests.SQUARE,
            thickness_in=8.0,
            top_elev_in=0.0,
        )["data"]
        self.assertEqual(
            service.apply_changeset(access["changeset_id"])["status"],
            "pending_approval",
        )

    def test_a_database_that_cannot_be_resolved_is_never_applied(self):
        def failing_lookup(_database_id):
            raise LookupError("registry unavailable")

        for label, resolve in (
            ("unregistered", {}.get),
            ("missing descriptor", lambda _database_id: None),
            ("lookup raises", failing_lookup),
        ):
            with self.subTest(label):
                service = AiTakeoffProposalService(
                    read_service=self.service,
                    proposals=self.proposals,
                    presets=PRESETS,
                    raster_fill=self._raster,
                    apply_blocked=lambda database_id, resolve=resolve: apply_block_for(
                        resolve, database_id
                    ),
                )
                scale = service.propose_scale("p1", [0, 0], [72, 0], real_in=96.0)
                self.assertTrue(scale["success"])
                element = service.propose_element(
                    "slab",
                    "p1",
                    polygon_ost=ElementProposalTests.SQUARE,
                    thickness_in=8.0,
                    top_elev_in=0.0,
                )
                for proposed in (scale["data"], element["data"]):
                    error = self.assert_error(
                        "sql_apply_unavailable",
                        lambda: service.apply_changeset(proposed["changeset_id"]),
                    )
                    self.assertEqual(error.message, DATABASE_UNRESOLVED_MESSAGE)
                    self.assertEqual(
                        self.proposals.get(proposed["changeset_id"]).status, "proposed"
                    )
                    self.proposals.discard(proposed["changeset_id"])


def _grid(cells_x, cells_y, origin=100.0, size=20.0):
    right = origin + cells_x * size
    bottom = origin + cells_y * size
    segments = []
    for column in range(cells_x + 1):
        x = origin + column * size
        segments.append(_raw(x, origin, x, bottom))
    for row in range(cells_y + 1):
        y = origin + row * size
        segments.append(_raw(origin, y, right, y))
    return segments


SQUARE = [0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0]


class ScaleArgumentTests(ProposalTestCase):
    def propose(self, *args, **kwargs):
        return self.service_m1b.propose_scale(*args, **kwargs)["data"]

    def error_message(self, code, call):
        return self.assert_error(code, call).message

    def test_points_must_be_lists_of_two_finite_numbers(self):
        cases = (
            ((0, 0), [100, 0], "p1_pts needs 2 numbers"),
            ([0, 0, 0], [100, 0], "p1_pts needs 2 numbers"),
            ([0, 0], [100], "p2_pts needs 2 numbers"),
            ([0, True], [100, 0], "p1_pts must be a number"),
            (["0", 0], [100, 0], "p1_pts must be a number"),
            ([0, 0], [float("inf"), 0], "p2_pts must be finite"),
            ([0, float("nan")], [100, 0], "p1_pts must be finite"),
        )
        for first, second, message in cases:
            with self.subTest(first=first, second=second):
                self.assertEqual(
                    self.error_message(
                        "invalid_argument",
                        lambda: self.propose("p1", first, second, real_in=10.0),
                    ),
                    message,
                )

    def test_the_minimum_distance_is_one_point_inclusive(self):
        for second in ([1, 0], [1.5, 0]):
            with self.subTest(second=second):
                data = self.propose("p1", [0, 0], second, preset="1:12")
                self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 12.0])
        self.assert_error(
            "invalid_argument",
            lambda: self.propose("p1", [0, 0], [0.999, 0], preset="1:12"),
        )

    def test_real_in_must_be_positive(self):
        for real in (0, 0.0, -1.0):
            with self.subTest(real=real):
                self.assertEqual(
                    self.error_message(
                        "invalid_argument",
                        lambda: self.propose("p1", [0, 0], [100, 0], real_in=real),
                    ),
                    "real_in must be positive",
                )
        data = self.propose("p1", [0, 0], [1, 0], real_in=0.5)
        self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 36.0])

    def test_a_real_distance_that_underflows_is_out_of_range(self):
        self.assertEqual(
            self.error_message(
                "invalid_argument",
                lambda: self.propose("p1", [0, 0], [2, 0], real_in=5e-324),
            ),
            "real_in gives a scale out of range",
        )

    def test_a_preset_alone_has_no_error_estimate(self):
        data = self.propose("p1", [0, 0], [100, 0], preset='1/4" = 1\' 0"')
        self.assertEqual(data["scale"]["sf1_sf2"], [0.25, 12.0])
        self.assertIsNone(data["scale"]["error_pct"])

    def test_custom_presets_parse_sf1_then_sf2(self):
        for preset, expected in (
            ("1:48", [1.0, 48.0]),
            ("2:48", [2.0, 48.0]),
            (" 0.5:12 ", [0.5, 12.0]),
            ("1:0.5", [1.0, 0.5]),
        ):
            with self.subTest(preset=preset):
                data = self.propose("p1", [0, 0], [100, 0], preset=preset)
                self.assertEqual(data["scale"]["sf1_sf2"], expected)
                self.assertEqual(
                    data["summary"]["value"],
                    f"Page scale {expected[0]:g} : {expected[1]:g}",
                )

    def test_invalid_presets_are_refused(self):
        for preset in (
            "abc",
            "a:b",
            "1:2:3",
            "0:48",
            "-1:-48",
            "1:0",
            "1:inf",
            "inf:1",
            "nan:1",
        ):
            with self.subTest(preset=preset):
                self.assertEqual(
                    self.error_message(
                        "invalid_argument",
                        lambda: self.propose("p1", [0, 0], [100, 0], preset=preset),
                    ),
                    "Unknown preset; use a listed scale or sf1:sf2",
                )
        for preset in ("", "   ", 5):
            with self.subTest(preset=preset):
                self.assertEqual(
                    self.error_message(
                        "invalid_argument",
                        lambda: self.propose("p1", [0, 0], [100, 0], preset=preset),
                    ),
                    "preset must be text",
                )

    def test_a_scale_that_underflows_to_zero_is_out_of_range(self):
        self.assertEqual(
            self.error_message(
                "invalid_argument",
                lambda: self.propose("p1", [0, 0], [100, 0], preset="1e10:5e-324"),
            ),
            "The proposed scale is out of range",
        )

    def service_with(self, presets):
        return AiTakeoffProposalService(
            read_service=self.service,
            proposals=self.proposals,
            presets=presets,
            raster_fill=self._raster,
        )

    def test_presets_within_one_percent_inclusive_are_matched(self):
        exact = self.service_with([(1.0, 7272.0, "101")])
        data = exact.propose_scale("p1", [0, 0], [1, 0], real_in=100.0)["data"]
        self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 7272.0])
        self.assertEqual(data["scale"]["error_pct"], 1.0)
        outside = self.service_with([(1.0, 7308.0, "101.5")])
        data = outside.propose_scale("p1", [0, 0], [1, 0], real_in=100.0)["data"]
        self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 7200.0])

    def test_custom_scales_are_rounded_to_six_decimals(self):
        data = self.propose("p1", [0, 0], [7, 0], real_in=10.0)
        self.assertEqual(data["scale"]["sf1_sf2"], [1.0, 102.857143])

    def test_the_previous_scale_and_open_bid_are_recorded(self):
        data = self.propose("p1", [0, 0], [100, 0], preset="1:12")
        self.assertEqual(data["scale"]["previous_sf1_sf2"], [0.25, 12.0])
        stored = self.store.get(data["changeset_id"])
        self.assertEqual((stored.database_id, stored.bid_uid), (ACCESS_PATH, "{BID-1}"))
        self.project.pages.append(
            Page(uid="p5", name="Unscaled", sequence=5, image_path="C:/plans/u.pdf")
        )
        self.project.pages[-1] = replace(
            self.project.pages[-1], scale_factor1=None, scale_factor2=None
        )
        data = self.propose("p5", [0, 0], [100, 0], preset="1:12")
        self.assertEqual(data["scale"]["previous_sf1_sf2"], [0.0, 0.0])

    def test_the_reason_and_sheet_reference_are_kept(self):
        data = self.propose(
            "p1", [0, 0], [100, 0], preset="1:12", reason="per S-101", sheet_ref="S-101"
        )
        (assumption,) = data["assumptions"]
        self.assertEqual(assumption["reason"]["value"], "per S-101")
        self.assertEqual(assumption["sheet_ref"]["value"], "S-101")
        self.assertEqual(assumption["value"]["value"], "1:12")
        default = self.propose("p1", [0, 0], [100, 0], preset="1:12")["assumptions"][0]
        self.assertEqual(
            default["reason"]["value"],
            "Scale proposed by the AI from a measured distance.",
        )
        self.assertEqual(default["sheet_ref"]["value"], "")

    def test_raster_results_are_immutable(self):
        result = RasterResult(((0.0, 0.0),), False)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.leak = True


class RegionLimitTests(ProposalTestCase):
    def find(self, **kwargs):
        return self.service_m1b.find_regions(
            self.snapshot(), kwargs.pop("bbox", [0, 0, 600, 700]), **kwargs
        )

    def test_limits_match_the_plan(self):
        self.assertEqual(
            (MAX_GAP_CLOSE_IN, MAX_REGIONS_RETURNED, MAX_CACHED_REGIONS),
            (48.0, 50, 200),
        )

    def test_region_ids_count_up_from_one(self):
        self.pdf.segments = _rect(100, 100, 460, 370)
        first = self.find()["data"]["regions"][0]["id"]
        second = self.find()["data"]["regions"][0]["id"]
        self.assertEqual((first, second), ("r1", "r2"))

    def test_at_most_fifty_regions_are_returned_without_a_seed(self):
        self.pdf.segments = _grid(7, 7)
        exact = self.find()["data"]
        self.assertEqual(len(exact["regions"]), MAX_REGIONS_RETURNED)
        self.assertFalse(exact["truncated"])
        self.pdf.segments = _grid(8, 8)
        many = self.find()["data"]
        self.assertEqual(len(many["regions"]), MAX_REGIONS_RETURNED)
        self.assertTrue(many["truncated"])
        seeded = self.find(seed_pts=[110, 110])["data"]
        self.assertEqual(len(seeded["regions"]), 1)
        self.assertFalse(seeded["truncated"])
        self.pdf.segments = _rect(100, 100, 460, 370)
        single = self.find()
        self.assertEqual(single["status"], "ok")
        self.assertFalse(single["data"]["truncated"])

    def test_the_region_cache_keeps_the_newest_two_hundred(self):
        self.pdf.segments = _rect(100, 100, 460, 370)
        ids = [
            self.find()["data"]["regions"][0]["id"] for _ in range(MAX_CACHED_REGIONS)
        ]
        self.assertEqual(ids[-1], "r200")

        def propose(region_id):
            return self.service_m1b.propose_element(
                "slab", "p1", region_id=region_id, thickness_in=8.0, top_elev_in=0.0
            )

        self.assertTrue(propose("r1")["success"])
        self.assertEqual(self.find()["data"]["regions"][0]["id"], "r201")
        self.assert_error("not_found", lambda: propose("r1"))
        for region_id in ("r2", "r201"):
            self.proposals.discard(propose(region_id)["data"]["changeset_id"])

    def test_gap_close_bounds_are_inclusive(self):
        self.pdf.segments = _rect(100, 100, 460, 370)
        for gap in (0, 0.0, None, 48, 48.0):
            with self.subTest(gap=gap):
                self.assertEqual(self.find(gap_close_in=gap)["status"], "ok")
        for gap in (-0.001, 48.0001, 48.5, 49, float("nan"), True, "6"):
            with self.subTest(gap=gap):
                self.assert_error(
                    "invalid_argument", lambda: self.find(gap_close_in=gap)
                )

    def test_small_gaps_stay_open_unless_asked_to_close(self):
        self.pdf.segments = [
            _raw(100, 100, 460, 100),
            _raw(460, 100, 460, 370),
            _raw(460, 370, 100, 370),
            _raw(100, 370, 100, 101),
        ]
        for kwargs in ({}, {"gap_close_in": None}, {"gap_close_in": 0.0}):
            with self.subTest(kwargs=kwargs):
                result = self.find(**kwargs)
                self.assertEqual(result["status"], "empty")
                self.assertEqual(result["data"]["regions"], [])
        self.assertEqual(len(self.find(gap_close_in=1.0)["data"]["regions"]), 1)

    def test_boxes_need_positive_width_and_height(self):
        self.pdf.segments = _rect(100, 100, 460, 370)
        for box in (
            [10, 0, 10, 10],
            [0, 10, 10, 10],
            [10, 0, 5, 10],
            [0, 10, 10, 5],
            [0, 0, 10],
        ):
            with self.subTest(box=box):
                self.assert_error("invalid_argument", lambda: self.find(bbox=box))

    def test_a_zero_or_negative_scale_is_unset(self):
        for k in (0.0, -1.0, None):
            with self.subTest(k=k):
                snapshot = PageSnapshot(
                    "p1", "C:/plans/S-101.pdf", 0, 612.0, 792.0, k, True
                )
                self.assert_error(
                    "scale_unset",
                    lambda: self.service_m1b.find_regions(snapshot, [0, 0, 10, 10]),
                )

    def test_unreadable_pages_report_their_status(self):
        self.pdf.info = PdfPageInfoDto(status="missing")
        result = self.find()
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["data"], {"page_uid": "p1", "regions": []})

    def test_too_many_segments_are_refused(self):
        self.pdf.segments = [
            _raw(10, 10 + i * 0.1, 20, 10 + i * 0.1) for i in range(4001)
        ]
        self.assert_error("invalid_argument", self.find)

    def test_region_areas_and_holes_are_in_ost_units(self):
        self.pdf.segments = _rect(100, 100, 461, 370) + _rect(200, 200, 260, 260)
        regions = self.find()["data"]["regions"]
        outer = regions[0]
        self.assertEqual(
            outer["area_sf"], round((361 * 270 - 60 * 60) * K * K / 144.0, 4)
        )
        self.assertEqual(outer["area_sf"], 289.7222)
        (hole,) = outer["holes_ost"]
        self.assertEqual(
            sorted(set(round(value, 6) for value in hole)),
            sorted({round(200 * K, 6), round(260 * K, 6)}),
        )
        self.pdf.segments = _rect(100, 100, 461, 370)
        self.assertEqual(self.find()["data"]["regions"][0]["area_sf"], 300.8333)


class RasterRegionTests(ProposalTestCase):
    RING = ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0))

    def find(self, gap_close_in=0.0):
        return self.service_m1b.find_regions(
            self.snapshot(),
            [0, 0, 600, 700],
            gap_close_in=gap_close_in,
            seed_pts=[15, 15],
        )

    def test_raster_regions_scale_to_ost_inches(self):
        self.raster_result = RasterResult(self.RING, False)
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(
            region["polygon_ost"], [value * K for point in self.RING for value in point]
        )
        self.assertEqual(region["area_sf"], 0.3086)
        self.assertEqual((region["holes_ost"], region["gaps"]), ([], []))
        self.assertFalse(region["leak_risk"])

    def test_the_raster_pen_covers_the_closing_gap(self):
        self.raster_result = RasterResult(self.RING, False)
        self.find()
        self.find(gap_close_in=6.0)
        self.assertEqual([call[2] for call in self.raster_calls], [1.0, 6.0 / K])
        self.assertEqual(
            self.raster_calls[0][:2], ((0.0, 0.0, 600.0, 700.0), (15.0, 15.0))
        )

    def test_no_raster_fill_means_no_region(self):
        result = self.find()
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["data"]["regions"], [])
        self.assertEqual(len(self.raster_calls), 1)

    def test_a_leaking_raster_region_cannot_be_proposed(self):
        self.raster_result = RasterResult(self.RING, True)
        (region,) = self.find()["data"]["regions"]
        self.assertTrue(region["leak_risk"])
        self.assert_error(
            "invalid_geometry",
            lambda: self.service_m1b.propose_element(
                "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
            ),
        )


class ElementArgumentTests(ProposalTestCase):
    def propose(self, **kwargs):
        arguments = {"polygon_ost": SQUARE, "thickness_in": 8.0, "top_elev_in": 0.0}
        arguments.update(kwargs)
        return self.service_m1b.propose_element("slab", "p1", **arguments)

    def test_thickness_bounds(self):
        for thickness in (0.5, 120, 120.0):
            with self.subTest(thickness=thickness):
                data = self.propose(thickness_in=thickness)["data"]
                self.assertEqual(
                    data["conditions"][0]["thickness_in"], float(thickness)
                )
                self.proposals.discard(data["changeset_id"])
        for thickness in (0, 0.0, -0.5, 120.0001, float("nan"), True, "8"):
            with self.subTest(thickness=thickness):
                self.assert_error(
                    "invalid_argument", lambda: self.propose(thickness_in=thickness)
                )

    def test_top_elevation_bounds(self):
        for top in (100000.0, -100000, 0):
            with self.subTest(top=top):
                data = self.propose(top_elev_in=top)["data"]
                self.assertEqual(data["conditions"][0]["top_elev_in"], float(top))
                self.proposals.discard(data["changeset_id"])
        for top in (100000.5, -100001.0, float("nan"), float("inf"), False):
            with self.subTest(top=top):
                self.assert_error(
                    "invalid_argument", lambda: self.propose(top_elev_in=top)
                )

    def test_polygons_must_be_lists_of_numbers(self):
        for polygon, message in (
            ("0,0,1,1", "polygon_ost needs a list of numbers"),
            (tuple(SQUARE), "polygon_ost needs a list of numbers"),
            ([0, 0, "1", 0, 1, 1], "polygon_ost must be a number"),
        ):
            with self.subTest(polygon=polygon):
                error = self.assert_error(
                    "invalid_argument", lambda: self.propose(polygon_ost=polygon)
                )
                self.assertEqual(error.message, message)

    def test_unscaled_pages_cannot_take_elements(self):
        self.project.pages[1] = replace(self.project.pages[1], scale_factor2=0.0)
        self.assert_error("scale_unset", self.propose)
        self.assertEqual(self.store.open_for_bid(ACCESS_PATH, "{BID-1}"), ())

    def test_an_existing_condition_needs_no_new_condition_or_assumptions(self):
        data = self.propose(condition_uid="C9", thickness_in=None, top_elev_in=None)[
            "data"
        ]
        self.assertEqual(data["conditions"], [])
        self.assertEqual(data["assumptions"], [])
        self.assertEqual(data["takeoffs"][0]["condition_key"], "existing:C9")
        self.assertEqual(data["summary"]["value"], "Slab on page p1")

    def test_quantity_deltas_are_rounded_to_four_decimals(self):
        data = self.propose(
            polygon_ost=[0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0]
        )
        (delta,) = data["data"]["quantity_delta"]
        self.assertEqual((delta["area_sf"], delta["volume_cy"]), (69.4444, 1.7147))

    def test_changesets_record_the_open_bid(self):
        uid = self.propose()["data"]["changeset_id"]
        stored = self.store.get(uid)
        self.assertEqual((stored.database_id, stored.bid_uid), (ACCESS_PATH, "{BID-1}"))


class ChangesetToolArgumentTests(ProposalTestCase):
    def proposed(self):
        return self.service_m1b.propose_element("slab", "p1", polygon_ost=SQUARE)[
            "data"
        ]["changeset_id"]

    def test_changeset_ids_are_required_text(self):
        service = self.service_m1b
        calls = {
            "update": lambda uid: service.update_assumption(
                uid, "add", subject="other", target_key="c1"
            ),
            "apply": service.apply_changeset,
            "discard": service.discard_changeset,
        }
        for name, call in calls.items():
            for uid in ("", "   ", None, 5):
                with self.subTest(call=name, uid=uid):
                    self.assert_error("invalid_argument", lambda: call(uid))

    def test_unknown_changesets_are_not_found(self):
        service = self.service_m1b
        for call in (
            lambda: service.update_assumption(
                "nope", "add", subject="other", target_key="c1"
            ),
            lambda: service.update_assumption("nope", "revise", assumption_id="a1"),
            lambda: service.discard_changeset("nope"),
        ):
            self.assert_error("not_found", call)

    def test_added_assumptions_default_to_empty_text(self):
        uid = self.proposed()
        data = self.service_m1b.update_assumption(
            uid, "add", subject="other", target_key="c1"
        )["data"]
        added = data["assumptions"][-1]
        self.assertEqual(
            (
                added["value"]["value"],
                added["reason"]["value"],
                added["sheet_ref"]["value"],
            ),
            ("", "", ""),
        )

    def test_target_and_assumption_ids_are_required(self):
        uid = self.proposed()
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid, "add", subject="other", target_key="  "
            ),
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(uid, "revise", assumption_id=""),
        )
        self.assertEqual(len(self.store.get(uid).assumptions), 2)

    def test_closing_segment_assumptions_use_the_given_length(self):
        uid = self.proposed()
        long_gap = self.service_m1b.update_assumption(
            uid, "add", subject="closing_segment", target_key="c1", length_in=20
        )["data"]["assumptions"][-1]
        short_gap = self.service_m1b.update_assumption(
            uid, "add", subject="closing_segment", target_key="c1", length_in=6.0
        )["data"]["assumptions"][-1]
        self.assertEqual(
            (long_gap["impact"], short_gap["impact"]), (IMPACT_HIGH, IMPACT_NORMAL)
        )
        self.assert_error(
            "invalid_argument",
            lambda: self.service_m1b.update_assumption(
                uid, "add", subject="closing_segment", target_key="c1", length_in="20"
            ),
        )

    def test_reported_statuses_are_returned_without_a_new_request(self):
        uid = self.service_m1b.propose_element(
            "slab", "p1", polygon_ost=SQUARE, thickness_in=8.0, top_elev_in=0.0
        )["data"]["changeset_id"]
        self.service_m1b.apply_changeset(uid)
        self.store.approve(uid)
        applying = self.service_m1b.apply_changeset(uid)
        self.assertEqual(
            (applying["status"], applying["data"]["status"]), ("applying", "applying")
        )
        self.assertNotIn("message", applying["data"])
        self.assertNotIn("applied", applying["data"])
        record = AppliedChangeset(
            folder_uid="F1",
            created_folder=True,
            condition_uids=("C1",),
            takeoff_uids=("T1",),
        )
        self.store.mark_applied(uid, record)
        applied = self.service_m1b.apply_changeset(uid)
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(
            applied["data"]["applied"],
            {"takeoff_uids": ["T1"], "condition_uids": ["C1"], "folder_uid": "F1"},
        )
        rejected = self.service_m1b.propose_element(
            "slab", "p1", polygon_ost=SQUARE, thickness_in=8.0, top_elev_in=0.0
        )["data"]["changeset_id"]
        self.service_m1b.apply_changeset(rejected)
        self.store.reject(rejected)
        self.assertEqual(
            self.service_m1b.apply_changeset(rejected)["status"], "rejected"
        )


if __name__ == "__main__":
    unittest.main()
