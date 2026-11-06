import json
import unittest
from ost_visualizer.infrastructure.mdb import schema_contract
from tests.paths import FIXTURES_ROOT

_EXPECTED_BID_SECTIONS = [
    "BidPlanRooms",
    "BidAreas",
    "BidTypAreas",
    "BidConditionFolders",
    "BidPageFolders",
    "BidSettings",
    "BidEmployees",
    "BidLayers",
    "BidTypAreaCounts",
    "BidConditions",
    "UserMasterConditions",
    "BidConditionUser",
    "BidZones",
    "BidTypGroupViews",
    "OCRProps",
]
_EXPECTED_PAGE_SECTIONS = [
    "BidTakeoffs",
    "BidHighlights",
    "BidTexts",
    "BidDimensions",
    "BidArrows",
    "BidALines",
    "BidCallOuts",
    "BidAnnotationRects",
    "BidAnnotationOvals",
    "BidAnnotationPolygons",
    "BidAnnotationClouds",
    "BidAnnoInk",
    "BidLegends",
    "BidPageSettings",
    "BidAreaTranslations",
    "BidMarkedPages",
    "BidComments",
]
_EXPECTED_GLOBAL_SECTIONS = [
    "Employees",
    "PayClasses",
    "AccessLevels",
    "CdnTypes",
    "JobStatuses",
]


