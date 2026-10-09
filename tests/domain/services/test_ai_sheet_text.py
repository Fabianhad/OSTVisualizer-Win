import unittest
from ost_visualizer.domain.services.ai_sheet_text import (
    SheetCandidate,
    TextLine,
    consistent_sheet_numbers,
    parse_dimension_in,
    parse_scale_label,
    plan_scale,
    scale_candidates,
    sheet_number,
    sheet_number_candidates,
    text_lines,
    title_block_crop,
)

W = 2592.0
H = 1728.0


def line(text, left, top, height=10.0, width=None):
    width = width if width is not None else 0.6 * height * len(text)
    return TextLine(text, left, top, left + width, top + height, height)


def corner(text, height=24.0):
    return line(text, 0.88 * W, 0.93 * H, height)


class TextLineTests(unittest.TestCase):
    def test_runs_on_a_baseline_join_and_lines_stay_apart(self):
        runs = [
            ("PLAN", 60, 100, 90, 110),
            ("FOUNDATION", 0, 101, 55, 111),
            ("SCALE:", 0, 200, 40, 210),
            (" ", 0, 300, 5, 310),
        ]
        lines = text_lines(runs)
        self.assertEqual([item.text for item in lines], ["FOUNDATION PLAN", "SCALE:"])
        self.assertEqual((lines[0].left, lines[0].right, lines[0].height), (0, 90, 10))
        self.assertEqual(text_lines([]), [])

    def test_wide_gaps_on_a_baseline_split_the_line(self):
        runs = [
            ("FOUNDATION PLAN", 50, 300, 170, 312),
            ("DETAIL 1", 300, 300, 360, 312),
            ("A", 360, 300, 366, 312),
        ]
        lines = text_lines(runs)
        self.assertEqual(
            [item.text for item in lines], ["FOUNDATION PLAN", "DETAIL 1 A"]
        )
        self.assertEqual((lines[1].left, lines[1].right), (300, 366))


