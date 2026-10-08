"""Corpus harness helpers on synthetic data only (no client drawings)."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from tools import ai_takeoff_corpus as corpus
from tools.ai_takeoff_corpus import (
    KIND_DETAIL,
    KIND_NOTES,
    KIND_PLAN,
    KIND_SCHEDULE,
    KIND_SECTION,
    KIND_UNKNOWN,
    TextLine,
    TextRun,
    classify_page,
    page_scale,
    parse_scales,
    sheet_number,
    text_lines,
)

NATIVE_CRASH = (
    "import ctypes; from ctypes import wintypes; k = ctypes.WinDLL('kernel32'); "
    "k.GetCurrentProcess.restype = wintypes.HANDLE; "
    "k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]; "
    "k.TerminateProcess(k.GetCurrentProcess(), 0xC0000005)"
)
WIDTH = 2592.0
HEIGHT = 1728.0


def _line(text, left=100.0, top=100.0, height=10.0):
    return TextLine(text, left, top, left + 10.0 * len(text), top + height, height)


def _title(text, height=14.0):
    return _line(text, left=0.85 * WIDTH, top=0.9 * HEIGHT, height=height)


def _structural(year, project, name):
    return str(
        Path(
            year,
            project,
            "01. Drawings",
            "1. Drawings",
            "3. Structural",
            "1. Current",
            name,
        )
    )


class TextLineTests(unittest.TestCase):
    def test_runs_on_one_baseline_join_left_to_right(self):
        runs = [
            TextRun("PLAN", 60, 100, 90, 110),
            TextRun("FOUNDATION", 0, 101, 55, 111),
            TextRun("SCALE:", 0, 200, 40, 210),
            TextRun('1/8"', 45, 200, 60, 210),
        ]
        lines = text_lines(runs)
        self.assertEqual(
            [line.text for line in lines], ["FOUNDATION PLAN", 'SCALE: 1/8"']
        )
        self.assertEqual((lines[0].left, lines[0].right), (0, 90))

    def test_runs_far_apart_vertically_stay_separate_and_blank_runs_vanish(self):
        runs = [
            TextRun("A", 0, 0, 5, 10),
            TextRun("B", 0, 30, 5, 40),
            TextRun("  ", 0, 60, 5, 70),
        ]
        self.assertEqual([line.text for line in text_lines(runs)], ["A", "B"])
        self.assertEqual(text_lines([]), [])


class ClassificationTests(unittest.TestCase):
    def test_title_block_text_outweighs_view_labels(self):
        lines = [_line("TYPICAL DETAIL"), _line("SECTION A"), _title("FOUNDATION PLAN")]
        self.assertEqual(
            classify_page(lines, WIDTH, HEIGHT), (KIND_PLAN, "FOUNDATION PLAN")
        )

    def test_each_kind_and_unknown(self):
        cases = {
            "GENERAL STRUCTURAL NOTES": KIND_NOTES,
            "FOOTING SCHEDULE": KIND_SCHEDULE,
            "BUILDING SECTIONS": KIND_SECTION,
            "TYPICAL CONCRETE DETAILS": KIND_DETAIL,
            "SECOND FLOOR FRAMING PLAN": KIND_PLAN,
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_page([_title(text)], WIDTH, HEIGHT)[0], kind)
        self.assertEqual(
            classify_page([_line("COLUMN GRID")], WIDTH, HEIGHT), (KIND_UNKNOWN, "")
        )

    def test_notes_win_over_plan_words_on_the_same_line(self):
        lines = [_title("GENERAL NOTES FOR PLANS")]
        self.assertEqual(classify_page(lines, WIDTH, HEIGHT)[0], KIND_NOTES)

    def test_the_largest_title_block_line_is_the_title(self):
        lines = [_title("ROOF PLAN", 8.0), _title("FOUNDATION PLAN", 20.0)]
        self.assertEqual(classify_page(lines, WIDTH, HEIGHT)[1], "FOUNDATION PLAN")

    def test_text_outside_the_title_block_gives_no_title(self):
        self.assertEqual(
            classify_page([_line("FOUNDATION PLAN")], WIDTH, HEIGHT), (KIND_PLAN, "")
        )


class SheetNumberTests(unittest.TestCase):
    def test_formats(self):
        for text, expected in (
            ("S-101", "S-101"),
            ("S2.01", "S2.01"),
            ("S201A", "S201A"),
            ("SD-1.2", "SD-1.2"),
            ("PS100", "PS100"),
        ):
            with self.subTest(text=text):
                self.assertEqual(sheet_number([_title(text)], WIDTH, HEIGHT), expected)

    def test_title_block_and_large_text_win(self):
        lines = [
            _line("SEE S-501", height=30.0),
            _title("S-201", 10.0),
            _title("S-101", 24.0),
        ]
        self.assertEqual(sheet_number(lines, WIDTH, HEIGHT), "S-101")

    def test_references_in_long_notes_are_ignored(self):
        lines = [_title("REFER TO S-301 FOR ALL TYPICAL REINFORCING")]
        self.assertEqual(sheet_number(lines, WIDTH, HEIGHT), "")
        self.assertEqual(sheet_number([], WIDTH, HEIGHT), "")


class ScaleParsingTests(unittest.TestCase):
    def test_architectural_scales(self):
        cases = {
            'SCALE: 1/8"=1\'-0"': ('1/8"=1\'-0"', 0.125),
            'SCALE: 3/16" = 1\'-0"': ('3/16"=1\'-0"', 0.1875),
            '1/4" = 1\' - 0"': ('1/4"=1\'-0"', 0.25),
            '1 1/2"=1\'-0"': ('1 1/2"=1\'-0"', 1.5),
            "3/4\u201d = 1\u2019-0\u201d": ('3/4"=1\'-0"', 0.75),
            "1/8 IN = 1 FT": ('1/8"=1\'-0"', 0.125),
        }
        for text, (label, sf1) in cases.items():
            with self.subTest(text=text):
                (hit,) = parse_scales(text)
                self.assertEqual((hit.label, hit.sf1, hit.sf2), (label, sf1, 12.0))
        self.assertAlmostEqual(parse_scales('1/8"=1\'-0"')[0].ost_per_point, 12.0 / 9.0)

    def test_engineering_nts_and_graphic_scales(self):
        (hit,) = parse_scales('1" = 20\'-0"')
        self.assertEqual((hit.label, hit.sf1, hit.sf2), ("1\"=20'", 1.0, 240.0))
        for text in ("NTS", "N.T.S.", "NOT TO SCALE"):
            with self.subTest(text=text):
                self.assertEqual([h.label for h in parse_scales(text)], ["NTS"])
                self.assertIsNone(parse_scales(text)[0].ost_per_point)
        self.assertEqual([h.label for h in parse_scales("GRAPHIC SCALE")], ["graphic"])
        self.assertEqual(parse_scales('12" CONC. SLAB'), [])
        self.assertEqual(parse_scales("TENTS AND COVERS"), [])

    def test_page_scale_status(self):
        self.assertEqual(page_scale([_line('SCALE: 1/8"=1\'-0"')])[:1], ("single",))
        status, chosen, hits = page_scale(
            [_line('1/4"=1\'-0"'), _line('1/8"=1\'-0"'), _line('1/8"=1\'-0"')]
        )
        self.assertEqual((status, chosen.label, hits), ("multiple", '1/8"=1\'-0"', 3))
        self.assertEqual(page_scale([_line("NTS")]), ("nts", None, 0))
        self.assertEqual(
            page_scale([_line("GRAPHIC SCALE")]), ("graphic_only", None, 0)
        )
        self.assertEqual(page_scale([_line("PLAN")]), ("none", None, 0))


class SmallHelperTests(unittest.TestCase):
    def test_width_buckets(self):
        self.assertEqual(
            [
                corpus.width_bucket(value)
                for value in (None, 0.0, 0.3, 0.74, 1.0, 1.9, 2.0, 5.0)
            ],
            ["fill", "<0.25", "<0.5", "<0.75", "<1.5", "<2", ">=2", ">=2"],
        )

    def test_file_patterns(self):
        cases = {
            "S-101.pdf": "S-###",
            "S2.01.pdf": "S#.#",
            "S201.pdf": "S###",
            "1. Structural SET.pdf": "set",
            "UD0201.pdf": "other",
        }
        for name, label in cases.items():
            with self.subTest(name=name):
                self.assertEqual(corpus.file_pattern(name), label)

    def test_percentiles(self):
        self.assertEqual(corpus.percentile([3.0, 1.0, 2.0], 0.5), 2.0)
        self.assertEqual(corpus.percentile([1.0, 2.0], 0.5), 1.5)
        self.assertIsNone(corpus.percentile([], 0.5))

    def test_structural_paths(self):
        self.assertEqual(
            corpus.structural_parts(_structural("2024", "24-001 X", "S1.pdf")),
            ("2024", "24-001 X"),
        )
        self.assertIsNone(
            corpus.structural_parts(
                str(
                    Path(
                        "2022",
                        "P",
                        "01. Drawings",
                        "1. Drawings",
                        "3. Structural",
                        "a",
                        "S.pdf",
                    )
                )
            )
        )
        self.assertIsNone(
            corpus.structural_parts(
                str(
                    Path(
                        "2024",
                        "P",
                        "01. Drawings",
                        "1. Drawings",
                        "2. Arch",
                        "a",
                        "A.pdf",
                    )
                )
            )
        )

    def test_local_names_hide_the_path(self):
        name = corpus.local_name(_structural("2024", "Client Name", "S1.pdf"))
        self.assertRegex(name, r"^[0-9a-f]{16}\.pdf$")
        self.assertEqual(
            name, corpus.local_name(_structural("2024", "Client Name", "S1.pdf"))
        )

    def test_long_paths(self):
        if sys.platform != "win32":
            self.skipTest("Windows paths")
        self.assertEqual(
            corpus.long_path(Path("\\\\server\\share\\a.pdf")),
            "\\\\?\\UNC\\server\\share\\a.pdf",
        )
        self.assertEqual(corpus.long_path(Path("C:\\x\\a.pdf")), "\\\\?\\C:\\x\\a.pdf")


class SamplingTests(unittest.TestCase):
    def rows(self):
        rows = []
        for year in ("2023", "2024", "2025"):
            for project in range(4):
                for index, name in enumerate(
                    ("S-101.pdf", "S2.01.pdf", "S301.pdf", "Struct SET.pdf")
                ):
                    size = 50_000_000 if name.startswith("Struct") else 100_000 + index
                    rows.append(
                        {
                            "rel": _structural(year, f"{year}-P{project}", name),
                            "size": str(size),
                        }
                    )
        rows.append({"rel": str(Path("2024", "P9", "Arch", "A1.pdf")), "size": "1"})
        return rows

    def test_the_sample_spreads_over_years_projects_and_patterns(self):
        chosen = corpus.stratified_sample(self.rows(), 12)
        self.assertEqual(len(chosen), 12)
        self.assertEqual(len({row["rel"] for row in chosen}), 12)
        years = {Path(row["rel"]).parts[0] for row in chosen}
        projects = {Path(row["rel"]).parts[1] for row in chosen}
        self.assertEqual(years, {"2023", "2024", "2025"})
        self.assertEqual(len(projects), 12)
        self.assertGreaterEqual(
            len({corpus.file_pattern(row["rel"]) for row in chosen}), 3
        )
        self.assertEqual(chosen, corpus.stratified_sample(self.rows(), 12))

    def test_large_sets_come_from_different_projects_and_size_is_capped(self):
        chosen = corpus.stratified_sample(self.rows(), 12)
        large = [row for row in chosen if int(row["size"]) >= 50_000_000]
        self.assertGreaterEqual(len(large), 2)
        self.assertEqual(len({Path(row["rel"]).parts[1] for row in large}), len(large))
        capped = corpus.stratified_sample(self.rows(), 12, max_bytes=1_000_000)
        self.assertTrue(all(int(row["size"]) < 1_000_000 for row in capped))
        self.assertEqual(corpus.stratified_sample([], 5), [])

    def test_copy_skips_unreadable_files_and_keeps_only_the_sample(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as out_dir:
            source, out = Path(source_dir), Path(out_dir)
            rows = self.rows()[:16]
            for row in rows[1:]:
                path = source / row["rel"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-1.4 synthetic")
            (out / "files").mkdir()
            (out / "files" / "stale.pdf").write_bytes(b"x")
            copied = corpus.copy_sample(source, out, rows, 4, float("inf"))
            self.assertEqual(len(copied), 4)
            self.assertNotIn(rows[0]["rel"], {row["rel"] for row in copied})
            self.assertEqual(
                sorted(path.name for path in (out / "files").iterdir()),
                sorted(row["local"] for row in copied),
            )
            with open(out / "sample.csv", encoding="utf-8") as handle:
                self.assertEqual(
                    [row["rel"] for row in csv.DictReader(handle)],
                    [row["rel"] for row in copied],
                )
            with open(out / "hand_values.csv", encoding="utf-8") as handle:
                self.assertEqual(
                    handle.read().strip(), ",".join(corpus.HAND_VALUE_COLUMNS)
                )
            for row in rows:
                self.assertTrue((source / row["rel"]).exists() or row is rows[0])


class OutputFolderTests(unittest.TestCase):
    def test_output_inside_the_repository_is_refused(self):
        self.assertTrue(corpus.inside_repository(corpus.REPO_ROOT / "corpus_out"))
        self.assertFalse(corpus.inside_repository(corpus.DEFAULT_ROOT))
        with self.assertRaises(SystemExit):
            corpus.main(["report", "--out", str(corpus.REPO_ROOT / "corpus_out")])
        self.assertFalse((corpus.REPO_ROOT / "corpus_out").exists())


class HandValueTests(unittest.TestCase):
    def test_rows_are_parsed_and_bad_rows_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hand_values.csv"
            corpus.write_csv(
                path,
                [
                    {
                        "pdf": "a.pdf",
                        "page": "2",
                        "seed_x": "10",
                        "seed_y": "20.5",
                        "expected_sf": "279.31",
                    },
                    {
                        "pdf": "a.pdf",
                        "page": "x",
                        "seed_x": "1",
                        "seed_y": "1",
                        "expected_sf": "1",
                    },
                ],
                corpus.HAND_VALUE_COLUMNS,
            )
            values = corpus.hand_values(path)
            self.assertEqual(
                dict(values),
                {("a.pdf", 2): [{"seed_pts": [10.0, 20.5], "expected_sf": 279.31}]},
            )
            self.assertEqual(
                dict(corpus.hand_values(Path(directory) / "missing.csv")), {}
            )


class ChildProcessTests(unittest.TestCase):
    def test_timeouts_are_hangs_and_failures_name_the_exception(self):
        hang = corpus._run_child(
            [sys.executable, "-c", "import time; time.sleep(5)"], 0.5
        )
        self.assertEqual(hang["status"], "hang")
        error = corpus._run_child(
            [sys.executable, "-c", "raise MemoryError('secret text')"], 30
        )
        self.assertEqual(error, {"status": "error", "error": "exit 1: MemoryError"})
        crash = corpus._run_child([sys.executable, "-c", NATIVE_CRASH], 30)
        self.assertEqual(crash["status"], "crash")
        self.assertEqual(
            corpus._run_child([sys.executable, "-c", "pass"], 30),
            {"status": "ok", "error": ""},
        )


class ReportTests(unittest.TestCase):
    def test_report_has_rates_categories_and_no_unlisted_content(self):
        rows = [
            {
                "rel": "2024\\P1\\S-101.pdf",
                "page": "1",
                "status": "ok",
                "seconds": "2.0",
                "kind": KIND_PLAN,
                "content": "vector_and_text",
                "text_runs": "40",
                "sheet_number": "S-101",
                "title": "FOUNDATION PLAN",
                "scale_status": "none",
                "filtered_status": "ok",
                "filtered_regions": "3",
                "filtered_seconds": "12.5",
                "seed_status": "ok",
                "seed_method": "raster",
                "widths": '{"<0.5": 10}',
                "kinds_wall": "5",
                "hand_error_pct": "1.2",
            },
            {
                "rel": "2024\\P1\\S-102.pdf",
                "page": "2",
                "status": "hang",
                "error": "timeout after 180 s",
                "seconds": "180",
            },
            {
                "rel": "2025\\P2\\S-201.pdf",
                "page": "1",
                "status": "ok",
                "seconds": "1.0",
                "kind": KIND_UNKNOWN,
                "content": "raster_only",
                "text_runs": "0",
                "outlined_text": "True",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "summary_x.md").read_text(
                encoding="utf-8"
            )
        self.assertIn(
            "| Page measured without crash, hang or error | 2/3 (67%) |", text
        )
        self.assertIn("| Hand values within 0.5% | 0/1 (0%) |", text)
        for category in (
            "page failed: hang (timeout after 180 s)",
            "raster-only page (no vectors, no text)",
            "text drawn as outlines (no extractable text)",
            "plan without a readable scale",
            "plan: seeded region fell back to raster",
            "plan: find_regions slower than 10 s",
            "hand value off by more than 0.5%",
        ):
            with self.subTest(category=category):
                self.assertIn(category, text)
        self.assertIn(
            "| 2024\\P1\\S-101.pdf | 1 | S-101 | plan | FOUNDATION PLAN | none |", text
        )
        categories = dict(corpus.failure_categories([dict(row) for row in rows]))
        self.assertEqual(len(categories["page failed: hang (timeout after 180 s)"]), 1)


if __name__ == "__main__":
    unittest.main()
