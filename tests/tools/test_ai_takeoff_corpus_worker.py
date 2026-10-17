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

    def test_long_lines_count_from_exactly_72_points_and_four_per_width(self):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        def lines(length, count, **kwargs):
            return [
                LineSegment(0, i, length, i, **dict({"width": 2.0}, **kwargs))
                for i in range(count)
            ]

        def histogram(items):
            return json.loads(worker.wall_profile(items)["long_width_histogram"])

        self.assertEqual(histogram(lines(72.0, 4)), {"2.0": 288.0})
        self.assertEqual(histogram(lines(71.9, 4)), {})
        target = "ost_visualizer.domain.services.ai_linework.heavy_width_threshold"
        with mock.patch(target, return_value=0.0):
            few = worker.wall_profile(lines(100.0, 3))
            enough = worker.wall_profile(lines(100.0, 4))
        self.assertEqual(
            (few["dominant_wall_width"], few["heaviest_long_width"]), (None, None)
        )
        self.assertEqual(
            (enough["dominant_wall_width"], enough["heaviest_long_width"]), (2.0, 2.0)
        )
        self.assertEqual(histogram(lines(100.0, 4, width=None)), {})
        self.assertEqual(histogram(lines(100.0, 4, stroked=False)), {})
        self.assertEqual(histogram(lines(100.0, 4, dash=(3.0, 3.0))), {})
        self.assertEqual(histogram(lines(100.0, 4, width=2.004)), {"2.0": 400.0})

    def test_a_wall_exactly_as_heavy_as_the_threshold_is_dominant(self):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        items = [LineSegment(0, i, 100, i, width=2.0) for i in range(4)]
        items += [LineSegment(0, 50 + i, 100, 50 + i, width=1.0) for i in range(8)]
        target = "ost_visualizer.domain.services.ai_linework.heavy_width_threshold"
        for threshold, dominant in ((2.0, 2.0), (2.0 + 1e-6, None), (1.0, 1.0)):
            with self.subTest(threshold=threshold):
                with mock.patch(target, return_value=threshold):
                    profile = worker.wall_profile(items)
                self.assertEqual(profile["dominant_wall_width"], dominant)
        with mock.patch(target, return_value=1.5):
            self.assertEqual(worker.wall_profile(items)["dominant_wall_width"], 2.0)

    def test_region_shape_reads_triangles_and_ignores_empty_search_boxes(self):
        triangle = [10, 10, 50, 10, 10, 50]
        touches, share = worker.region_shape(triangle, 1.0, 100.0, 100.0)
        self.assertEqual((touches, share), (False, round(800.0 / 10000.0, 4)))
        self.assertEqual(
            worker.region_shape([10, 10, 50, 10], 1.0, 100.0, 100.0), (False, 0.0)
        )
        for width, height in ((0.0, 100.0), (100.0, 0.0), (-5.0, 100.0), (100.0, -5.0)):
            with self.subTest(width=width, height=height):
                self.assertEqual(
                    worker.region_shape(triangle, 1.0, width, height), (False, 0.0)
                )

    def test_a_region_within_one_point_of_the_search_box_edge_touches_it(self):
        def touches(low_x, low_y, high_x, high_y):
            polygon = [low_x, low_y, high_x, low_y, high_x, high_y, low_x, high_y]
            return worker.region_shape(polygon, 1.0, 200.0, 100.0)[0]

        self.assertFalse(touches(1.5, 20, 150, 60))
        self.assertTrue(touches(1.0, 20, 150, 60))
        self.assertFalse(touches(20, 1.5, 150, 60))
        self.assertTrue(touches(20, 1.0, 150, 60))
        self.assertFalse(touches(20, 20, 198.5, 60))
        self.assertTrue(touches(20, 20, 199.0, 60))
        self.assertFalse(touches(20, 20, 150, 98.5))
        self.assertTrue(touches(20, 20, 150, 99.0))

    def test_the_auto_seed_accepts_a_region_of_exactly_half_the_search_box(self):
        half = {"polygon_ost": [20, 0, 70, 0, 70, 200, 20, 200]}
        larger = {"polygon_ost": [20, 0, 70, 0, 70, 201, 20, 201]}
        self.assertIs(worker.seed_region([larger, half], 1.0, 100.0, 200.0), half)
        self.assertIsNone(worker.seed_region([larger], 1.0, 100.0, 200.0))

    def test_title_block_text_starts_at_seventy_and_eighty_percent_of_the_page(self):
        from tools.ai_takeoff_corpus import TextRun

        def count(left, right, top, bottom):
            return worker.drawing_text_runs(
                [TextRun("X", left, top, right, bottom)], 100.0, 100.0
            )

        self.assertEqual(count(60, 79, 10, 20), 1)
        self.assertEqual(count(60, 80, 10, 20), 0)
        self.assertEqual(count(10, 20, 70, 89), 1)
        self.assertEqual(count(10, 20, 70, 90), 0)

    def test_page_sizes_match_within_a_little_over_half_an_inch(self):
        label = worker._size_class
        self.assertEqual(label(36 * 72 + 30, 24 * 72), "ARCH D 24x36")
        self.assertEqual(label(36 * 72, 24 * 72 - 30), "ARCH D 24x36")
        self.assertEqual(label(36 * 72 + 65, 24 * 72), "other 37x24")
        self.assertEqual(label(36 * 72, 24 * 72 + 65), "other 36x25")
        self.assertEqual(label(36 * 72, 20 * 72), "other 36x20")
        self.assertEqual(label(40 * 72, 24 * 72), "other 40x24")
        self.assertEqual(label(11 * 72, 8.5 * 72), "Letter")

    def test_interior_points_start_at_the_centre_of_the_region(self):
        square = [0, 0, 200, 0, 200, 100, 0, 100]
        self.assertEqual(worker._interior_point(square, 2.0), [47.5, 23.75])
        offset = [100, 40, 300, 40, 300, 140, 100, 140]
        self.assertEqual(worker._interior_point(offset, 2.0), [97.5, 43.75])
        self.assertIsNone(worker._interior_point([0, 0, 1, 0, 2, 0], 1.0))

    def test_region_summaries_count_leaks_gaps_and_pass_the_exclusions_through(self):
        timing = {"status": "ok", "seconds": 0.5}
        result = {
            "data": {
                "regions": [
                    {"leak_risk": True, "gaps": [1, 2]},
                    {"leak_risk": False, "gaps": []},
                    {"leak_risk": True, "gaps": [3]},
                ],
                "total_count": 7,
                "suppressed_symbol_count": 4,
                "excluded": {"thin": 2, "dashed": 1},
            }
        }
        self.assertEqual(
            worker._region_summary("list", timing, result),
            {
                "list_status": "ok",
                "list_seconds": 0.5,
                "list_regions": 7,
                "list_leaks": 2,
                "list_gaps": 3,
                "list_suppressed": 4,
                "list_excluded": '{"dashed": 1, "thin": 2}',
            },
        )
        bare = {"data": {"regions": [{"leak_risk": False, "gaps": []}]}}
        self.assertEqual(
            worker._region_summary("x", timing, bare),
            {
                "x_status": "ok",
                "x_seconds": 0.5,
                "x_regions": 1,
                "x_leaks": 0,
                "x_gaps": 0,
                "x_suppressed": "",
                "x_excluded": "{}",
            },
        )
        failed = {"status": "invalid_argument", "seconds": 0.25}
        self.assertEqual(
            worker._region_summary("y", failed, None),
            {
                "y_status": "invalid_argument",
                "y_seconds": 0.25,
                "y_regions": 0,
                "y_leaks": 0,
                "y_gaps": 0,
                "y_suppressed": "",
                "y_excluded": "{}",
            },
        )

    def test_a_seeded_variant_records_the_region_it_found_and_why_it_found_none(self):
        class Proposal:
            def __init__(self, outcome):
                self.outcome = outcome
                self.calls = []

            def find_regions(self, snapshot, whole, **kwargs):
                self.calls.append((snapshot, whole, kwargs))
                if isinstance(self.outcome, Exception):
                    raise self.outcome
                return self.outcome

        def variant(outcome, min_width=1.5):
            proposal = Proposal(outcome)
            row = worker._seeded_variant(
                "v",
                proposal,
                "snap",
                [0.0, 0.0, 200.0, 100.0],
                [5.0, 6.0],
                min_width,
                1.0,
            )
            self.assertEqual(
                proposal.calls,
                [
                    (
                        "snap",
                        [0.0, 0.0, 200.0, 100.0],
                        {
                            "seed_pts": [5.0, 6.0],
                            "min_width": min_width,
                            "max_gap_in": 36.0,
                        },
                    )
                ],
            )
            return {key: value for key, value in row.items() if key != "v_seconds"}

        region = {
            "polygon_ost": [20, 20, 80, 20, 80, 60, 20, 60],
            "method": "vector",
            "area_sf": 12.5,
            "leak_risk": True,
            "open_gaps": [1, 2],
            "dashed_outline": {"x": 1},
        }
        self.assertEqual(
            variant(
                {"status": "ok", "data": {"regions": [region], "segment_count": 9}}
            ),
            {
                "v_status": "ok",
                "v_min_width": 1.5,
                "v_found": True,
                "v_segments": 9,
                "v_method": "vector",
                "v_area_sf": 12.5,
                "v_touches_edge": False,
                "v_box_ratio": round(2400.0 / 20000.0, 4),
                "v_leak": True,
                "v_open_gaps": 2,
                "v_dashed_outline": True,
                "v_wall_failure": False,
            },
        )
        plain = dict(region, open_gaps=None, dashed_outline=None, leak_risk=False)
        found = variant(
            {"status": "ok", "data": {"regions": [plain], "segment_count": 0}}
        )
        self.assertEqual(
            (found["v_open_gaps"], found["v_dashed_outline"], found["v_wall_failure"]),
            (0, False, True),
        )
        self.assertEqual(
            variant(
                {"status": "ok", "data": {"regions": [], "segment_count": 0}}, None
            ),
            {
                "v_status": "ok",
                "v_min_width": None,
                "v_found": False,
                "v_segments": 0,
                "v_wall_failure": True,
            },
        )
        self.assertEqual(
            variant({"status": "ok", "data": {"regions": [], "segment_count": 5}}),
            {
                "v_status": "ok",
                "v_min_width": 1.5,
                "v_found": False,
                "v_segments": 5,
                "v_wall_failure": False,
            },
        )
        self.assertEqual(
            variant({"status": "ok", "data": {"regions": []}})["v_segments"], 0
        )
        self.assertEqual(
            variant(RuntimeError("SECRET")),
            {
                "v_status": "exception:RuntimeError",
                "v_min_width": 1.5,
                "v_found": False,
            },
        )

    def test_sheet_hint_rows_report_the_sheet_number_source_and_a_missing_title_block(
        self,
    ):
        hints = {
            "text_extractable": False,
            "reason": None,
            "sheet_number": None,
            "sheet_number_source": None,
            "scale_candidates": [],
            "plan_scale": {"status": "none", "label": None},
            "title_block_crop_pts": None,
        }
        row = worker.sheet_hint_row(4, hints)
        self.assertEqual(row["title_block_crop"], False)
        self.assertEqual(row["plan_scale_label"], "")
        self.assertEqual(row["scale_views"], "{}")
        self.assertEqual(row["scale_candidates"], 0)

    def test_peak_memory_converts_the_working_set_to_megabytes_with_one_decimal(self):
        from types import SimpleNamespace

        calls = []

        def memory_info(handle, reference, size):
            calls.append((handle, size))
            reference._obj.PeakWorkingSetSize = int(5.25 * 1024 * 1024)

        libraries = {
            "psapi": SimpleNamespace(GetProcessMemoryInfo=memory_info),
            "kernel32": SimpleNamespace(GetCurrentProcess=lambda: 77),
        }
        with mock.patch.object(worker.ctypes, "WinDLL", lambda name: libraries[name]):
            self.assertEqual(worker.peak_mb(), 5.2)
        self.assertEqual(calls, [(77, worker.ctypes.sizeof(worker._Counters))])

    def test_long_line_lengths_are_summed_to_a_tenth_of_a_point(self):
        from ost_visualizer.domain.services.ai_linework import LineSegment

        items = [LineSegment(0, i, 72.26, i, width=2.0) for i in range(4)]
        histogram = json.loads(worker.wall_profile(items)["long_width_histogram"])
        self.assertEqual(histogram, {"2.0": 289.0})

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

    def prepared_plan(self, content, **options):
        pdf = write_content_pdf(self.work / "plan.pdf", content, **options)
        prepared = self.prepare_in_subprocess(pdf, "plan.json")
        return pdf, prepared, prepared["pages"][0]["uid"]

    def prepare_in_subprocess(self, pdf, json_name):
        # Access databases are created in a child process: every in-process DAO
        # engine stays alive until the test process ends and exhausts Jet's
        # "client tasks" when the whole suite shares one process.
        prepared_path = self.work / json_name
        self.call("prepare", str(pdf), str(self.work), str(prepared_path))
        return json.loads(prepared_path.read_text(encoding="utf-8"))

    def test_the_measured_row_reports_the_page_text_and_linework_counts(self):
        _pdf, prepared, uid = self.prepared_plan(fx.s101_content() + TITLE)
        seeds = [{"seed_pts": fx.SEED_PTS, "expected_sf": round(fx.ROOM_AREA_SF, 2)}]
        row = worker.measure_page(prepared, uid, seeds)
        label = '1/8"=1\'-0"'
        expected = {
            "status": "ok",
            "width_pts": 612.0,
            "height_pts": 792.0,
            "rotation": 0,
            "visible_offset": "no",
            "page_size_class": "Letter",
            "text_runs": 16,
            "segments": 143,
            "curves": 88,
            "extraction_truncated": False,
            "content": "vector_and_text",
            "outlined_text": False,
            "kind": "plan",
            "title": "FOUNDATION PLAN",
            "sheet_number_legacy": "S-101",
            "scale_status": "single",
            "scale_label": label,
            "scale_hits": 1,
            "plan_scale_status": "resolved",
            "plan_scale_label": label,
            "scale_used": label,
            "kinds_wall": 24,
            "kinds_dashed": 20,
            "kinds_thin": 28,
            "kinds_symbol": 71,
            "dash_arrays": 1,
            "dominant_wall_width": 2.0,
            "heaviest_long_width": 2.0,
            "drawing_text_runs": 9,
            "callouts_as_lines": False,
            "seed_source": "hand",
            "list_status": "ok",
            "list_extraction_scope": "page",
            "filtered_status": "ok",
            "seed_status": "ok",
            "seed_method": "vector",
            "seed_gaps": 1,
            "proposal_status": "ok",
            "proposal_assumptions": 1,
            "proposal_subjects": '{"closing_segment": 1}',
            "proposal_outline_vertices": 5,
            "proposal_hole_vertices": 0,
            "proposal_holes_dropped": 0,
            "hand_expected_sf": 333.33,
        }
        self.assertEqual({key: row[key] for key in expected}, expected)
        self.assertEqual(json.loads(row["widths"])["fill"], 12)
        self.assertEqual(sum(json.loads(row["widths"]).values()), 143)
        self.assertGreater(row["heavy_threshold"], 0.0)
        self.assertGreater(row["list_regions"], 0)
        self.assertGreater(row["filtered_regions"], 0)
        self.assertEqual(row["list_gaps"], 0)
        self.assertAlmostEqual(row["seed_area_sf"], fx.ROOM_AREA_SF, delta=0.1)
        self.assertAlmostEqual(row["hand_error_pct"], 0.0, delta=0.5)
        for key in ("default_area_sf", "zero_area_sf", "heavy_area_sf"):
            self.assertAlmostEqual(row[key], fx.ROOM_AREA_SF, delta=0.1)

    def test_a_page_without_a_scale_label_is_measured_at_the_default_scale(self):
        title = (
            "BT /F1 14 Tf 450 60 Td (FOUNDATION PLAN) Tj ET\n"
            "BT /F1 20 Tf 520 20 Td (S-101) Tj ET\n"
        )
        _pdf, prepared, uid = self.prepared_plan(fx.s101_content() + title)
        seeds = [{"seed_pts": fx.SEED_PTS, "expected_sf": round(fx.ROOM_AREA_SF, 2)}]
        row = worker.measure_page(prepared, uid, seeds)
        self.assertEqual(
            (row["scale_status"], row["plan_scale_status"], row["plan_scale_label"]),
            ("none", "none", ""),
        )
        self.assertEqual(row["scale_used"], "default 1/8")
        self.assertEqual(row["scale_label"], "")
        self.assertAlmostEqual(row["seed_area_sf"], fx.ROOM_AREA_SF, delta=0.1)

    def test_a_cropped_page_reports_that_its_visible_area_is_offset(self):
        boxes = "/MediaBox [0 0 700 900] /CropBox [36 36 648 828]"
        _pdf, prepared, uid = self.prepared_plan(
            fx.s101_content() + TITLE, page_boxes=boxes
        )
        row = worker.measure_page(prepared, uid, [])
        self.assertEqual(
            (row["visible_offset"], row["width_pts"], row["height_pts"]),
            ("yes", 612.0, 792.0),
        )

    def test_a_vector_heavy_page_with_little_drawing_text_is_flagged_as_callouts(self):
        lines = "".join(
            f"{10 + i % 50} {100 + i} m {40 + i % 50} {100 + i} l S\n"
            for i in range(600)
        )
        _pdf, prepared, uid = self.prepared_plan(lines + TITLE)
        row = worker.measure_page(prepared, uid, [])
        self.assertEqual(row["kind"], "plan")
        self.assertGreaterEqual(row["segments"], 500)
        self.assertEqual(row["drawing_text_runs"], 0)
        self.assertTrue(row["callouts_as_lines"])

    def test_measuring_and_listing_remove_their_temporary_folders_and_clear_the_cache(
        self,
    ):
        from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache

        pdf, prepared, uid = self.prepared_plan(fx.s101_content() + TITLE)
        created = []
        original = worker.tempfile.TemporaryDirectory

        def tracked(*args, **kwargs):
            directory = original(*args, **kwargs)
            created.append(directory)
            return directory

        with mock.patch.object(worker.tempfile, "TemporaryDirectory", tracked):
            with mock.patch.object(
                PageCache, "clear", autospec=True, side_effect=PageCache.clear
            ) as cleared:
                worker.measure_page(prepared, uid, [])
                self.assertEqual(cleared.call_count, 1)
                worker.sheets(prepared, self.work / "sheets.json")
                self.assertEqual(cleared.call_count, 2)
        self.assertEqual(len(created), 2)
        self.assertFalse(any(Path(directory.name).exists() for directory in created))

    def test_main_dispatches_each_command_and_adds_the_peak_memory(self):
        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        prepared = self.prepare_in_subprocess(pdf, "plan.json")
        prepared_path = self.work / "plan.json"
        sheets_path = self.work / "sheets.json"
        self.assertEqual(
            worker.main(["sheets", str(prepared_path), str(sheets_path)]), 0
        )
        self.assertEqual(
            [row["sheet_number"] for row in json.loads(sheets_path.read_text("utf-8"))],
            ["S-101"],
        )
        out = self.work / "page.json"
        self.assertEqual(
            worker.main(
                [
                    "page",
                    str(prepared_path),
                    prepared["pages"][0]["uid"],
                    "[]",
                    str(out),
                ]
            ),
            0,
        )
        row = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(row["kind"], "plan")
        self.assertGreater(row["peak_mb"], 1.0)

    def test_prepare_creates_one_named_page_per_pdf_page_in_order(self):
        pdf = _pages_pdf(self.work / "set.pdf", [TITLE, TWO_PLANS, "0 0 m 9 9 l S\n"])
        prepared_path = self.work / "set.json"
        # The reference-metadata step needs a DAO engine; skipping it keeps this
        # in-process creation from using up the process's Jet client tasks.
        with mock.patch.object(
            access.DatabaseCreator,
            "_apply_reference_schema_metadata",
            lambda *a, **k: None,
        ):
            self.assertEqual(worker.prepare(pdf, self.work, prepared_path), 0)
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        self.assertEqual([page["index"] for page in prepared["pages"]], [0, 1, 2])
        self.assertEqual(prepared["pdf"], str(pdf))
        self.assertEqual(prepared["db"], str(self.work / "set.mdb"))
        connections = access.MdbConnectionManager()
        try:
            stored = access.MdbReader(connections).get_bid_data(
                prepared["db"], prepared["bid_uid"]
            )[3]
        finally:
            connections.close()
        by_uid = {str(uid): page for uid, page in stored.items()}
        self.assertEqual(
            [by_uid[page["uid"]].name for page in prepared["pages"]],
            ["Page 1", "Page 2", "Page 3"],
        )
        for page in prepared["pages"]:
            stored_page = by_uid[page["uid"]]
            self.assertEqual(
                (
                    stored_page.width_pts,
                    stored_page.height_pts,
                    stored_page.scale_factor1,
                    stored_page.scale_factor2,
                    stored_page.image_path,
                ),
                (612.0, 792.0, 0.125, 12.0, str(pdf)),
            )
        pdf.unlink()
        Path(prepared["db"]).unlink()
        self.assertFalse(pdf.exists() or Path(prepared["db"]).exists())

    def test_sheet_hints_in_process_cover_every_page_with_its_kind_in_page_order(self):
        pdf = _pages_pdf(
            self.work / "set.pdf", [TITLE, TWO_PLANS, "0 0 m 100 100 l S\n"]
        )
        self.prepare_in_subprocess(pdf, "set.json")
        prepared_path = self.work / "set.json"
        out = self.work / "set_sheets.json"
        self.assertEqual(worker.main(["sheets", str(prepared_path), str(out)]), 0)
        hints = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([hint["index"] for hint in hints], [0, 1, 2])
        self.assertEqual([hint["kind"] for hint in hints], ["plan", "plan", "unknown"])
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

    def test_pages_without_a_plan_or_without_linework_are_not_traced_in_process(self):
        skipped = ("skipped",) * 3
        keys = ("list_status", "filtered_status", "seed_status")
        notes = write_content_pdf(
            self.work / "notes.pdf",
            "BT /F1 14 Tf 450 60 Td (GENERAL NOTES) Tj ET\n0 0 m 100 100 l S\n",
        )
        prepared = self.prepare_in_subprocess(notes, "notes.json")
        row = worker.measure_page(prepared, prepared["pages"][0]["uid"], [])
        self.assertEqual((row["kind"], row["segments"]), ("general_notes", 1))
        self.assertEqual(tuple(row[key] for key in keys), skipped)
        self.assertNotIn("dominant_wall_width", row)
        empty = write_content_pdf(self.work / "empty.pdf", TITLE)
        prepared = self.prepare_in_subprocess(empty, "empty.json")
        row = worker.measure_page(prepared, prepared["pages"][0]["uid"], [])
        self.assertEqual((row["kind"], row["segments"]), ("plan", 0))
        self.assertEqual(tuple(row[key] for key in keys), skipped)
        self.assertNotIn("dominant_wall_width", row)

    def test_page_dimensions_are_reported_to_a_tenth_of_a_point(self):
        _pdf, prepared, uid = self.prepared_plan(
            fx.s101_content() + TITLE, width=612.34, height=791.66
        )
        row = worker.measure_page(prepared, uid, [])
        self.assertEqual((row["width_pts"], row["height_pts"]), (612.3, 791.7))

    def test_truncated_pages_count_only_the_quadrants_that_are_still_truncated(self):
        from ost_visualizer.presentation.services import ai_takeoff_pdf_source

        _pdf, prepared, uid = self.prepared_plan(fx.s101_content() + TITLE)
        for cap, quadrants in ((8, 3), (20, 2), (40, 1)):
            with self.subTest(cap=cap):
                with mock.patch.object(
                    ai_takeoff_pdf_source, "MAX_PAGE_PATH_ITEMS", cap
                ):
                    row = worker.measure_page(prepared, uid, [])
                self.assertTrue(row["extraction_truncated"])
                self.assertEqual(row["box_quadrants_truncated"], quadrants)

    def test_the_hand_seed_error_is_reported_in_percent_of_the_expected_area(self):
        _pdf, prepared, uid = self.prepared_plan(fx.s101_content() + TITLE)
        row = worker.measure_page(
            prepared, uid, [{"seed_pts": fx.SEED_PTS, "expected_sf": 300.0}]
        )
        self.assertAlmostEqual(row["hand_error_pct"], 11.111, places=2)
        self.assertEqual(row["hand_expected_sf"], 300.0)
        self.assertEqual(row["hand_error_pct"], round(row["hand_error_pct"], 3))

    def test_main_reads_the_command_line_when_no_arguments_are_passed(self):
        pdf = write_content_pdf(self.work / "plan.pdf", fx.s101_content() + TITLE)
        self.prepare_in_subprocess(pdf, "plan.json")
        out = self.work / "sheets.json"
        command = ["worker", "sheets", str(self.work / "plan.json"), str(out)]
        with mock.patch.object(sys, "argv", command):
            self.assertEqual(worker.main(), 0)
        self.assertEqual(
            [
                row["sheet_number"]
                for row in json.loads(out.read_text(encoding="utf-8"))
            ],
            ["S-101"],
        )

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