class SchemaContractCompatibilityTests(unittest.TestCase):
    def test_schema_contract_builds_raw_table_groups(self):
        self.assertIn("BidLayers", schema_contract.BID_SECTIONS)
        self.assertIn("BidPages", schema_contract.RAW_BID_TABLES)
        self.assertIn("BidNamedViews", schema_contract.RAW_BID_TABLES)
        self.assertIn("Employees", schema_contract.RAW_GLOBAL_TABLES)
        self.assertEqual(schema_contract.singular("BidLayers"), "BidLayer")
        self.assertEqual(
            schema_contract.RAW_BID_TABLES,
            schema_contract.BID_SECTIONS
            + ["BidPages"]
            + schema_contract.BID_TAIL_SECTIONS,
        )
        self.assertEqual(
            schema_contract.RAW_GLOBAL_TABLES,
            schema_contract.GLOBAL_SECTIONS,
        )
        self.assertEqual(
            len(schema_contract.RAW_BID_TABLES),
            len(set(schema_contract.RAW_BID_TABLES)),
        )
        self.assertEqual(
            schema_contract.BID_TAIL_SECTIONS, ["BidNamedViews", "BidHotLinks"]
        )

    def test_section_lists_match_the_exact_ordered_literal_table_names(self):
        # Order is the XML section / write order, so it is part of the contract.
        self.assertEqual(schema_contract.BID_SECTIONS, _EXPECTED_BID_SECTIONS)
        self.assertEqual(schema_contract.PAGE_SECTIONS, _EXPECTED_PAGE_SECTIONS)
        self.assertEqual(
            schema_contract.BID_TAIL_SECTIONS, ["BidNamedViews", "BidHotLinks"]
        )
        self.assertEqual(schema_contract.GLOBAL_SECTIONS, _EXPECTED_GLOBAL_SECTIONS)
        self.assertEqual(
            schema_contract.RAW_BID_TABLES,
            _EXPECTED_BID_SECTIONS + ["BidPages", "BidNamedViews", "BidHotLinks"],
        )
        self.assertEqual(schema_contract.RAW_GLOBAL_TABLES, _EXPECTED_GLOBAL_SECTIONS)
        for name in (
            "BID_SECTIONS",
            "PAGE_SECTIONS",
            "BID_TAIL_SECTIONS",
            "GLOBAL_SECTIONS",
            "RAW_BID_TABLES",
            "RAW_GLOBAL_TABLES",
        ):
            self.assertIsInstance(getattr(schema_contract, name), list, name)

    def test_every_contract_table_exists_in_the_reference_schema_fixture(self):
        fixture = json.loads(
            (FIXTURES_ROOT / "reference_mdb_schema.json").read_text(encoding="utf-8")
        )
        reference_tables = set(fixture["uid_required_tables"])
        self.assertEqual(len(reference_tables), 64)
        contract_tables = (
            set(schema_contract.BID_SECTIONS)
            | set(schema_contract.PAGE_SECTIONS)
            | set(schema_contract.BID_TAIL_SECTIONS)
            | set(schema_contract.GLOBAL_SECTIONS)
            | {"BidPages"}
        )
        self.assertEqual(len(contract_tables), 15 + 17 + 2 + 5 + 1)
        self.assertEqual(contract_tables - reference_tables, set())

    def test_singular_applies_irregular_overrides_and_leaves_non_plural_names(self):
        self.assertEqual(schema_contract.singular("JobStatuses"), "JobStatuse")
        self.assertEqual(schema_contract.singular("PayClasses"), "PayClass")
        self.assertEqual(schema_contract.singular("BidAreas"), "BidArea")
        self.assertEqual(schema_contract.singular("OCRProps"), "OCRProp")
        self.assertEqual(schema_contract.singular("BidSettings"), "BidSetting")
        self.assertEqual(schema_contract.singular("Bid"), "Bid")

    def test_singular_of_every_section_table_strips_exactly_one_trailing_s(self):
        expected = {
            "BidPlanRooms": "BidPlanRoom",
            "BidTypAreas": "BidTypArea",
            "BidConditionFolders": "BidConditionFolder",
            "BidPageFolders": "BidPageFolder",
            "BidEmployees": "BidEmployee",
            "BidTypAreaCounts": "BidTypAreaCount",
            "BidConditions": "BidCondition",
            "UserMasterConditions": "UserMasterCondition",
            "BidConditionUser": "BidConditionUser",
            "BidZones": "BidZone",
            "BidTypGroupViews": "BidTypGroupView",
            "BidTakeoffs": "BidTakeoff",
            "BidAnnoInk": "BidAnnoInk",
            "BidLegends": "BidLegend",
            "BidPageSettings": "BidPageSetting",
            "BidAreaTranslations": "BidAreaTranslation",
            "BidMarkedPages": "BidMarkedPage",
            "BidComments": "BidComment",
            "BidPages": "BidPage",
            "BidNamedViews": "BidNamedView",
            "BidHotLinks": "BidHotLink",
            "Employees": "Employee",
            "AccessLevels": "AccessLevel",
            "CdnTypes": "CdnType",
            "Boss": "Bos",
            "": "",
        }
        for table, singular in expected.items():
            with self.subTest(table=table):
                self.assertEqual(schema_contract.singular(table), singular)

    def test_ost_xml_column_aliases_are_exact_inverses(self):
        self.assertEqual(
            schema_contract.DATABASE_TO_OST_XML_COLUMN,
            {"CopyTimeStamp": "CopyTimestamp"},
        )
        self.assertEqual(
            schema_contract.OST_XML_TO_DATABASE_COLUMN,
            {"CopyTimestamp": "CopyTimeStamp"},
        )

    def test_default_layer_rows_define_the_four_named_layers_with_unique_orders(self):
        names = [row[0] for row in schema_contract.DEFAULT_LAYER_ROWS]
        orders = [row[3] for row in schema_contract.DEFAULT_LAYER_ROWS]
        self.assertEqual(names, ["Default", "Annotation", "Image", "Comments"])
        self.assertEqual(sorted(orders), [0, 1, 2, 3])

    def test_default_layer_rows_exact_values_and_types(self):
        rows = schema_contract.DEFAULT_LAYER_ROWS
        self.assertIsInstance(rows, tuple)
        self.assertEqual(
            rows,
            (
                ("Default", True, True, 2),
                ("Annotation", True, True, 1),
                ("Image", True, True, 0),
                ("Comments", True, True, 3),
            ),
        )
        for row in rows:
            with self.subTest(layer=row[0]):
                self.assertIs(row[1], True)
                self.assertIs(row[2], True)
                self.assertIs(type(row[3]), int)
