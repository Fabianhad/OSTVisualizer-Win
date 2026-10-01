import unittest
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_bid_clipboard_file_unload_invalidates_equivalent_source_path(self):
        clipboard = BidClipboardService()
        clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        revision_before_unload = clipboard.ownership_revision
        self.assertTrue(clipboard.clear_for_file("C:\\jobs\\test.mdb"))
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)
        self.assertEqual(clipboard.bid_refs, [])
        self.assertGreater(clipboard.ownership_revision, revision_before_unload)

    def test_unloading_unrelated_or_blank_file_keeps_clipboard(self):
        clipboard = BidClipboardService()
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        clipboard.cut([bid_ref])
        revision = clipboard.ownership_revision
        self.assertFalse(clipboard.clear_for_file("C:/jobs/other.mdb"))
        self.assertFalse(clipboard.clear_for_file(""))
        self.assertEqual(clipboard.bid_refs, [bid_ref])
        self.assertTrue(clipboard.is_cut)
        self.assertEqual(clipboard.ownership_revision, revision)

    def test_stale_cut_completion_cannot_consume_recopied_clipboard(self):
        clipboard = BidClipboardService()
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        clipboard.cut([bid_ref])
        stale_revision = clipboard.ownership_revision
        clipboard.cut([bid_ref])
        self.assertFalse(clipboard.complete_cut(stale_revision, [bid_ref]))
        self.assertEqual(clipboard.bid_refs, [bid_ref])
        self.assertTrue(clipboard.complete_cut(clipboard.ownership_revision, [bid_ref]))
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)
