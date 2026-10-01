import unittest
from ost_visualizer.infrastructure.mdb import schema_contract


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

    def test_singular_applies_irregular_overrides_and_leaves_non_plural_names(self):
        self.assertEqual(schema_contract.singular("JobStatuses"), "JobStatuse")
        self.assertEqual(schema_contract.singular("PayClasses"), "PayClass")
        self.assertEqual(schema_contract.singular("BidAreas"), "BidArea")
        self.assertEqual(schema_contract.singular("OCRProps"), "OCRProp")
        self.assertEqual(schema_contract.singular("BidSettings"), "BidSetting")
        self.assertEqual(schema_contract.singular("Bid"), "Bid")

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
