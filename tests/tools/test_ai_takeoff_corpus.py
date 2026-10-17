"""Corpus harness helpers on synthetic data only (no client drawings)."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
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
    def test_other_spellings_of_a_folder_inside_the_root_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "tools").mkdir(parents=True)
            prefix = "\\\\?\\"
            spellings = [
                Path(prefix + str(root / "out")),
                Path(prefix + str(root / "tools" / "new" / "deeper")),
                Path(prefix + str(root).upper() + "\\x"),
            ]
            for spelling in spellings:
                with self.subTest(spelling=str(spelling)):
                    self.assertTrue(corpus.inside(spelling, root))
            self.assertFalse(corpus.inside(Path(prefix + directory) / "other", root))
            self.assertFalse(corpus.inside(Path(directory) / "repository", root))

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
            "x/corpus_summary_1_keys.csv",
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
        for name in (
            "Plan: seeded region found (default width)",
            "Plan: wall-filter failure (default width)",
            "Plan: leak not flagged (region touches the box or fills 80%)",
        ):
            with self.subTest(name=name):
                self.assertEqual(table[name], ("not measured", "not measured"))
        seeded = [
            _plan(
                default_found="True",
                default_wall_failure="True",
                default_leak="False",
                default_touches_edge="True",
            ),
            _plan(page="2", default_found="False", default_wall_failure="True"),
            _plan(
                page="3",
                default_found="True",
                default_wall_failure="False",
                default_leak="True",
                default_box_ratio="0.9",
            ),
        ]
        later = dict(
            (name, new) for name, _old, new in corpus.compare_metrics(before, seeded)
        )
        self.assertEqual(
            later["Plan: seeded region found (default width)"], "2/3 (67%)"
        )
        self.assertEqual(
            later["Plan: wall-filter failure (default width)"], "2/3 (67%)"
        )
        self.assertEqual(
            later["Plan: leak not flagged (region touches the box or fills 80%)"],
            "1/3 (33%)",
        )
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


class PlanPageCapTests(unittest.TestCase):
    def run_with(self, cap):
        import json
        from unittest import mock

        measured = []

        def fake_child(command, timeout):
            step = command[3]
            if step == "prepare":
                pages = [{"uid": f"u{i}", "index": i} for i in range(5)]
                Path(command[6]).write_text(
                    json.dumps(
                        {"db": "x.mdb", "bid_uid": "b", "pdf": "p.pdf", "pages": pages}
                    ),
                    encoding="utf-8",
                )
                return {"status": "ok", "error": ""}
            if step == "sheets":
                kinds = ["plan", "plan", "detail", "plan", "plan"]
                Path(command[5]).write_text(
                    json.dumps(
                        [{"index": i, "kind": kind} for i, kind in enumerate(kinds)]
                    ),
                    encoding="utf-8",
                )
                return {"status": "ok", "error": ""}
            measured.append(command[5])
            Path(command[7]).write_text(
                json.dumps({"status": "ok", "kind": "plan"}), encoding="utf-8"
            )
            return {"status": "ok", "error": ""}

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            rel = "2025\P1\a.pdf"
            corpus.write_csv(
                out / "sample.csv",
                [{"rel": rel, "local": corpus.local_name(rel), "size": 1}],
                ("rel", "local", "size"),
            )
            with mock.patch.object(corpus, "_run_child", fake_child):
                path = corpus.run(out, 1, sys.executable, max_plan_pages=cap)
            rows = corpus.read_csv(path)
        return measured, [(row["page"], row["status"], row["kind"]) for row in rows]

    def test_at_most_n_plan_pages_spread_over_the_set_are_measured(self):
        measured, rows = self.run_with(2)
        self.assertEqual(measured, ["u0", "u4"])
        self.assertEqual(
            rows,
            [
                ("1", "ok", "plan"),
                ("2", "not_measured", "plan"),
                ("3", "not_measured", "detail"),
                ("4", "not_measured", "plan"),
                ("5", "ok", "plan"),
            ],
        )

    def test_without_a_cap_every_page_is_measured(self):
        measured, rows = self.run_with(None)
        self.assertEqual(measured, ["u0", "u1", "u2", "u3", "u4"])
        self.assertEqual([status for _page, status, _kind in rows], ["ok"] * 5)


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


class NotMeasuredReportTests(unittest.TestCase):
    def test_pages_skipped_by_the_plan_page_cap_are_not_failures(self):
        rows = [{"rel": "a.pdf", "page": "1", "status": "ok", "kind": KIND_PLAN}]
        rows += [
            {"rel": "a.pdf", "page": str(page), "status": "not_measured"}
            for page in range(2, 11)
        ]
        names = dict(corpus.failure_categories(rows))
        self.assertFalse([name for name in names if "not_measured" in name])
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "s.md").read_text(
                encoding="utf-8"
            )
        self.assertIn(
            "| Page measured without crash, hang or error | 1/1 (100%) |", text
        )
        self.assertNotIn("not_measured (", text)


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


class FailureCategoryTests(unittest.TestCase):
    def names(self, **fields):
        row = {
            "rel": "a.pdf",
            "page": "1",
            "status": "ok",
            "kind": KIND_NOTES,
            "sheet_number": "S-1",
        }
        row.update(fields)
        return {name for name, _members in corpus.failure_categories([row])}

    def test_a_clean_page_has_no_category_and_unmeasured_pages_are_skipped(self):
        self.assertEqual(self.names(), set())
        self.assertEqual(self.names(status="not_measured"), set())

    def test_failed_pages_are_listed_by_status_and_error_and_nothing_else(self):
        self.assertEqual(
            self.names(status="timeout", error="hang", sheet_number=""),
            {"page failed: timeout (hang)"},
        )
        self.assertEqual(
            self.names(status="crash", sheet_number=""), {"page failed: crash ()"}
        )

    def test_page_content_categories_follow_their_flags_exactly(self):
        cases = (
            ({"content": "raster_only"}, "raster-only page (no vectors, no text)"),
            ({"outlined_text": "True"}, "text drawn as outlines (no extractable text)"),
            ({"extraction_truncated": "True"}, "extraction over 250,000 pieces"),
            ({"kind": KIND_UNKNOWN}, "page kind not recognised"),
            ({"sheet_number": ""}, "sheet number not found"),
            ({"sheet_number": None}, "sheet number not found"),
        )
        for fields, name in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.names(**fields), {name})
        for fields in (
            {"content": "vector"},
            {"outlined_text": "False"},
            {"extraction_truncated": "False"},
            {"kind": KIND_PLAN},
        ):
            with self.subTest(clean=fields):
                self.assertEqual(self.names(**fields), set())

    def test_scale_categories_apply_to_plans_only(self):
        for scale in ("none", "graphic_only"):
            with self.subTest(scale=scale):
                self.assertEqual(
                    self.names(kind=KIND_PLAN, scale_status=scale),
                    {"plan without a readable scale"},
                )
                self.assertEqual(
                    self.names(kind=KIND_DETAIL, scale_status=scale), set()
                )
        self.assertEqual(
            self.names(kind=KIND_PLAN, scale_status="multiple"),
            {"plan with several scales"},
        )
        self.assertEqual(self.names(kind=KIND_DETAIL, scale_status="multiple"), set())
        self.assertEqual(self.names(kind=KIND_PLAN, scale_status="single"), set())

    def test_find_regions_statuses_are_reported_per_call_for_plans_only(self):
        for prefix in ("list", "filtered", "seed"):
            for status in ("invalid_argument", "deadline", "exception:ValueError"):
                with self.subTest(prefix=prefix, status=status):
                    self.assertEqual(
                        self.names(kind=KIND_PLAN, **{f"{prefix}_status": status}),
                        {f"find_regions {prefix}: {status}"},
                    )
            for status in ("ok", "empty", "truncated", "skipped", ""):
                with self.subTest(prefix=prefix, quiet=status):
                    fields = {f"{prefix}_status": status}
                    self.assertEqual(
                        self.names(kind=KIND_PLAN, **fields)
                        - {"plan: no region with wall-width filter"},
                        set(),
                    )
            self.assertEqual(
                self.names(kind=KIND_NOTES, **{f"{prefix}_status": "invalid_argument"}),
                set(),
            )

    def test_plan_outcomes_are_categorised_by_their_thresholds(self):
        plan = {"kind": KIND_PLAN}
        self.assertEqual(
            self.names(filtered_status="empty", **plan),
            {"plan: no region with wall-width filter"},
        )
        self.assertEqual(
            self.names(seed_method="raster", **plan),
            {"plan: seeded region fell back to raster"},
        )
        self.assertEqual(self.names(seed_method="vector", **plan), set())
        for unlocated in ("36.0", 12):
            self.assertEqual(
                self.names(seed_unlocated=unlocated, **plan),
                {"plan: raster may have closed unseen openings"},
            )
        for unlocated in ("", None, "None"):
            self.assertEqual(self.names(seed_unlocated=unlocated, **plan), set())
        self.assertEqual(
            self.names(filtered_seconds="10.5", **plan),
            {"plan: find_regions slower than 10 s"},
        )
        for seconds in ("10.0", "9.9", "", None):
            self.assertEqual(self.names(filtered_seconds=seconds, **plan), set())
        for error in ("0.6", "-0.51", 7):
            self.assertEqual(
                self.names(hand_error_pct=error, **plan),
                {"hand value off by more than 0.5%"},
            )
        for error in ("0.5", "-0.5", "", None):
            self.assertEqual(self.names(hand_error_pct=error, **plan), set())
        non_plan = {
            "filtered_status": "empty",
            "seed_method": "raster",
            "seed_unlocated": "9",
            "filtered_seconds": "99",
            "hand_error_pct": "9",
        }
        self.assertEqual(self.names(**non_plan), set())

    def test_the_most_frequent_category_comes_first_and_keeps_its_pages(self):
        rows = [
            {"rel": "a.pdf", "page": "1", "status": "ok", "kind": KIND_NOTES},
            {
                "rel": "a.pdf",
                "page": "2",
                "status": "ok",
                "kind": KIND_UNKNOWN,
                "sheet_number": "S-1",
            },
            {"rel": "a.pdf", "page": "3", "status": "ok", "kind": KIND_NOTES},
        ]
        categories = corpus.failure_categories(rows)
        self.assertEqual(
            [(name, [row["page"] for row in members]) for name, members in categories],
            [
                ("sheet number not found", ["1", "3"]),
                ("page kind not recognised", ["2"]),
            ],
        )


class SamplingBoundaryTests(unittest.TestCase):
    def test_structural_files_sit_at_least_six_levels_deep_in_a_known_year(self):
        parts = corpus.structural_parts
        folder = ("P1", "01. Drawings", "1. Drawings", "3. Structural")
        self.assertEqual(
            parts(
                str(
                    Path(
                        "2024",
                        "P1",
                        "01. Drawings",
                        "1. Drawings",
                        "3. Structural",
                        "S.pdf",
                    )
                )
            ),
            ("2024", "P1"),
        )
        self.assertIsNone(
            parts(
                str(Path("2024", "P1", "01. Drawings", "1. Drawings", "3. Structural"))
            )
        )
        self.assertIsNone(parts(str(Path("1999", *folder, "S.pdf"))))
        self.assertIsNone(
            parts(
                str(
                    Path(
                        "2024", "P1", "01. Drawings", "1. Drawings", "2. Arch", "S.pdf"
                    )
                )
            )
        )

    def test_files_of_exactly_the_size_limit_are_still_sampled(self):
        rows = [
            {"rel": _structural("2024", "P1", "S-101.pdf"), "size": "1000"},
            {"rel": _structural("2024", "P2", "S-101.pdf"), "size": "1001"},
        ]
        chosen = corpus.stratified_sample(rows, 5, max_bytes=1000)
        self.assertEqual([row["size"] for row in chosen], ["1000"])


class ReportExactnessTests(unittest.TestCase):
    def rows(self):
        plan = {
            "rel": _structural("2024", "J1", "a.pdf"),
            "page": "1",
            "status": "ok",
            "kind": KIND_PLAN,
            "content": "vector_and_text",
            "text_runs": "5",
            "sheet_number": "S-1",
            "scale_status": "single",
            "page_size_class": "ARCH D 24x36",
            "rotation": "0",
            "visible_offset": "no",
            "seconds": "1.0",
            "list_seconds": "0.5",
            "filtered_status": "ok",
            "filtered_regions": "2",
            "filtered_seconds": "2.0",
            "seed_status": "ok",
            "seed_method": "vector",
            "seed_seconds": "3.0",
            "proposal_status": "ok",
            "kinds_wall": "10",
            "kinds_dashed": "1",
            "kinds_thin": "2",
            "kinds_symbol": "3",
            "widths": '{"<0.5": 4, ">=2": 6}',
            "peak_mb": "100",
        }
        notes = {
            "rel": _structural("2024", "J1", "a.pdf"),
            "page": "2",
            "status": "ok",
            "kind": KIND_NOTES,
            "content": "text_only",
            "text_runs": "0",
            "sheet_number": "",
            "scale_status": "none",
            "page_size_class": "Letter",
            "rotation": "90",
            "visible_offset": "yes",
            "seconds": "3.0",
            "kinds_wall": "1",
            "kinds_dashed": "0",
            "kinds_thin": "0",
            "kinds_symbol": "0",
            "widths": '{"<0.5": 1}',
            "peak_mb": "300",
        }
        hung = {
            "rel": _structural("2025", "J2", "b.pdf"),
            "page": "1",
            "status": "timeout",
            "error": "hang",
            "seconds": "9.0",
        }
        return [plan, notes, hung]

    def report_lines(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            return (
                corpus.report(run_csv, Path(directory) / "s.md")
                .read_text(encoding="utf-8")
                .splitlines()
            )

    def section(self, lines, heading):
        start = lines.index(heading) + 1
        end = next(
            (i for i in range(start, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        return [line for line in lines[start:end] if line]

    def test_pass_rates_count_the_right_pages(self):
        lines = self.report_lines(self.rows())
        self.assertIn("PDFs: 2; pages: 3; plan-like pages: 1.", lines)
        self.assertEqual(
            self.section(lines, "## Pass rates")[2:],
            [
                "| Page measured without crash, hang or error | 2/3 (67%) |",
                "| Vector content | 1/2 (50%) |",
                "| Extractable text | 1/2 (50%) |",
                "| Sheet number found | 1/2 (50%) |",
                "| Page kind recognised | 2/2 (100%) |",
                "| Plan: numeric scale read | 1/1 (100%) |",
                "| Plan: under the 20,000 region cap (filtered) | 1/1 (100%) |",
                "| Plan: regions found with wall-width filter | 1/1 (100%) |",
                "| Plan: seeded call returned a vector region | 1/1 (100%) |",
                "| Plan: changeset proposed (never applied) | 1/1 (100%) |",
                "| Hand values within 0.5% | n/a |",
            ],
        )

    def test_the_page_mix_lists_each_value_with_its_count(self):
        lines = self.report_lines(self.rows())
        self.assertEqual(
            self.section(lines, "## Page mix"),
            [
                "- kind: plan 1, general_notes 1",
                "- content: vector_and_text 1, text_only 1",
                "- scale_status: single 1, none 1",
                "- page_size_class: ARCH D 24x36 1, Letter 1",
                "- rotation: 0 1, 90 1",
                "- visible_offset: no 1, yes 1",
            ],
        )

    def test_timing_percentiles_interpolate_and_skip_measures_without_values(self):
        lines = self.report_lines(self.rows())
        self.assertEqual(
            self.section(lines, "## Timing percentiles (seconds)")[2:],
            [
                "| seconds | 3.00 | 7.80 | 8.88 | 9.00 |",
                "| list_seconds | 0.50 | 0.50 | 0.50 | 0.50 |",
                "| filtered_seconds | 2.00 | 2.00 | 2.00 | 2.00 |",
                "| seed_seconds | 3.00 | 3.00 | 3.00 | 3.00 |",
                "| peak_mb | 200 | 280 | 298 | 300 |",
            ],
        )
        rows = self.rows()
        for row in rows:
            row.pop("list_seconds", None)
            row.pop("peak_mb", None)
        text = "\n".join(self.report_lines(rows))
        self.assertNotIn("| list_seconds |", text)
        self.assertNotIn("| peak_mb |", text)

    def test_failure_categories_and_project_line_kinds_are_listed_per_project(self):
        lines = self.report_lines(self.rows())
        self.assertEqual(
            self.section(lines, "## Failure categories (most frequent first)"),
            [
                "- **sheet number not found**: 1 page(s). Examples: P01 p2",
                "- **page failed: timeout (hang)**: 1 page(s). Examples: P02 p1",
            ],
        )
        self.assertEqual(
            self.section(lines, "## Line kinds and widths by project (proxy for firm)")[
                2:
            ],
            ["| J01 | 2 | 11 | 1 | 2 | 3 | <0.5 5, >=2 6 |"],
        )

    def test_outlined_text_rates_count_pages_with_segments_but_no_text_runs(self):
        rows = self.rows()
        rows[0]["segments"] = "4"
        rows[1]["segments"] = "4"
        line = "| Vector pages without any text (outlined text) | {} |"
        self.assertIn(
            line.format("1/2 (50%)"),
            self.section(self.report_lines(rows), "## Outlined text"),
        )
        rows[1]["segments"] = "0"
        self.assertIn(
            line.format("0/2 (0%)"),
            self.section(self.report_lines(rows), "## Outlined text"),
        )


class ReportPredicateTests(unittest.TestCase):
    def test_a_region_that_escaped_without_a_leak_warning_is_a_missed_leak(self):
        base = {"default_found": "True", "default_leak": "False"}
        self.assertTrue(corpus._leak_missed(dict(base, default_touches_edge="True")))
        self.assertTrue(corpus._leak_missed(dict(base, default_box_ratio="0.81")))
        self.assertFalse(corpus._leak_missed(dict(base, default_box_ratio="0.8")))
        self.assertFalse(corpus._leak_missed(dict(base, default_touches_edge="False")))
        self.assertFalse(
            corpus._leak_missed(
                dict(base, default_leak="True", default_touches_edge="True")
            )
        )
        self.assertFalse(
            corpus._leak_missed(
                {"default_found": "False", "default_touches_edge": "True"}
            )
        )
        self.assertTrue(
            corpus._leak_missed({"heavy_found": "True", "heavy_box_ratio": "0.9"})
        )
        self.assertFalse(
            corpus._leak_missed({"default_found": "True", "default_box_ratio": ""})
        )

    def test_a_seeded_call_is_slow_above_half_the_proxy_timeout(self):
        self.assertFalse(corpus._slow({"zero_seconds": "60.0"}))
        self.assertTrue(corpus._slow({"zero_seconds": "60.01"}))
        self.assertTrue(corpus._slow({"heavy_seconds": "100"}))
        self.assertFalse(corpus._slow({"default_seconds": ""}))
        self.assertFalse(corpus._slow({}))

    def test_a_hand_value_is_within_half_a_percent_either_way(self):
        within = corpus._hand_within
        self.assertTrue(within({"hand_error_pct": "0.5"}))
        self.assertTrue(within({"hand_error_pct": "-0.5"}))
        self.assertFalse(within({"hand_error_pct": "0.51"}))
        self.assertFalse(within({"hand_error_pct": "-0.51"}))
        self.assertFalse(within({"hand_error_pct": ""}))
        self.assertFalse(within({}))

    def test_rates_medians_examples_and_identifiers_are_formatted_for_the_summary(self):
        self.assertEqual(corpus._rate([], bool), "n/a")
        self.assertEqual(corpus._rate([1, 0, 1], bool), "2/3 (67%)")
        self.assertEqual(corpus._median([3.0, None, 1.0]), "2.00")
        self.assertEqual(corpus._median([None]), "n/a")
        ids = {"a.pdf": "P01"}
        rows = [{"rel": "a.pdf", "page": str(page)} for page in range(1, 6)]
        self.assertEqual(corpus._example(rows, ids), "P01 p1; P01 p2; P01 p3")
        self.assertEqual(corpus._example(rows, ids, limit=1), "P01 p1")
        many = [{"rel": f"{index:03d}/p.pdf"} for index in range(100)]
        pdf_ids, project_ids = corpus.corpus_ids(many)
        self.assertEqual(pdf_ids["000/p.pdf"], "P001")
        self.assertEqual(pdf_ids["099/p.pdf"], "P100")
        self.assertEqual(project_ids["p.pdf"], "J01")
        few, projects = corpus.corpus_ids([{"rel": "a/b.pdf"}, {"rel": "c/d.pdf"}])
        self.assertEqual((few["a/b.pdf"], projects["b.pdf"]), ("P01", "J01"))
        self.assertEqual(corpus._project("only.pdf"), "only.pdf")

    def test_seeded_pages_and_percentiles_follow_their_definitions(self):
        rows = [
            {"default_found": "True"},
            {"default_found": "False"},
            {"default_found": ""},
            {},
        ]
        self.assertEqual(len(corpus._seeded(rows, "default")), 2)
        self.assertIsNone(corpus.percentile([], 0.5))
        self.assertEqual(corpus.percentile([4.0], 0.99), 4.0)
        self.assertEqual(corpus.percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
        self.assertAlmostEqual(corpus.percentile([1.0, 2.0, 3.0, 4.0], 0.9), 3.7)
        self.assertEqual(corpus.percentile([None, 5.0, 1.0], 0.0), 1.0)


class CommandLineDefaultsTests(unittest.TestCase):
    def run_main(self, arguments, **patches):
        import contextlib
        import io

        error = io.StringIO()
        with contextlib.redirect_stderr(error), contextlib.redirect_stdout(
            io.StringIO()
        ):
            with contextlib.ExitStack() as stack:
                for name, replacement in patches.items():
                    stack.enter_context(mock.patch.object(corpus, name, replacement))
                try:
                    return corpus.main(arguments), error.getvalue()
                except SystemExit as exit_request:
                    return exit_request.code, error.getvalue()

    def test_sampling_defaults_to_thirty_pdfs_of_at_most_150_megabytes(self):
        import csv as csv_module

        calls = []
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "out"
            out.mkdir()
            with open(
                out / "inventory.csv", "w", newline="", encoding="utf-8"
            ) as handle:
                csv_module.writer(handle).writerow(["rel", "size"])
            code, _error = self.run_main(
                ["sample", "--out", str(out)],
                stratified_sample=lambda rows, count, max_bytes: calls.append(
                    (count, max_bytes)
                )
                or [],
            )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [(30, 150 * 1024 * 1024)])

    def test_the_size_cap_and_count_come_from_the_command_line(self):
        import csv as csv_module

        calls = []
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "out"
            out.mkdir()
            with open(
                out / "inventory.csv", "w", newline="", encoding="utf-8"
            ) as handle:
                csv_module.writer(handle).writerow(["rel", "size"])
            self.run_main(
                ["sample", "--out", str(out), "--count", "7", "--max-mb", "2"],
                stratified_sample=lambda rows, count, max_bytes: calls.append(
                    (count, max_bytes)
                )
                or [],
            )
        self.assertEqual(calls, [(7, 2 * 1024 * 1024)])

    def test_a_run_uses_a_180_second_child_timeout_unless_told_otherwise(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "out"
            out.mkdir()
            (out / "sample.csv").write_text("rel\n", encoding="utf-8")
            fake = lambda *args: calls.append(args) or "run.csv"
            self.run_main(["run", "--out", str(out)], run=fake)
            self.run_main(
                ["run", "--out", str(out), "--timeout", "30", "--max-plan-pages", "4"],
                run=fake,
            )
        self.assertEqual(calls[0][1], 180.0)
        self.assertIsNone(calls[0][3])
        self.assertEqual((calls[1][1], calls[1][3]), (30.0, 4))

    def test_an_output_folder_inside_the_repository_is_refused_with_the_reason(self):
        code, error = self.run_main(
            [
                "inventory",
                "--out",
                str(corpus.REPO_ROOT / "corpus_out"),
                "--source",
                "x",
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("--out must be outside the repository", error)
        self.assertIn("confidential", error)
        self.assertFalse((corpus.REPO_ROOT / "corpus_out").exists())

    def test_the_output_folder_is_created_when_it_is_missing(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as source:
            target = Path(folder) / "a" / "b"
            code, _error = self.run_main(
                ["inventory", "--out", str(target), "--source", source],
                inventory=lambda source, out: [],
            )
            self.assertEqual(code, 0)
            self.assertTrue(target.is_dir())

    def test_sampling_prints_the_chosen_files_one_per_line(self):
        import contextlib
        import csv as csv_module
        import io

        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "out"
            out.mkdir()
            with open(
                out / "inventory.csv", "w", newline="", encoding="utf-8"
            ) as handle:
                csv_module.writer(handle).writerow(["rel", "size"])
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                with mock.patch.object(
                    corpus,
                    "stratified_sample",
                    lambda *a, **k: [{"rel": "a.pdf"}, {"rel": "b.pdf"}],
                ):
                    corpus.main(["sample", "--out", str(out)])
        self.assertEqual(printed.getvalue().splitlines(), ["a.pdf", "b.pdf"])


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
        for private in ("2024", "S-101", "S-102", "FOUNDATION PLAN", ".pdf"):
            with self.subTest(private=private):
                self.assertNotIn(private, text)
        self.assertIn("| P01 | 1 | 100 | 101.2 | 1.2 |", text)
        self.assertIn("Examples: P02 p2", text)
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
        self.assertIn("| P01 | 2 | 50 | none | n/a |", text)
        self.assertIn("| P01 | 3 | 75 | none | n/a |", text)

    def test_the_key_file_stays_next_to_the_summary(self):
        rows = [
            {"rel": "2025\\B\\b.pdf", "page": "1", "status": "ok"},
            {"rel": "2025\\A\\a.pdf", "page": "1", "status": "ok"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            corpus.report(run_csv, Path(directory) / "corpus_summary_x.md")
            keys = corpus.read_csv(Path(directory) / "corpus_summary_x_keys.csv")
        self.assertEqual(
            [(row["id"], row["project"], row["rel"]) for row in keys],
            [("P01", "J01", "2025\\A\\a.pdf"), ("P02", "J02", "2025\\B\\b.pdf")],
        )

    def test_pentest_sections_and_the_fix_list(self):
        def plan(page, rel="2025\\A\\a.pdf", **values):
            row = {
                "rel": rel,
                "page": str(page),
                "status": "ok",
                "kind": KIND_PLAN,
                "text_runs": "50",
                "segments": "900",
            }
            row.update({key: str(value) for key, value in values.items()})
            return row

        rows = [
            plan(
                1,
                suggestion_removes_dominant=True,
                default_found=True,
                default_touches_edge=True,
                default_box_ratio=0.9,
                default_segments=10,
                default_leak=False,
                default_wall_failure=True,
                default_seconds=130.0,
                zero_found=True,
                zero_touches_edge=False,
                zero_box_ratio=0.1,
                zero_segments=500,
                zero_leak=True,
                zero_open_gaps=2,
                zero_dashed_outline=True,
                zero_wall_failure=False,
                zero_seconds=3.0,
                proposal_status="ok",
                proposal_subjects='{"closing_segment": 2}',
                callouts_as_lines=True,
                dash_arrays=4,
                dominant_wall_width=2.0,
            ),
            plan(
                2,
                suggestion_removes_dominant=False,
                default_found=True,
                default_touches_edge=False,
                default_box_ratio=0.2,
                default_segments=0,
                default_leak=False,
                default_wall_failure=True,
                default_seconds=70.0,
                proposal_status="changeset_too_large",
                callouts_as_lines=False,
                dominant_wall_width=2.0,
            ),
            plan(
                3,
                rel="2026\\B\\b.pdf",
                suggestion_removes_dominant=False,
                default_found=True,
                default_touches_edge=False,
                default_box_ratio=0.3,
                default_segments=40,
                default_leak=False,
                default_wall_failure=False,
                default_seconds=2.0,
                proposal_status="ok",
                callouts_as_lines=False,
                extraction_truncated=True,
                dominant_wall_width=1.0,
            ),
            {
                "rel": "2026\\B\\b.pdf",
                "page": "4",
                "status": "ok",
                "kind": KIND_UNKNOWN,
                "text_runs": "0",
                "segments": "800",
                "content": "vector",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            run_csv = Path(directory) / "corpus_run_x.csv"
            corpus.write_csv(run_csv, rows, corpus.RUN_COLUMNS)
            text = corpus.report(run_csv, Path(directory) / "s.md").read_text(
                encoding="utf-8"
            )
        for expected in (
            "| Suggestion removes the dominant wall weight | 1/3 (33%) |",
            "| Seeded region touches the search-box edge | 1/3 (33%) |",
            "| Seeded region keeps zero edges | 1/3 (33%) |",
            "| Seeded region above 80% of the box | 1/3 (33%) |",
            "| Wall-filter failure (any of the three) | 2/3 (67%) |",
            "| default | 3 | 3 | 0 | 0 | 0 | 1 | 1 | 2 | 0.30 |",
            "| zero | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0.10 |",
            "| Vector pages without any text (outlined text) | 1/4 (25%) |",
            "| Plans whose callouts are lines | 1/3 (33%) |",
            "| default | 70.00 | 118.00 | 130.00 | 2 | 1 |",
            "| zero | 3.00 | 3.00 | 3.00 | 0 | 0 |",
            "| ok | 2 |",
            "| changeset_too_large | 1 |",
            "| closing_segment | 2 |",
            "| J01 | 2 | 2 | 2.0 | 4 | 0/2 (0%) | 2/2 (100%) | 1/2 (50%) |",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        fixes = text.split("## Prioritized fix list", 1)[1]
        order = [
            fixes.index(name)
            for name in ("Wall-width suggestion", "Outlined-text fallback")
        ]
        self.assertEqual(order, sorted(order))
        self.assertIn("Leak guard coverage", fixes)
        self.assertIn("Examples: P01 p1", fixes)

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
