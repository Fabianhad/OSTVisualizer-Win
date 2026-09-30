import unittest
from pathlib import Path


class BidLockPermissionTests(unittest.TestCase):
    def test_area_dialog_without_selected_bid_has_no_stale_presence_reference(self):
        source = Path(
            "ost_visualizer/presentation/coordinators/ui_event_coordinator.py"
        ).read_text(encoding="utf-8")
        method = source.split("    def open_areas_dialog", 1)[1].split(
            "    def _save_bid_areas_from_dialog", 1
        )[0]
        self.assertNotIn("prev_bid_ref", method)
