"""Corpus worker on synthetic PDFs only (no client drawings)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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
                    "sheet_number",
                    "scale_status",
                    "content",
                )
            },
            {
                "status": "ok",
                "kind": "plan",
                "title": "FOUNDATION PLAN",
                "sheet_number": "S-101",
                "scale_status": "single",
                "content": "vector_and_text",
            },
        )
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
