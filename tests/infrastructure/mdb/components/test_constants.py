from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from types import MappingProxyType, SimpleNamespace
import unittest
from ost_visualizer.infrastructure.mdb.components.constants import (
    BID_TABLES_WRITE_ORDER,
    PAGE_ANNOTATION_TABLES,
    PAGE_CONTENT_TABLES,
    PAGE_DELETE_CONFIRMATION_TABLES,
    hex_to_color_int,
)


class ConstantsPersistenceTests(unittest.TestCase):
    def test_static_mdb_lookup_tables_are_immutable(self):
        self.assertIsInstance(
            AnnotationOperationsMixin._ANNOTATION_TABLE, MappingProxyType
        )
        self.assertIsInstance(
            ConditionOperationsMixin._FIELD_TO_COLUMN, MappingProxyType
        )
        self.assertIsInstance(PageOperationsMixin._POSITION_TABLES, tuple)
        with self.assertRaises(TypeError):
            AnnotationOperationsMixin._ANNOTATION_TABLE["Injected"] = "BidInjected"
        with self.assertRaises(TypeError):
            ConditionOperationsMixin._FIELD_TO_COLUMN["injected"] = "Injected"
        self.assertNotIn("Injected", AnnotationOperationsMixin._ANNOTATION_TABLE)
        self.assertNotIn("injected", ConditionOperationsMixin._FIELD_TO_COLUMN)
        self.assertEqual(
            PageOperationsMixin._POSITION_TABLES,
            PAGE_CONTENT_TABLES + ("BidTypGroupViews",),
        )

    def test_hex_to_color_int_packs_bgr_with_or_without_hash(self):
        self.assertEqual(hex_to_color_int("#FF0000"), 0x0000FF)
        self.assertEqual(hex_to_color_int("00ff00"), 0x00FF00)
        self.assertEqual(hex_to_color_int("#0000FF"), 0xFF0000)
        self.assertEqual(hex_to_color_int("#102030"), 0x302010)

    def test_bid_write_order_places_pages_before_page_dependents(self):
        self.assertEqual(len(BID_TABLES_WRITE_ORDER), len(set(BID_TABLES_WRITE_ORDER)))
        order = BID_TABLES_WRITE_ORDER
        self.assertLess(order.index("BidPages"), order.index("BidSettings"))
        self.assertLess(order.index("BidPages"), order.index("BidTypGroupViews"))
        self.assertLess(order.index("BidSettings"), order.index("BidNamedViews"))
        self.assertEqual(order[-2:], ["BidNamedViews", "BidHotLinks"])


class PageDeleteConfirmationTableTests(unittest.TestCase):
    def test_empty_page_legend_rows_do_not_trigger_delete_confirmation(self):
        self.assertIn("BidLegends", PAGE_CONTENT_TABLES)
        self.assertNotIn("BidLegends", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertEqual(
            PAGE_DELETE_CONFIRMATION_TABLES,
            tuple(t for t in PAGE_CONTENT_TABLES if t != "BidLegends"),
        )

    def test_delete_confirmation_still_includes_user_page_content(self):
        self.assertIn("BidTakeoffs", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidComments", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidTexts", PAGE_DELETE_CONFIRMATION_TABLES)
        for table in PAGE_ANNOTATION_TABLES:
            if table != "BidLegends":
                with self.subTest(table=table):
                    self.assertIn(table, PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidNamedViews", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidHotLinks", PAGE_DELETE_CONFIRMATION_TABLES)
