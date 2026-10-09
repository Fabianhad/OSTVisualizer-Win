"""Corpus worker on synthetic PDFs only (no client drawings)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tests.integration.ai_takeoff import s101_fixture as fx
from tests.paths import REPO_ROOT
from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf
from tools import ai_takeoff_corpus_worker as worker
from tools.ai_takeoff_corpus import RUN_COLUMNS
import tests.helpers.mdb.schema_support as access

TITLE = (
    "BT /F1 14 Tf 450 60 Td (FOUNDATION PLAN) Tj ET\n"
    'BT /F1 9 Tf 450 45 Td (SCALE: 1/8" = 1\'-0") Tj ET\n'
    "BT /F1 20 Tf 520 20 Td (S-101) Tj ET\n"
)
TWO_PLANS = (
    "BT /F1 14 Tf 60 400 Td (FRAMING PLAN) Tj ET\n"
    'BT /F1 9 Tf 60 385 Td (SCALE: 1/8" = 1\'-0") Tj ET\n'
    "BT /F1 14 Tf 330 400 Td (ROOF PLAN) Tj ET\n"
    'BT /F1 9 Tf 330 385 Td (SCALE: 1/4" = 1\'-0") Tj ET\n'
    "BT /F1 20 Tf 520 20 Td (S-102) Tj ET\n"
)


def _pages_pdf(path, contents, width=612, height=792):
    count = len(contents)
    font = 3 + 2 * count
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
            + f"] /Count {count} >>"
        ).encode("latin-1"),
    ]
    for index, content in enumerate(contents):
        data = content.encode("latin-1")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + 2 * index} 0 R >>"
            ).encode("latin-1")
        )
        objects.append(
            f"<< /Length {len(data)} >>\nstream\n".encode("latin-1")
            + data
            + b"endstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    Path(path).write_bytes(bytes(output))
    return Path(path)


class WorkerHelperTests(unittest.TestCase):
    def test_content_classes(self):
        self.assertEqual(
            [worker._content(s, r) for s, r in ((5, 5), (5, 0), (0, 5), (0, 0))],
            ["vector_and_text", "vector", "text_only", "raster_only"],
        )

    def test_page_size_classes(self):
        self.assertEqual(worker._size_class(2592, 1728), "ARCH D 24x36")
        self.assertEqual(worker._size_class(1728, 2592), "ARCH D 24x36")
        self.assertEqual(worker._size_class(3024, 2160), "ARCH E1 30x42")
        self.assertEqual(worker._size_class(612, 792), "Letter")
        self.assertEqual(worker._size_class(1000, 700), "other 14x10")

    def test_interior_points_fall_inside_the_region(self):
        k = 2.0
        square = [0, 0, 200, 0, 200, 200, 0, 200]
        point = worker._interior_point(square, k)
        self.assertTrue(40.0 < point[0] < 60.0 and 40.0 < point[1] < 60.0)
        ring = [0, 0, 300, 0, 300, 60, 60, 60, 60, 300, 0, 300]
        point = worker._interior_point(ring, k)
        self.assertIsNotNone(point)
        self.assertTrue(point[0] < 30 or point[1] < 30)

    def test_a_ring_without_inside_samples_has_no_interior_point(self):
        self.assertIsNone(worker._interior_point([0, 0, 100, 100, 0, 0.001], 1.0))

    def test_timed_calls_report_error_codes_without_their_messages(self):
        from ost_visualizer.application.dtos.ai_takeoff_dtos import (
            AiTakeoffRequestError,
        )

        def refuse():
            raise AiTakeoffRequestError("invalid_argument", "SECRET drawing text")

        def crash():
            raise ZeroDivisionError("SECRET")

        for call, status in (
            (refuse, "invalid_argument"),
            (crash, "exception:ZeroDivisionError"),
        ):
            timing, result = worker._timed(call)
            self.assertEqual((timing["status"], result), (status, None))
            self.assertGreaterEqual(timing["seconds"], 0.0)
            self.assertNotIn("SECRET", json.dumps(timing))
        timing, result = worker._timed(lambda: {"status": "ok", "data": {}})
        self.assertEqual((timing["status"], result["status"]), ("ok", "ok"))

    def test_the_wall_profile_finds_the_dominant_and_heaviest_long_classes(self):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        lines = [LineSegment(0, i, 200, i, width=2.0) for i in range(30)]
        lines += [LineSegment(0, 300 + i, 200, 300 + i, width=0.7) for i in range(10)]
        lines += [LineSegment(0, 400 + i, 10, 400 + i, width=0.25) for i in range(200)]
        lines += [LineSegment(0, 700 + i, 300, 700 + i, width=4.0) for i in range(5)]
        lines += [
            LineSegment(0, 800 + i, 300, 800 + i, width=6.0, dash=(6.0, 3.0))
            for i in range(9)
        ]
        lines += [LineSegment(0, 900, 500, 900, width=9.0)]
        profile = worker.wall_profile(lines)
        self.assertEqual(profile["dominant_wall_width"], 2.0)
        self.assertEqual(profile["heaviest_long_width"], 4.0)
        self.assertEqual(
            json.loads(profile["long_width_histogram"]),
            {"0.7": 2000.0, "2.0": 6000.0, "4.0": 1500.0, "9.0": 500.0},
        )
        self.assertEqual(
            worker.wall_profile([]),
            {
                "dominant_wall_width": None,
                "heaviest_long_width": None,
                "long_width_histogram": "{}",
            },
        )
        self.assertTrue(worker.removes_dominant(2.5, 2.0))
        self.assertFalse(worker.removes_dominant(2.0, 2.0))
        self.assertFalse(worker.removes_dominant(None, 2.0))
        self.assertFalse(worker.removes_dominant(3.0, None))

    def test_annotation_linework_is_never_the_dominant_wall_weight(self):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        walls = [LineSegment(0, i, 200, i, width=2.0) for i in range(10)]
        grid = [LineSegment(0, 300 + i, 2000, 300 + i, width=0.24) for i in range(100)]
        profile = worker.wall_profile(walls + grid)
        self.assertEqual(profile["dominant_wall_width"], 2.0)
        self.assertEqual(worker.wall_profile(grid)["dominant_wall_width"], None)

    def test_the_auto_seed_skips_frame_sized_regions(self):
        k = 1.0
        frame = {"polygon_ost": [10, 10, 600, 10, 600, 780, 10, 780]}
        room = {"polygon_ost": [100, 100, 300, 100, 300, 300, 100, 300]}
        closet = {"polygon_ost": [400, 400, 420, 400, 420, 420, 400, 420]}
        self.assertIs(worker.seed_region([frame, room, closet], k, 612.0, 792.0), room)
        self.assertIsNone(worker.seed_region([frame], k, 612.0, 792.0))
        self.assertIsNone(worker.seed_region([], k, 612.0, 792.0))

    def test_region_shapes_against_the_search_box(self):
        k = 2.0
        inner = [20, 20, 200, 20, 200, 200, 20, 200]
        self.assertEqual(
            worker.region_shape(inner, k, 612.0, 792.0),
            (False, round(8100.0 / (612.0 * 792.0), 4)),
        )
        edge = [0, 0, 1224, 0, 1224, 1584, 0, 1584]
        self.assertEqual(worker.region_shape(edge, k, 612.0, 792.0), (True, 1.0))
        near = [0.4, 40, 100, 40, 100, 100, 0.4, 100]
        self.assertTrue(worker.region_shape(near, k, 612.0, 792.0)[0])
        self.assertEqual(worker.region_shape([], k, 612.0, 792.0), (False, 0.0))

    def test_wall_filter_failures(self):
        self.assertFalse(worker.wall_filter_failure(False, 0.2, 50))
        self.assertTrue(worker.wall_filter_failure(True, 0.2, 50))
        self.assertTrue(worker.wall_filter_failure(False, 0.81, 50))
        self.assertFalse(worker.wall_filter_failure(False, 0.8, 50))
        self.assertTrue(worker.wall_filter_failure(False, 0.2, 0))

    def test_plan_pages_are_spread_across_the_set(self):
        self.assertEqual(worker.spread(list(range(5)), 12), [0, 1, 2, 3, 4])
        self.assertEqual(worker.spread(list(range(100)), 4), [0, 33, 66, 99])
        self.assertEqual(worker.spread([7, 9, 11], 1), [7])
        self.assertEqual(worker.spread([], 3), [])

    def test_drawing_text_leaves_out_the_title_block(self):
        from tools.ai_takeoff_corpus import TextRun

        runs = [
            TextRun('4" SLAB', 100, 100, 140, 108),
            TextRun("S-101", 2400, 1650, 2450, 1670),
            TextRun("FOUNDATION PLAN", 100, 1500, 300, 1514),
            TextRun("NOTE", 2000, 100, 2040, 108),
        ]
        self.assertEqual(worker.drawing_text_runs(runs, 2592.0, 1728.0), 1)
        self.assertEqual(worker.drawing_text_runs([], 2592.0, 1728.0), 0)

    def test_quadrants_tile_the_page(self):
        self.assertEqual(
            worker.quadrants(200.0, 100.0),
            [
                (0.0, 0.0, 100.0, 50.0),
                (100.0, 0.0, 200.0, 50.0),
                (0.0, 50.0, 100.0, 100.0),
                (100.0, 50.0, 200.0, 100.0),
            ],
        )

    def test_sheet_hint_rows_keep_metrics_and_the_sheet_number_only(self):
        hints = {
            "text_extractable": True,
            "reason": None,
            "sheet_number": {"value": "S-101", "untrusted": True, "truncated": False},
            "sheet_number_source": "label",
            "sheet_number_bbox_pts": [1, 2, 3, 4],
            "scale_candidates": [
                {"view_kind": "plan", "view_title": {"value": "SECRET"}},
                {"view_kind": None, "view_title": {"value": ""}},
            ],
            "plan_scale": {
                "status": "resolved",
                "label": '1/4"=1\'-0"',
                "sf1_sf2": [0.25, 12.0],
            },
            "title_block_crop_pts": [0, 0, 10, 10],
        }
        row = worker.sheet_hint_row(2, hints)
        self.assertEqual(
            row,
            {
                "index": 2,
                "sheet_number": "S-101",
                "sheet_number_source": "label",
                "text_extractable": True,
                "text_reason": "",
                "plan_scale_status": "resolved",
                "plan_scale_label": '1/4"=1\'-0"',
                "scale_candidates": 2,
                "scale_views": '{"none": 1, "plan": 1}',
                "title_block_crop": True,
            },
        )
        empty = dict(
            hints, sheet_number=None, sheet_number_source=None, reason="no_text"
        )
        self.assertEqual(
            (
                worker.sheet_hint_row(0, empty)["sheet_number"],
                worker.sheet_hint_row(0, empty)["text_reason"],
            ),
            ("", "no_text"),
        )

    def test_peak_memory_is_reported_in_megabytes(self):
        value = worker.peak_mb()
        self.assertGreater(value, 1.0)
        self.assertLess(value, 100000.0)


class WorkerProcessTests(unittest.TestCase):
    def setUp(self):
        if not access._access_available():
            self.skipTest("Access ODBC/ADOX unavailable")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)

    def call(self, *args):
        completed = subprocess.run(
            [sys.executable, "-m", "tools.ai_takeoff_corpus_worker", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])

    def test_a_synthetic_plan_is_measured_against_a_scratch_access_bid(self):
        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        prepared = self.work / "plan.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared))
        bid = json.loads(prepared.read_text(encoding="utf-8"))
        self.assertTrue(Path(bid["db"]).is_file())
        self.assertEqual([page["index"] for page in bid["pages"]], [0])
        out = self.work / "p1.json"
        seeds = [{"seed_pts": fx.SEED_PTS, "expected_sf": round(fx.ROOM_AREA_SF, 2)}]
        self.call(
            "page", str(prepared), bid["pages"][0]["uid"], json.dumps(seeds), str(out)
        )
        row = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                key: row[key]
                for key in (
                    "status",
                    "kind",
                    "title",
                    "sheet_number_legacy",
                    "scale_status",
                    "plan_scale_status",
                    "content",
                )
            },
            {
                "status": "ok",
                "kind": "plan",
                "title": "FOUNDATION PLAN",
                "sheet_number_legacy": "S-101",
                "scale_status": "single",
                "plan_scale_status": "resolved",
                "content": "vector_and_text",
            },
        )
        self.assertNotIn("sheet_number", row)
        self.assertIn(row["list_min_width_source"], ("suggested", "none"))
        self.assertEqual(row["list_extraction_scope"], "page")
        self.assertEqual(row["box_quadrants_truncated"], "")
        self.assertEqual(row["proposal_holes_dropped"], 0)
        self.assertGreaterEqual(row["proposal_outline_vertices"], 4)
        self.assertLessEqual(abs(row["proposal_area_change_pct"]), 0.1)
        self.assertEqual(row["scale_used"], '1/8"=1\'-0"')
        self.assertEqual(
            (row["seed_source"], row["seed_method"], row["seed_gaps"]),
            ("hand", "vector", 1),
        )
        self.assertLess(abs(row["hand_error_pct"]), 0.5)
        self.assertEqual(
            (row["proposal_status"], row["proposal_assumptions"]), ("ok", 1)
        )
        self.assertEqual(row["kinds_dashed"], 1 + fx.EXPLODED_DASHES)
        self.assertGreater(row["peak_mb"], 1.0)
        self.assertEqual(set(row) - set(RUN_COLUMNS), set())
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("IGNORE", text)
        self.assertNotIn("OFFICE", text)

    def test_sheet_hints_come_from_list_sheets_for_the_whole_pdf(self):
        pdf = _pages_pdf(
            self.work / "set.pdf",
            [TITLE, TWO_PLANS, "0 0 m 100 100 l S\n"],
        )
        prepared = self.work / "set.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared))
        out = self.work / "set_sheets.json"
        self.call("sheets", str(prepared), str(out))
        hints = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([hint["index"] for hint in hints], [0, 1, 2])
        self.assertEqual(
            [
                (h["sheet_number"], h["text_extractable"], h["text_reason"])
                for h in hints
            ],
            [("S-101", True, ""), ("S-102", True, ""), ("", False, "no_text")],
        )
        self.assertEqual(
            [(h["plan_scale_status"], h["scale_candidates"]) for h in hints],
            [("resolved", 1), ("ambiguous", 2), ("none", 0)],
        )
        self.assertEqual(hints[0]["plan_scale_label"], '1/8"=1\'-0"')
        self.assertEqual(json.loads(hints[1]["scale_views"]), {"plan": 2})
        self.assertTrue(all(hint["title_block_crop"] for hint in hints))
        self.assertEqual([hint["kind"] for hint in hints], ["plan", "plan", "unknown"])
        columns = set(RUN_COLUMNS)
        self.assertEqual(set(hints[0]) - {"index"} - columns, set())

    def test_prepare_refuses_unreadable_pdfs_and_replaces_an_old_scratch_bid(self):
        bad = self.work / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        with self.assertRaisesRegex(RuntimeError, "PDF did not open"):
            worker.prepare(bad, self.work, self.work / "bad.json")
        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        stale = self.work / "plan.mdb"
        stale.write_bytes(b"stale scratch file")
        self.call("prepare", str(pdf), str(self.work), str(self.work / "plan.json"))
        self.assertNotEqual(stale.read_bytes()[:18], b"stale scratch file")
        self.assertEqual(len(list(self.work.glob("*.mdb"))), 1)
        with mock.patch.object(
            access.DatabaseCreator, "create_database", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "not created"):
                worker.prepare(pdf, self.work / "other", self.work / "other.json")

    def test_wall_width_variants_and_callouts_are_measured(self):
        from tools.ai_takeoff_corpus import RUN_COLUMNS

        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        prepared_path = self.work / "plan.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared_path))
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        row = worker.measure_page(prepared, prepared["pages"][0]["uid"], [])
        self.assertEqual(
            (row["dominant_wall_width"], row["suggestion_removes_dominant"]),
            (2.0, False),
        )
        self.assertEqual(row["suggested_min_width"], row["list_min_width"])
        for prefix in ("default", "zero", "heavy"):
            with self.subTest(prefix=prefix):
                self.assertEqual(row[f"{prefix}_status"], "ok")
                self.assertTrue(row[f"{prefix}_found"])
                self.assertFalse(row[f"{prefix}_touches_edge"])
                self.assertTrue(0.0 < row[f"{prefix}_box_ratio"] < 0.8)
                self.assertGreater(row[f"{prefix}_segments"], 0)
                self.assertFalse(row[f"{prefix}_wall_failure"])
                self.assertIn(row[f"{prefix}_open_gaps"], (0, 1, 2))
                self.assertIsInstance(row[f"{prefix}_dashed_outline"], bool)
                self.assertLess(row[f"{prefix}_seconds"], worker.PROXY_TIMEOUT_S)
        self.assertEqual(row["zero_min_width"], 0.0)
        self.assertEqual(row["heavy_min_width"], row["heaviest_long_width"])
        self.assertEqual(
            row["drawing_text_runs"],
            len("OFFICE 101".split()) + len(fx.INJECTED.split()),
        )
        self.assertFalse(row["callouts_as_lines"])
        self.assertEqual(row["proposal_status"], "ok")
        self.assertEqual(
            sum(json.loads(row["proposal_subjects"]).values()),
            row["proposal_assumptions"],
        )
        self.assertEqual(set(row) - set(RUN_COLUMNS), set())

    def test_in_process_measurement_of_truncated_and_unseeded_pages(self):
        from ost_visualizer.presentation.services import ai_takeoff_pdf_source

        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        prepared_path = self.work / "plan.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared_path))
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        uid = prepared["pages"][0]["uid"]
        row = worker.measure_page(prepared, uid, [])
        self.assertEqual(
            (row["extraction_truncated"], row["box_quadrants_truncated"]), (False, "")
        )
        self.assertEqual(row["seed_source"], "largest_region")
        self.assertIn(row["seed_status"], ("ok", "empty"))
        with mock.patch.object(ai_takeoff_pdf_source, "MAX_PAGE_PATH_ITEMS", 8):
            truncated = worker.measure_page(prepared, uid, [])
        self.assertTrue(truncated["extraction_truncated"])
        self.assertIsInstance(truncated["box_quadrants_truncated"], int)
        self.assertTrue(0 < truncated["box_quadrants_truncated"] <= 4)
        self.assertEqual(truncated["list_extraction_scope"], "box")

    def test_plans_without_regions_skip_seeding_and_a_missed_hand_seed_stops(self):
        pdf = write_content_pdf(
            self.work / "open.pdf", "2 w 100 100 m 400 100 l S\n" + TITLE
        )
        prepared_path = self.work / "open.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared_path))
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        uid = prepared["pages"][0]["uid"]
        unseeded = worker.measure_page(prepared, uid, [])
        self.assertEqual(
            (unseeded["kind"], unseeded["seed_status"]), ("plan", "skipped")
        )
        missed = worker.measure_page(
            prepared, uid, [{"seed_pts": [-500.0, -500.0], "expected_sf": 5.0}]
        )
        self.assertEqual(missed["seed_source"], "hand")
        self.assertNotIn("hand_error_pct", missed)
        self.assertNotIn("proposal_status", missed)

    def test_pages_that_are_not_plans_are_measured_but_not_traced(self):
        pdf = write_content_pdf(
            self.work / "notes.pdf",
            "BT /F1 14 Tf 450 60 Td (GENERAL NOTES) Tj ET\n0 0 m 100 100 l S\n",
        )
        prepared = self.work / "notes.json"
        self.call("prepare", str(pdf), str(self.work), str(prepared))
        bid = json.loads(prepared.read_text(encoding="utf-8"))
        out = self.work / "notes_p1.json"
        self.call("page", str(prepared), bid["pages"][0]["uid"], "[]", str(out))
        row = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(row["kind"], "general_notes")
        self.assertEqual(
            (row["list_status"], row["filtered_status"], row["seed_status"]),
            ("skipped",) * 3,
        )
        self.assertEqual(row["segments"], 1)


if __name__ == "__main__":
    unittest.main()
