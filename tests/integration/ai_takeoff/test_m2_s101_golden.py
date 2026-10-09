import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.application.services.ai_takeoff_proposal_service import (
    AiTakeoffProposalService,
)
from ost_visualizer.application.services.ai_takeoff_read_service import (
    AiTakeoffReadService,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.database_descriptor import DatabaseDescriptor
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.persistence.repositories.json_ai_takeoff_sidecar_repository import (
    JsonAiTakeoffSidecarRepository,
)
from ost_visualizer.presentation.services.ai_region_raster import raster_fill_region
from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
    PageCachePdfSource,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from tests.application.services.test_ai_takeoff_read_service import FakeProjectData
from tests.integration.ai_takeoff import s101_fixture as fx

ACCESS_PATH = "C:/bids/s101.mdb"
AREA_TOLERANCE = 0.005
S101_PDF_ENV = "OSTV_S101_PDF"


def _services(
    pdf_path: str, page_index: int = 0, scale=fx.SCALE_FACTORS, size=(612.0, 792.0)
):
    directory = tempfile.TemporaryDirectory()
    page = Page(
        uid="p1",
        name="S-101",
        sheet_no="S-101",
        sequence=1,
        image_path=pdf_path,
        page_index=page_index,
        width_pts=size[0],
        height_pts=size[1],
        scale_factor1=scale[0],
        scale_factor2=scale[1],
    )
    project = FakeProjectData(
        BidRef(ACCESS_PATH, "{BID-1}"),
        Bid(uid="{BID-1}", name="Better Wash"),
        [page],
        {},
        [],
    )
    cache = PageCache()
    read = AiTakeoffReadService(
        project,
        PageCachePdfSource(cache),
        JsonAiTakeoffSidecarRepository(Path(directory.name) / "bids"),
        {
            ACCESS_PATH: DatabaseDescriptor.for_access(ACCESS_PATH, database_id="db-1")
        }.get,
    )
    proposal = AiTakeoffProposalService(
        read, AiChangesetProposals(AiChangesetStore()), [], raster_fill_region
    )
    return read, proposal, directory, cache


class S101LikeGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.directory = tempfile.TemporaryDirectory()
        cls.pdf = fx.write_s101_pdf(Path(cls.directory.name) / "S101.pdf")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.read, self.proposal, directory, cache = _services(str(self.pdf))
        self.addCleanup(directory.cleanup)
        self.addCleanup(cache.clear)
        self.snapshot = self.read.page_snapshot("p1")

    def find(self, **kwargs):
        return self.proposal.find_regions(self.snapshot, fx.BBOX_PTS, **kwargs)

    def seeded(self, **kwargs):
        return self.find(seed_pts=fx.SEED_PTS, max_gap_in=fx.GAP_IN, **kwargs)

    def test_the_room_matches_the_hand_value_with_the_door_recorded(self):
        result = self.seeded()
        (room,) = result["data"]["regions"]
        self.assertEqual(room["method"], "vector")
        self.assertAlmostEqual(
            room["area_sf"], fx.ROOM_AREA_SF, delta=fx.ROOM_AREA_SF * AREA_TOLERANCE
        )
        self.assertEqual(room["holes_ost"], [])
        (gap,) = room["gaps"]
        self.assertAlmostEqual(gap["length_in"], fx.DOOR_WIDTH_IN, delta=0.01)
        self.assertGreater(gap["length_in"], 12.0)
        data = self.proposal.propose_element(
            "slab", "p1", region_id=room["id"], thickness_in=8.0, top_elev_in=0.0
        )["data"]
        (closing,) = data["assumptions"]
        self.assertEqual(
            (closing["subject"], closing["impact"]), ("closing_segment", "high")
        )
        self.assertEqual(data["blocking_assumption_ids"], [closing["id"]])

    def test_dashes_are_excluded_and_symbols_are_not_holes(self):
        data = self.seeded()["data"]
        self.assertEqual(data["excluded"]["dashed"], 1 + fx.EXPLODED_DASHES)
        self.assertEqual(data["suppressed_symbol_count"], fx.SYMBOL_SHAPES)
        for left, top, right, bottom in data["suppressed_symbols_pts"]:
            self.assertLess(max(right - left, bottom - top), 48.0)

    def test_regions_are_sorted_with_a_total(self):
        data = self.find(min_width=1.0, limit=1)
        self.assertEqual(
            data["data"]["total_count"],
            len(self.find(min_width=1.0)["data"]["regions"]),
        )
        areas = [r["area_sf"] for r in self.find(min_width=1.0)["data"]["regions"]]
        self.assertEqual(areas, sorted(areas, reverse=True))

    def test_turning_the_m2_defaults_off_brings_back_the_s101_failures(self):
        old = self.seeded(
            exclude_dashed=False,
            symbol_max_pts=0,
            exclude_thin_curves=False,
            min_width=0,
        )
        (room,) = old["data"]["regions"]
        self.assertLess(room["area_sf"], fx.ROOM_AREA_SF * (1.0 - AREA_TOLERANCE))
        self.assertEqual(room["gaps"], [])
        (holed,) = self.seeded(symbol_max_pts=0, min_width=1.0)["data"]["regions"]
        self.assertEqual(len(holed["holes_ost"]), 2)
        self.assertEqual(len(holed["gaps"]), 1)
        self.assertLess(holed["area_sf"], fx.ROOM_AREA_SF * (1.0 - AREA_TOLERANCE))
        (split,) = self.seeded(exclude_dashed=False, min_width=0)["data"]["regions"]
        self.assertLess(split["area_sf"], fx.ROOM_AREA_SF * 0.6)
        self.assertEqual(split["gaps"], [])

    def test_segment_kinds_widths_and_dashes(self):
        segments = self.read.list_segments(self.snapshot, limit=500)["data"]["segments"]
        kinds = {segment["kind"] for segment in segments}
        self.assertEqual(kinds, {"wall", "dashed", "thin", "symbol"})
        self.assertIn([6.0, 3.0], [s["dash_pts"] for s in segments])
        self.assertTrue(any(s["curve"] for s in segments))
        self.assertEqual(
            {s["paint"] for s in segments if s["kind"] == "wall"}, {"stroke", "fill"}
        )

    def test_a_whole_sheet_call_stays_within_the_time_budget(self):
        started = time.perf_counter()
        self.proposal.find_regions(
            self.snapshot, [0, 0, 612, 792], max_gap_in=fx.GAP_IN
        )
        self.assertLess(time.perf_counter() - started, 10.0)


@unittest.skipUnless(
    os.environ.get(S101_PDF_ENV), f"set {S101_PDF_ENV} to a licensed S101 PDF"
)
class RealS101Tests(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        path = os.environ[S101_PDF_ENV]
        page_index = int(os.environ.get("OSTV_S101_PAGE", "0"))
        sf1, sf2 = (
            float(v) for v in os.environ.get("OSTV_S101_SCALE", "0.125:12").split(":")
        )
        source = PageCachePdfSource(PageCache())
        info = source.get_page_info(path, page_index)
        self.read, self.proposal, directory, cache = _services(
            path,
            page_index,
            (sf1, sf2),
            (info.effective_width_pts, info.effective_height_pts),
        )
        self.addCleanup(directory.cleanup)
        self.addCleanup(cache.clear)
        self.snapshot = self.read.page_snapshot("p1")

    def test_the_real_sheet_has_kinds_and_a_bounded_whole_building_call(self):
        segments = self.read.list_segments(self.snapshot, limit=500)
        self.assertTrue(segments["success"], segments)
        self.assertGreater(segments["meta"]["total_count"], 0)
        whole = [0.0, 0.0, self.snapshot.width_pts, self.snapshot.height_pts]
        started = time.perf_counter()
        result = self.proposal.find_regions(self.snapshot, whole, min_width=1.0)
        self.assertTrue(result["success"], result)
        self.assertLess(time.perf_counter() - started, 60.0)
        seed = os.environ.get("OSTV_S101_SEED")
        hand = os.environ.get("OSTV_S101_HAND_SF")
        if seed and hand:
            x, y = (float(v) for v in seed.split(","))
            (room,) = self.proposal.find_regions(
                self.snapshot, whole, seed_pts=[x, y], max_gap_in=40.0, min_width=1.0
            )["data"]["regions"]
            self.assertAlmostEqual(
                room["area_sf"], float(hand), delta=float(hand) * AREA_TOLERANCE
            )


if __name__ == "__main__":
    unittest.main()
