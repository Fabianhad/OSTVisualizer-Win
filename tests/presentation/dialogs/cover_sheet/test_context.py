import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext


class CoverSheetDeferredBoundaryTests(unittest.TestCase):
    def test_cover_sheet_save_flushes_pending_visual_state_before_write(self):
        write_calls = []
        deferred = SimpleNamespace(flush_for_file=lambda _db_path: False)
        context = CoverSheetContext(
            project_read_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(
                save_cover_sheet=lambda db_path, bid_uid, updates: write_calls.append(
                    (db_path, bid_uid, updates)
                )
                or True
            ),
            bid_ref=BidRef("a.mdb", "bid-1"),
            deferred_persistence_manager=deferred,
        )
        self.assertFalse(context.save_cover_sheet({"job_name": "A"}))
        self.assertEqual(write_calls, [])
