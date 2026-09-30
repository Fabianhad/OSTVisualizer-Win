import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)


class SummaryTabIndexTests(unittest.TestCase):
    def test_summary_tab_index_is_third_tab(self):
        self.assertEqual(TAB_INDEX_SUMMARY, 2)
