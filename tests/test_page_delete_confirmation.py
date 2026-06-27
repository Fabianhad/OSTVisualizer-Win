import unittest

from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_CONTENT_TABLES,
    PAGE_DELETE_CONFIRMATION_TABLES,
)


class PageDeleteConfirmationTableTests(unittest.TestCase):
    def test_empty_page_legend_rows_do_not_trigger_delete_confirmation(self):
        self.assertIn("BidLegends", PAGE_CONTENT_TABLES)
        self.assertNotIn("BidLegends", PAGE_DELETE_CONFIRMATION_TABLES)

    def test_delete_confirmation_still_includes_user_page_content(self):
        self.assertIn("BidTakeoffs", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidComments", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidTexts", PAGE_DELETE_CONFIRMATION_TABLES)


if __name__ == "__main__":
    unittest.main()
