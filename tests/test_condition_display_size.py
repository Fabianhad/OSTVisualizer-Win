import unittest
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)


class ConditionDisplaySizeTests(unittest.TestCase):
    def test_non_positive_display_size_reads_as_default_percent(self):
        self.assertEqual(BidDataReaderMixin._normalize_display_size(None), 100.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size(0), 100.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size("0"), 100.0)

    def test_positive_display_size_reads_unchanged(self):
        self.assertEqual(BidDataReaderMixin._normalize_display_size(75), 75.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size("125"), 125.0)


if __name__ == "__main__":
    unittest.main()
