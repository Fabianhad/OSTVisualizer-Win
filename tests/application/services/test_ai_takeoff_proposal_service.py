import dataclasses
import math
import unittest
from dataclasses import replace
from unittest import mock
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AiTakeoffRequestError,
    PageSnapshot,
)
from ost_visualizer.application.dtos.pdf_metadata_dtos import (
    PdfPageInfoDto,
    PdfPathStyleDto,
    PdfTextRunDto,
    PdfVectorSegmentDto,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services import ai_takeoff_proposal_service as module
from ost_visualizer.application.services.ai_takeoff_proposal_service import (
    DASHED_MATCH_SHARE,
    LEAK_GAP_MAX_IN,
    MAX_CACHED_REGIONS,
    MAX_GAP_CLOSE_IN,
    MAX_REGIONS_RETURNED,
    AiTakeoffProposalService,
    RasterResult,
    _RegionRecord,
    _sealed_openings,
)
from ost_visualizer.domain.entities.ai_changeset import (
    ERROR_ASSUMPTION_UNRESOLVED,
    STATUS_APPLYING,
    ChangesetError,
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
from ost_visualizer.domain.services.ai_planar_regions import RegionTooComplex
from tests.application.services.test_ai_takeoff_read_service import (
    ACCESS_PATH,
    ServiceTestCase,
)
from tests.helpers import ai_mat_outline as mat

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

    def dimension_text(self, text, x=300.0, y=90.0):
        self.pdf.runs = [
            PdfTextRunDto(
                text,
                left=x,
                top=PAGE_HEIGHT - y,
                right=x + 30,
                bottom=PAGE_HEIGHT - y - 8,
            )
        ]

    def test_a_preset_is_checked_against_a_nearby_dimension(self):
        self.dimension_text("24'-0\"")
        data = self.service_m1b.propose_scale(
            "p1", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        check = data["scale"]["dimension_check"]
        self.assertEqual(
            (check["real_in"], check["error_pct"], check["agrees"]), (288.0, 0.0, True)
        )
        self.assertEqual(
            check["text"], {"value": "24'-0\"", "untrusted": True, "truncated": False}
        )
        self.assertNotIn("dimension", data["assumptions"][0]["reason"]["value"])

    def test_a_disagreeing_dimension_is_reported_in_the_assumption(self):
        self.dimension_text("30'-0\"")
        data = self.service_m1b.propose_scale(
            "p1", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        check = data["scale"]["dimension_check"]
        self.assertFalse(check["agrees"])
        self.assertAlmostEqual(check["error_pct"], 20.0)
        self.assertIn("dimension", data["assumptions"][0]["reason"]["value"])
        self.assertEqual(data["assumptions"][0]["impact"], IMPACT_HIGH)

    def test_the_nearest_dimension_is_used(self):
        self.pdf.runs = [
            PdfTextRunDto(
                "30'-0\"",
                left=300,
                top=PAGE_HEIGHT - 130,
                right=330,
                bottom=PAGE_HEIGHT - 138,
            ),
            PdfTextRunDto(
                "24'-0\"",
                left=300,
                top=PAGE_HEIGHT - 90,
                right=330,
                bottom=PAGE_HEIGHT - 98,
            ),
        ]
        data = self.service_m1b.propose_scale(
            "p1", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        self.assertEqual(data["scale"]["dimension_check"]["real_in"], 288.0)

    def test_other_text_and_raster_pages_give_no_dimension_check(self):
        self.pdf.runs = [
            PdfTextRunDto(
                "FOUNDATION PLAN",
                left=300,
                top=PAGE_HEIGHT - 90,
                right=400,
                bottom=PAGE_HEIGHT - 98,
            )
        ]
        data = self.service_m1b.propose_scale(
            "p1", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        self.assertIsNone(data["scale"]["dimension_check"])
        self.dimension_text("24'-0\"")
        raster = self.service_m1b.propose_scale(
            "p3", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        self.assertIsNone(raster["scale"]["dimension_check"])
        self.assertEqual(raster["scale"]["page_uid"], "p3")

    def test_dimensions_far_from_the_measured_points_are_ignored(self):
        self.dimension_text("24'-0\"", x=300.0, y=600.0)
        data = self.service_m1b.propose_scale(
            "p1", [100, 100], [532, 100], preset='1/4" = 1\' 0"'
        )["data"]
        self.assertIsNone(data["scale"]["dimension_check"])

    def test_the_scale_proposal_can_be_split_for_a_worker(self):
        self.dimension_text("24'-0\"")
        finish = self.service_m1b.plan_scale(
            "p1", [100, 100], [532, 100], real_in=288.0
        )
        self.assertEqual(self.proposals_count(), 0)
        data = finish()["data"]
        self.assertEqual(data["scale"]["dimension_check"]["agrees"], True)
        self.assertEqual(self.proposals_count(), 1)

    def proposals_count(self):
        return len(
            self.store.open_for_bid(
                self.project.bid_ref.file_path, self.project.bid_ref.bid_uid
            )
        )

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
        self.assertEqual(
            result["data"]["coordinate_space"],
            {
                "regions[].polygon_ost": "ost_inches",
                "regions[].holes_ost": "ost_inches",
                "regions[].gaps[].p1_pts": "page_pts_y_down",
                "regions[].gaps[].p2_pts": "page_pts_y_down",
                "suppressed_symbols_pts": "page_pts_y_down",
            },
        )
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
        self.assertEqual(result["data"]["regions"], [])
        self.assertEqual(
            sorted(result["data"]["coordinate_space"]),
            [
                "regions[].gaps[].p1_pts",
                "regions[].gaps[].p2_pts",
                "regions[].holes_ost",
                "regions[].polygon_ost",
                "suppressed_symbols_pts",
            ],
        )

    def test_too_many_segments_are_refused(self):
        self.pdf.segments = [
            _raw(10, 10 + i * 0.01, 20, 10 + i * 0.01) for i in range(20001)
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


WALL_STYLE = PdfPathStyleDto(2.0, (), 0x000000FF, 0, True, False)
THIN_STYLE = PdfPathStyleDto(0.25, (), 0x000000FF, 0, True, False)
RED_STYLE = PdfPathStyleDto(2.0, (), 0xFF0000FF, 0, True, False)
DASH_STYLE = PdfPathStyleDto(0.5, (6.0, 3.0), 0x000000FF, 0, True, False)
POCHE_STYLE = PdfPathStyleDto(0.0, (), 0, 0x404040FF, False, True)


def _styled(x1, y1, x2, y2, style=WALL_STYLE, group="", closed=False, curve=False):
    return PdfVectorSegmentDto(
        x1,
        PAGE_HEIGHT - y1,
        x2,
        PAGE_HEIGHT - y2,
        group=group,
        closed=closed,
        curve=curve,
        style=style,
    )


def _swing(hinge_x, hinge_y, radius, style=THIN_STYLE, pieces=12):
    points = [
        (
            hinge_x + radius * math.sin(math.radians(90.0 * i / pieces)),
            hinge_y - radius * math.cos(math.radians(90.0 * i / pieces)),
        )
        for i in range(pieces + 1)
    ]
    leaf = [_styled(hinge_x, hinge_y, hinge_x, hinge_y - radius, style=style)]
    return leaf + [
        _styled(*a, *b, style=style, group="77:0", curve=True)
        for a, b in zip(points, points[1:])
    ]


def _styled_rect(x1, y1, x2, y2, style=WALL_STYLE, group=""):
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return [
        _styled(*a, *b, style=style, group=group, closed=bool(group))
        for a, b in zip(corners, corners[1:] + corners[:1])
    ]


def _door_room(door_left=200.0, door_right=254.0):
    return [
        _styled(100, 100, 400, 100),
        _styled(400, 100, 400, 300),
        _styled(100, 300, 100, 100),
        _styled(100, 300, door_left, 300),
        _styled(door_right, 300, 400, 300),
        _styled(92, 92, 408, 92),
        _styled(408, 92, 408, 308),
        _styled(92, 308, 92, 92),
        _styled(92, 308, door_left, 308),
        _styled(door_right, 308, 408, 308),
        _styled(door_left, 300, door_left, 308),
        _styled(door_right, 300, door_right, 308),
    ]


class FindRegionFilterTests(ProposalTestCase):
    def find(self, **kwargs):
        return self.service_m1b.find_regions(
            self.snapshot(), kwargs.pop("bbox", [0, 0, 600, 700]), **kwargs
        )

    def three_rooms(self):
        return (
            _rect(100, 100, 200, 200)
            + _rect(300, 100, 500, 300)
            + _rect(100, 400, 150, 450)
        )

    def test_regions_are_sorted_by_area_with_a_total_and_a_cursor(self):
        self.pdf.segments = self.three_rooms()
        result = self.find()
        areas = [region["area_sf"] for region in result["data"]["regions"]]
        self.assertEqual(areas, sorted(areas, reverse=True))
        self.assertEqual(len(areas), 3)
        self.assertEqual(result["data"]["total_count"], 3)
        self.assertEqual(result["meta"]["total_count"], 3)
        self.assertIsNone(result["meta"]["next_cursor"])
        first = self.find(limit=2)
        self.assertEqual(first["status"], "truncated")
        self.assertTrue(first["data"]["truncated"])
        self.assertEqual(first["meta"]["next_cursor"], "c:2")
        self.assertEqual([r["area_sf"] for r in first["data"]["regions"]], areas[:2])
        rest = self.find(limit=2, cursor="c:2")
        self.assertEqual(rest["status"], "ok")
        self.assertFalse(rest["data"]["truncated"])
        self.assertEqual([r["area_sf"] for r in rest["data"]["regions"]], areas[2:])
        self.assertEqual(rest["data"]["total_count"], 3)

    def test_dashed_lines_are_left_out_unless_asked_for(self):
        self.pdf.segments = _styled_rect(100, 100, 300, 300) + [
            _styled(90, 200, 310, 200, style=DASH_STYLE)
        ]
        result = self.find()
        (region,) = result["data"]["regions"]
        self.assertAlmostEqual(region["area_sf"], 200 * 200 * K * K / 144.0, places=3)
        self.assertEqual(result["data"]["excluded"]["dashed"], 1)
        kept = self.find(exclude_dashed=False)["data"]
        self.assertEqual(len(kept["regions"]), 3)
        self.assertEqual(kept["excluded"]["dashed"], 0)

    def test_exploded_dashes_are_never_bridged_into_a_wall(self):
        dashes = [
            _styled(100 + i * 10, 200, 106 + i * 10, 200, style=THIN_STYLE)
            for i in range(9)
        ]
        dashes.append(_styled(190, 200, 200, 200, style=THIN_STYLE))
        self.pdf.segments = _styled_rect(100, 100, 200, 300) + dashes
        bridged = self.find(gap_close_in=3.0, exclude_dashed=False)["data"]
        self.assertEqual(len(bridged["regions"]), 3)
        self.assertGreaterEqual(
            sum(len(region["gaps"]) for region in bridged["regions"]), 9
        )
        result = self.find(gap_close_in=3.0)["data"]
        (region,) = result["regions"]
        self.assertEqual(region["gaps"], [])
        self.assertEqual(result["excluded"]["dashed"], 10)

    def test_min_width_leaves_out_thin_lines_but_keeps_fills(self):
        self.pdf.segments = (
            _styled_rect(100, 100, 300, 300)
            + [_styled(100, 200, 300, 200, style=THIN_STYLE)]
            + _styled_rect(400, 100, 450, 150, style=POCHE_STYLE)
        )
        self.assertEqual(len(self.find()["data"]["regions"]), 4)
        result = self.find(min_width=1.0)["data"]
        self.assertEqual(len(result["regions"]), 2)
        self.assertEqual(result["excluded"]["thin"], 1)
        self.assertEqual(len(self.find(min_width=0.25)["data"]["regions"]), 4)
        self.assertEqual(self.find(min_width=0.2501)["data"]["excluded"]["thin"], 1)

    def test_colors_keep_only_the_listed_colors(self):
        self.pdf.segments = _styled_rect(100, 100, 300, 300) + [
            _styled(100, 200, 300, 200, style=RED_STYLE)
        ]
        result = self.find(colors=["#000000"])["data"]
        self.assertEqual(len(result["regions"]), 1)
        self.assertEqual(result["excluded"]["color"], 1)
        self.assertEqual(
            len(self.find(colors=["#000000", "#FF0000"])["data"]["regions"]), 3
        )
        self.pdf.segments = _rect(100, 100, 300, 300)
        self.assertEqual(self.find(colors=["#000000"])["data"]["excluded"]["color"], 4)

    def test_min_area_drops_small_regions_from_the_total(self):
        self.pdf.segments = self.three_rooms()
        small_sf = 50 * 50 * K * K / 144.0
        result = self.find(min_area_sf=small_sf + 0.01)["data"]
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(
            self.find(min_area_sf=small_sf - 0.01)["data"]["total_count"], 3
        )
        self.assertEqual(self.find(min_area_sf=0)["data"]["total_count"], 3)

    def test_small_symbols_are_not_holes_and_are_counted(self):
        self.pdf.segments = (
            _styled_rect(100, 100, 400, 400)
            + _styled_rect(150, 150, 170, 170, style=THIN_STYLE, group="9:0")
            + _rect(200, 150, 210, 160)
            + _styled_rect(250, 250, 310, 310, group="")
        )
        result = self.find(seed_pts=[120, 380])["data"]
        (room,) = result["regions"]
        self.assertEqual(len(room["holes_ost"]), 1)
        self.assertAlmostEqual(
            room["area_sf"], (300 * 300 - 60 * 60) * K * K / 144.0, places=3
        )
        self.assertEqual(result["suppressed_symbol_count"], 2)
        self.assertEqual(
            sorted(result["suppressed_symbols_pts"]),
            [[150.0, 150.0, 170.0, 170.0], [200.0, 150.0, 210.0, 160.0]],
        )
        everything = self.find(seed_pts=[120, 380], symbol_max_pts=0)["data"]
        self.assertEqual(len(everything["regions"][0]["holes_ost"]), 3)
        self.assertEqual(everything["suppressed_symbol_count"], 0)
        self.assertEqual(
            result["coordinate_space"]["suppressed_symbols_pts"], "page_pts_y_down"
        )

    def test_max_gap_in_is_the_same_setting_as_gap_close_in(self):
        self.pdf.segments = [
            _raw(100, 100, 460, 100),
            _raw(460, 100, 460, 370),
            _raw(460, 370, 100, 370),
            _raw(100, 370, 100, 104.5),
        ]
        self.assertEqual(self.find()["data"]["regions"], [])
        for kwargs in (
            {"max_gap_in": 6.0},
            {"gap_close_in": 6.0},
            {"gap_close_in": 6.0, "max_gap_in": 6},
        ):
            with self.subTest(kwargs=kwargs):
                (region,) = self.find(**kwargs)["data"]["regions"]
                self.assertEqual(len(region["gaps"]), 1)
        self.assert_error(
            "invalid_argument", lambda: self.find(gap_close_in=6.0, max_gap_in=8.0)
        )
        for gap in (-1, 48.5, "6", True):
            with self.subTest(gap=gap):
                self.assert_error("invalid_argument", lambda: self.find(max_gap_in=gap))

    def test_filters_are_echoed_with_their_defaults(self):
        self.pdf.segments = _rect(100, 100, 300, 300)
        self.assertEqual(
            self.find()["data"]["filters"],
            {
                "max_gap_in": 0.0,
                "min_width": None,
                "exclude_dashed": True,
                "exclude_thin_curves": True,
                "colors": None,
                "min_area_sf": 0.0,
                "symbol_max_pts": 48.0,
                "min_width_source": "none",
                "boundary_kinds": None,
            },
        )
        self.assertEqual(
            self.find(
                max_gap_in=2,
                min_width=1,
                exclude_dashed=False,
                colors=["#ABCDEF"],
                min_area_sf=3,
                symbol_max_pts=10,
            )["data"]["filters"],
            {
                "max_gap_in": 2.0,
                "min_width": 1.0,
                "exclude_dashed": False,
                "exclude_thin_curves": True,
                "colors": ["#abcdef"],
                "min_area_sf": 3.0,
                "symbol_max_pts": 10.0,
                "min_width_source": "given",
                "boundary_kinds": None,
            },
        )

    def test_invalid_filters_are_refused(self):
        self.pdf.segments = _rect(100, 100, 300, 300)
        cases = {
            "min_width": (-1, "1", True, float("inf")),
            "exclude_dashed": ("yes", 1, 0),
            "colors": ("#000000", ["black"], ["#12345"], [1], ["#1234567"]),
            "min_area_sf": (-0.1, "3"),
            "symbol_max_pts": (-1, "48"),
            "limit": (0, 51, 1.5, True),
            "cursor": ("bad", 5),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    self.assert_error(
                        "invalid_argument", lambda: self.find(**{name: value})
                    )

    def test_a_door_opening_found_from_a_seed_is_closed_and_recorded(self):
        self.pdf.segments = _door_room()
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        result = self.find(seed_pts=[250, 200], max_gap_in=40.0)
        (region,) = result["data"]["regions"]
        self.assertEqual(region["method"], "vector")
        self.assertAlmostEqual(region["area_sf"], 300 * 200 * K * K / 144.0, places=3)
        (gap,) = region["gaps"]
        self.assertEqual(
            sorted([gap["p1_pts"], gap["p2_pts"]]), [[200.0, 300.0], [254.0, 300.0]]
        )
        self.assertAlmostEqual(gap["length_in"], 54 * K)
        self.assertTrue(region["leak_risk"])
        self.assertEqual(self.raster_calls[0][2], 40.0 / K)
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        (closing,) = data["assumptions"]
        self.assertEqual(
            (closing["subject"], closing["impact"]), ("closing_segment", IMPACT_HIGH)
        )
        self.assertEqual(closing["value"]["value"], "36.00 in")
        self.assertIn("(200.0, 300.0)", closing["reason"]["value"])
        self.assertIn("(254.0, 300.0)", closing["reason"]["value"])
        self.assertEqual(data["blocking_assumption_ids"], [closing["id"]])

    def test_a_passage_to_an_island_is_not_an_opening(self):
        self.pdf.segments = _door_room() + _styled_rect(180, 120, 200, 140)
        self.raster_result = RasterResult(
            (
                (100.0, 100.0),
                (185.0, 100.0),
                (180.0, 120.0),
                (180.0, 140.0),
                (200.0, 140.0),
                (200.0, 120.0),
                (195.0, 100.0),
                (400.0, 100.0),
                (400.0, 300.0),
                (100.0, 300.0),
            ),
            False,
            4.0,
        )
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=40.0, symbol_max_pts=0)[
            "data"
        ]["regions"]
        self.assertEqual(region["method"], "vector")
        self.assertEqual(
            [sorted([gap["p1_pts"], gap["p2_pts"]]) for gap in region["gaps"]],
            [[[200.0, 300.0], [254.0, 300.0]]],
        )
        self.assertEqual(len(region["holes_ost"]), 1)
        self.assertAlmostEqual(
            region["area_sf"], (300 * 200 - 20 * 20) * K * K / 144.0, places=3
        )

    def test_an_opening_as_wide_as_the_pen_is_still_found(self):
        self.pdf.segments = _door_room()
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=51.0 * K)["data"][
            "regions"
        ]
        self.assertEqual(region["method"], "vector")
        self.assertEqual(len(region["gaps"]), 1)

    def test_a_vector_outline_that_disagrees_with_the_fill_is_not_used(self):
        self.pdf.segments = _door_room()
        ring = (
            (100.0, 100.0),
            (250.0, 100.0),
            (250.0, -200.0),
            (400.0, -200.0),
            (400.0, 300.0),
            (100.0, 300.0),
        )
        self.raster_result = RasterResult(ring, False, 4.0)
        (region,) = self.find(seed_pts=[300, 200], max_gap_in=40.0)["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        self.assertAlmostEqual(region["area_sf"], 105000 * K * K / 144.0, places=3)
        (gap,) = region["gaps"]
        self.assertEqual(
            sorted([gap["p1_pts"], gap["p2_pts"]]), [[200.0, 300.0], [254.0, 300.0]]
        )

    def test_an_opening_must_continue_a_drawn_line_at_both_ends(self):
        ring = ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0))
        raster = RasterResult(ring, False, 4.0)
        frame = [
            (100.0, 100.0, 400.0, 100.0),
            (400.0, 100.0, 400.0, 300.0),
            (100.0, 300.0, 100.0, 100.0),
        ]
        both = frame + [(100.0, 300.0, 200.0, 300.0), (254.0, 300.0, 400.0, 300.0)]
        self.assertEqual(
            _sealed_openings(raster, both, 60.0, (250.0, 200.0)),
            [(254.0, 300.0, 200.0, 300.0)],
        )
        left_stub = frame + [
            (100.0, 300.9, 199.0, 300.9),
            (200.0, 300.0, 200.0, 330.0),
            (254.0, 300.0, 400.0, 300.0),
        ]
        self.assertEqual(_sealed_openings(raster, left_stub, 60.0, (250.0, 200.0)), [])
        right_stub = frame + [
            (100.0, 300.0, 200.0, 300.0),
            (254.0, 300.0, 254.0, 330.0),
            (255.0, 300.9, 400.0, 300.9),
        ]
        self.assertEqual(_sealed_openings(raster, right_stub, 60.0, (250.0, 200.0)), [])

    def test_lines_left_of_the_box_are_ignored(self):
        self.pdf.segments = _rect(10, 100, 60, 150)
        self.assertEqual(self.find(bbox=[100, 0, 600, 700])["data"]["regions"], [])
        self.assertEqual(len(self.find(bbox=[0, 0, 600, 700])["data"]["regions"]), 1)

    def test_the_minimum_area_is_inclusive(self):
        self.pdf.segments = _rect(100, 100, 160, 160)
        exact = 3600 * K * K / 144.0
        self.assertEqual(exact * 144.0 / (K * K), 3600.0)
        self.assertEqual(self.find(min_area_sf=exact)["data"]["total_count"], 1)

    def test_a_short_opening_closure_is_a_normal_assumption(self):
        self.pdf.segments = _door_room(200.0, 215.0)
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=40.0)["data"]["regions"]
        (gap,) = region["gaps"]
        self.assertAlmostEqual(gap["length_in"], 10.0)
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        (closing,) = data["assumptions"]
        self.assertEqual(closing["impact"], IMPACT_NORMAL)
        self.assertEqual(data["blocking_assumption_ids"], [])

    def test_a_sealed_opening_is_recorded_even_when_the_vector_outline_stays_open(self):
        self.pdf.segments = [
            _styled(100, 300, 200, 300),
            _styled(254, 300, 400, 300),
            _styled(100, 300, 100, 500),
            _styled(400, 300, 400, 500),
            _styled(100, 500, 400, 500),
        ]
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=40.0)["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        (gap,) = region["gaps"]
        self.assertEqual(
            sorted([gap["p1_pts"], gap["p2_pts"]]), [[200.0, 300.0], [254.0, 300.0]]
        )
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        self.assertEqual(
            [a["subject"] for a in data["assumptions"]], ["closing_segment"]
        )

    def test_a_raster_region_without_openings_keeps_no_gaps(self):
        self.pdf.segments = _styled_rect(100, 100, 400, 300)[:3] + [
            _styled(100, 300, 400, 300, style=THIN_STYLE)
        ]
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        (region,) = self.find(seed_pts=[250, 200], min_width=1.0)["data"]["regions"]
        self.assertEqual((region["method"], region["gaps"]), ("raster", []))

    def test_thin_door_swings_never_close_an_opening_silently(self):
        self.pdf.segments = _door_room() + _swing(200.0, 300.0, 54.0)
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        result = self.find(seed_pts=[250, 200], max_gap_in=40.0)["data"]
        (region,) = result["regions"]
        self.assertAlmostEqual(region["area_sf"], 300 * 200 * K * K / 144.0, places=3)
        self.assertEqual(len(region["gaps"]), 1)
        self.assertEqual(result["excluded"]["thin_curve"], 12)
        swung = self.find(
            seed_pts=[250, 200], max_gap_in=40.0, exclude_thin_curves=False
        )
        (closed,) = swung["data"]["regions"]
        self.assertEqual(closed["gaps"], [])
        self.assertLess(closed["area_sf"], region["area_sf"] - 5.0)
        self.assertEqual(swung["data"]["excluded"]["thin_curve"], 0)

    def test_heavy_curves_stay_region_edges(self):
        arc = [
            _styled(*a, *b, curve=True)
            for a, b in zip(
                [
                    (
                        300 + 100 * math.cos(math.radians(a)),
                        200 - 100 * math.sin(math.radians(a)),
                    )
                    for a in range(-90, 91, 10)
                ],
                [
                    (
                        300 + 100 * math.cos(math.radians(a)),
                        200 - 100 * math.sin(math.radians(a)),
                    )
                    for a in range(-80, 101, 10)
                ],
            )
        ][:-1]
        self.pdf.segments = (
            [
                _styled(300, 100, 100, 100),
                _styled(100, 100, 100, 300),
                _styled(100, 300, 300, 300),
            ]
            + arc
            + [_styled(0, 600, 300, 600, style=THIN_STYLE) for _ in range(30)]
        )
        (region,) = self.find()["data"]["regions"]
        expected = (200 * 200 + math.pi * 100 * 100 / 2) * K * K / 144.0
        self.assertAlmostEqual(region["area_sf"], expected, delta=expected * 0.005)

    def dimension_line(self):
        return [
            _styled(92, 332, 408, 332, style=THIN_STYLE),
            _styled(92, 326, 92, 338, style=THIN_STYLE),
            _styled(408, 326, 408, 338, style=THIN_STYLE),
        ]

    def test_a_seed_closes_its_own_openings_before_bridging_nearby_lines(self):
        self.pdf.segments = _door_room() + self.dimension_line()
        self.raster_result = RasterResult(
            ((100.0, 100.0), (400.0, 100.0), (400.0, 300.0), (100.0, 300.0)), False, 4.0
        )
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=40.0)["data"]["regions"]
        self.assertAlmostEqual(region["area_sf"], 300 * 200 * K * K / 144.0, places=3)
        self.assertEqual(len(region["gaps"]), 1)
        listed = self.find(max_gap_in=40.0)["data"]["regions"]
        self.assertTrue(any(len(item["gaps"]) == 2 for item in listed))

    def test_global_gap_closing_is_the_fallback_when_no_opening_is_found(self):
        self.pdf.segments = _door_room() + self.dimension_line()
        (region,) = self.find(seed_pts=[250, 200], max_gap_in=40.0)["data"]["regions"]
        self.assertEqual(region["method"], "vector")
        self.assertEqual(len(region["gaps"]), 2)
        self.assertEqual(len(self.raster_calls), 1)

    def test_a_raster_fill_that_may_have_closed_unseen_openings_says_so(self):
        self.raster_result = RasterResult(
            ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)), False, 4.0
        )
        (region,) = self.find(
            seed_pts=[15, 15], max_gap_in=18.0, bbox=[0, 0, 600, 700]
        )["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        self.assertEqual(
            (region["gaps"], region["unlocated_gaps_up_to_in"]), ([], 18.0)
        )
        self.assertTrue(region["leak_risk"])
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        (closing,) = data["assumptions"]
        self.assertEqual(closing["value"]["value"], "up to 18.00 in")
        self.assertIn("could not be located", closing["reason"]["value"])
        self.assertEqual(closing["impact"], IMPACT_HIGH)
        (small,) = self.find(seed_pts=[15, 15], max_gap_in=K)["data"]["regions"]
        self.assertIsNone(small["unlocated_gaps_up_to_in"])
        (wider,) = self.find(seed_pts=[15, 15], max_gap_in=K * 1.01)["data"]["regions"]
        self.assertAlmostEqual(wider["unlocated_gaps_up_to_in"], K * 1.01)

    def walled_page(self):
        rooms = []
        for index in range(6):
            left = 50 + index * 90
            rooms += _styled_rect(left, 100, left + 80, 300)
        split = [_styled(50, 200, 130, 200, style=THIN_STYLE)]
        hatch = [_styled(10, 600 + i, 40, 600 + i, style=THIN_STYLE) for i in range(40)]
        return rooms + split + hatch

    def test_a_suggested_wall_width_is_applied_by_default(self):
        self.pdf.segments = self.walled_page()
        data = self.find()["data"]
        self.assertEqual(data["total_count"], 6)
        self.assertEqual(data["filters"]["min_width"], 2.0)
        self.assertEqual(data["filters"]["min_width_source"], "suggested")
        self.assertEqual(data["excluded"]["thin"], 41)
        given = self.find(min_width=0.1)["data"]
        self.assertEqual(given["total_count"], 8)
        self.assertEqual(
            (given["filters"]["min_width"], given["filters"]["min_width_source"]),
            (0.1, "given"),
        )
        off = self.find(min_width=0)["data"]
        self.assertEqual(off["total_count"], 8)
        self.assertEqual(off["excluded"]["thin"], 0)

    def test_a_truncated_page_is_read_again_inside_the_box(self):
        self.pdf.segments = self.three_rooms()
        whole = self.find()["data"]
        self.assertEqual(
            (whole["extraction_scope"], whole["extraction_truncated"]), ("page", False)
        )
        self.pdf.truncated = True
        boxed = self.find(bbox=[90, 90, 210, 210], min_width=0)["data"]
        self.assertEqual(
            (boxed["extraction_scope"], boxed["extraction_truncated"]), ("box", False)
        )
        self.assertEqual(boxed["total_count"], 1)
        self.assertEqual(len(self.pdf.boxes), 1)
        self.pdf.box_truncated = True
        still = self.find(bbox=[90, 90, 210, 210], min_width=0)["data"]
        self.assertEqual(
            (still["extraction_scope"], still["extraction_truncated"]), ("box", True)
        )

    def test_the_suggested_width_keeps_dashed_lines_the_caller_asked_for(self):
        page = self.walled_page()
        page[24] = _styled(50, 200, 130, 200, style=DASH_STYLE)
        self.pdf.segments = page
        kept = self.find(exclude_dashed=False)["data"]
        self.assertEqual(kept["filters"]["min_width_source"], "suggested")
        self.assertEqual(
            (kept["total_count"], kept["excluded"]["thin"], kept["excluded"]["dashed"]),
            (8, 40, 0),
        )
        given = self.find(exclude_dashed=False, min_width=2.0)["data"]
        self.assertEqual((given["total_count"], given["excluded"]["thin"]), (6, 41))
        dropped = self.find()["data"]
        self.assertEqual(
            (dropped["total_count"], dropped["excluded"]["dashed"]), (6, 1)
        )

    def test_no_suggestion_without_two_width_classes(self):
        self.pdf.segments = _rect(100, 100, 300, 300) + [_raw(100, 200, 300, 200)]
        data = self.find()["data"]
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(
            (data["filters"]["min_width"], data["filters"]["min_width_source"]),
            (None, "none"),
        )

    def test_exclude_thin_curves_must_be_true_or_false(self):
        self.pdf.segments = _rect(100, 100, 300, 300)
        for value in ("no", 0, 1):
            with self.subTest(value=value):
                self.assert_error(
                    "invalid_argument", lambda: self.find(exclude_thin_curves=value)
                )

    def test_too_many_segments_after_filtering_are_refused_but_filtered_ones_are_not(
        self,
    ):
        crowd = [
            _styled(10, 10 + i * 0.01, 600, 10 + i * 0.01, style=THIN_STYLE)
            for i in range(20001)
        ]
        self.pdf.segments = crowd
        self.assert_error("invalid_argument", self.find)
        self.assertEqual(self.find(min_width=1.0)["data"]["regions"], [])


class RegionSimplificationTests(ProposalTestCase):
    def propose(self, region_id):
        return self.service_m1b.propose_element(
            "slab", "p1", region_id=region_id, thickness_in=8.0, top_elev_in=0.0
        )

    def test_a_dense_traced_outline_is_simplified_before_the_proposal(self):
        count = 2500
        points = [
            (
                320 + 260 * math.cos(2 * math.pi * i / count),
                370 + 260 * math.sin(2 * math.pi * i / count),
            )
            for i in range(count)
        ]
        self.pdf.segments = [
            _raw(*a, *b) for a, b in zip(points, points[1:] + points[:1])
        ]
        (region,) = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 600, 700], seed_pts=[320, 370], min_width=0
        )["data"]["regions"]
        self.assertEqual(len(region["polygon_ost"]) // 2, count)
        data = self.propose(region["id"])["data"]
        geometry = data["geometry"]
        self.assertEqual(geometry["outline_vertices"][0], count)
        self.assertLess(geometry["outline_vertices"][1], 2000)
        self.assertLessEqual(abs(geometry["area_change_pct"]), 0.1)
        self.assertEqual(geometry["holes_dropped"], 0)
        self.assertEqual(
            data["takeoffs"][0]["vertex_count"], geometry["outline_vertices"][1]
        )
        self.assertAlmostEqual(
            data["quantity_delta"][0]["area_sf"],
            region["area_sf"],
            delta=region["area_sf"] * 0.001,
        )

    def test_the_element_proposal_can_be_split_for_a_worker(self):
        self.pdf.segments = _rect(100, 100, 300, 300)
        (region,) = self.service_m1b.find_regions(
            self.snapshot(), [50, 50, 600, 700], seed_pts=[200, 200], min_width=0
        )["data"]["regions"]
        before = len(
            self.store.open_for_bid(
                self.project.bid_ref.file_path, self.project.bid_ref.bid_uid
            )
        )
        finish = self.service_m1b.plan_element(
            "slab", "p1", region_id=region["id"], thickness_in=8.0, top_elev_in=0.0
        )
        self.assertEqual(
            len(
                self.store.open_for_bid(
                    self.project.bid_ref.file_path, self.project.bid_ref.bid_uid
                )
            ),
            before,
        )
        data = finish()["data"]
        self.assertEqual(data["geometry"]["holes_dropped"], 0)
        self.assertEqual(
            len(
                self.store.open_for_bid(
                    self.project.bid_ref.file_path, self.project.bid_ref.bid_uid
                )
            ),
            before + 1,
        )
        self.assert_error(
            "not_found",
            lambda: self.service_m1b.plan_element("slab", "p1", region_id="r-missing"),
        )

    def test_a_traced_hole_that_crosses_its_outline_is_left_out_and_recorded(self):
        record = _RegionRecord(
            "p1",
            (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0),
            (
                (100.0, 100.0, 160.0, 100.0, 160.0, 160.0, 100.0, 160.0),
                (-10.0, 200.0, 50.0, 200.0, 50.0, 250.0, -10.0, 250.0),
            ),
            (),
            False,
            K,
        )
        region_id = self.service_m1b._store_region(record)
        data = self.propose(region_id)["data"]
        self.assertEqual(data["takeoffs"][0]["hole_count"], 1)
        self.assertEqual(data["geometry"]["holes_dropped"], 1)
        (other,) = data["assumptions"]
        self.assertEqual((other["subject"], other["impact"]), ("other", IMPACT_NORMAL))
        self.assertIn("1 traced hole", other["reason"]["value"])
        self.assertEqual(data["blocking_assumption_ids"], [])

    def test_given_polygons_are_not_simplified(self):
        noisy = [0.0, 0.0, 240.0, 0.1, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0]
        data = self.service_m1b.propose_element(
            "slab", "p1", polygon_ost=noisy, thickness_in=8.0, top_elev_in=0.0
        )["data"]
        self.assertEqual(data["takeoffs"][0]["vertex_count"], 5)
        self.assertNotIn("geometry", data)


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
        self.assertIsNone(region["unlocated_gaps_up_to_in"])
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


OUTLINE_STYLE = PdfPathStyleDto(mat.OUTLINE_WIDTH, (), 0x000000FF, 0, True, False)
RED_OUTLINE_STYLE = PdfPathStyleDto(mat.OUTLINE_WIDTH, (), 0xFF0000FF, 0, True, False)
MAT_BOX = [80, 80, 210, 290]
ROOM_BOX = [50, 50, 550, 350]
GAP_PTS = 39.0 / K


def _sf(area_pts):
    return area_pts * K * K / 144.0


def _mat_page(skip_on_top=(), style=OUTLINE_STYLE):
    dashes, arcs = mat.outline_segments(skip_on_top=skip_on_top)
    return [_styled(*segment, style=style) for segment in dashes + arcs] + [
        _styled(*segment) for segment in mat.wall_segments()
    ]


def _two_rooms(gap=GAP_PTS):
    return [
        _styled(*segment) for segment in mat.rect_segments((100, 100, 500, 300))
    ] + [
        _styled(300, 100, 300, 150),
        _styled(300, 150 + gap, 300, 300),
    ]


def _diagonal_edges(polygon):
    points = list(zip(polygon[0::2], polygon[1::2]))
    return [
        (a, b)
        for a, b in zip(points, points[1:] + points[:1])
        if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6
    ]


class DashedBoundaryTests(ProposalTestCase):
    def find(self, bbox=MAT_BOX, seed=mat.SEED, **kwargs):
        return self.service_m1b.find_regions(
            self.snapshot(), bbox, seed_pts=list(seed), **kwargs
        )

    def propose(self, region_id):
        return self.service_m1b.propose_element(
            "slab", "p1", region_id=region_id, thickness_in=30.0, top_elev_in=0.0
        )["data"]

    def test_boundary_kinds_must_be_a_list_of_known_kinds(self):
        self.pdf.segments = _mat_page()
        for bad in (["symbol"], [], "dashed", ("dashed",), [3], ["dashed", "hidden"]):
            self.assert_error(
                "invalid_argument", lambda bad=bad: self.find(boundary_kinds=bad)
            )
        filters = self.find(boundary_kinds=["dashed", "wall", "dashed"])["data"][
            "filters"
        ]
        self.assertEqual(filters["boundary_kinds"], ["wall", "dashed"])
        self.assertEqual(filters["min_width_source"], "none")
        self.assertIsNone(filters["min_width"])

    def test_the_suggested_width_is_not_applied_to_boundary_kinds(self):
        walls = [_styled(400, 300 + i * 5, 450, 300 + i * 5) for i in range(25)]
        thin = [
            _styled(400, 450 + i * 5, 450, 450 + i * 5, style=THIN_STYLE)
            for i in range(25)
        ]
        self.pdf.segments = _mat_page() + walls + thin
        default = self.find()["data"]["filters"]
        self.assertEqual(
            (default["min_width"], default["min_width_source"]), (2.0, "suggested")
        )
        filters = self.find(boundary_kinds=["dashed"])["data"]["filters"]
        self.assertEqual(
            (filters["min_width"], filters["min_width_source"]), (None, "none")
        )

    def test_the_default_call_is_unchanged_and_reports_the_ignored_outline(self):
        self.pdf.segments = _mat_page()
        data = self.find()["data"]
        self.assertIsNone(data["filters"]["boundary_kinds"])
        self.assertNotIn("kind", data["excluded"])
        self.assertEqual(data["dash_bridge_count"], 0)
        (region,) = data["regions"]
        self.assertEqual(region["method"], "vector")
        self.assertAlmostEqual(region["area_sf"], _sf(mat.wall_face_area()), delta=1e-3)
        self.assertFalse(region["leak_risk"])
        self.assertEqual(region["open_gaps"], [])
        self.assertAlmostEqual(
            region["dashed_outline"]["area_sf"],
            _sf(mat.outline_area()),
            delta=_sf(mat.outline_area()) * 0.005,
        )
        proposed = self.propose(region["id"])
        (ignored,) = proposed["assumptions"]
        self.assertEqual(
            (ignored["subject"], ignored["impact"], ignored["value"]["value"]),
            ("other", IMPACT_HIGH, "dashed outline ignored"),
        )
        self.assertIn("mat, footing or below-grade", ignored["reason"]["value"])
        self.assertIn(
            f"{region['dashed_outline']['area_sf']:.1f} SF", ignored["reason"]["value"]
        )
        self.assertEqual(proposed["blocking_assumption_ids"], [ignored["id"]])

    def test_a_seed_inside_the_dashed_outline_returns_it_with_rounded_corners(self):
        self.pdf.segments = _mat_page()
        data = self.find(boundary_kinds=["dashed"])["data"]
        (region,) = data["regions"]
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(region["area_sf"], expected, delta=expected * 0.005)
        self.assertEqual(region["method"], "vector")
        self.assertEqual((region["gaps"], region["open_gaps"]), ([], []))
        self.assertFalse(region["leak_risk"])
        self.assertIsNone(region["dashed_outline"])
        self.assertGreaterEqual(
            len(_diagonal_edges(region["polygon_ost"])), 4 * mat.CORNER_PIECES
        )
        self.assertGreater(data["dash_bridge_count"], 0)
        self.assertEqual(data["excluded"]["kind"], len(mat.wall_segments()))
        self.assertEqual(data["excluded"]["dashed"], 0)
        self.assertEqual(self.propose(region["id"])["assumptions"], [])

    def test_a_crossing_dashed_line_does_not_cut_the_outline(self):
        self.pdf.segments = _mat_page() + [
            _styled(x, 180, x + 6, 180, style=OUTLINE_STYLE) for x in range(60, 230, 9)
        ]
        (region,) = self.find(boundary_kinds=["dashed"], bbox=[50, 80, 240, 290])[
            "data"
        ]["regions"]
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(region["area_sf"], expected, delta=expected * 0.005)

    def test_a_dashed_line_joined_to_the_outline_does_not_cut_it(self):
        crossing = mat.dash_line((100.0, 182.0), (188.44, 182.0), (5.0, 3.0))
        self.pdf.segments = _mat_page() + [
            _styled(*segment, style=OUTLINE_STYLE) for segment in crossing
        ]
        (region,) = self.find(boundary_kinds=["dashed"])["data"]["regions"]
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(region["area_sf"], expected, delta=expected * 0.005)
        (default,) = self.find()["data"]["regions"]
        self.assertAlmostEqual(
            default["dashed_outline"]["area_sf"], expected, delta=expected * 0.005
        )

    def test_dashed_corner_curves_stay_in_the_outline(self):
        dashes, arcs = mat.outline_segments()
        self.pdf.segments = [
            _styled(*segment, style=OUTLINE_STYLE) for segment in dashes
        ] + [_styled(*segment, style=OUTLINE_STYLE, curve=True) for segment in arcs]
        data = self.find(boundary_kinds=["wall", "dashed"])["data"]
        (region,) = data["regions"]
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(region["area_sf"], expected, delta=expected * 0.005)
        self.assertEqual(data["excluded"]["thin_curve"], 0)

    def test_walls_and_dashes_together_follow_the_walls(self):
        self.pdf.segments = _mat_page()
        data = self.find(boundary_kinds=["wall", "dashed"])["data"]
        (region,) = data["regions"]
        self.assertAlmostEqual(region["area_sf"], _sf(mat.wall_face_area()), delta=1e-3)
        self.assertIsNotNone(region["dashed_outline"])
        self.assertGreater(data["dash_bridge_count"], 0)
        self.assertEqual(data["excluded"]["kind"], 0)

    def test_a_given_width_never_drops_dashed_boundary_pieces(self):
        self.pdf.segments = _mat_page()
        (region,) = self.find(boundary_kinds=["dashed"], min_width=1.0)["data"][
            "regions"
        ]
        self.assertAlmostEqual(
            region["area_sf"],
            _sf(mat.outline_area()),
            delta=_sf(mat.outline_area()) * 0.005,
        )
        thin = self.find(boundary_kinds=["wall", "thin"], min_width=1.0)["data"]
        self.assertEqual(thin["excluded"]["kind"], len(_mat_page()) - 8)
        mixed = self.find(boundary_kinds=["wall", "dashed"], min_width=1.0)["data"]
        self.assertEqual((mixed["excluded"]["thin"], mixed["excluded"]["kind"]), (0, 0))

    def test_thin_curves_stay_out_of_thin_boundaries(self):
        swing = [
            _styled(130, 200, 135, 205, style=THIN_STYLE, curve=True),
            _styled(135, 205, 140, 212, style=THIN_STYLE, curve=True),
        ]
        self.pdf.segments = _mat_page() + swing
        data = self.find(boundary_kinds=["thin"])["data"]
        self.assertEqual(data["excluded"]["thin_curve"], 2)

    def test_a_gap_longer_than_the_pattern_gap_is_reported_with_its_end_points(self):
        self.pdf.segments = _mat_page(skip_on_top=(1,))
        box = ((80.0, 80.0), (210.0, 80.0), (210.0, 290.0), (80.0, 290.0))
        self.raster_result = RasterResult(box, True, 4.0)
        (region,) = self.find(boundary_kinds=["dashed"])["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        self.assertTrue(region["leak_risk"])
        self.assertEqual(region["gaps"], [])
        (opening,) = region["open_gaps"]
        left, top = mat.OUTLINE[0] + mat.CORNER_RADIUS, mat.OUTLINE[1]
        self.assertEqual(
            sorted([opening["p1_pts"], opening["p2_pts"]]),
            [[left + 13.44, top], [left + 24.0, top]],
        )
        self.assertAlmostEqual(opening["length_in"], 10.56 * K, places=6)

    def test_colors_choose_the_dashed_outline(self):
        self.pdf.segments = _mat_page(style=RED_OUTLINE_STYLE)
        self.assertEqual(
            self.find(boundary_kinds=["dashed"], colors=["#000000"])["data"]["regions"],
            [],
        )
        (region,) = self.find(boundary_kinds=["dashed"], colors=["#ff0000"])["data"][
            "regions"
        ]
        self.assertAlmostEqual(
            region["area_sf"],
            _sf(mat.outline_area()),
            delta=_sf(mat.outline_area()) * 0.005,
        )

    def test_an_outline_within_half_a_percent_of_the_region_is_not_reported(self):
        outline = (100.0, 100.0, 300.0, 300.0)
        square = 200.0 * 200.0
        found = {}
        for radius in (10.0, 20.0):
            dashes, arcs = mat.outline_segments(outline=outline, radius=radius)
            self.pdf.segments = [
                _styled(*segment, style=OUTLINE_STYLE) for segment in dashes + arcs
            ] + [_styled(*segment) for segment in mat.rect_segments(outline)]
            (region,) = self.find(
                bbox=[80, 80, 320, 320], seed=(200, 200), min_width=1.0
            )["data"]["regions"]
            self.assertAlmostEqual(region["area_sf"], _sf(square), delta=1e-3)
            found[radius] = region["dashed_outline"]
            share = (square - mat.outline_area(outline, radius)) / square
            self.assertEqual(share > DASHED_MATCH_SHARE, radius == 20.0)
        self.assertIsNone(found[10.0])
        expected = _sf(mat.outline_area(outline, 20.0))
        self.assertAlmostEqual(found[20.0]["area_sf"], expected, delta=expected * 0.005)

    def test_huge_dash_gaps_neither_fail_nor_bridge_separate_outlines(self):
        for gap in (300.0, math.inf):
            style = PdfPathStyleDto(0.5, (5.0, gap), 0x000000FF, 0, True, False)
            self.pdf.segments = _styled_rect(
                100, 100, 200, 200, style=style
            ) + _styled_rect(240, 100, 340, 200, style=style)
            (region,) = self.find(
                bbox=[0, 0, 600, 700], seed=(150, 150), boundary_kinds=["dashed"]
            )["data"]["regions"]
            self.assertAlmostEqual(region["area_sf"], _sf(100 * 100), delta=1e-3)
            self.assertEqual(
                self.find(bbox=[0, 0, 600, 700], seed=(150, 150))["status"], "empty"
            )

    def test_a_dashed_outline_too_complex_to_trace_is_skipped(self):
        self.pdf.segments = _mat_page()
        real = module.find_planar_regions_report

        def traced(segments, *args, **kwargs):
            if "symbol_max" not in kwargs:
                raise RegionTooComplex("too many")
            return real(segments, *args, **kwargs)

        with mock.patch.object(module, "find_planar_regions_report", traced):
            (region,) = self.find()["data"]["regions"]
        self.assertIsNone(region["dashed_outline"])


class LeakGuardTests(ProposalTestCase):
    def find(self, seed=(200, 200), **kwargs):
        return self.service_m1b.find_regions(
            self.snapshot(), ROOM_BOX, seed_pts=list(seed), **kwargs
        )

    def test_two_rooms_joined_by_a_39_in_gap_are_never_silently_merged(self):
        self.pdf.segments = _two_rooms()
        for max_gap in (0.0, 36.0, 48.0):
            (region,) = self.find(max_gap_in=max_gap)["data"]["regions"]
            self.assertTrue(region["leak_risk"], max_gap)
            (opening,) = region["open_gaps"]
            self.assertEqual(
                sorted([opening["p1_pts"], opening["p2_pts"]]),
                [[300.0, 150.0], [300.0, 150.0 + GAP_PTS]],
            )
            self.assertAlmostEqual(opening["length_in"], 39.0, places=6)
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=4.0, top_elev_in=0.0
        )["data"]
        (open_gap,) = data["assumptions"]
        self.assertEqual(
            (open_gap["subject"], open_gap["impact"], open_gap["value"]["value"]),
            ("other", IMPACT_HIGH, "39.00 in opening not closed"),
        )
        self.assertIn("(300.0, 150.0) to (300.0, 208.5)", open_gap["reason"]["value"])
        self.assertEqual(data["blocking_assumption_ids"], [open_gap["id"]])

    def test_an_open_gap_assumption_blocks_approval_until_accepted(self):
        self.pdf.segments = _two_rooms()
        (region,) = self.find(max_gap_in=36.0)["data"]["regions"]
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=4.0, top_elev_in=0.0
        )["data"]
        changeset_id = data["changeset_id"]
        (open_gap,) = data["assumptions"]
        self.assertEqual(
            self.service_m1b.apply_changeset(changeset_id)["status"],
            STATUS_PENDING_APPROVAL,
        )
        with self.assertRaises(ChangesetError) as refused:
            self.store.approve(changeset_id)
        self.assertEqual(refused.exception.code, ERROR_ASSUMPTION_UNRESOLVED)
        self.store.accept_assumption(changeset_id, open_gap["id"])
        self.assertEqual(self.store.approve(changeset_id).status, STATUS_APPLYING)
        self.assertEqual(
            [item.uid for item in self.store.get(changeset_id).assumptions],
            [open_gap["id"]],
        )

    def test_a_closed_room_has_no_open_gaps(self):
        self.pdf.segments = [
            _styled(*segment) for segment in mat.rect_segments((100, 100, 300, 300))
        ]
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["open_gaps"], [])
        self.assertFalse(region["leak_risk"])

    def test_openings_wider_than_the_check_are_not_reported(self):
        self.pdf.segments = _two_rooms(gap=LEAK_GAP_MAX_IN / K + 1.0)
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["open_gaps"], [])
        self.pdf.segments = _two_rooms(gap=LEAK_GAP_MAX_IN / K - 1.0)
        (region,) = self.find()["data"]["regions"]
        (opening,) = region["open_gaps"]
        self.assertAlmostEqual(opening["length_in"], LEAK_GAP_MAX_IN - K, places=6)

    def test_only_the_opening_to_a_second_area_is_reported(self):
        self.pdf.segments = _two_rooms() + [
            _styled(120, 100, 120, 115),
            _styled(120, 115, 108, 115),
        ]
        (region,) = self.find()["data"]["regions"]
        (opening,) = region["open_gaps"]
        self.assertAlmostEqual(opening["length_in"], 39.0, places=6)

    def test_an_opening_the_region_closed_is_not_reported_again(self):
        self.pdf.segments = [
            _styled(100, 100, 500, 100),
            _styled(500, 100, 500, 300),
            _styled(500, 300, 100, 300),
            _styled(100, 300, 100, 210),
            _styled(100, 190, 100, 100),
            _styled(300, 100, 300, 150),
            _styled(300, 150 + GAP_PTS, 300, 300),
        ]
        (region,) = self.find(max_gap_in=20.0)["data"]["regions"]
        (door,) = region["gaps"]
        self.assertAlmostEqual(door["length_in"], 20.0 * K, places=6)
        (opening,) = region["open_gaps"]
        self.assertAlmostEqual(opening["length_in"], 39.0, places=6)

    def test_a_raster_region_that_matches_the_room_reports_no_opening(self):
        ring = ((100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0))
        self.raster_result = RasterResult(ring, False, 4.0)
        self.pdf.segments = [
            _styled(100, 100, 170, 100),
            _styled(170 + GAP_PTS, 100, 300, 100),
            _styled(300, 100, 300, 300),
            _styled(300, 300, 100, 300),
            _styled(100, 300, 100, 100),
        ]
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        self.assertEqual(region["open_gaps"], [])

    def test_open_gaps_keep_the_closures_the_region_was_traced_with(self):
        segments = [
            (100.0, 100.0, 500.0, 100.0),
            (500.0, 100.0, 500.0, 300.0),
            (500.0, 300.0, 100.0, 300.0),
            (100.0, 300.0, 100.0, 220.0),
            (100.0, 180.0, 100.0, 100.0),
            (300.0, 100.0, 300.0, 150.0),
            (300.0, 150.0 + GAP_PTS, 300.0, 300.0),
        ]
        closure = (100.0, 180.0, 100.0, 220.0)
        report = module._planar(segments, 0.0, 48.0, [closure])
        region = module._smallest_containing(report.regions, (200.0, 200.0))
        choice = module._SeedChoice(report, region=region, closures=(closure,))
        (opening,) = module._open_gaps(
            segments, choice, (200.0, 200.0), region.outer, K, 48.0
        )
        self.assertEqual(
            sorted([opening.p1, opening.p2]), [(300.0, 150.0), (300.0, 150.0 + GAP_PTS)]
        )

    def test_a_capped_double_wall_opening_is_reported(self):
        self.pdf.segments = [
            _styled(*segment) for segment in mat.rect_segments((100, 100, 500, 300))
        ] + [
            _styled(296, 100, 296, 150),
            _styled(296, 150, 304, 150),
            _styled(304, 150, 304, 100),
            _styled(296, 300, 296, 150 + GAP_PTS),
            _styled(296, 150 + GAP_PTS, 304, 150 + GAP_PTS),
            _styled(304, 150 + GAP_PTS, 304, 300),
        ]
        (region,) = self.find(max_gap_in=36.0)["data"]["regions"]
        self.assertTrue(region["leak_risk"])
        self.assertEqual(
            sorted(sorted([g["p1_pts"], g["p2_pts"]]) for g in region["open_gaps"]),
            [[[296.0, 150.0], [296.0, 150.0 + GAP_PTS]]],
        )

    def test_a_small_corner_split_off_by_a_stray_line_is_not_a_leak(self):
        self.pdf.segments = [
            _styled(*segment) for segment in mat.rect_segments((100, 100, 300, 300))
        ] + [_styled(100, 120, 110, 120)]
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["open_gaps"], [])
        self.assertFalse(region["leak_risk"])

    def test_an_opening_that_cannot_be_traced_is_skipped(self):
        self.pdf.segments = _two_rooms()
        real = module.find_planar_regions_report

        def traced(segments, *args, **kwargs):
            if kwargs.get("closures"):
                raise RegionTooComplex("too many")
            return real(segments, *args, **kwargs)

        with mock.patch.object(module, "find_planar_regions_report", traced):
            (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["open_gaps"], [])

    def test_a_raster_region_reports_an_opening_to_the_outside(self):
        ring = ((60.0, 60.0), (540.0, 60.0), (540.0, 340.0), (60.0, 340.0))
        self.raster_result = RasterResult(ring, False, 4.0)
        self.pdf.segments = [
            _styled(100, 100, 500, 100),
            _styled(100, 300, 500, 300),
            _styled(100, 100, 100, 300),
            _styled(300, 100, 300, 150),
            _styled(300, 150 + GAP_PTS, 300, 300),
        ]
        (region,) = self.find()["data"]["regions"]
        self.assertEqual(region["method"], "raster")
        (opening,) = region["open_gaps"]
        self.assertAlmostEqual(opening["length_in"], 39.0, places=6)
        self.assertTrue(region["leak_risk"])
        data = self.service_m1b.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=4.0, top_elev_in=0.0
        )["data"]
        self.assertEqual(
            [item["value"]["value"] for item in data["assumptions"]],
            ["39.00 in opening not closed"],
        )

    def test_region_records_default_to_no_warnings(self):
        record = _RegionRecord("p1", (), (), (), False, K)
        self.assertEqual((record.open_gaps, record.dashed_outline_sf), ((), None))
        self.assertEqual(module._region_warnings(record), ())


if __name__ == "__main__":
    unittest.main()
