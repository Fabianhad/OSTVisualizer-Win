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
from ost_visualizer.infrastructure.mdb.components import constants
from ost_visualizer.infrastructure.mdb.components.constants import (
    BID_TABLES_WRITE_ORDER,
    PAGE_ANNOTATION_TABLES,
    PAGE_CONTENT_TABLES,
    PAGE_DELETE_CONFIRMATION_TABLES,
    hex_to_color_int,
)
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
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

    def test_hex_to_color_int_edge_inputs(self):
        self.assertEqual(hex_to_color_int("#000000"), 0)
        self.assertEqual(hex_to_color_int("#FFFFFF"), 0xFFFFFF)
        self.assertEqual(hex_to_color_int("aBcDeF"), 0xEFCDAB)
        self.assertEqual(hex_to_color_int("##FF0000"), 0x0000FF)
        # Only the first six hex digits are used; an alpha suffix is ignored.
        self.assertEqual(hex_to_color_int("#FF0000AA"), 0x0000FF)
        # Each channel is its own byte: no channel bleeds into another.
        self.assertEqual(hex_to_color_int("#010000"), 0x000001)
        self.assertEqual(hex_to_color_int("#000100"), 0x000100)
        self.assertEqual(hex_to_color_int("#000001"), 0x010000)
        for bad in (
            "",
            "#",
            "#FFF",
            "#FF00",
            "GG0000",
            "#12G456",
            "#XFF0000",
            "XXFF0000",
        ):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    hex_to_color_int(bad)

    def test_bid_write_order_places_pages_before_page_dependents(self):
        self.assertEqual(len(BID_TABLES_WRITE_ORDER), len(set(BID_TABLES_WRITE_ORDER)))
        order = BID_TABLES_WRITE_ORDER
        self.assertLess(order.index("BidPages"), order.index("BidSettings"))
        self.assertLess(order.index("BidPages"), order.index("BidTypGroupViews"))
        self.assertLess(order.index("BidSettings"), order.index("BidNamedViews"))
        self.assertEqual(order[-2:], ["BidNamedViews", "BidHotLinks"])

    def test_bid_write_order_exact_literal_sequence(self):
        self.assertEqual(
            BID_TABLES_WRITE_ORDER,
            [
                "BidPlanRooms",
                "BidAreas",
                "BidTypAreas",
                "BidConditionFolders",
                "BidPageFolders",
                "BidEmployees",
                "BidLayers",
                "BidTypAreaCounts",
                "BidConditions",
                "UserMasterConditions",
                "BidConditionUser",
                "BidZones",
                "OCRProps",
                "BidPages",
                "BidSettings",
                "BidTypGroupViews",
                "BidNamedViews",
                "BidHotLinks",
            ],
        )
        self.assertIsInstance(BID_TABLES_WRITE_ORDER, list)


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