class SheetNumberTests(unittest.TestCase):
    def test_the_large_title_block_number_wins(self):
        lines = [line("S-101", 300, 300, 30), corner("S-201", 30)]
        self.assertEqual(sheet_number(lines, W, H).number, "S-201")

    def test_formats(self):
        for text in ("S-101", "S2.01", "S201A", "SD-1.2", "SF4.22", "S100A", "S4.12"):
            with self.subTest(text=text):
                self.assertEqual(sheet_number([corner(text)], W, H).number, text)

    def test_text_next_to_a_sheet_label(self):
        for label in ("SHEET NO.", "SHEET NUMBER", "DRAWING NO", "DWG NO:", "SHEET"):
            with self.subTest(label=label):
                lines = [
                    line(label, 0.80 * W, 0.90 * H, 8),
                    line("S3.1", 0.80 * W, 0.90 * H + 14, 12),
                    corner("S9.9", 12),
                ]
                candidate = sheet_number(lines, W, H)
                self.assertEqual(
                    (candidate.number, candidate.source), ("S3.1", "label")
                )
        same_line = [line("SHEET NO: S-401", 0.8 * W, 0.9 * H, 10)]
        self.assertEqual(sheet_number(same_line, W, H).number, "S-401")

    def test_references_and_notes_are_rejected(self):
        for text in (
            "SEE 3/S501",
            "3/S501",
            "REFER TO S-301 FOR TYPICAL REINFORCING",
            "SIM S2.1",
            "DETAIL 4 S501",
            "TYP S-101",
            "SEE 790",
            "SEC 12",
            "SIM 3",
        ):
            with self.subTest(text=text):
                self.assertEqual(sheet_number_candidates([corner(text)], W, H), [])

    def test_s0_and_zero_sheets_are_false_positives(self):
        for text in ("S0", "S00", "S-0", "S 0"):
            with self.subTest(text=text):
                self.assertIsNone(sheet_number([corner(text)], W, H))
        self.assertEqual(sheet_number([corner("S0.1")], W, H).number, "S0.1")
        self.assertEqual(sheet_number([corner("S001")], W, H).number, "S001")

    def test_unlabelled_numbers_in_the_upper_right_drawing_area_are_references(self):
        for y in (0.1, 0.4, 0.65):
            with self.subTest(y=y):
                self.assertEqual(
                    sheet_number_candidates([line("SP326", 0.84 * W, y * H, 10)], W, H),
                    [],
                )
        self.assertEqual(
            sheet_number([line("SP326", 0.84 * W, 0.72 * H, 10)], W, H).number, "SP326"
        )
        self.assertEqual(sheet_number([corner("S 101")], W, H).number, "S 101")

    def test_a_number_far_from_the_title_block_needs_a_label(self):
        self.assertIsNone(sheet_number([line("S-101", 0.3 * W, 0.3 * H, 10)], W, H))
        lines = [
            line("SHEET", 0.3 * W, 0.3 * H, 8),
            line("S-101", 0.3 * W, 0.3 * H + 12, 10),
        ]
        self.assertEqual(sheet_number(lines, W, H).number, "S-101")

    def test_no_text_means_no_sheet_number(self):
        self.assertIsNone(sheet_number([], W, H))

    def test_scores_and_sources(self):
        lines = [
            corner("S-201", 24),
            line("SHEET NO", 0.3 * W, 0.3 * H, 8),
            line("S-101", 0.3 * W, 0.3 * H + 12, 12),
            line("S-301", 0.75 * W, 0.75 * H, 12),
            line("S-401", 0.1 * W, 0.9 * H, 12),
        ]
        found = {
            c.number: (round(c.score, 6), c.source)
            for c in sheet_number_candidates(lines, W, H)
        }
        self.assertEqual(
            found,
            {
                "S-201": (5.0, "title_block"),
                "S-101": (5.0, "label"),
                "S-301": (4.0, "title_block"),
                "S-401": (3.0, "title_block"),
            },
        )

    def test_labels_beside_the_number_and_on_the_same_line(self):
        beside = [
            line("SHEET NO", 0.3 * W, 0.3 * H, 10),
            line("S-501", 0.3 * W + 80, 0.3 * H, 10),
        ]
        candidate = sheet_number(beside, W, H)
        self.assertEqual((candidate.number, candidate.source), ("S-501", "label"))
        inline = sheet_number([line("SHEET NO: S-401", 0.3 * W, 0.3 * H, 10)], W, H)
        self.assertEqual((inline.number, inline.source), ("S-401", "label"))

    def test_candidates_carry_their_box_and_score_order(self):
        lines = [corner("S-201", 30), line("S-101", 0.1 * W, 0.85 * H, 10)]
        candidates = sheet_number_candidates(lines, W, H)
        self.assertEqual([c.number for c in candidates], ["S-201", "S-101"])
        self.assertGreater(candidates[0].score, candidates[1].score)
        self.assertEqual(candidates[0].bbox[:2], (0.88 * W, 0.93 * H))


class ConsistentSheetNumberTests(unittest.TestCase):
    def candidate(self, number, x, y, score=3.0, source="title_block"):
        return SheetCandidate(
            number, (x * W, y * H, x * W + 40, y * H + 20), score, source
        )

    def test_pages_follow_the_dominant_location(self):
        pages = [
            [self.candidate("S101", 0.9, 0.95)],
            [self.candidate("S102", 0.9, 0.95)],
            [
                self.candidate("S501", 0.75, 0.10, score=3.5),
                self.candidate("S103", 0.9, 0.95, score=3.0),
            ],
            [self.candidate("S104", 0.9, 0.951)],
        ]
        chosen = consistent_sheet_numbers([(W, H, page) for page in pages])
        self.assertEqual([c.number for c in chosen], ["S101", "S102", "S103", "S104"])

    def test_off_location_numbers_are_dropped_unless_labelled_and_the_best_near_one_wins(
        self,
    ):
        pages = [
            [self.candidate("S101", 0.9, 0.95)],
            [self.candidate("S102", 0.9, 0.95)],
            [self.candidate("S103", 0.9, 0.95)],
            [self.candidate("S9", 0.2, 0.2)],
            [self.candidate("S8", 0.3, 0.3, source="label")],
            [
                self.candidate("S10X", 0.9, 0.95, score=2.0),
                self.candidate("S105", 0.9, 0.95, score=3.0),
            ],
        ]
        chosen = consistent_sheet_numbers([(W, H, page) for page in pages])
        self.assertEqual(
            [None if c is None else c.number for c in chosen],
            ["S101", "S102", "S103", None, "S8", "S105"],
        )

    def test_scattered_numbers_have_no_dominant_location(self):
        pages = [
            [self.candidate("S101", 0.9, 0.95)],
            [self.candidate("S102", 0.2, 0.9)],
            [self.candidate("S103", 0.75, 0.1)],
        ]
        chosen = consistent_sheet_numbers([(W, H, page) for page in pages])
        self.assertEqual([c.number for c in chosen], ["S101", "S102", "S103"])

    def test_a_number_on_two_of_six_pages_is_kept(self):
        numbers = ["S1", "S1", "S2", "S3", "S4", "S5"]
        pages = [[self.candidate(number, 0.9, 0.95)] for number in numbers]
        chosen = consistent_sheet_numbers([(W, H, page) for page in pages])
        self.assertEqual([c.number for c in chosen], numbers)

    def test_a_number_repeated_on_most_pages_is_dropped_unless_labelled(self):
        pages = [[self.candidate("S1", 0.9, 0.95)] for _ in range(4)]
        self.assertEqual(
            consistent_sheet_numbers([(W, H, page) for page in pages]), [None] * 4
        )
        labelled = [[self.candidate("S1", 0.9, 0.95, source="label")] for _ in range(4)]
        self.assertEqual(
            [
                c.number
                for c in consistent_sheet_numbers([(W, H, page) for page in labelled])
            ],
            ["S1"] * 4,
        )

    def test_single_pages_and_empty_pages(self):
        self.assertEqual(consistent_sheet_numbers([]), [])
        self.assertEqual(consistent_sheet_numbers([(W, H, [])]), [None])
        only = self.candidate("S7", 0.2, 0.2)
        self.assertEqual(consistent_sheet_numbers([(W, H, [only])]), [only])


