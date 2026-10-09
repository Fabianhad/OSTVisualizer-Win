import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
    PageCachePdfSource,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from tests.helpers import ai_mat_outline as mat
from tests.integration.ai_takeoff import s101_fixture as fx
from tests.integration.ai_takeoff.test_m2_s101_golden import _services
from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf

AREA_TOLERANCE = 0.005
PAGE_HEIGHT = 792.0
MAT_BOX = [80.0, 80.0, 210.0, 290.0]
ROOM_BOX = [80.0, 380.0, 420.0, 620.0]
GAP_PTS = 39.0 / fx.OST_PER_POINT
S100_PDF_ENV = "OSTV_S100_PDF"


def _sf(area_pts: float) -> float:
    return area_pts * fx.OST_PER_POINT * fx.OST_PER_POINT / 144.0


def _two_rooms_content() -> str:
    def line(x1, y1, x2, y2):
        return f"{x1} {PAGE_HEIGHT - y1} m {x2} {PAGE_HEIGHT - y2} l S"

    commands = ["2 w 0 G"]
    commands += [line(*segment) for segment in mat.rect_segments((100, 400, 400, 600))]
    commands += [line(250, 400, 250, 450), line(250, 450 + GAP_PTS, 250, 600)]
    return "\n".join(commands) + "\n"


class SyntheticMatOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.directory = tempfile.TemporaryDirectory()
        cls.pdf = write_content_pdf(
            Path(cls.directory.name) / "mat.pdf",
            mat.outline_pdf_content(PAGE_HEIGHT) + _two_rooms_content(),
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.read, self.proposal, directory, cache = _services(str(self.pdf))
        self.addCleanup(directory.cleanup)
        self.addCleanup(cache.clear)
        self.snapshot = self.read.page_snapshot("p1")

    def find(self, box, seed, **kwargs):
        return self.proposal.find_regions(
            self.snapshot, box, seed_pts=list(seed), **kwargs
        )

    def test_the_extracted_dashes_close_into_the_rounded_outline(self):
        kinds = {
            segment["kind"]
            for segment in self.read.list_segments(self.snapshot, MAT_BOX, limit=500)[
                "data"
            ]["segments"]
            if abs(segment["width_pts"] - mat.OUTLINE_WIDTH) < 0.01
        }
        self.assertIn("thin", kinds)
        data = self.find(MAT_BOX, mat.SEED, boundary_kinds=["dashed"])["data"]
        (region,) = data["regions"]
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(
            region["area_sf"], expected, delta=expected * AREA_TOLERANCE
        )
        self.assertEqual((region["gaps"], region["open_gaps"]), ([], []))
        self.assertGreater(data["dash_bridge_count"], 0)

    def test_the_default_call_keeps_the_wall_face_and_names_the_outline(self):
        (region,) = self.find(MAT_BOX, mat.SEED)["data"]["regions"]
        self.assertAlmostEqual(
            region["area_sf"],
            _sf(mat.wall_face_area()),
            delta=_sf(mat.wall_face_area()) * AREA_TOLERANCE,
        )
        expected = _sf(mat.outline_area())
        self.assertAlmostEqual(
            region["dashed_outline"]["area_sf"],
            expected,
            delta=expected * AREA_TOLERANCE,
        )
        data = self.proposal.propose_element(
            "slab", "p1", region_id=region["id"], thickness_in=30.0, top_elev_in=0.0
        )["data"]
        (ignored,) = data["assumptions"]
        self.assertEqual(data["blocking_assumption_ids"], [ignored["id"]])

    def test_two_rooms_joined_by_a_39_in_gap_do_not_merge_silently(self):
        (region,) = self.find(ROOM_BOX, (175.0, 500.0), max_gap_in=36.0)["data"][
            "regions"
        ]
        self.assertTrue(region["leak_risk"])
        (opening,) = region["open_gaps"]
        self.assertAlmostEqual(opening["length_in"], 39.0, places=3)
        self.assertEqual(
            sorted([opening["p1_pts"], opening["p2_pts"]]),
            [[250.0, 450.0], [250.0, 450.0 + GAP_PTS]],
        )


class TransformedMatOutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.directory = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def outline_area(self, name, boxes, content, size):
        pdf = write_content_pdf(
            Path(self.directory.name) / f"{name}.pdf", content, page_boxes=boxes
        )
        read, proposal, directory, cache = _services(str(pdf), size=size)
        self.addCleanup(directory.cleanup)
        self.addCleanup(cache.clear)
        snapshot = read.page_snapshot("p1")
        data = proposal.find_regions(
            snapshot,
            [0.0, 0.0, snapshot.width_pts, snapshot.height_pts],
            boundary_kinds=["dashed"],
            min_area_sf=1.0,
        )["data"]
        (region,) = data["regions"]
        return region["area_sf"]

    def test_rotated_cropped_and_scaled_pages_keep_the_outline(self):
        content = mat.outline_pdf_content(PAGE_HEIGHT)
        expected = _sf(mat.outline_area())
        cases = [
            (
                "rotate90",
                "/MediaBox [0 0 612 792] /Rotate 90",
                content,
                (792, 612),
                1.0,
            ),
            (
                "rotate270_crop",
                "/MediaBox [0 0 612 792] /CropBox [50 30 400 780] /Rotate 270",
                content,
                (750, 350),
                1.0,
            ),
            (
                "scaled_half",
                "",
                "\n".join(["q 0.5 0 0 0.5 0 396 cm", content, "Q", ""]),
                (612, 792),
                0.25,
            ),
        ]
        for name, boxes, body, size, factor in cases:
            with self.subTest(name=name):
                self.assertAlmostEqual(
                    self.outline_area(name, boxes, body, size),
                    expected * factor,
                    delta=expected * factor * AREA_TOLERANCE,
                )


def _pairs(name: str):
    text = os.environ.get(name, "")
    return [
        tuple(float(value) for value in item.split(","))
        for item in text.split(";")
        if item.strip()
    ]


@unittest.skipUnless(
    os.environ.get(S100_PDF_ENV), f"set {S100_PDF_ENV} to a licensed S-100 PDF"
)
class RealS100Tests(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        path = os.environ[S100_PDF_ENV]
        page_index = int(os.environ.get("OSTV_S100_PAGE", "0"))
        sf1, sf2 = (
            float(v) for v in os.environ.get("OSTV_S100_SCALE", "0.09375:12").split(":")
        )
        info = PageCachePdfSource(PageCache()).get_page_info(path, page_index)
        self.read, self.proposal, directory, cache = _services(
            path,
            page_index,
            (sf1, sf2),
            (info.effective_width_pts, info.effective_height_pts),
        )
        self.addCleanup(directory.cleanup)
        self.addCleanup(cache.clear)
        self.snapshot = self.read.page_snapshot("p1")
        self.whole = [0.0, 0.0, self.snapshot.width_pts, self.snapshot.height_pts]

    def test_a_seed_in_each_pit_returns_its_dashed_outline(self):
        seeds = _pairs("OSTV_S100_SEEDS")
        hands = [
            float(v) for v in os.environ.get("OSTV_S100_HAND_SF", "").split(";") if v
        ]
        if not seeds or len(seeds) != len(hands):
            self.skipTest("set OSTV_S100_SEEDS and OSTV_S100_HAND_SF")
        for seed, hand in zip(seeds, hands):
            (region,) = self.proposal.find_regions(
                self.snapshot,
                self.whole,
                seed_pts=list(seed),
                boundary_kinds=["dashed"],
            )["data"]["regions"]
            self.assertAlmostEqual(region["area_sf"], hand, delta=hand * AREA_TOLERANCE)
            self.assertFalse(region["leak_risk"])
            (default,) = self.proposal.find_regions(
                self.snapshot, self.whole, seed_pts=list(seed)
            )["data"]["regions"]
            self.assertIsNotNone(default["dashed_outline"])

    def test_the_leak_case_is_never_silently_merged(self):
        (seed,) = _pairs("OSTV_S100_LEAK_SEED") or [None]
        if seed is None:
            self.skipTest(
                "set OSTV_S100_LEAK_SEED (and optionally OSTV_S100_LEAK_ARGS)"
            )
        arguments = json.loads(os.environ.get("OSTV_S100_LEAK_ARGS", "{}"))
        box = arguments.pop("bbox_pts", self.whole)
        regions = self.proposal.find_regions(
            self.snapshot, box, seed_pts=list(seed), **arguments
        )["data"]["regions"]
        for region in regions:
            self.assertTrue(region["leak_risk"])
            self.assertTrue(region["open_gaps"] or region["gaps"])


if __name__ == "__main__":
    unittest.main()
