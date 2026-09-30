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
    PAGE_CONTENT_TABLES,
    PAGE_DELETE_CONFIRMATION_TABLES,
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


class PageDeleteConfirmationTableTests(unittest.TestCase):
    def test_empty_page_legend_rows_do_not_trigger_delete_confirmation(self):
        self.assertIn("BidLegends", PAGE_CONTENT_TABLES)
        self.assertNotIn("BidLegends", PAGE_DELETE_CONFIRMATION_TABLES)

    def test_delete_confirmation_still_includes_user_page_content(self):
        self.assertIn("BidTakeoffs", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidComments", PAGE_DELETE_CONFIRMATION_TABLES)
        self.assertIn("BidTexts", PAGE_DELETE_CONFIRMATION_TABLES)