class ScaleTests(unittest.TestCase):
    def test_scale_labels(self):
        cases = {
            '1/8"=1\'-0"': ('1/8"=1\'-0"', 0.125, 12.0),
            '3/16" = 1\'-0"': ('3/16"=1\'-0"', 0.1875, 12.0),
            '1/4" = 1\' - 0"': ('1/4"=1\'-0"', 0.25, 12.0),
            "3/4” = 1’-0”": ('3/4"=1\'-0"', 0.75, 12.0),
            '1 1/2"=1\'-0"': ('1 1/2"=1\'-0"', 1.5, 12.0),
            '1" = 20\'-0"': ("1\"=20'", 1.0, 240.0),
            "NTS": ("NTS", None, None),
            "N.T.S.": ("NTS", None, None),
            "NOT TO SCALE": ("NTS", None, None),
            "GRAPHIC SCALE": ("graphic", None, None),
        }
        for text, (label, sf1, sf2) in cases.items():
            with self.subTest(text=text):
                (hit,) = parse_scale_label(text)
                self.assertEqual((hit[0], hit[1], hit[2]), (label, sf1, sf2))
        self.assertEqual(parse_scale_label('12" CONC SLAB'), [])
        self.assertEqual(parse_scale_label('0"=1\'-0"'), [])
        self.assertEqual(parse_scale_label('1/0"=1\'-0"'), [])
        self.assertEqual(parse_scale_label("1\"=0'"), [])
        self.assertEqual(parse_scale_label("TENTS"), [])

    def test_one_inch_to_the_foot_is_one_scale(self):
        self.assertEqual(parse_scale_label('1"=1\'-0"'), [('1"=1\'-0"', 1.0, 12.0)])
        lines = [
            line("FOUNDATION PLAN", 200, 900, 18),
            line('SCALE: 1" = 1\'-0"', 200, 922, 9),
        ]
        resolved = plan_scale(scale_candidates(lines))
        self.assertEqual(
            (resolved.status, resolved.candidate.label), ("resolved", '1"=1\'-0"')
        )
        self.assertEqual(parse_scale_label("1\"=10'"), [("1\"=10'", 1.0, 120.0)])

    def test_hyphenated_mixed_fractions(self):
        self.assertEqual(
            parse_scale_label('SCALE: 1-1/2"=1\'-0"'), [('1 1/2"=1\'-0"', 1.5, 12.0)]
        )
        self.assertEqual(
            parse_scale_label('3-1/2" = 1\'-0"'), [('3 1/2"=1\'-0"', 3.5, 12.0)]
        )

    def test_reference_notes_are_not_view_titles(self):
        lines = [
            line("TYPICAL FOOTING DETAIL", 200, 880, 14),
            line("SEE FOUNDATION PLAN FOR LOCATIONS", 200, 900, 9),
            line('SCALE: 3/4"=1\'-0"', 200, 914, 9),
        ]
        (candidate,) = scale_candidates(lines)
        self.assertEqual(
            (candidate.view_title, candidate.view_kind),
            ("TYPICAL FOOTING DETAIL", "detail"),
        )
        self.assertEqual(plan_scale([candidate]).status, "no_plan_view")

    def test_an_elevation_value_does_not_make_a_plan_an_elevation_view(self):
        from ost_visualizer.domain.services.ai_sheet_text import view_kind

        self.assertEqual(
            view_kind("LEVEL 2 FRAMING PLAN - SLAB ELEVATION 112'-0\""), "plan"
        )
        self.assertEqual(
            view_kind("FOUNDATION PLAN TOP OF SLAB ELEV. = 100'-0\""), "plan"
        )
        self.assertEqual(view_kind("NORTH ELEVATION"), "elevation")
        self.assertEqual(view_kind("BUILDING ELEVATIONS"), "elevation")

    def test_a_loose_scale_beside_titled_views_is_not_a_sheet_scale(self):
        lines = [
            line("DETAIL 1", 200, 900, 14),
            line('SCALE: 3/4"=1\'-0"', 200, 918, 9),
            line('SCALE: 1/8"=1\'-0"', 1800, 300, 9),
        ]
        self.assertEqual(plan_scale(scale_candidates(lines)).status, "no_plan_view")

    def test_each_scale_belongs_to_the_view_title_above_it(self):
        lines = [
            line("FOUNDATION PLAN", 200, 900, 18),
            line('SCALE: 1/8" = 1\'-0"', 200, 922, 9),
            line("TYPICAL FOOTING DETAIL", 1500, 900, 14),
            line('SCALE: 3/4" = 1\'-0"', 1500, 918, 9),
            line("SECTION A-A", 1500, 400, 14),
            line("NTS", 1500, 418, 9),
        ]
        candidates = scale_candidates(lines)
        found = {(c.label, c.view_title) for c in candidates}
        self.assertEqual(
            found,
            {
                ('1/8"=1\'-0"', "FOUNDATION PLAN"),
                ('3/4"=1\'-0"', "TYPICAL FOOTING DETAIL"),
                ("NTS", "SECTION A-A"),
            },
        )
        plan = next(c for c in candidates if c.view_title == "FOUNDATION PLAN")
        self.assertEqual(plan.view_kind, "plan")
        self.assertEqual(plan.bbox[:2], (200, 922))
        self.assertAlmostEqual(plan.ost_per_point, 12.0 / 9.0)

    def test_a_title_and_scale_on_one_line(self):
        (candidate,) = scale_candidates(
            [line('ROOF FRAMING PLAN   SCALE: 1/4"=1\'-0"', 100, 100)]
        )
        self.assertEqual(
            (candidate.view_title, candidate.view_kind), ("ROOF FRAMING PLAN", "plan")
        )

    def test_the_nearest_title_above_wins_and_far_titles_are_ignored(self):
        near = line("FOUNDATION PLAN", 200, 900, 18)
        farther = line("SECTION A", 200, 880, 14)
        scale = line('SCALE: 1/8" = 1\'-0"', 200, 922, 9)
        for lines in ([near, farther, scale], [farther, near, scale]):
            (candidate,) = scale_candidates(lines)
            self.assertEqual(candidate.view_title, "FOUNDATION PLAN")
        far = [
            line("FOUNDATION PLAN", 200, 100, 18),
            line('SCALE: 1/8" = 1\'-0"', 200, 300, 9),
        ]
        (alone,) = scale_candidates(far)
        self.assertEqual(alone.view_title, "")

    def test_a_scale_with_no_title_nearby_has_no_view(self):
        (candidate,) = scale_candidates(
            [line('SCALE: 1/4"=1\'-0"', 100, 100), line("FOUNDATION PLAN", 900, 900)]
        )
        self.assertEqual((candidate.view_title, candidate.view_kind), ("", ""))

    def test_plan_scale_is_resolved_only_without_ambiguity(self):
        def candidates(*pairs):
            lines = []
            for index, (title, scale) in enumerate(pairs):
                lines.append(line(title, 200 + 700 * index, 900, 18))
                lines.append(line(f"SCALE: {scale}", 200 + 700 * index, 922, 9))
            return scale_candidates(lines)

        resolved = plan_scale(
            candidates(("FOUNDATION PLAN", '1/8"=1\'-0"'), ("DETAIL 1", '3/4"=1\'-0"'))
        )
        self.assertEqual(
            (resolved.status, resolved.candidate.label), ("resolved", '1/8"=1\'-0"')
        )
        two = plan_scale(
            candidates(("FOUNDATION PLAN", '1/8"=1\'-0"'), ("ROOF PLAN", '1/8"=1\'-0"'))
        )
        self.assertEqual(two.status, "resolved")
        conflict = plan_scale(
            candidates(
                ("FOUNDATION PLAN", '1/8"=1\'-0"'), ("ENLARGED PLAN", '1/4"=1\'-0"')
            )
        )
        self.assertEqual((conflict.status, conflict.candidate), ("ambiguous", None))
        nts = plan_scale(candidates(("FOUNDATION PLAN", "NTS")))
        self.assertEqual(nts.status, "nts")
        details = plan_scale(
            candidates(("DETAIL 1", '3/4"=1\'-0"'), ("DETAIL 2", '1"=1\'-0"'))
        )
        self.assertEqual(details.status, "no_plan_view")
        single = plan_scale(
            scale_candidates([line('SCALE: 1/8"=1\'-0"', 2400, 1650, 9)])
        )
        self.assertEqual(
            (single.status, single.candidate.label), ("sheet", '1/8"=1\'-0"')
        )
        self.assertEqual(plan_scale([]).status, "none")
        graphic_only = plan_scale(candidates(("FOUNDATION PLAN", "GRAPHIC SCALE")))
        self.assertEqual((graphic_only.status, graphic_only.candidate), ("none", None))
        loose = scale_candidates(
            [
                line('SCALE: 1/8"=1\'-0"', 200, 200, 9),
                line('SCALE: 1/4"=1\'-0"', 1800, 1200, 9),
            ]
        )
        self.assertEqual(plan_scale(loose).status, "none")
        (nts,) = scale_candidates(
            [line("SECTION A", 100, 100, 14), line("NTS", 100, 118, 9)]
        )
        self.assertIsNone(nts.ost_per_point)


