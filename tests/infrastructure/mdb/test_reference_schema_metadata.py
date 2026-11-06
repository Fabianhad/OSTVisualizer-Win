import json
import unittest
from ost_visualizer.infrastructure.mdb import reference_schema_metadata as metadata
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)
from tests.paths import FIXTURES_ROOT


def _load_fixture() -> dict:
    return json.loads(
        (FIXTURES_ROOT / "reference_mdb_schema.json").read_text(encoding="utf-8")
    )


class ReferenceSchemaMetadataFixtureTests(unittest.TestCase):
    """The DAO metadata applied to new MDBs equals the captured reference."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = _load_fixture()

    def test_fixture_has_the_expected_reference_cardinalities(self):
        self.assertEqual(len(self.fixture["uid_required_tables"]), 64)
        self.assertEqual(len(self.fixture["field_defaults"]), 61)
        self.assertEqual(len(self.fixture["explicit_indexes"]), 131)
        self.assertEqual(len(self.fixture["relationships"]), 83)

    def test_uid_required_tables_match_the_reference_exactly(self):
        tables = metadata.UID_REQUIRED_TABLES
        self.assertIsInstance(tables, tuple)
        self.assertEqual(len(tables), 64)
        self.assertEqual(len(set(tables)), 64)
        self.assertEqual(sorted(tables), sorted(self.fixture["uid_required_tables"]))

    def test_field_defaults_match_the_reference_exactly(self):
        defaults = metadata.FIELD_DEFAULTS
        self.assertIsInstance(defaults, dict)
        self.assertEqual(len(defaults), 61)
        expected = {
            (item["table"], item["field"]): item["default"]
            for item in self.fixture["field_defaults"]
        }
        self.assertEqual(len(expected), 61)
        self.assertEqual(defaults, expected)
        for key, value in defaults.items():
            with self.subTest(field=key):
                self.assertIs(type(value), str)

    def test_field_defaults_pin_the_non_zero_backup_settings(self):
        defaults = metadata.FIELD_DEFAULTS
        self.assertEqual(defaults[("Settings", "BackupNo")], "2")
        self.assertEqual(defaults[("Settings", "BackupPeriod")], "2")
        self.assertEqual(defaults[("Settings", "CompressPeriod")], "3")
        self.assertEqual(
            sorted(key for key, value in defaults.items() if value != "0"),
            [
                ("Settings", "BackupNo"),
                ("Settings", "BackupPeriod"),
                ("Settings", "CompressPeriod"),
            ],
        )

    def test_explicit_indexes_match_the_reference_exactly(self):
        indexes = metadata.EXPLICIT_INDEXES
        self.assertIsInstance(indexes, tuple)
        self.assertEqual(len(indexes), 131)
        expected = {
            (item["table"], item["name"], item["unique"], tuple(item["fields"]))
            for item in self.fixture["explicit_indexes"]
        }
        self.assertEqual(len(expected), 131)
        self.assertEqual(set(indexes), expected)
        self.assertEqual(len(set(indexes)), 131)
        for table, name, unique, columns in indexes:
            with self.subTest(index=name):
                self.assertIs(type(unique), bool)
                self.assertIsInstance(columns, tuple)

    def test_only_the_locking_indexes_are_unique(self):
        self.assertEqual(
            [entry for entry in metadata.EXPLICIT_INDEXES if entry[2]],
            [
                ("Locking", "UI_Locking", True, ("Essence", "Owner")),
                ("Locking", "UI_Locking2", True, ("Essence",)),
            ],
        )

    def test_relationships_match_the_reference_exactly(self):
        relationships = metadata.REFERENCE_RELATIONSHIPS
        self.assertIsInstance(relationships, tuple)
        self.assertEqual(len(relationships), 83)
        expected = {
            (
                item["name"],
                item["child_table"],
                item["child_column"],
                item["parent_table"],
                item["parent_column"],
            )
            for item in self.fixture["relationships"]
        }
        self.assertEqual(len(expected), 83)
        self.assertEqual(set(relationships), expected)
        self.assertEqual(len({r[0] for r in relationships}), 83)

    def test_relationship_names_follow_the_dao_naming_convention(self):
        # DAO names each relation <child>_<column>1, except the legacy BidNotes_Bids1.
        irregular = {
            ("BidNotes_Bids1", "BidNotes", "BidUID", "Bids", "UID"),
        }
        for name, child, column, parent, parent_column in (
            metadata.REFERENCE_RELATIONSHIPS
        ):
            with self.subTest(relation=name):
                self.assertEqual(parent_column, "UID")
                if (name, child, column, parent, parent_column) in irregular:
                    continue
                self.assertEqual(name, f"{child}_{column}1")


class ReferenceSchemaMetadataDdlConsistencyTests(unittest.TestCase):
    """Cross-checks the metadata against the independent CREATE TABLE DDL."""

    @classmethod
    def setUpClass(cls):
        schema = get_reference_schema_model()
        cls.columns = {
            table.name.casefold(): {column.name.casefold() for column in table.columns}
            for table in schema.tables
        }

    def test_uid_required_tables_are_tables_with_a_uid_column(self):
        self.assertEqual(len(self.columns), 64)
        for table in metadata.UID_REQUIRED_TABLES:
            with self.subTest(table=table):
                self.assertIn("uid", self.columns[table.casefold()])
        self.assertEqual(
            {table.casefold() for table in metadata.UID_REQUIRED_TABLES},
            set(self.columns),
        )

    def test_field_defaults_name_existing_columns(self):
        for table, field in metadata.FIELD_DEFAULTS:
            with self.subTest(table=table, field=field):
                self.assertIn(field.casefold(), self.columns[table.casefold()])

    def test_index_and_relationship_endpoints_name_existing_columns(self):
        for table, name, _unique, fields in metadata.EXPLICIT_INDEXES:
            for field in fields:
                with self.subTest(index=name, field=field):
                    self.assertIn(field.casefold(), self.columns[table.casefold()])
        for name, child, child_column, parent, parent_column in (
            metadata.REFERENCE_RELATIONSHIPS
        ):
            with self.subTest(relation=name):
                self.assertIn(child_column.casefold(), self.columns[child.casefold()])
                self.assertIn(
                    parent_column.casefold(), self.columns[parent.casefold()]
                )
