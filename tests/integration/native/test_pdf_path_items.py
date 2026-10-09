import math
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.presentation.visualization.pdf import ost_pdf
from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf

CAP = 100000
CIRCLE_K = 0.5523


def _circle(cx, cy, r):
    k = CIRCLE_K * r
    return (
        f"{cx + r} {cy} m "
        f"{cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} c "
        f"{cx - k} {cy + r} {cx - r} {cy + k} {cx - r} {cy} c "
        f"{cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} c "
        f"{cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy} c "
    )


class PdfPathItemsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def extract(self, content, forms=(), max_items=CAP):
        path = write_content_pdf(
            Path(self.directory.name) / f"p{len(content)}_{len(forms)}.pdf",
            content,
            forms=forms,
        )
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:
            return renderer.extract_path_items(0, max_items), renderer
        finally:
            renderer.close()

    def items(self, content, forms=()):
        extraction, _renderer = self.extract(content, forms)
        self.assertFalse(extraction.truncated)
        return list(extraction.items)

    def test_stroke_width_dash_and_color_are_scaled_by_the_transform(self):
        (item,) = self.items(
            "2 0 0 2 0 0 cm 0.5 w [3 2] 0 d 1 0 0 RG 10 10 m 50 10 l S"
        )
        self.assertEqual(
            (item.x1, item.y1, item.x2, item.y2), (20.0, 20.0, 100.0, 20.0)
        )
        self.assertAlmostEqual(item.stroke_width, 1.0, places=5)
        self.assertEqual([round(value, 5) for value in item.dash], [6.0, 4.0])
        self.assertEqual(item.stroke_rgba, 0xFF0000FF)
        self.assertTrue(item.stroked)
        self.assertFalse(item.filled)
        self.assertFalse(item.curve)
        self.assertFalse(item.closed)

    def test_huge_dash_arrays_are_capped_per_piece(self):
        dash = " ".join("1 2" for _ in range(10000))
        lines = "".join(f"10 {10 + i} m 50 {10 + i} l S " for i in range(3))
        items = self.items(f"0.5 w [{dash}] 0 d {lines}")
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertEqual(list(item.dash), [1.0, 2.0] * 16)

    def test_solid_lines_have_no_dash_and_hairlines_have_zero_width(self):
        solid, hairline = self.items(
            "3 w 0 0 0 RG 10 10 m 50 10 l S 0 w 0 0 1 RG 10 20 m 50 20 l S"
        )
        self.assertEqual(list(solid.dash), [])
        self.assertAlmostEqual(solid.stroke_width, 3.0, places=5)
        self.assertEqual(hairline.stroke_width, 0.0)
        self.assertEqual(hairline.stroke_rgba, 0x0000FFFF)

    def test_fill_only_rectangle_is_closed_and_not_stroked(self):
        items = self.items("0 0 1 rg 10 10 20 30 re f")
        self.assertEqual(len(items), 4)
        for item in items:
            self.assertTrue(item.filled)
            self.assertFalse(item.stroked)
            self.assertTrue(item.closed)
            self.assertEqual(item.fill_rgba, 0x0000FFFF)
        self.assertEqual(
            {(item.x1, item.y1) for item in items},
            {(10.0, 10.0), (30.0, 10.0), (30.0, 40.0), (10.0, 40.0)},
        )

    def test_stroke_and_fill_sets_both_flags(self):
        items = self.items("0 1 0 rg 1 0 0 RG 10 10 20 20 re B")
        self.assertTrue(all(item.stroked and item.filled for item in items))

    def test_bezier_curves_are_flattened_close_to_the_circle(self):
        items = self.items("1 w " + _circle(200.0, 300.0, 50.0) + "h S")
        self.assertGreaterEqual(len(items), 16)
        self.assertLessEqual(len(items), 4 * 32 + 1)
        curved = [item for item in items if item.curve]
        self.assertGreaterEqual(len(curved), 16)
        for item in curved:
            for x, y in ((item.x1, item.y1), (item.x2, item.y2)):
                self.assertAlmostEqual(
                    math.hypot(x - 200.0, y - 300.0), 50.0, delta=0.2
                )
            middle = ((item.x1 + item.x2) / 2.0, (item.y1 + item.y2) / 2.0)
            self.assertLess(
                50.0 - math.hypot(middle[0] - 200.0, middle[1] - 300.0), 0.3
            )
        self.assertTrue(all(item.closed for item in items))
        first, last = curved[0], curved[-1]
        self.assertAlmostEqual(first.x1, last.x2, places=3)
        self.assertAlmostEqual(first.y1, last.y2, places=3)

    def test_curves_are_still_ignored_by_extract_path_segments(self):
        path = write_content_pdf(
            Path(self.directory.name) / "curve.pdf",
            "1 w " + _circle(200.0, 300.0, 50.0) + "S",
        )
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:
            self.assertEqual(list(renderer.extract_path_segments(0)), [])
        finally:
            renderer.close()

    def test_form_xobjects_are_followed_with_their_matrices(self):
        items = self.items(
            "q 1 0 0 1 100 200 cm /X1 Do Q 5 5 m 6 5 l S",
            forms=(("X1", "2 0 0 2 0 0", "0.5 w 0 0 m 10 0 l S"),),
        )
        form_item = next(item for item in items if item.object_id != "1")
        self.assertEqual(form_item.object_id, "0.0")
        self.assertAlmostEqual(form_item.x1, 100.0, places=4)
        self.assertAlmostEqual(form_item.y1, 200.0, places=4)
        self.assertAlmostEqual(form_item.x2, 120.0, places=4)
        self.assertAlmostEqual(form_item.y2, 200.0, places=4)
        self.assertAlmostEqual(form_item.stroke_width, 1.0, places=5)
        page_item = next(item for item in items if item.object_id == "1")
        self.assertEqual((page_item.x1, page_item.x2), (5.0, 6.0))

    def test_nested_forms_compose_every_matrix(self):
        items = self.items(
            "q 1 0 0 1 10 0 cm /A Do Q",
            forms=(
                ("A", "1 0 0 1 0 20", "q 3 0 0 3 0 0 cm /B Do Q"),
                ("B", "1 0 0 1 1 1", "0 0 m 2 0 l S"),
            ),
        )
        (item,) = items
        self.assertEqual(item.object_id, "0.0.0")
        self.assertAlmostEqual(item.x1, 13.0, places=4)
        self.assertAlmostEqual(item.y1, 23.0, places=4)
        self.assertAlmostEqual(item.x2, 19.0, places=4)
        self.assertAlmostEqual(item.y2, 23.0, places=4)

    def test_ids_are_stable_and_unique_across_calls(self):
        content = (
            "10 10 m 50 10 l 50 50 l S 0 0 1 rg 60 60 10 10 re f "
            + _circle(200.0, 200.0, 20.0)
            + "S"
        )
        first = self.items(content)
        second = self.items(content)
        keys = [(i.object_id, i.subpath_index, i.segment_index) for i in first]
        self.assertEqual(
            keys, [(i.object_id, i.subpath_index, i.segment_index) for i in second]
        )
        self.assertEqual(
            len({(i.object_id, i.segment_index) for i in first}), len(first)
        )
        self.assertEqual([i.segment_index for i in first if i.object_id == "0"], [0, 1])

    def test_subpaths_are_numbered_and_only_closed_ones_are_marked(self):
        items = self.items("10 10 m 50 10 l S 0 0 m 5 0 l 5 5 l h S")
        open_line = [item for item in items if item.object_id == "0"]
        triangle = [item for item in items if item.object_id == "1"]
        self.assertFalse(any(item.closed for item in open_line))
        self.assertEqual(len(triangle), 3)
        self.assertTrue(all(item.closed for item in triangle))
        two = self.items("0 0 m 5 0 l 0 10 m 5 10 l 5 15 l 0 10 l S")
        self.assertEqual([item.subpath_index for item in two], [0, 1, 1, 1])
        self.assertEqual([item.closed for item in two], [False, True, True, True])

    def test_max_items_truncates_and_reports_it(self):
        extraction, _renderer = self.extract(
            "10 10 20 20 re S 50 50 20 20 re S", max_items=3
        )
        self.assertTrue(extraction.truncated)
        self.assertEqual(len(extraction.items), 3)
        exact, _renderer = self.extract("10 10 20 20 re S", max_items=4)
        self.assertFalse(exact.truncated)
        self.assertEqual(len(exact.items), 4)

    def test_a_box_limits_the_pieces_and_the_cap_counts_only_the_box(self):
        content = "10 10 m 50 10 l S 300 300 m 340 300 l S 90 200 m 400 200 l S"
        path = write_content_pdf(Path(self.directory.name) / "boxed.pdf", content)
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:
            whole = renderer.extract_path_items(0, 2)
            self.assertTrue(whole.truncated)
            self.assertEqual(len(whole.items), 2)
            boxed = renderer.extract_path_items(0, 1, (280.0, 250.0, 360.0, 350.0))
            self.assertFalse(boxed.truncated)
            self.assertEqual([(i.x1, i.x2) for i in boxed.items], [(300.0, 340.0)])
            crossing = renderer.extract_path_items(0, CAP, (100.0, 150.0, 120.0, 250.0))
            self.assertEqual([(i.x1, i.x2) for i in crossing.items], [(90.0, 400.0)])
            self.assertEqual(crossing.items[0].object_id, "2")
            touching = renderer.extract_path_items(0, CAP, (50.0, 0.0, 60.0, 10.0))
            self.assertEqual([(i.x1, i.x2) for i in touching.items], [(10.0, 50.0)])
            empty = renderer.extract_path_items(0, CAP, (500.0, 500.0, 600.0, 600.0))
            self.assertEqual((list(empty.items), empty.truncated), ([], False))
            self.assertEqual(len(renderer.extract_path_items(0, CAP, None).items), 3)
        finally:
            renderer.close()

    def test_box_boundaries(self):
        content = (
            "10 10 m 50 10 l S "
            "0 100 m 400 100 l S "
            "200 200 m 200 260 l S "
            "300 300 m 340 300 l 340 340 l 300 340 l h S"
        )
        path = write_content_pdf(Path(self.directory.name) / "edges.pdf", content)
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:

            def pieces(box):
                return [
                    (i.object_id, i.x1, i.y1, i.x2, i.y2)
                    for i in renderer.extract_path_items(0, CAP, box).items
                ]

            self.assertEqual(
                pieces((150.0, 90.0, 160.0, 110.0)), [("1", 0.0, 100.0, 400.0, 100.0)]
            )
            self.assertEqual(
                pieces((200.0, 260.0, 200.0, 260.0)),
                [("2", 200.0, 200.0, 200.0, 260.0)],
            )
            self.assertEqual(
                pieces((340.0, 320.0, 360.0, 330.0)),
                [("3", 340.0, 300.0, 340.0, 340.0)],
            )
            self.assertEqual(pieces((500.0, 500.0, 500.0, 500.0)), [])
            self.assertEqual(
                pieces((160.0, 110.0, 150.0, 90.0)), pieces((150.0, 90.0, 160.0, 110.0))
            )
            for bad in (
                (float("nan"), 0.0, 10.0, 10.0),
                (0.0, 0.0, float("inf"), 10.0),
            ):
                with self.subTest(box=bad):
                    with self.assertRaises(ValueError):
                        renderer.extract_path_items(0, CAP, bad)
        finally:
            renderer.close()

    def test_truncation_means_a_piece_was_left_out(self):
        path = write_content_pdf(
            Path(self.directory.name) / "trunc.pdf",
            "10 10 m 100 10 l S BT /F1 12 Tf 50 50 Td (Hi) Tj ET 120 120 m 130 120 l S 0 300 m 300 300 l S",
        )
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:
            whole = renderer.extract_path_items(0, 1)
            self.assertEqual((len(whole.items), whole.truncated), (1, True))
            only_text_after = renderer.extract_path_items(0, 1, (0.0, 0.0, 110.0, 60.0))
            self.assertEqual(
                (len(only_text_after.items), only_text_after.truncated), (1, False)
            )
            boxed = renderer.extract_path_items(0, 1, (100.0, 100.0, 200.0, 200.0))
            self.assertEqual((len(boxed.items), boxed.truncated), (1, False))
            two = renderer.extract_path_items(0, 1, (0.0, 0.0, 400.0, 400.0))
            self.assertEqual((len(two.items), two.truncated), (1, True))
        finally:
            renderer.close()

    def test_ids_do_not_depend_on_the_box(self):
        path = write_content_pdf(
            Path(self.directory.name) / "ids.pdf",
            "10 10 m 100 10 l 100 300 l 10 300 l S",
        )
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:

            def keyed(box):
                return {
                    (i.object_id, i.subpath_index, i.segment_index): (
                        i.x1,
                        i.y1,
                        i.x2,
                        i.y2,
                    )
                    for i in renderer.extract_path_items(0, CAP, box).items
                }

            whole = keyed(None)
            boxed = keyed((50.0, 250.0, 200.0, 400.0))
            self.assertEqual(len(boxed), 2)
            for key, piece in boxed.items():
                self.assertEqual(whole[key], piece)
        finally:
            renderer.close()

    def test_text_and_zero_length_pieces_are_skipped(self):
        items = self.items(
            "BT /F1 12 Tf 10 10 Td (Hello) Tj ET 5 5 m 5 5 l S 1 1 m 2 1 l S"
        )
        self.assertEqual([(i.x1, i.x2) for i in items], [(1.0, 2.0)])

    def test_invalid_pages_return_nothing(self):
        path = write_content_pdf(Path(self.directory.name) / "one.pdf", "0 0 m 1 1 l S")
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(str(path)))
        try:
            for index in (-1, 1, 99):
                extraction = renderer.extract_path_items(index, CAP)
                self.assertEqual(list(extraction.items), [])
                self.assertFalse(extraction.truncated)
        finally:
            renderer.close()
        self.assertEqual(
            list(ost_pdf.PDFRenderer().extract_path_items(0, CAP).items), []
        )


if __name__ == "__main__":
    unittest.main()
