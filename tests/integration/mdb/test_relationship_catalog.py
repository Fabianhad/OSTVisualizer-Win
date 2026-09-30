import unittest
from ost_visualizer.infrastructure.mdb.components.constants import (
    LAYER_REFERENCE_TABLES,
    PAGE_DELETE_CHILD_TABLES,
)
from ost_visualizer.infrastructure.mdb.database_creator import (
    DatabaseCreator,
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import BID_RELATIONSHIPS


class RelationshipCatalogCompatibilityTests(unittest.TestCase):
    def test_layer_reference_tables_match_the_shared_mdb_and_sql_schema(self):
        schema = get_reference_schema_model()
        schema_layer_tables = {
            table.name
            for table in schema.tables
            if any(column.name == "BidLayerUID" for column in table.columns)
        }
        self.assertEqual(schema_layer_tables, set(LAYER_REFERENCE_TABLES))
        self.assertTrue(
            {
                "BidTakeoffs",
                "BidDimensions",
                "BidArrows",
                "BidALines",
                "BidAnnoInk",
                "BidLegends",
            }.isdisjoint(schema_layer_tables)
        )

    def test_bid_relationship_catalog_covers_schema_foreign_keys(self):
        catalog = {
            (
                relationship.child_table.casefold(),
                relationship.child_column.casefold(),
                relationship.parent_table.casefold(),
                relationship.parent_column.casefold(),
            )
            for relationship in BID_RELATIONSHIPS
        }
        excluded_external_relationships = {
            (
                "conditionsetstyles",
                "conditionstyleuid",
                "bidconditions",
                "uid",
            ),
        }
        schema_relationships = {
            (
                relationship.child_table.casefold(),
                relationship.child_column.casefold(),
                relationship.parent_table.casefold(),
                relationship.parent_column.casefold(),
            )
            for relationship in get_reference_schema_model().foreign_keys
            if relationship.child_table.casefold().startswith("bid")
            or relationship.parent_table.casefold().startswith("bid")
        }
        self.assertEqual(
            schema_relationships - catalog, excluded_external_relationships
        )

    def test_page_delete_catalog_covers_every_direct_page_child(self):
        direct_page_children = {
            table.name
            for table in get_reference_schema_model().tables
            if any(column.name == "BidPageUID" for column in table.columns)
        }
        specially_ordered_children = {
            "BidTakeoffs",
            "BidNamedViews",
            "BidHotLinks",
        }
        self.assertEqual(
            set(PAGE_DELETE_CHILD_TABLES) | specially_ordered_children,
            direct_page_children,
        )
