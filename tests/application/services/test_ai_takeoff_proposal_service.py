import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.ai_takeoff_dtos import AiTakeoffRequestError
from ost_visualizer.application.dtos.pdf_metadata_dtos import PdfVectorSegmentDto
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_proposal_service import (
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
from ost_visualizer.domain.entities.ai_changeset import apply_blocked_reason
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


if __name__ == "__main__":
    unittest.main()
