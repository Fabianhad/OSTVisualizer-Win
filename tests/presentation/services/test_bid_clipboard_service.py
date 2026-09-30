import unittest
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_bid_clipboard_file_unload_invalidates_equivalent_source_path(self):
        clipboard = BidClipboardService()
        clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        self.assertTrue(clipboard.clear_for_file("C:\\jobs\\test.mdb"))
        self.assertFalse(clipboard.has_content())
        self.assertFalse(clipboard.is_cut)
