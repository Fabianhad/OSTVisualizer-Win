import os
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tests.integration.ai_takeoff import s101_fixture as fx
from tests.integration.ai_takeoff.access_app_support import (
    dump_tables,
    run_in_access_child,
    seed_access_bid,
    temporary_home,
)
from tests.integration.ai_takeoff import test_m1b_golden_end_to_end as m1b

AREA_TOLERANCE = 0.005


class M2LineworkEndToEndTests(unittest.TestCase):
    window = m1b.M1bGoldenEndToEndTests.window
    call = m1b.M1bGoldenEndToEndTests.call
    token_path = m1b.M1bGoldenEndToEndTests.token_path

    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        directory = temporary_home()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.server_name = f"OstvTakeoffM2-{uuid.uuid4().hex[:12]}"
        self.db_path = self.home / "s101.mdb"

    def seed(self):
        pdf = fx.write_s101_pdf(self.home / "S101.pdf")
        bid_uid, page_uids, _existing = seed_access_bid(
            self.db_path,
            [("S-101", 8.5, 11.0, *fx.SCALE_FACTORS)],
            image_path=str(pdf),
        )
        return bid_uid, page_uids[0]

    def test_s101_like_sheet_from_linework_to_an_approved_slab_and_back(self):
        if self.skip_body:
            return
        bid_uid, page_uid = self.seed()
        before = dump_tables(self.db_path)
        with self.window(bid_uid) as (win, controller):
            segments = self.call("list_segments", {"page_uid": page_uid, "limit": 500})
            self.assertTrue(segments["success"], segments)
            data = segments["data"]
            self.assertEqual(
                data["new_fields"],
                ["width_pts", "dash_pts", "color", "paint", "curve", "kind"],
            )
            walls = [
                s
                for s in data["segments"]
                if s["kind"] == "wall" and s["paint"] == "stroke"
            ]
            self.assertTrue(walls)
            self.assertEqual({s["width_pts"] for s in walls}, {2.0})
            dashed = self.call(
                "list_segments",
                {"page_uid": page_uid, "kinds": ["dashed"], "limit": 500},
            )["data"]["segments"]
            self.assertEqual(len(dashed), 1 + fx.EXPLODED_DASHES)
            self.assertEqual(
                [s["dash_pts"] for s in dashed if s["dash_pts"]], [[6.0, 3.0]]
            )
            again = self.call("list_segments", {"page_uid": page_uid, "limit": 500})
            self.assertEqual(
                [s["id"] for s in again["data"]["segments"]],
                [s["id"] for s in data["segments"]],
            )
            listed = self.call(
                "find_regions",
                {"page_uid": page_uid, "bbox_pts": fx.BBOX_PTS, "min_width": 1.0},
            )
            self.assertTrue(listed["success"], listed)
            areas = [region["area_sf"] for region in listed["data"]["regions"]]
            self.assertEqual(areas, sorted(areas, reverse=True))
            self.assertEqual(listed["data"]["total_count"], len(areas))
            regions = self.call(
                "find_regions",
                {
                    "page_uid": page_uid,
                    "bbox_pts": fx.BBOX_PTS,
                    "seed_pts": fx.SEED_PTS,
                    "max_gap_in": fx.GAP_IN,
                },
            )
            self.assertTrue(regions["success"], regions)
            (region,) = regions["data"]["regions"]
            self.assertEqual(region["method"], "vector")
            self.assertAlmostEqual(
                region["area_sf"],
                fx.ROOM_AREA_SF,
                delta=fx.ROOM_AREA_SF * AREA_TOLERANCE,
            )
            self.assertEqual(region["holes_ost"], [])
            (gap,) = region["gaps"]
            self.assertAlmostEqual(gap["length_in"], fx.DOOR_WIDTH_IN, delta=0.01)
            inner_face = fx.PAGE_HEIGHT - fx.INNER[1]
            self.assertEqual({gap["p1_pts"][1], gap["p2_pts"][1]}, {inner_face})
            self.assertEqual(
                regions["data"]["excluded"]["dashed"], 1 + fx.EXPLODED_DASHES
            )
            self.assertEqual(
                regions["data"]["suppressed_symbol_count"], fx.SYMBOL_SHAPES
            )
            proposed = self.call(
                "propose_element",
                {
                    "kind": "slab",
                    "page_uid": page_uid,
                    "region_id": region["id"],
                    "thickness_in": 8.0,
                    "top_elev_in": 0.0,
                    "summary": fx.INJECTED,
                },
            )
            self.assertTrue(proposed["success"], proposed)
            (closing,) = proposed["data"]["assumptions"]
            self.assertEqual(
                (closing["subject"], closing["impact"]), ("closing_segment", "high")
            )
            self.assertEqual(closing["value"]["value"], "36.00 in")
            self.assertIn(f"{inner_face:.1f})", closing["reason"]["value"])
            changeset_id = proposed["data"]["changeset_id"]
            pending = self.call("apply_changeset", {"changeset_id": changeset_id})
            self.assertEqual(pending["status"], "pending_approval")
            self.assertEqual(dump_tables(self.db_path), before)
            dialog = win._ai_approval.dialog_for(changeset_id)
            self.assertIsNotNone(dialog)
            self.assertFalse(dialog.accept_button.isEnabled())
            dialog.accept_assumption_button(0).click()
            self.assertTrue(dialog.accept_button.isEnabled())
            dialog.accept_button.click()
            self.app.processEvents()
            applied = self.call("apply_changeset", {"changeset_id": changeset_id})
            self.assertEqual(
                applied["status"], "applied", win._ai_approval.last_error(changeset_id)
            )
            quantities = self.call("get_quantities", {"group_by": "condition"})
            (row,) = [
                row
                for row in quantities["data"]["rows"]
                if row["condition_uid"] in applied["data"]["applied"]["condition_uids"]
            ]
            values = {item["uom"]: item["value"] for item in row["quantities"]}
            self.assertAlmostEqual(
                values["SF"], fx.ROOM_AREA_SF, delta=fx.ROOM_AREA_SF * AREA_TOLERANCE
            )
            expected_cy = fx.ROOM_AREA_SF * 8.0 / 12.0 / 27.0
            self.assertAlmostEqual(
                values["CY"], expected_cy, delta=expected_cy * AREA_TOLERANCE
            )
            undone = self.call("undo_last_ai_changeset", {"changeset_id": changeset_id})
            self.assertEqual(undone["data"]["status"], "undone")
        self.assertEqual(dump_tables(self.db_path), before)


if __name__ == "__main__":
    unittest.main()
