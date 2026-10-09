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
            copied = corpus.copy_sample(source, out, rows, len(rows), float("inf"))
            self.assertEqual(len(copied), len(rows) - 1)
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


class SamplingEdgeTests(unittest.TestCase):
    def test_one_large_set_per_project_and_no_endless_loop_when_rows_run_out(self):
        rows = [
            {
                "rel": _structural("2025", "BIG", f"Struct {i}.pdf"),
                "size": str(60_000_000 + i),
            }
            for i in range(3)
        ] + [{"rel": _structural("2025", "SMALL", "S-101.pdf"), "size": "100"}]
        chosen = corpus.stratified_sample(rows, 12)
        self.assertEqual(len(chosen), 4)
        self.assertEqual(
            sorted(row["rel"] for row in chosen), sorted(row["rel"] for row in rows)
        )
        first_two = corpus.stratified_sample(rows, 2)
        self.assertEqual(len(first_two), 2)
        self.assertEqual(len({Path(row["rel"]).parts[1] for row in first_two}), 2)


class CommandLineTests(unittest.TestCase):
    def tree(self, source):
        files = {
            _structural("2025", "P1", "S-101.pdf"): b"%PDF-1.4 a",
            _structural("2025", "P1", "notes.txt"): b"x",
            _structural("2026", "P2", "S2.01.PDF"): b"%PDF-1.4 bb",
            str(Path("2026", "P3", "Arch", "A1.pdf")): b"%PDF-1.4 c",
        }
        for rel, data in files.items():
            path = source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (source / "2027").write_bytes(b"not a folder")
        return files

    def snapshot(self, source):
        return {str(p): p.read_bytes() for p in source.rglob("*") if p.is_file()}

    def test_inventory_sample_report_and_compare_from_the_command_line(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory:
            source, out = Path(directory) / "share", Path(directory) / "out"
            self.tree(source)
            before = self.snapshot(source)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.assertEqual(
                    corpus.main(
                        ["inventory", "--source", str(source), "--out", str(out)]
                    ),
                    0,
                )
                self.assertEqual(
                    corpus.main(
                        [
                            "sample",
                            "--source",
                            str(source),
                            "--out",
                            str(out),
                            "--count",
                            "2",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    corpus.main(
                        [
                            "sample",
                            "--source",
                            str(source),
                            "--out",
                            str(out),
                            "--count",
                            "2",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    corpus.main(["sample", "--out", str(out), "--count", "1"]), 0
                )
            inventory = corpus.read_csv(out / "inventory.csv")
            self.assertEqual(
                sorted(row["rel"] for row in inventory),
                sorted(
                    [
                        _structural("2025", "P1", "S-101.pdf"),
                        _structural("2026", "P2", "S2.01.PDF"),
                    ]
                ),
            )
            self.assertIn("2 PDFs", printed.getvalue())
            self.assertEqual(len(list((out / "files").iterdir())), 2)
            self.assertEqual(self.snapshot(source), before)
            run_csv = out / "corpus_run_1.csv"
            corpus.write_csv(
                run_csv,
                [{"rel": "a.pdf", "page": "1", "status": "ok", "kind": KIND_PLAN}],
                corpus.RUN_COLUMNS,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                corpus.main(["report", "--out", str(out), "--run", str(run_csv)])
                corpus.main(
                    [
                        "compare",
                        "--out",
                        str(out),
                        "--before",
                        str(run_csv),
                        "--run",
                        str(run_csv),
                    ]
                )
            self.assertTrue((out / "corpus_summary_1.md").is_file())
            self.assertIn(
                "| Sheet number found | 0/1 (0%) | 0/1 (0%) |",
                (out / "corpus_compare_1.md").read_text(encoding="utf-8"),
            )


class OutputFolderTests(unittest.TestCase):
    def test_output_inside_the_repository_is_refused(self):
        self.assertTrue(corpus.inside_repository(corpus.REPO_ROOT / "corpus_out"))
        self.assertFalse(corpus.inside_repository(corpus.DEFAULT_ROOT))
        with self.assertRaises(SystemExit):
            corpus.main(["report", "--out", str(corpus.REPO_ROOT / "corpus_out")])
        self.assertFalse((corpus.REPO_ROOT / "corpus_out").exists())

    def test_output_inside_the_source_share_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "share"
            (source / "2025").mkdir(parents=True)
            before = sorted(str(p) for p in source.rglob("*"))
            for out in (source, source / "corpus"):
                with self.subTest(out=out):
                    with self.assertRaises(SystemExit):
                        corpus.main(
                            ["sample", "--source", str(source), "--out", str(out)]
                        )
            self.assertEqual(sorted(str(p) for p in source.rglob("*")), before)

    def test_reports_are_never_written_into_the_source_or_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "share"
            source.mkdir()
            inside = source / "corpus_run_1.csv"
            corpus.write_csv(
                inside,
                [{"rel": "a.pdf", "page": "1", "status": "ok"}],
                corpus.RUN_COLUMNS,
            )
            outside = Path(directory) / "corpus_run_2.csv"
            corpus.write_csv(
                outside,
                [{"rel": "a.pdf", "page": "1", "status": "ok"}],
                corpus.RUN_COLUMNS,
            )
            out = str(Path(directory) / "out")
            for argv in (
                ["report", "--out", out, "--source", str(source), "--run", str(inside)],
                [
                    "compare",
                    "--out",
                    out,
                    "--source",
                    str(source),
                    "--before",
                    str(outside),
                    "--run",
                    str(inside),
                ],
                [
                    "report",
                    "--out",
                    out,
                    "--run",
                    str(corpus.REPO_ROOT / "corpus_run_9.csv"),
                ],
            ):
                with self.subTest(argv=argv[0]):
                    with self.assertRaises(SystemExit):
                        corpus.main(argv)
            self.assertEqual(
                sorted(p.name for p in source.iterdir()), ["corpus_run_1.csv"]
            )
            self.assertFalse((corpus.REPO_ROOT / "corpus_summary_9.md").exists())
            import contextlib
            import io

            for argv, message in (
                (
                    [
                        "report",
                        "--out",
                        out,
                        "--run",
                        str(corpus.REPO_ROOT / "corpus_run_9.csv"),
                    ],
                    "--run must be outside the repository",
                ),
                (
                    [
                        "report",
                        "--out",
                        out,
                        "--source",
                        str(source),
                        "--run",
                        str(inside),
                    ],
                    "--run must be outside --source",
                ),
            ):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
                    corpus.main(argv)
                self.assertIn(message, errors.getvalue())

    def test_missing_input_files_are_usage_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            for argv in (
                ["run", "--out", str(out)],
                [
                    "report",
                    "--out",
                    str(out),
                    "--run",
                    str(Path(directory) / "corpus_run_missing.csv"),
                ],
            ):
                with self.subTest(argv=argv[0]):
                    with self.assertRaises(SystemExit) as raised:
                        corpus.main(argv)
                    self.assertEqual(raised.exception.code, 2)

    def test_outputs_are_ignored_by_git(self):
        import subprocess

        names = [
            "x/corpus_run_1.csv",
            "x/corpus_summary_1.md",
            "x/corpus_compare_1.md",
            "x/sample.csv",
            "x/inventory.csv",
            "x/hand_values.csv",
        ]
        checked = subprocess.run(
            ["git", "check-ignore", "--no-index", *names],
            cwd=corpus.REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(sorted(checked.stdout.split()), sorted(names))

    def test_children_run_from_the_repository_whatever_the_working_folder(self):
        import os

        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            os.chdir(directory)
            try:
                done = corpus._run_child(
                    [sys.executable, "-c", "import tools.ai_takeoff_corpus_worker"], 60
                )
            finally:
                os.chdir(previous)
        self.assertEqual(done, {"status": "ok", "error": ""})

    def test_missing_arguments_are_usage_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            out = str(Path(directory) / "out")
            for argv in (
                ["inventory", "--out", out],
                ["sample", "--out", out],
                ["report", "--out", out],
                [
                    "compare",
                    "--out",
                    out,
                    "--run",
                    str(Path(directory) / "corpus_run_x.csv"),
                ],
                ["compare", "--out", out, "--before", str(Path(directory) / "a.csv")],
            ):
                with self.subTest(argv=argv[0:1] + argv[3:]):
                    with self.assertRaises(SystemExit) as raised:
                        corpus.main(argv)
                    self.assertEqual(raised.exception.code, 2)


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


class SheetHintMergeTests(unittest.TestCase):
    def test_hints_join_their_page_rows_and_failures_are_marked(self):
        rows = [{"rel": "a.pdf", "page": 1}, {"rel": "a.pdf", "page": 2}]
        corpus.merge_sheet_hints(
            rows,
            "ok",
            [{"index": 1, "sheet_number": "S-102", "plan_scale_status": "nts"}],
        )
        self.assertEqual(
            rows,
            [
                {"rel": "a.pdf", "page": 1, "sheets_status": "ok"},
                {
                    "rel": "a.pdf",
                    "page": 2,
                    "sheets_status": "ok",
                    "sheet_number": "S-102",
                    "plan_scale_status": "nts",
                },
            ],
        )
        failed = [{"rel": "b.pdf", "page": 1}]
        corpus.merge_sheet_hints(failed, "hang", [])
        self.assertEqual(failed, [{"rel": "b.pdf", "page": 1, "sheets_status": "hang"}])


def _plan(**values):
    row = {"rel": "a.pdf", "page": "1", "status": "ok", "kind": KIND_PLAN}
    row.update(values)
    return row


class CompareTests(unittest.TestCase):
    def test_before_and_after_metrics(self):
        before = [
            _plan(
                sheet_number="S0",
                scale_status="single",
                list_status="invalid_argument",
                extraction_truncated="True",
                proposal_status="changeset_too_large",
            ),
            _plan(
                page="2",
                sheet_number="S0",
                scale_status="multiple",
                list_status="ok",
                extraction_truncated="False",
                proposal_status="ok",
            ),
            {
                "rel": "a.pdf",
                "page": "3",
                "status": "ok",
                "kind": "detail",
                "sheet_number": "",
            },
        ]
        after = [
            _plan(
                sheet_number="S-101",
                scale_status="single",
                plan_scale_status="resolved",
                list_status="ok",
                extraction_truncated="True",
                box_quadrants_truncated="0",
                proposal_status="ok",
            ),
            _plan(
                page="2",
                sheet_number="S-102",
                scale_status="multiple",
                plan_scale_status="ambiguous",
                list_status="ok",
                extraction_truncated="False",
                box_quadrants_truncated="",
                proposal_status="ok",
            ),
            {
                "rel": "a.pdf",
                "page": "3",
                "status": "ok",
                "kind": "detail",
                "sheet_number": "S-501",
                "extraction_truncated": "True",
                "box_quadrants_truncated": "",
            },
        ]
        table = dict(
            (name, (old, new))
            for name, old, new in corpus.compare_metrics(before, after)
        )
        self.assertEqual(table["Sheet number found"], ("2/3 (67%)", "3/3 (100%)"))
        self.assertEqual(
            table["Zero sheet numbers (S0 style)"], ("2/3 (67%)", "0/3 (0%)")
        )
        self.assertEqual(
            table["Sheet number repeated within its PDF"], ("2/3 (67%)", "0/3 (0%)")
        )
        self.assertEqual(
            table["Plan: one plan scale resolved"], ("1/2 (50%)", "1/2 (50%)")
        )
        self.assertEqual(
            table["Plan: region list over the segment cap (default filter)"],
            ("1/2 (50%)", "0/2 (0%)"),
        )
        self.assertEqual(
            table["Pages truncated (whole page)"], ("1/3 (33%)", "2/3 (67%)")
        )
        self.assertEqual(
            table["Truncated plan pages still truncated in a quarter-page box"],
            ("not measured", "0/1 (0%)"),
        )
        self.assertEqual(table["Plan: proposal failures"], ("1/2 (50%)", "0/2 (0%)"))
        with tempfile.TemporaryDirectory() as directory:
            first, second = (
                Path(directory) / "corpus_run_a.csv",
                Path(directory) / "corpus_run_b.csv",
            )
            corpus.write_csv(first, before, corpus.RUN_COLUMNS)
            corpus.write_csv(second, after, corpus.RUN_COLUMNS)
            text = corpus.compare(
                first, second, Path(directory) / "compare.md"
            ).read_text(encoding="utf-8")
        self.assertIn("| Plan: proposal failures | 1/2 (50%) | 0/2 (0%) |", text)
        self.assertIn("corpus_run_a", text)


class RunOrchestrationTests(unittest.TestCase):
    def test_a_hand_value_on_a_page_that_hangs_is_still_listed(self):
        import json
        from unittest import mock

        def fake_child(command, timeout):
            step = command[3]
            if step == "prepare":
                Path(command[6]).write_text(
                    json.dumps(
                        {
                            "db": "x.mdb",
                            "bid_uid": "b",
                            "pdf": "p.pdf",
                            "pages": [{"uid": "u1", "index": 0}],
                        }
                    ),
                    encoding="utf-8",
                )
                return {"status": "ok", "error": ""}
            if step == "sheets":
                Path(command[5]).write_text(
                    json.dumps([{"index": 0, "sheet_number": "S-101"}]),
                    encoding="utf-8",
                )
                return {"status": "ok", "error": ""}
            return {"status": "hang", "error": "timeout after 1 s"}

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "files").mkdir()
            rel = "2025\\P1\\a.pdf"
            corpus.write_csv(
                out / "sample.csv",
                [{"rel": rel, "local": corpus.local_name(rel), "size": 1}],
                ("rel", "local", "size"),
            )
            corpus.write_csv(
                out / "hand_values.csv",
                [
                    {
                        "pdf": rel,
                        "page": "1",
                        "seed_x": "1",
                        "seed_y": "2",
                        "expected_sf": "120.5",
                    }
                ],
                corpus.HAND_VALUE_COLUMNS,
            )
            with mock.patch.object(corpus, "_run_child", fake_child):
                path = corpus.run(out, 1, sys.executable)
            (row,) = corpus.read_csv(path)
        self.assertEqual(
            (
                row["status"],
                row["hand_expected_sf"],
                row["sheet_number"],
                row["sheets_status"],
            ),
            ("hang", "120.5", "S-101", "ok"),
        )


class RunFailureTests(unittest.TestCase):
    def test_a_pdf_that_cannot_be_prepared_is_one_failed_row_and_main_runs(self):
        import contextlib
        import io
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            rel = "2025\P1\a.pdf"
            corpus.write_csv(
                out / "sample.csv",
                [{"rel": rel, "local": corpus.local_name(rel), "size": 1}],
                ("rel", "local", "size"),
            )
            failing = mock.patch.object(
                corpus,
                "_run_child",
                lambda command, timeout: {
                    "status": "crash",
                    "error": "exit 3221225477: no exception line",
                },
            )
            printed = io.StringIO()
            with failing, contextlib.redirect_stdout(printed):
                self.assertEqual(
                    corpus.main(["run", "--out", str(out), "--timeout", "5"]), 0
                )
            (row,) = corpus.read_csv(Path(printed.getvalue().strip()))
        self.assertEqual(
            (row["rel"], row["page"], row["status"]), (rel, "", "prepare_crash")
        )

    def test_long_paths_that_are_already_prefixed_are_kept(self):
        prefixed = "\\\\?\\C:\\x\\y.pdf"
        self.assertEqual(corpus.long_path(Path(prefixed)), prefixed)


class RunEndToEndTests(unittest.TestCase):
    def test_a_synthetic_sample_runs_end_to_end_with_a_hand_value(self):
        import tests.helpers.mdb.schema_support as access
        from tests.integration.ai_takeoff import s101_fixture as fx
        from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf

        if not access._access_available():
            self.skipTest("Access ODBC/ADOX unavailable")
        title = (
            "BT /F1 14 Tf 450 60 Td (FOUNDATION PLAN) Tj ET\n"
            'BT /F1 9 Tf 450 45 Td (SCALE: 1/8" = 1\'-0") Tj ET\n'
            "BT /F1 20 Tf 520 20 Td (S-101) Tj ET\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            rel = "2025\\P1\\01. Drawings\\1. Drawings\\3. Structural\\S-101.pdf"
            (out / "files").mkdir()
            write_content_pdf(
                out / "files" / corpus.local_name(rel), fx.s101_content() + title
            )
            corpus.write_csv(
                out / "sample.csv",
                [{"rel": rel, "local": corpus.local_name(rel), "size": 1}],
                ("rel", "local", "size"),
            )
            corpus.write_csv(
                out / "hand_values.csv",
                [
                    {
                        "pdf": rel,
                        "page": "1",
                        "seed_x": fx.SEED_PTS[0],
                        "seed_y": fx.SEED_PTS[1],
                        "expected_sf": round(fx.ROOM_AREA_SF, 2),
                    }
                ],
                corpus.HAND_VALUE_COLUMNS,
            )
            path = corpus.run(out, 300, sys.executable)
            (row,) = corpus.read_csv(path)
            summary = (
                (out / path.name.replace("run_", "summary_", 1))
                .with_suffix(".md")
                .read_text(encoding="utf-8")
            )
        self.assertEqual(
            (
                row["status"],
                row["sheets_status"],
                row["sheet_number"],
                row["plan_scale_status"],
                row["proposal_status"],
            ),
            ("ok", "ok", "S-101", "resolved", "ok"),
        )
        self.assertLess(abs(float(row["hand_error_pct"])), 0.5)
        self.assertIn("| Hand values within 0.5% | 1/1 (100%) |", summary)
        self.assertNotIn("IGNORE", summary)
        self.assertNotIn("OFFICE", summary)


class LegacyHelperTests(unittest.TestCase):
    def test_edge_cases_of_the_legacy_page_reading(self):
        self.assertFalse(corpus.in_title_block(_line("X"), 0.0, 100.0))
        self.assertEqual(
            [(h.label, h.sf1) for h in parse_scales('1.5"=1\'-0"')],
            [('1.5"=1\'-0"', 1.5)],
        )
        self.assertEqual(parse_scales('0"=1\'-0"'), [])
        self.assertEqual(parse_scales("1\"=0'"), [])
        tie = [_line("S-101", 2000, 1500, 10), _line("S-102", 2100, 1500, 10)]
        self.assertEqual(sheet_number(tie, 2592, 1728), "S-101")
        titles = [
            _line("FOUNDATION PLAN", 2000, 1600, 14),
            _line("SECOND FLOOR PLAN", 2000, 1650, 12),
        ]
        self.assertEqual(classify_page(titles, 2592, 1728)[1], "FOUNDATION PLAN")

    def test_every_failure_category_is_reported(self):
        row = {
            "rel": "a.pdf",
            "page": "1",
            "status": "ok",
            "kind": KIND_PLAN,
            "sheet_number": "S-1",
            "extraction_truncated": "True",
            "scale_status": "multiple",
            "list_status": "invalid_argument",
            "seed_unlocated": "36.0",
            "filtered_status": "empty",
            "peak_mb": "512",
        }
        names = dict(corpus.failure_categories([row]))
        for name in (
            "extraction over 250,000 pieces",
            "plan with several scales",
            "find_regions list: invalid_argument",
            "plan: raster may have closed unseen openings",
            "plan: no region with wall-width filter",
        ):
            with self.subTest(name=name):
                self.assertIn(name, names)
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, [row], corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "s.md").read_text(
                encoding="utf-8"
            )
        self.assertIn("| peak_mb | 512 | 512 | 512 | 512 |", text)


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
                "seed_area_sf": "101.2",
                "hand_expected_sf": "100",
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
        self.assertIn("## Hand values", text)
        self.assertNotIn("Not measured", text)
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
        self.assertIn("| 2024\\P1\\S-101.pdf | 1 | 100 | 101.2 | 1.2 |", text)
        categories = dict(corpus.failure_categories([dict(row) for row in rows]))
        self.assertEqual(len(categories["page failed: hang (timeout after 180 s)"]), 1)

    def test_hand_values_that_failed_are_listed_and_counted(self):
        rows = [
            {
                "rel": "a.pdf",
                "page": "1",
                "status": "ok",
                "kind": KIND_PLAN,
                "hand_expected_sf": "100",
                "seed_area_sf": "100.2",
                "hand_error_pct": "0.2",
            },
            {
                "rel": "a.pdf",
                "page": "2",
                "status": "ok",
                "kind": KIND_PLAN,
                "hand_expected_sf": "50",
            },
            {"rel": "a.pdf", "page": "3", "status": "hang", "hand_expected_sf": "75"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "s.md").read_text(
                encoding="utf-8"
            )
        self.assertIn("| Hand values within 0.5% | 1/3 (33%) |", text)
        self.assertIn("| a.pdf | 2 | 50 | none | n/a |", text)
        self.assertIn("| a.pdf | 3 | 75 | none | n/a |", text)

    def test_hand_values_without_expected_areas_are_not_measured(self):
        rows = [{"rel": "a.pdf", "page": "1", "status": "ok", "kind": KIND_PLAN}]
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "s.md").read_text(
                encoding="utf-8"
            )
        self.assertIn(
            "Not measured: hand_values.csv has no expected_sf rows for these pages.",
            text,
        )


if __name__ == "__main__":
    unittest.main()
