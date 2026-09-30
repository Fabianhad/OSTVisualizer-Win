import unittest
from ost_visualizer.infrastructure.mdb import schema_contract


class SchemaContractCompatibilityTests(unittest.TestCase):
    def test_schema_contract_builds_raw_table_groups(self):
        self.assertIn("BidLayers", schema_contract.BID_SECTIONS)
        self.assertIn("BidPages", schema_contract.RAW_BID_TABLES)
        self.assertIn("BidNamedViews", schema_contract.RAW_BID_TABLES)
        self.assertIn("Employees", schema_contract.RAW_GLOBAL_TABLES)
        self.assertEqual(schema_contract.singular("BidLayers"), "BidLayer")
