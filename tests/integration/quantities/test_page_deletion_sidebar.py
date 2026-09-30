import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from PySide6 import QtWidgets


class PageDeletionQuantitySidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_conditions_spanning_deleted_and_remaining_pages_recalculate(self):
        spanning = Condition(
            uid="spanning",
            name="Spanning",
            condition_type=Condition.TYPE_COUNT,
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
        )
        deleted_only = Condition(
            uid="deleted-only",
            name="Deleted only",
            condition_type=Condition.TYPE_COUNT,
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
        )
        conditions = {spanning.uid: spanning, deleted_only.uid: deleted_only}
        takeoffs = [
            Takeoff(uid="takeoff-1", condition_uid=spanning.uid, page_uid="page-1"),
            Takeoff(uid="takeoff-2", condition_uid=spanning.uid, page_uid="page-2"),
            Takeoff(
                uid="takeoff-3",
                condition_uid=deleted_only.uid,
                page_uid="page-1",
            ),
        ]
        remaining_takeoffs = [
            takeoff for takeoff in takeoffs if takeoff.page_uid == "page-2"
        ]
        quantities = compute_page_quantities(conditions, remaining_takeoffs)
        sidebar = ConditionsSidebar(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
        )
        try:
            sidebar.load_conditions(conditions, {}, "Bid", grayscale=False)
            sidebar.update_quantities(quantities)
            self.assertEqual(sidebar._condition_items[spanning.uid].text(2), "1 EA")
            self.assertEqual(sidebar._condition_items[deleted_only.uid].text(2), "0 EA")
        finally:
            sidebar.deleteLater()