class DimensionTests(unittest.TestCase):
    def test_dimensions(self):
        cases = {
            "24'-0\"": 288.0,
            "24'-6\"": 294.0,
            "6'-8 1/2\"": 80.5,
            "10'": 120.0,
            "12' - 0\"": 144.0,
            "0'-8\"": 8.0,
            '8"': 8.0,
            '3 1/2"': 3.5,
        }
        for text, value in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_dimension_in(text), value)
        for text in ("S-101", '1/8"=1\'-0"', '#5 @ 12"', "", "FOUNDATION"):
            with self.subTest(text=text):
                self.assertIsNone(parse_dimension_in(text))


class TitleBlockCropTests(unittest.TestCase):
    def test_crop_follows_the_sheet_number_or_falls_back_to_the_right_strip(self):
        candidate = SheetCandidate(
            "S-101", (2300.0, 1600.0, 2400.0, 1630.0), 4.0, "title_block"
        )
        x, y, w, h = title_block_crop(W, H, candidate)
        self.assertTrue(
            x <= 2300.0 and y <= 1600.0 and x + w >= 2400.0 and y + h >= 1630.0
        )
        self.assertTrue(0.0 <= x and 0.0 <= y and x + w <= W and y + h <= H)
        for got, expected in zip((x, y, w, h), (1911.2, 1340.8, 618.4, 375.6)):
            self.assertAlmostEqual(got, expected, places=6)
        self.assertEqual(title_block_crop(W, H, None), [0.78 * W, 0.0, 0.22 * W, H])
        for box in (
            (W + 50.0, H + 20.0, W + 90.0, H + 40.0),
            (2 * W, 2 * H, 2 * W + 40, 2 * H + 20),
            (-600.0, -600.0, -550.0, -500.0),
        ):
            with self.subTest(box=box):
                x, y, w, h = title_block_crop(
                    W, H, SheetCandidate("S-101", box, 4.0, "title_block")
                )
                self.assertTrue(
                    0.0 <= x
                    and 0.0 <= y
                    and w >= 0.0
                    and h >= 0.0
                    and x + w <= W
                    and y + h <= H
                )
        self.assertEqual(title_block_crop(H, W, None), [0.0, 0.8 * W, H, 0.2 * W])


if __name__ == "__main__":
    unittest.main()