class ConstantsLiteralCatalogTests(unittest.TestCase):
    """Pins every table/column catalog constant to an independent literal."""

    def test_page_table_catalogs_exact_literal_values(self):
        self.assertEqual(
            constants.PAGE_ANNOTATION_TABLES,
            (
                "BidDimensions",
                "BidALines",
                "BidArrows",
                "BidHighlights",
                "BidTexts",
                "BidCallOuts",
                "BidAnnotationRects",
                "BidAnnotationOvals",
                "BidAnnotationPolygons",
                "BidAnnotationClouds",
                "BidAnnoInk",
                "BidLegends",
                "BidComments",
            ),
        )
        self.assertEqual(
            constants.PAGE_AUXILIARY_CHILD_TABLES,
            (
                "BidPageSettings",
                "BidAreaTranslations",
                "BidMarkedPages",
                "BidPercents",
                "BidTakeoffTotals",
                "BidLaborCostCodeTotals",
                "BidTypicalGroupTotals",
                "BidTypGroupViews",
                "Boost",
                "DPCCalcFilter",
            ),
        )
        self.assertEqual(
            constants.PAGE_DELETE_CHILD_TABLES,
            constants.PAGE_ANNOTATION_TABLES + constants.PAGE_AUXILIARY_CHILD_TABLES,
        )
        self.assertEqual(
            len(constants.PAGE_DELETE_CHILD_TABLES),
            len(set(constants.PAGE_DELETE_CHILD_TABLES)),
        )
        self.assertEqual(
            constants.PAGE_CONTENT_TABLES,
            (
                "BidTakeoffs",
                "BidDimensions",
                "BidALines",
                "BidArrows",
                "BidHighlights",
                "BidTexts",
                "BidCallOuts",
                "BidAnnotationRects",
                "BidAnnotationOvals",
                "BidAnnotationPolygons",
                "BidAnnotationClouds",
                "BidAnnoInk",
                "BidLegends",
                "BidComments",
                "BidNamedViews",
                "BidHotLinks",
            ),
        )
        self.assertEqual(
            constants.PAGE_DELETE_CONFIRMATION_TABLES,
            (
                "BidTakeoffs",
                "BidDimensions",
                "BidALines",
                "BidArrows",
                "BidHighlights",
                "BidTexts",
                "BidCallOuts",
                "BidAnnotationRects",
                "BidAnnotationOvals",
                "BidAnnotationPolygons",
                "BidAnnotationClouds",
                "BidAnnoInk",
                "BidComments",
                "BidNamedViews",
                "BidHotLinks",
            ),
        )

    def test_takeoff_reference_catalogs_exact_literal_values(self):
        self.assertEqual(
            constants.TAKEOFF_REFERENCE_TABLES,
            ("BidDimensions", "BidALines", "BidArrows"),
        )
        self.assertEqual(
            constants.TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
            ("BidTakeoffFromUID", "BidTakeoffToUID"),
        )
        self.assertEqual(
            constants.TAKEOFF_SELF_REFERENCE_COLUMNS,
            (
                "ParentUID",
                "TypGroupTakeoffUID",
                "TypPageTakeoffUID",
                "TypGroupMarkerUID",
            ),
        )
        self.assertEqual(
            constants.LAYER_REFERENCE_TABLES,
            (
                "BidConditions",
                "BidZones",
                "BidComments",
                "BidAnnotationClouds",
                "BidAnnotationOvals",
                "BidAnnotationPolygons",
                "BidAnnotationRects",
                "BidTexts",
                "BidHighlights",
                "BidHotLinks",
                "BidCallOuts",
            ),
        )

    def test_bid_duplication_catalogs_exact_literal_values(self):
        self.assertEqual(
            constants.HANDLED_SEPARATELY,
            {
                "BidTypGroupViews",
                "BidSettings",
                "BidTakeoffTotals",
                "OCRProps",
                "BidConditions",
                "BidConditionFolders",
                "BidLayers",
                "BidAreas",
                "BidZones",
                "BidPageFolders",
                "BidNamedViews",
            },
        )
        self.assertIs(type(constants.HANDLED_SEPARATELY), set)
        self.assertEqual(
            constants.ADDITIONAL_BID_TABLES_COPIED_BY_DUPLICATION,
            (
                "AffectDPCTypGroupViews",
                "BidLaborCostCodeTotals",
                "BidTypicalGroupTotals",
                "Boost",
                "DPCCalcFilter",
                "BidLaborActivity",
                "BidLaborCostCodes",
                "BidDPCSubscribers",
                "BidNotes",
                "BidTimeCardStates",
            ),
        )
        self.assertEqual(
            constants.DERIVED_BID_TOTAL_TABLES,
            frozenset(
                {
                    "BidTakeoffTotals",
                    "BidLaborCostCodeTotals",
                    "BidTypicalGroupTotals",
                }
            ),
        )
        self.assertIsInstance(constants.DERIVED_BID_TOTAL_TABLES, frozenset)

    def test_scalar_constants_exact_literal_values(self):
        self.assertIs(type(constants.COVER_SHEET_PAGE_SELECTION_TYPE), int)
        self.assertEqual(constants.COVER_SHEET_PAGE_SELECTION_TYPE, 1)
        self.assertEqual(
            constants.NUMERIC_TYPE_SUBSTRINGS,
            (
                "int",
                "long",
                "short",
                "double",
                "float",
                "real",
                "bit",
                "byte",
                "counter",
                "currency",
                "single",
                "numeric",
                "decimal",
            ),
        )

    def test_numeric_substrings_classify_odbc_type_names(self):
        def is_numeric(type_name):
            return any(t in type_name for t in constants.NUMERIC_TYPE_SUBSTRINGS)

        for numeric in (
            "integer",
            "smallint",
            "counter",
            "currency",
            "double",
            "single",
            "bit",
            "byte",
            "decimal",
            "numeric",
            "real",
            "float",
        ):
            with self.subTest(numeric=numeric):
                self.assertIs(is_numeric(numeric), True)
        for non_numeric in ("varchar", "text", "datetime", "image", "char", "guid"):
            with self.subTest(non_numeric=non_numeric):
                self.assertIs(is_numeric(non_numeric), False)

    def test_catalog_tables_and_columns_exist_in_the_reference_schema(self):
        schema = get_reference_schema_model()
        catalog_tables = (
            set(constants.BID_TABLES_WRITE_ORDER)
            | constants.HANDLED_SEPARATELY
            | set(constants.ADDITIONAL_BID_TABLES_COPIED_BY_DUPLICATION)
            | constants.DERIVED_BID_TOTAL_TABLES
            | set(constants.TAKEOFF_REFERENCE_TABLES)
            | set(constants.PAGE_DELETE_CHILD_TABLES)
            | set(constants.PAGE_CONTENT_TABLES)
            | set(constants.LAYER_REFERENCE_TABLES)
        )
        self.assertEqual(catalog_tables - schema.table_names, set())
        takeoff_columns = {c.name for c in schema.table("BidTakeoffs").columns}
        for column in constants.TAKEOFF_SELF_REFERENCE_COLUMNS:
            with self.subTest(self_reference=column):
                self.assertIn(column, takeoff_columns)
        for table in constants.TAKEOFF_REFERENCE_TABLES:
            columns = {c.name for c in schema.table(table).columns}
            for column in constants.TAKEOFF_ANNOTATION_REFERENCE_COLUMNS:
                with self.subTest(table=table, column=column):
                    self.assertIn(column, columns)
