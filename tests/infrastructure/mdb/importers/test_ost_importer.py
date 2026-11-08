import logging
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
import pyodbc
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.importers import (
    ost_importer as ost_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    RAW_BID_RELATIONSHIPS,
    prepare_raw_bid_data_for_export,
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from tests.helpers.mdb.import_export_support import (
    _CapturingImportWriter as _import_export_support__CapturingImportWriter,
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
    _orphan_named_view_hotlink_xml as _import_export_support__orphan_named_view_hotlink_xml,
)


class OstImporterRelationshipTests(unittest.TestCase):
    def _mutation_importer(self, value):
        calls = []

        def import_ost_data(target_db_path, raw_data, transform_fn, target_project_uid):
            calls.append((target_db_path, target_project_uid, transform_fn))
            return value

        importer = OstImporter(SimpleNamespace(import_ost_data=import_ost_data))
        return importer, calls

    @staticmethod
    def _mutation_recorder():
        records = []
        recorder = SimpleNamespace(
            record=lambda resource, operation, *, changed_fields=(), payload="": records.append(
                (resource, operation)
            )
        )
        return recorder, records

    def test_sql_import_mutation_records_every_authoritative_family(self):
        value = {
            "project_uids": {"target": "9"},
            "bid_uids": {"1": "10"},
            "page_uids": {"2": "20"},
            "condition_uids": {"3": "30"},
            "layer_uids": {"4": "40"},
            "area_uids": {"5": "50"},
            "takeoff_uids": {"6": "60"},
            "annotation_uids": {"7": "70"},
            "table_uid_maps": {},
            "global_uid_maps": {},
        }
        importer, calls = self._mutation_importer(value)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "CdnTypes": [{"UID": "1"}],
                "JobStatuses": [{"UID": "2"}],
                "Employees": [{"UID": "3"}],
                "PayClasses": [{"UID": "4"}],
            },
        )
        recorder, records = self._mutation_recorder()
        with patch.object(importer, "_validated_raw_data", return_value=raw_data):
            result = importer.import_ost_mutation(
                "source.ost", "database", "9", recorder
            )
        self.assertIs(result, value)
        self.assertEqual([(call[0], call[1]) for call in calls], [("database", "9")])
        self.assertEqual(calls[0][2].__func__, OstImporter._transform)
        self.assertEqual(
            records,
            [
                (ResourceRef("bid", "10", 10), ChangeOperation.CREATE),
                (ResourceRef("project_bids", "9"), ChangeOperation.UPDATE),
                *(
                    (ResourceRef(resource_type, "10", 10), ChangeOperation.BULK_REFRESH)
                    for resource_type in (
                        "conditions_collection",
                        "areas_collection",
                        "pages_collection",
                        "layers_collection",
                        "takeoffs_collection",
                        "annotations_collection",
                        "cover_sheet",
                    )
                ),
                *(
                    (
                        ResourceRef(resource_type, "database"),
                        ChangeOperation.BULK_REFRESH,
                    )
                    for resource_type in (
                        "condition_types_collection",
                        "job_statuses_collection",
                        "employees_collection",
                        "pay_classes_collection",
                    )
                ),
            ],
        )

    def test_sql_import_mutation_omits_absent_global_families_and_orphan_project(self):
        value = {"bid_uids": {"1": "10"}}
        importer, calls = self._mutation_importer(value)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"CdnTypes": [], "Employees": [{"UID": "3"}]},
        )
        recorder, records = self._mutation_recorder()
        with patch.object(importer, "_validated_raw_data", return_value=raw_data):
            importer.import_ost_mutation("source.ost", "database", None, recorder)
        self.assertEqual(calls[0][1], None)
        self.assertEqual(
            [
                (resource.resource_type, resource.resource_id)
                for resource, _op in records
            ],
            [
                ("bid", "10"),
                ("project_bids", "orphan"),
                ("conditions_collection", "10"),
                ("areas_collection", "10"),
                ("pages_collection", "10"),
                ("layers_collection", "10"),
                ("takeoffs_collection", "10"),
                ("annotations_collection", "10"),
                ("cover_sheet", "10"),
                ("employees_collection", "database"),
            ],
        )

    def test_sql_import_mutation_rejects_non_authoritative_writer_results(self):
        raw_data = RawBidData(bid_row={"UID": "1"})
        for value, message in (
            (True, "did not return authoritative identities"),
            ({}, "exactly one imported bid"),
            ({"bid_uids": {"1": "10", "2": "11"}}, "exactly one imported bid"),
            ({"bid_uids": ["10"]}, "exactly one imported bid"),
        ):
            with self.subTest(value=value):
                importer, _calls = self._mutation_importer(value)
                recorder, records = self._mutation_recorder()
                with patch.object(
                    importer, "_validated_raw_data", return_value=raw_data
                ):
                    with self.assertRaisesRegex(RuntimeError, message):
                        importer.import_ost_mutation(
                            "source.ost", "database", "9", recorder
                        )
                self.assertEqual(records, [])

    def test_ost_import_restores_database_column_name_for_copy_timestamp(self):
        xml = '<XML_ROOT><Bid UID="1" CopyTimestamp="2026 7 19 0 39 2"/></XML_ROOT>'
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "copy_timestamp.ost"
            ost_path.write_text(xml, encoding="utf-8")
            raw_data = OstImporter(object())._parse_ost_xml(str(ost_path))
        self.assertEqual(raw_data.bid_row["CopyTimeStamp"], "2026 7 19 0 39 2")
        self.assertNotIn("CopyTimestamp", raw_data.bid_row)
        self.assertEqual(raw_data.bid_row["UID"], "1")

    def test_ost_import_without_bid_element_fails_before_writer(self):
        writer = _import_export_support__CapturingImportWriter()
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "no_bid.ost"
            ost_path.write_text("<XML_ROOT/>", encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ):
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
            with self.assertRaisesRegex(ValueError, "No Bid element"):
                OstImporter(writer)._parse_ost_xml(str(ost_path))
        self.assertFalse(writer.called)

    def test_ost_import_rejects_multiple_bid_settings_rows(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="20"/>
              <BidSetting UID="31" BidUID="1" BidPageSelectedUID="21"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="First" Sequence="1"/>
              <BidPage UID="21" BidUID="1" Name="Second" Sequence="2"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "duplicate_settings.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn(
            "BidSettings has 2 rows for Bids.UID=1; expected at most 1",
            logs.output[0],
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidSettings").fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_skips_orphaned_takeoffs_and_cascading_children(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions>
              <BidCondition UID="10" BidUID="1" Name="Footing"/>
            </BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Primary"/>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30"
                              Name="Valid Child"/>
                  <BidTakeoff UID="32" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="999"
                              Name="Orphan"/>
                  <BidTakeoff UID="33" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="32"
                              Name="Cascading Orphan"/>
                  <BidTakeoff UID="34" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="33"
                              Name="Nested Cascading Orphan"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "orphan_takeoffs.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        takeoffs = connection.execute(
            "SELECT UID, ParentUID, Name FROM BidTakeoffs ORDER BY Name"
        ).fetchall()
        self.assertEqual([row[2] for row in takeoffs], ["Primary", "Valid Child"])
        takeoff_uids = {row[2]: row[0] for row in takeoffs}
        parent_uids = {row[2]: row[1] for row in takeoffs}
        self.assertIsNone(parent_uids["Primary"])
        self.assertEqual(parent_uids["Valid Child"], takeoff_uids["Primary"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Skipping 3 invalid takeoff(s)", logs.output[0])
        self.assertIn("missing-parent roots", logs.output[0])
        self.assertIn("BidTakeoffs.UID=32 ParentUID=999", logs.output[0])
        self.assertIn("skipped dependent descendants", logs.output[0])
        self.assertIn("BidTakeoffs.UID=33 ParentUID=32", logs.output[0])
        self.assertIn("BidTakeoffs.UID=34 ParentUID=33", logs.output[0])

    def test_ost_import_resolves_child_before_parent_after_full_parse(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30" Name="Child"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Parent"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
            "BidPageUID INTEGER, BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "child_first.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                OstImporter(
                    _import_export_support__SqliteMdbWriter(connection)
                ).import_ost(str(ost_path), "target.mdb")
            )
        rows = connection.execute(
            "SELECT UID, ParentUID, Name FROM BidTakeoffs ORDER BY Name"
        ).fetchall()
        by_name = {name: (uid, parent_uid) for uid, parent_uid, name in rows}
        self.assertEqual(sorted(by_name), ["Child", "Parent"])
        self.assertIsNone(by_name["Parent"][1])
        self.assertEqual(by_name["Child"][1], by_name["Parent"][0])

    def test_ost_import_rejects_duplicate_takeoff_uid_before_remapping(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="First"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" Name="Duplicate"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "duplicate_takeoff.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidTakeoffs.UID=30 occurs 2 times", logs.output[0])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_rejects_duplicate_page_uid_before_backend_remapping(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="First"/>
              <BidPage UID="20" BidUID="1" Name="Duplicate"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        writer = _import_export_support__CapturingImportWriter()
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "duplicate_page.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidPages.UID=20 occurs 2 times", logs.output[0])
        self.assertFalse(writer.called)

    def test_ost_import_rejects_malformed_bid_owned_uid_before_backend_remapping(self):
        for table, element, expected in (
            (
                "BidLayers",
                '<BidLayer UID="0" BidUID="1" Name="Layer"/>',
                "BidLayers.UID=0 has malformed UID=0",
            ),
            (
                "BidConditionFolders",
                '<BidConditionFolder UID="   " BidUID="1" Name="Folder"/>',
                "BidConditionFolders.UID=    has malformed UID=   ",
            ),
            (
                "BidZones",
                '<BidZone BidUID="1" Name="Zone"/>',
                "BidZones.UID=<no UID> has malformed UID=<missing>",
            ),
            (
                "BidTypAreas",
                '<BidTypArea UID="not-a-uid" BidUID="1"/>',
                "BidTypAreas.UID=not-a-uid has malformed UID=not-a-uid",
            ),
        ):
            with self.subTest(table=table):
                xml = f"""
                <XML_ROOT>
                  <Bid UID="1" JobName="Imported">
                    <{table}>{element}</{table}>
                  </Bid>
                </XML_ROOT>
                """
                writer = _import_export_support__CapturingImportWriter()
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "malformed_uid.ost"
                    ost_path.write_text(xml, encoding="utf-8")
                    with self.assertLogs(
                        "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                        level="ERROR",
                    ) as logs:
                        self.assertFalse(
                            OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                        )
                self.assertIn(expected, logs.output[0])
                self.assertFalse(writer.called)

    def test_ost_import_rejects_malformed_bid_and_annotation_uids(self):
        cases = (
            (
                '<Bid UID="0" JobName="Imported"/>',
                "Bids.UID=0 has malformed UID=0",
            ),
            (
                """
                <Bid UID="1" JobName="Imported">
                  <BidPages>
                    <BidPage UID="20" BidUID="1" Name="Sheet"/>
                  </BidPages>
                  <BidNamedViews>
                    <BidNamedView UID="0" BidUID="1" BidPageUID="20" Name="View"/>
                  </BidNamedViews>
                </Bid>
                """,
                "BidNamedViews.UID=0 has malformed UID=0",
            ),
        )
        for bid_xml, expected in cases:
            with self.subTest(expected=expected):
                writer = _import_export_support__CapturingImportWriter()
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "malformed_root_uid.ost"
                    ost_path.write_text(
                        f"<XML_ROOT>{bid_xml}</XML_ROOT>", encoding="utf-8"
                    )
                    with self.assertLogs(
                        "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                        level="ERROR",
                    ) as logs:
                        self.assertFalse(
                            OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                        )
                self.assertIn(expected, logs.output[0])
                self.assertFalse(writer.called)

    def test_ost_import_rejects_malformed_takeoff_uid_before_remapping(self):
        cases = (
            (
                'UID="not-a-uid"',
                "BidTakeoffs.UID=not-a-uid has malformed UID=not-a-uid",
            ),
            (
                'UID="30" ParentUID="not-a-uid"',
                "BidTakeoffs.UID=30 has malformed ParentUID=not-a-uid",
            ),
        )
        for takeoff_identity, expected_diagnostic in cases:
            with self.subTest(takeoff_identity=takeoff_identity):
                xml = f"""
                <XML_ROOT>
                  <Bid UID="1" JobName="Imported">
                    <BidConditions>
                      <BidCondition UID="10" BidUID="1"/>
                    </BidConditions>
                    <BidPages>
                      <BidPage UID="20" BidUID="1" Name="Sheet">
                        <BidTakeoffs>
                          <BidTakeoff {takeoff_identity} BidUID="1"
                                      BidPageUID="20" BidConditionUID="10"/>
                        </BidTakeoffs>
                      </BidPage>
                    </BidPages>
                  </Bid>
                </XML_ROOT>
                """
                writer = _import_export_support__CapturingImportWriter()
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "malformed_takeoff_uid.ost"
                    ost_path.write_text(xml, encoding="utf-8")
                    with self.assertLogs(
                        "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                        level="ERROR",
                    ) as logs:
                        self.assertFalse(
                            OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                        )
                self.assertIn(expected_diagnostic, logs.output[0])
                self.assertFalse(writer.called)

    def test_ost_import_rejects_takeoff_parent_cycle(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="31"/>
                  <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                              BidConditionUID="10" ParentUID="30"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "takeoff_cycle.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn(
            "BidTakeoffs.UID=30 participates in a ParentUID cycle; "
            "BidTakeoffs.UID=31 participates in a ParentUID cycle",
            logs.output[0],
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_rejects_area_parent_cycle_before_writer(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidAreas>
              <BidArea UID="7" BidUID="1" ParentUID="8" Name="First"/>
              <BidArea UID="8" BidUID="1" ParentUID="7" Name="Second"/>
            </BidAreas>
          </Bid>
        </XML_ROOT>
        """
        writer = _import_export_support__CapturingImportWriter()
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "area_cycle.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn(
            "BidAreas.UID=7 participates in a ParentUID cycle; "
            "BidAreas.UID=8 participates in a ParentUID cycle",
            logs.output[0],
        )
        self.assertFalse(writer.called)

    def test_ost_import_rejects_takeoff_missing_required_condition(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_condition.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn(
            "BidTakeoffs.UID=30 BidConditionUID=<missing> missing BidConditions.UID",
            logs.output[0],
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_clears_missing_annotation_takeoff_attachments(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidDimensions>
                  <BidDimension UID="31" BidUID="1" BidPageUID="20"
                                BidTakeoffFromUID="901" BidTakeoffToUID="902"
                                Position="dimension-geometry"/>
                </BidDimensions>
                <BidArrows>
                  <BidArrow UID="32" BidUID="1" BidPageUID="20"
                            BidTakeoffFromUID="903" BidTakeoffToUID="904"
                            Position="arrow-geometry"/>
                </BidArrows>
                <BidALines>
                  <BidALine UID="33" BidUID="1" BidPageUID="20"
                            BidTakeoffFromUID="905" BidTakeoffToUID="906"
                            Position="line-geometry"/>
                </BidALines>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        for table in ("BidDimensions", "BidArrows", "BidALines"):
            connection.execute(
                f"CREATE TABLE {table} ("
                "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
                "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER, Position TEXT)"
            )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_annotation_attachments.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        expected_geometry = {
            "BidDimensions": "dimension-geometry",
            "BidArrows": "arrow-geometry",
            "BidALines": "line-geometry",
        }
        for table, geometry in expected_geometry.items():
            with self.subTest(table=table):
                row = connection.execute(
                    f"SELECT BidTakeoffFromUID, BidTakeoffToUID, Position "
                    f"FROM {table}"
                ).fetchone()
                self.assertEqual(row, (None, None, geometry))
        warning = logs.output[0]
        self.assertIn("6 missing annotation takeoff attachment reference(s)", warning)
        for uid in range(901, 907):
            self.assertIn(f"={uid} missing BidTakeoffs.UID", warning)

    def test_ost_import_still_rejects_takeoff_with_missing_condition(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidConditions/>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                              BidConditionUID="999" Name="Unsafe Orphan"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        connection.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidConditionUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "missing_condition.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("BidTakeoffs.UID=30 BidConditionUID=999", logs.output[0])
        bid_count = connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0]
        self.assertEqual(bid_count, 0)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_ost_import_remaps_estimator_to_imported_employee(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" EstimatorUID="7" JobName="Imported">
            <BidAreas/>
            <BidPages/>
          </Bid>
          <PayClasses>
            <PayClass UID="3" Name="Regular"/>
          </PayClasses>
          <Employees>
            <Employee UID="7" EmployeeNo="E100" FirstName="Alice"
                      LastName="Estimator" PayClassUID="3"/>
          </Employees>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, LastName) "
            "VALUES (7, 'EXISTING', 'Existing', 'Employee')"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                OstImporter(writer).import_ost(str(ost_path), "target.mdb", "5")
            )
        imported_employee = connection.execute(
            "SELECT UID, PayClassUID FROM Employees WHERE EmployeeNo='E100'"
        ).fetchone()
        imported_pay_class = connection.execute(
            "SELECT UID FROM PayClasses WHERE Name='Regular'"
        ).fetchone()
        imported_bid = connection.execute(
            "SELECT BidProjectUID, EstimatorUID FROM Bids WHERE JobName='Imported'"
        ).fetchone()
        self.assertIsNotNone(imported_employee)
        self.assertIsNotNone(imported_pay_class)
        self.assertEqual(imported_employee[1], imported_pay_class[0])
        self.assertEqual(imported_bid, (5, imported_employee[0]))

    def test_ost_import_preserves_bid_employee_through_authoritative_employee_uid(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidEmployees>
              <BidEmployee UID="20" BidUID="1" EmployeeUID="7"/>
            </BidEmployees>
            <BidPages/>
          </Bid>
          <Employees>
            <Employee UID="7" EmployeeNo="E100" FirstName="Alice"
                      LastName="Estimator"/>
          </Employees>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "CREATE TABLE BidEmployees ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, EmployeeUID INTEGER)"
        )
        connection.execute(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, LastName) "
            "VALUES (70, 'E100', 'Existing', 'Employee')"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "bid_employee.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        self.assertEqual(
            connection.execute("SELECT EmployeeUID FROM BidEmployees").fetchone()[0],
            70,
        )
        self.assertEqual(
            connection.execute("SELECT UID FROM Employees").fetchall(), [(70,)]
        )

    def test_ost_import_remaps_bid_settings_selected_page_to_imported_page(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="20"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        page_uid = connection.execute(
            "SELECT UID FROM BidPages WHERE Name='Sheet'"
        ).fetchone()[0]
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertEqual(selected_uid, page_uid)

    def test_ost_import_remaps_area_translation_and_comment_parent_refs(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidAreas>
              <BidArea UID="10" BidUID="1" Name="Area" Sequence="1"/>
            </BidAreas>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidAreaTranslations>
                  <BidAreaTranslation UID="30" BidPageUID="20"
                                      MasterAreaUID="10" TranslateAreaUID="10"/>
                </BidAreaTranslations>
                <BidComments>
                  <BidComment UID="40" BidUID="1" BidPageUID="20"/>
                  <BidComment UID="41" BidUID="1" BidPageUID="20"
                              ParentCommentUID="40"/>
                </BidComments>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            """
            CREATE TABLE BidAreaTranslations (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER,
                MasterAreaUID INTEGER,
                TranslateAreaUID INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE BidComments (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                ParentCommentUID INTEGER
            )
            """
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        area_uid = connection.execute(
            "SELECT UID FROM BidAreas WHERE Name='Area'"
        ).fetchone()[0]
        translation = connection.execute(
            "SELECT MasterAreaUID, TranslateAreaUID FROM BidAreaTranslations"
        ).fetchone()
        comments = connection.execute(
            "SELECT UID, ParentCommentUID FROM BidComments ORDER BY UID"
        ).fetchall()
        self.assertEqual(translation, (area_uid, area_uid))
        self.assertEqual(comments[1][1], comments[0][0])

    def test_ost_import_clears_missing_bid_settings_selected_page(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="999"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="WARNING",
            ) as logs:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("missing selected-page reference", logs.output[0])
        self.assertIn("BidSettings.UID=30 BidPageSelectedUID=999", logs.output[0])
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertIsNone(selected_uid)

    def test_ost_import_clears_zero_and_blank_selected_page(self):
        for selected_value in ("0", ""):
            with self.subTest(selected_value=selected_value):
                xml = f"""
                <XML_ROOT>
                  <Bid UID="1" JobName="Imported">
                    <BidSettings>
                      <BidSetting UID="30" BidUID="1"
                                  BidPageSelectedUID="{selected_value}"/>
                    </BidSettings>
                    <BidPages>
                      <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
                    </BidPages>
                  </Bid>
                </XML_ROOT>
                """
                connection = sqlite3.connect(":memory:")
                _import_export_support__create_import_schema(connection)
                writer = _import_export_support__SqliteMdbWriter(connection)
                with tempfile.TemporaryDirectory() as temp_dir:
                    ost_path = Path(temp_dir) / "import.ost"
                    ost_path.write_text(xml, encoding="utf-8")
                    self.assertTrue(
                        OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                    )
                selected_uid = connection.execute(
                    "SELECT BidPageSelectedUID FROM BidSettings"
                ).fetchone()[0]
                self.assertIsNone(selected_uid)

    def test_ost_import_rejects_non_numeric_selected_page_uid(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="not-a-uid"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn(
            "BidSettings.UID=30 BidPageSelectedUID=not-a-uid missing BidPages.UID",
            logs.output[0],
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidSettings").fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )

    def test_ost_import_drops_only_stale_named_views_and_their_hotlinks(self):
        for bid_uid in ("1", "2"):
            with self.subTest(
                bid_uid=bid_uid
            ), tempfile.TemporaryDirectory() as temp_dir:
                root = ET.fromstring(
                    _import_export_support__orphan_named_view_hotlink_xml()
                )
                bid = root.find("Bid")
                bid.set("UID", bid_uid)
                for row in bid.iter():
                    if "BidUID" in row.attrib:
                        row.set("BidUID", bid_uid)
                links = bid.find("BidHotLinks")
                for row in list(links):
                    if row.get("UID") in ("42", "43"):
                        links.remove(row)
                # Same-name candidates cannot establish ownership of missing 99.
                ET.SubElement(
                    bid.find("BidPages"),
                    "BidPage",
                    UID="21",
                    BidUID=bid_uid,
                    Name="Sheet",
                    GUID="different",
                )
                views = bid.find("BidNamedViews")
                ET.SubElement(
                    views,
                    "BidNamedView",
                    UID="32",
                    BidUID=bid_uid,
                    BidPageUID="99",
                    Name="Second stale",
                    Position="1;2;3;4;0",
                )
                valid = dict(views[0].attrib)
                path = Path(temp_dir) / "partial.ost"
                ET.ElementTree(root).write(path, encoding="unicode")
                with self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                    level="WARNING",
                ) as logs:
                    result = OstImporter(None)._validated_raw_data(str(path))
                self.assertEqual(len(logs.records), 1)
                self.assertRegex(
                    logs.records[0].getMessage(),
                    rf"\ADiscarded 2 stale Named View\(s\) and 1 dependent Hot Link\(s\) "
                    rf"during OST import for Bid {bid_uid}; absent Page references: ",
                )
                self.assertEqual(result.bid_tables["BidNamedViews"], [valid])
                self.assertEqual(
                    [row["UID"] for row in result.bid_tables["BidHotLinks"]], ["40"]
                )
                self.assertEqual(len(result.bid_tables["BidPages"]), 2)
                self.assertEqual(validate_raw_bid_integrity(result), [])
                remapped = OstImporter(None)._transform(result, 100, {}, {}, {}, {})
                self.assertEqual(validate_raw_bid_integrity(remapped), [])
                view = remapped.bid_tables["BidNamedViews"][0]
                self.assertEqual(view["Name"], valid["Name"])
                self.assertEqual(
                    view["BidPageUID"], remapped.bid_tables["BidPages"][0]["UID"]
                )
                self.assertEqual(
                    remapped.bid_tables["BidHotLinks"][0]["BidPageViewUID"], view["UID"]
                )

    def test_stale_named_view_normalization_does_not_hide_invalid_bid_or_duplicate_uid(
        self,
    ):
        for invalid_attributes in ({"BidUID": "2"}, {"UID": "30"}, {"UID": "bad"}):
            with self.subTest(
                attributes=invalid_attributes
            ), tempfile.TemporaryDirectory() as temp_dir:
                root = ET.fromstring(
                    _import_export_support__orphan_named_view_hotlink_xml()
                )
                bid = root.find("Bid")
                bid.remove(bid.find("BidHotLinks"))
                bid.find("BidNamedViews")[1].attrib.update(invalid_attributes)
                path = Path(temp_dir) / "invalid.ost"
                ET.ElementTree(root).write(path, encoding="unicode")
                with self.assertRaisesRegex(ValueError, "invalid references"):
                    OstImporter(None)._validated_raw_data(str(path))

    def test_ost_import_rejects_named_views_and_hotlinks_for_missing_pages(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys=ON")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            """
            CREATE TABLE BidNamedViews (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                Name TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE BidHotLinks (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER REFERENCES BidPages(UID),
                BidPageViewUID INTEGER REFERENCES BidNamedViews(UID),
                Name TEXT
            )
            """
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(
                _import_export_support__orphan_named_view_hotlink_xml(),
                encoding="utf-8",
            )
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                level="ERROR",
            ) as logs:
                self.assertFalse(
                    OstImporter(writer).import_ost(str(ost_path), "target.mdb")
                )
        self.assertIn("invalid database references", logs.output[0])
        self.assertIn("BidHotLinks.UID=43 BidLayerUID=99", logs.output[0])
        bid_count = connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0]
        named_view_count = connection.execute(
            "SELECT COUNT(*) FROM BidNamedViews"
        ).fetchone()[0]
        hotlink_count = connection.execute(
            "SELECT COUNT(*) FROM BidHotLinks"
        ).fetchone()[0]
        self.assertEqual((bid_count, named_view_count, hotlink_count), (0, 0, 0))

    def test_ost_transform_remaps_internal_global_and_null_references(self):
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "BidProjectUID": "3",
                "EstimatorUID": "7",
                "PrManagerUID": "8",
                "JobStatusUID": "5",
                "JobName": "0",
            },
            bid_tables={
                "BidPages": [
                    {"UID": "20", "BidUID": "1", "MasterPageUID": "0"},
                    {"UID": "21", "BidUID": "1", "MasterPageUID": "20"},
                ],
                "BidSettings": [
                    {"UID": "30", "BidUID": "1", "BidPageSelectedUID": "21"},
                    {"UID": "31", "BidUID": "1", "BidPageSelectedUID": "0"},
                    {"UID": "32", "BidUID": "1", "BidPageSelectedUID": "999"},
                ],
                "BidConditions": [
                    {"UID": "40", "BidUID": "1", "CdnTypeUID": "4"},
                    {"UID": "41", "BidUID": "1", "CdnTypeUID": "77"},
                ],
                "BidEmployees": [
                    {"UID": "50", "BidUID": "1", "EmployeeUID": "7"},
                    {"UID": "51", "BidUID": "1", "EmployeeUID": "8"},
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "60",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "40",
                        "ParentUID": "0",
                    },
                    {
                        "UID": "61",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "40",
                        "ParentUID": "60",
                    },
                ]
            },
        )
        remapped = OstImporter(None)._transform(
            raw_data,
            100,
            {"4": "400"},
            {"5": "500"},
            {"7": "700"},
            {},
        )
        self.assertEqual(
            remapped.bid_row,
            {
                "UID": "101",
                "BidProjectUID": "NULL",
                "EstimatorUID": "700",
                "PrManagerUID": "NULL",
                "JobStatusUID": "500",
                "JobName": "0",
            },
        )
        pages = remapped.bid_tables["BidPages"]
        self.assertEqual(
            [(row["UID"], row["BidUID"], row["MasterPageUID"]) for row in pages],
            [("102", "101", "NULL"), ("103", "101", "102")],
        )
        self.assertEqual(
            [row["BidPageSelectedUID"] for row in remapped.bid_tables["BidSettings"]],
            ["103", "NULL", "NULL"],
        )
        self.assertEqual(
            [row["CdnTypeUID"] for row in remapped.bid_tables["BidConditions"]],
            ["400", "77"],
        )
        self.assertEqual(
            [row["EmployeeUID"] for row in remapped.bid_tables["BidEmployees"]],
            ["700", "NULL"],
        )
        takeoffs = remapped.page_tables["BidTakeoffs"]
        self.assertEqual(
            [(row["UID"], row["BidPageUID"], row["ParentUID"]) for row in takeoffs],
            [("111", "102", "NULL"), ("112", "102", "111")],
        )
        self.assertEqual(
            [row["BidConditionUID"] for row in takeoffs],
            [remapped.bid_tables["BidConditions"][0]["UID"]] * 2,
        )
        self.assertEqual(raw_data.bid_row["UID"], "1")

    def test_ost_remap_row_maps_or_nulls_master_data_references_per_field(self):
        importer = OstImporter(None)
        remapped = importer._remap_row(
            {
                "UID": "5",
                "JobStatusUID": "6",
                "PayClassUID": "9",
                "EmployeeUID": "8",
                "CdnTypeUID": "11",
                "OCRUID": "12",
                "Note": "0",
            },
            {"5": "105"},
            {},
            {"11": "111"},
            {"6": "206"},
            {},
            {"9": "309"},
        )
        self.assertEqual(
            remapped,
            {
                "UID": "105",
                "JobStatusUID": "206",
                "PayClassUID": "309",
                "EmployeeUID": "NULL",
                "CdnTypeUID": "111",
                "OCRUID": "NULL",
                "Note": "0",
            },
        )
        unmapped = importer._remap_row(
            {"JobStatusUID": "7", "PayClassUID": "10", "CdnTypeUID": "13"},
            {},
            {},
            {},
            {"6": "206"},
            {},
            {"9": "309"},
        )
        self.assertEqual(
            unmapped,
            {"JobStatusUID": "NULL", "PayClassUID": "NULL", "CdnTypeUID": "13"},
        )

    def test_a_named_view_without_a_page_is_not_stale(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1"}],
                "BidNamedViews": [
                    {"UID": "30", "BidUID": "1", "BidPageUID": "0"},
                    {"UID": "31", "BidUID": "1", "BidPageUID": "20"},
                ],
                "BidHotLinks": [{"UID": "40", "BidUID": "1", "BidPageViewUID": "30"}],
            },
        )
        OstImporter._discard_stale_named_views(raw_data)
        self.assertEqual(
            [row["UID"] for row in raw_data.bid_tables["BidNamedViews"]], ["30", "31"]
        )
        self.assertEqual(len(raw_data.bid_tables["BidHotLinks"]), 1)

    def test_page_selection_references_map_only_known_non_zero_pages(self):
        remap = lambda value, page_map: OstImporter(None)._remap_uid_value(
            "BidPageSelectedUID", value, {}, page_map, {}, {}, {}, {}
        )
        pages = {"": "5", "0": "6", "7": "17"}
        self.assertEqual(remap("7", pages), "17")
        self.assertEqual(remap(" 7 ", pages), "17")
        self.assertEqual(remap("0", pages), "NULL")
        self.assertEqual(remap("", pages), "NULL")
        self.assertEqual(remap(None, pages), "NULL")
        self.assertEqual(remap("8", pages), "NULL")

    def test_empty_references_are_kept_as_they_are(self):
        importer = OstImporter(None)
        for value in ("", None):
            with self.subTest(value=value):
                self.assertEqual(
                    importer._remap_uid_value(
                        "BidAreaUID", value, {}, {}, {}, {}, {}, {}
                    ),
                    value,
                )

    def test_ost_page_uid_zero_is_never_a_page_and_collapses_as_no_page_selection(
        self,
    ):
        # Decision D11: source Page UID 0 is "no page". It is never assigned a new
        # UID or page mapping, and a 0 reference becomes NULL before the page-area
        # selections are canonicalised (one surviving selection for no page).
        importer = OstImporter(None)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"UID": "0"}, {"UID": "7"}]},
            page_tables={},
        )
        uid_map = importer._build_uid_map(raw_data, 100)
        self.assertEqual(uid_map, {"1": "101", "7": "102"})
        self.assertEqual(importer._build_page_uid_map(raw_data, uid_map), {"7": "102"})
        # Even a uid map that did contain 0 must not make it a page.
        self.assertEqual(
            importer._build_page_uid_map(raw_data, {**uid_map, "0": "999"}),
            {"7": "102"},
        )
        settings = [
            {"UID": "30", "BidPageUID": "0", "BidAreaUID": "4", "BidAreaSelected": "1"},
            {"UID": "31", "BidPageUID": "0", "BidAreaUID": "5", "BidAreaSelected": "1"},
            {"UID": "32", "BidPageUID": "7", "BidAreaUID": "4", "BidAreaSelected": "1"},
        ]
        remapped = [
            importer._remap_row(row, uid_map, {"7": "102"}, {}, {}, {}, {})
            for row in settings
        ]
        self.assertEqual(
            [row["BidPageUID"] for row in remapped], ["NULL", "NULL", "102"]
        )
        self.assertEqual(
            [
                (row["UID"], row["BidPageUID"])
                for row in importer._canonicalize_page_area_settings(remapped)
            ],
            [("31", "NULL"), ("32", "102")],
        )

    def test_ost_blank_and_zero_page_selections_leave_one_no_page_selection(self):
        # Decision D16: selected BidPageSettings rows whose source BidPageUID is
        # "" (kept as-is by the remap), "0" (rewritten to the "NULL" placeholder)
        # or absent are one no-page group, so exactly one selection survives for
        # it (BidAreaSelected DESC, UID DESC) while the real page, a second real
        # page and inactive rows are untouched.
        importer = OstImporter(None)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"UID": "7"}, {"UID": "8"}]},
            page_tables={
                "BidPageSettings": [
                    {
                        "UID": "30",
                        "BidPageUID": "",
                        "BidAreaUID": "4",
                        "BidAreaSelected": "1",
                    },
                    {
                        "UID": "31",
                        "BidPageUID": "0",
                        "BidAreaUID": "5",
                        "BidAreaSelected": "2",
                    },
                    {"UID": "32", "BidAreaUID": "6", "BidAreaSelected": "1"},
                    {
                        "UID": "33",
                        "BidPageUID": "7",
                        "BidAreaUID": "4",
                        "BidAreaSelected": "1",
                    },
                    {
                        "UID": "34",
                        "BidPageUID": "8",
                        "BidAreaUID": "4",
                        "BidAreaSelected": "1",
                    },
                    {
                        "UID": "35",
                        "BidPageUID": "0",
                        "BidAreaUID": "7",
                        "BidAreaSelected": "0",
                    },
                ]
            },
        )
        uid_map = importer._build_uid_map(raw_data, 100)
        page_uid_map = importer._build_page_uid_map(raw_data, uid_map)
        remapped = importer._remap_data(raw_data, uid_map, page_uid_map, {}, {}, {}, {})
        settings = remapped.page_tables["BidPageSettings"]
        # The "0" row carries the highest selection rank of the no-page group.
        self.assertEqual(
            [(row["UID"], row.get("BidPageUID")) for row in settings],
            [
                (uid_map["35"], "NULL"),
                (uid_map["31"], "NULL"),
                (uid_map["33"], page_uid_map["7"]),
                (uid_map["34"], page_uid_map["8"]),
            ],
        )
        # Equal rank: the highest remapped UID of the group wins, whichever
        # spelling it uses (here the blank one is last).
        raw_data.page_tables["BidPageSettings"][1]["BidAreaSelected"] = "1"
        raw_data.page_tables["BidPageSettings"][0]["UID"] = "29"
        uid_map = importer._build_uid_map(raw_data, 100)
        remapped = importer._remap_data(
            raw_data,
            uid_map,
            importer._build_page_uid_map(raw_data, uid_map),
            {},
            {},
            {},
            {},
        )
        no_page = [
            row
            for row in remapped.page_tables["BidPageSettings"]
            if row.get("BidAreaSelected") != "0"
            and row.get("BidPageUID") in (None, "", "NULL")
        ]
        self.assertEqual([row["UID"] for row in no_page], [uid_map["32"]])


_OST_LOGGER = "ost_visualizer.infrastructure.mdb.importers.ost_importer"


class _RecordingImportWriter:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def import_ost_data(self, target_db_path, raw_data, transform, project_uid):
        self.calls.append((target_db_path, raw_data, transform, project_uid))
        if self.error is not None:
            raise self.error
        return self.result


def _bare_recorder():
    return OstImporterRelationshipTests._mutation_recorder()


class OstImporterFailurePathTests(unittest.TestCase):
    def _write(self, text, name="source.ost"):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_import_ost_reports_exact_booleans_for_writer_results(self):
        source = self._write('<XML_ROOT><Bid UID="1" JobName="J"/></XML_ROOT>')
        for result, expected in (
            (True, True),
            ({"bid_uids": {"1": "2"}}, True),
            (False, False),
            (None, False),
            (0, False),
            ({}, False),
        ):
            with self.subTest(result=result):
                writer = _RecordingImportWriter(result=result)
                with self.assertNoLogs(_OST_LOGGER, level="WARNING"):
                    outcome = OstImporter(writer).import_ost(source, "t.mdb", "9")
                self.assertIs(outcome, expected)
                self.assertEqual(len(writer.calls), 1)
                target, raw_data, transform, project_uid = writer.calls[0]
                self.assertEqual((target, project_uid), ("t.mdb", "9"))
                self.assertEqual(raw_data.bid_row, {"UID": "1", "JobName": "J"})
                self.assertEqual(transform.__func__, OstImporter._transform)

    def test_import_ost_without_project_uid_passes_none_to_the_writer(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        writer = _RecordingImportWriter()
        self.assertIs(OstImporter(writer).import_ost(source, "t.mdb"), True)
        self.assertIsNone(writer.calls[0][3])

    def test_import_ost_logs_and_swallows_writer_exceptions(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        writer = _RecordingImportWriter(error=RuntimeError("disk full"))
        with self.assertLogs(_OST_LOGGER, level="ERROR") as logs:
            outcome = OstImporter(writer).import_ost(source, "t.mdb")
        self.assertIs(outcome, False)
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(), f"Failed to import OST file {source}"
        )
        self.assertIs(logs.records[0].exc_info[0], RuntimeError)

    def test_import_ost_rejects_unreadable_or_malformed_files_before_the_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / "missing.ost")
        cases = (
            ("missing file", missing, FileNotFoundError),
            ("empty file", self._write(""), ET.ParseError),
            ("truncated xml", self._write('<XML_ROOT><Bid UID="1">'), ET.ParseError),
            ("not xml", self._write("MDB\x00binary garbage"), ET.ParseError),
            ("no bid", self._write("<XML_ROOT/>"), ValueError),
        )
        for label, source, error_type in cases:
            with self.subTest(case=label):
                writer = _RecordingImportWriter()
                with self.assertLogs(_OST_LOGGER, level="ERROR") as logs:
                    outcome = OstImporter(writer).import_ost(source, "t.mdb")
                self.assertIs(outcome, False)
                self.assertEqual(writer.calls, [])
                self.assertEqual(
                    logs.records[0].getMessage(), f"Failed to import OST file {source}"
                )
                self.assertIs(logs.records[0].exc_info[0], error_type)

    def test_import_ost_mutation_propagates_validation_failures_untouched(self):
        takeoff_xml = """
        <XML_ROOT>
          <Bid UID="1">
            <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
            <BidPages>
              <BidPage UID="20" BidUID="1">
                <BidTakeoffs>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20" BidConditionUID="10"/>
                  <BidTakeoff UID="30" BidUID="1" BidPageUID="20" BidConditionUID="10"/>
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        dangling_xml = """
        <XML_ROOT>
          <Bid UID="1">
            <BidPages><BidPage UID="20" BidUID="1"/></BidPages>
            <BidSettings>
              <BidSetting UID="30" BidUID="1" BidPageSelectedUID="not-a-uid"/>
            </BidSettings>
          </Bid>
        </XML_ROOT>
        """
        cases = (
            (
                "no bid",
                "<XML_ROOT/>",
                ValueError,
                "^No Bid element found in OST file$",
                False,
            ),
            (
                "truncated",
                '<XML_ROOT><Bid UID="1">',
                ET.ParseError,
                "no element found",
                False,
            ),
            (
                "duplicate takeoff",
                takeoff_xml,
                ValueError,
                "^The imported takeoff graph is invalid: "
                "BidTakeoffs.UID=30 occurs 2 times$",
                False,
            ),
            (
                "dangling reference",
                dangling_xml,
                ValueError,
                "^The imported project contains invalid references[.]$",
                True,
            ),
        )
        for label, xml, error_type, pattern, logs_error in cases:
            with self.subTest(case=label):
                writer = _RecordingImportWriter()
                recorder, records = _bare_recorder()
                with self.assertRaisesRegex(error_type, pattern):
                    if logs_error:
                        with self.assertLogs(_OST_LOGGER, level="ERROR"):
                            OstImporter(writer).import_ost_mutation(
                                self._write(xml), "database", "9", recorder
                            )
                    else:
                        OstImporter(writer).import_ost_mutation(
                            self._write(xml), "database", "9", recorder
                        )
                self.assertEqual(writer.calls, [])
                self.assertEqual(records, [])

    def test_import_ost_mutation_propagates_writer_failures_without_records(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        writer = _RecordingImportWriter(error=RuntimeError("sql write failed"))
        recorder, records = _bare_recorder()
        with self.assertRaisesRegex(RuntimeError, "^sql write failed$"):
            OstImporter(writer).import_ost_mutation(source, "db", "9", recorder)
        self.assertEqual(records, [])

    def test_import_ost_mutation_rejects_non_numeric_bid_uid_before_recording(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        writer = _RecordingImportWriter(result={"bid_uids": {"1": "abc"}})
        recorder, records = _bare_recorder()
        with self.assertRaises(ValueError):
            OstImporter(writer).import_ost_mutation(source, "db", "9", recorder)
        self.assertEqual(records, [])

    def test_import_ost_mutation_formats_the_bid_uid_as_text_and_number(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        writer = _RecordingImportWriter(result={"bid_uids": {"1": 42}})
        recorder, records = _bare_recorder()
        OstImporter(writer).import_ost_mutation(source, "db", "9", recorder)
        bid_ref, operation = records[0]
        self.assertIs(operation, ChangeOperation.CREATE)
        self.assertEqual(
            (bid_ref.resource_type, bid_ref.resource_id, bid_ref.bid_uid),
            ("bid", "42", 42),
        )
        self.assertIs(type(bid_ref.resource_id), str)

    def test_import_ost_mutation_bad_writer_results_use_exact_messages(self):
        source = self._write('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        for result, message in (
            (True, "The SQL import writer did not return authoritative identities."),
            ({}, "The SQL import writer did not return exactly one imported bid."),
            (
                {"bid_uids": {}},
                "The SQL import writer did not return exactly one imported bid.",
            ),
        ):
            with self.subTest(result=result):
                writer = _RecordingImportWriter(result=result)
                with self.assertRaises(RuntimeError) as caught:
                    OstImporter(writer).import_ost_mutation(
                        source, "db", "9", _bare_recorder()[0]
                    )
                self.assertEqual(str(caught.exception), message)


class OstImporterParsingAndRemapContractTests(unittest.TestCase):
    def _parse(self, xml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "source.ost"
        path.write_text(xml, encoding="utf-8")
        return OstImporter(None)._parse_ost_xml(str(path))

    def _validated(self, xml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "source.ost"
        path.write_text(xml, encoding="utf-8")
        return OstImporter(None)._validated_raw_data(str(path))

    def test_section_children_match_the_singular_or_plural_minus_s_tag(self):
        matches = ost_importer_module._matches_section_child
        for section, tag, expected in (
            ("BidAreas", "BidArea", True),
            ("BidAreas", "BidAreas", False),
            ("BidAreas", "BidLayer", False),
            ("JobStatuses", "JobStatuse", True),
            ("JobStatuses", "JobStatus", False),
            ("JobStatuses", "JobStatuses", False),
            ("PayClasses", "PayClass", True),
            ("PayClasses", "PayClasse", True),
            ("BidConditionUser", "BidConditionUser", True),
            ("BidConditionUser", "BidConditionUse", False),
            ("BidConditionUser", "BidConditionUsers", False),
            ("OCRProps", "OCRProp", True),
            ("BidAreas", "", False),
        ):
            with self.subTest(section=section, tag=tag):
                self.assertIs(matches(section, tag), expected)

    def test_parse_reads_each_section_family_from_its_own_container_only(self):
        xml = """
        <XML_ROOT>
          <Bid UID="1" CopyTimestamp="2026 1 2 3 4 5">
            <BidAreas>
              <BidArea UID="10" Name="Area A"/>
              <BidLayer UID="11" Name="Wrong tag"/>
              <BidArea UID="12" Name="Area B"/>
            </BidAreas>
            <BidConditionUser><BidConditionUser UID="13"/><Other UID="99"/></BidConditionUser>
            <BidTakeoffs><BidTakeoff UID="500"/></BidTakeoffs>
            <BidPages>
              <Stray UID="900"/>
              <BidPage UID="20" Name="P1" CopyTimestamp="2026 1 2 3 4 5">
                <BidTakeoffs>
                  <BidTakeoff UID="30"/>
                  <BidArea UID="98"/>
                </BidTakeoffs>
                <BidComments><BidComment UID="40"/></BidComments>
                <BidAreas><BidArea UID="97"/></BidAreas>
              </BidPage>
              <Stray UID="901"/>
              <BidPage UID="21" Name="P2">
                <BidTakeoffs><BidTakeoff UID="31"/></BidTakeoffs>
              </BidPage>
            </BidPages>
            <BidNamedViews><BidNamedView UID="50"/></BidNamedViews>
            <BidHotLinks><BidHotLink UID="60"/><BidHotLinks UID="61"/></BidHotLinks>
            <Employees><Employee UID="999"/></Employees>
          </Bid>
          <Employees><Employee UID="7"/></Employees>
          <PayClasses>
            <PayClass UID="3"/>
            <PayClasse UID="4"/>
            <PayClasses UID="5"/>
          </PayClasses>
          <JobStatuses>
            <JobStatuse UID="8"/>
            <JobStatus UID="9"/>
            <Other UID="10"/>
          </JobStatuses>
          <CdnTypes><CdnType UID="11" Name="C"/></CdnTypes>
        </XML_ROOT>
        """
        raw = self._parse(xml)
        self.assertEqual(raw.bid_row, {"UID": "1", "CopyTimeStamp": "2026 1 2 3 4 5"})
        self.assertEqual(
            [row["UID"] for row in raw.bid_tables["BidAreas"]], ["10", "12"]
        )
        self.assertEqual(
            [row["UID"] for row in raw.bid_tables["BidConditionUser"]], ["13"]
        )
        self.assertEqual(
            raw.bid_tables["BidPages"],
            [
                {"UID": "20", "Name": "P1", "CopyTimeStamp": "2026 1 2 3 4 5"},
                {"UID": "21", "Name": "P2"},
            ],
        )
        self.assertEqual(
            [row["UID"] for row in raw.bid_tables["BidNamedViews"]], ["50"]
        )
        self.assertEqual([row["UID"] for row in raw.bid_tables["BidHotLinks"]], ["60"])
        self.assertNotIn("BidTakeoffs", raw.bid_tables)
        self.assertEqual(
            {
                name: [row["UID"] for row in rows]
                for name, rows in raw.page_tables.items()
            },
            {"BidTakeoffs": ["30", "31"], "BidComments": ["40"]},
        )
        self.assertEqual(
            {
                name: [row["UID"] for row in rows]
                for name, rows in raw.global_tables.items()
            },
            {
                "Employees": ["7"],
                "PayClasses": ["3", "4"],
                "AccessLevels": [],
                "CdnTypes": ["11"],
                "JobStatuses": ["8"],
            },
        )

    def test_parse_always_provides_every_bid_and_tail_section_key(self):
        raw = self._parse('<XML_ROOT><Bid UID="1"/></XML_ROOT>')
        self.assertEqual(
            sorted(raw.bid_tables),
            sorted(
                [
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
                    "BidPages",
                    "BidNamedViews",
                    "BidHotLinks",
                ]
            ),
        )
        self.assertTrue(all(rows == [] for rows in raw.bid_tables.values()))
        self.assertEqual(raw.page_tables, {})
        self.assertEqual(
            sorted(raw.global_tables),
            ["AccessLevels", "CdnTypes", "Employees", "JobStatuses", "PayClasses"],
        )

    def test_remap_prefixes_name_every_reference_field_family_per_field(self):
        importer = OstImporter(None)
        uid_map = {"5": "105"}
        zero_fields = (
            "BidProjectUID",
            "ParentBidUID",
            "OrigBidProjectUID",
            "OrigParentBidUID",
            "SourceBidUID",
            "OCRUID",
            "CoverSheetSelItemUID",
        )
        employee_fields = (
            "EstimatorUID",
            "PrManagerUID",
            "JobSiteManagerUID",
            "EmployeeUID",
        )
        internal_fields = (
            "UID",
            "BidUID",
            "BidPageUID",
            "BidConditionUID",
            "BidLayerUID",
            "BidZoneUID",
            "BidAreaUID",
            "BidTypAreaUID",
            "ParentUID",
            "ParentCommentUID",
            "MasterPageUID",
            "MasterAreaUID",
            "TranslateAreaUID",
            "BidConditionFolderUID",
            "BidPageFolderUID",
            "BidTakeoffFromUID",
            "BidTakeoffToUID",
            "BidPageViewUID",
            "TypGroupTakeoffUID",
            "TypPageTakeoffUID",
            "TypGroupMarkerUID",
            "TypGroupUID",
        )

        def remap(field, value, employees=None):
            return importer._remap_uid_value(
                field, value, uid_map, {}, {}, {}, employees or {}, {}
            )

        for field in zero_fields:
            with self.subTest(family="source-database", field=field):
                self.assertEqual(remap(field, "5"), "NULL")
                self.assertEqual(remap(field, "77"), "NULL")
        for field in employee_fields:
            with self.subTest(family="employee", field=field):
                self.assertEqual(remap(field, "5", {"5": "605"}), "605")
                self.assertEqual(remap(field, "5", {"6": "606"}), "NULL")
        for field in internal_fields:
            with self.subTest(family="bid-internal", field=field):
                self.assertEqual(remap(field, "5"), "105")
                self.assertEqual(remap(field, "77"), "77")
        for field in (*zero_fields, *employee_fields, *internal_fields):
            with self.subTest(family="zero", field=field):
                self.assertEqual(remap(field, "0"), "NULL")
        for field in ("Name", "Sequence", "SomethingElseUID"):
            with self.subTest(family="untouched", field=field):
                self.assertEqual(remap(field, "5"), "5")
        self.assertEqual(remap("Sequence", "0"), "0")
        self.assertEqual(remap("SomethingElseUID", "0"), "NULL")

    def test_uid_assignment_skips_rows_without_a_usable_uid_without_gaps(self):
        importer = OstImporter(None)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidAreas": [
                    {"Name": "no uid"},
                    {"UID": "", "Name": "blank"},
                    {"UID": "0", "Name": "zero"},
                    {"UID": "10"},
                    {"UID": "10", "Name": "repeat"},
                ],
                "BidPages": [{"UID": "20"}, {"BidUID": "1"}],
            },
            page_tables={"BidTakeoffs": [{"Name": "no uid"}, {"UID": "30"}]},
        )
        self.assertEqual(
            importer._build_uid_map(raw_data, 100),
            {"1": "101", "10": "102", "20": "103", "30": "104"},
        )
        self.assertEqual(
            importer._build_uid_map(RawBidData(bid_row={"Name": "no uid"}), 5), {}
        )
        self.assertEqual(
            importer._build_uid_map(
                RawBidData(
                    bid_row={"Name": "no uid"},
                    bid_tables={"BidAreas": [{"UID": "7"}]},
                ),
                5,
            ),
            {"7": "6"},
        )

    def test_page_uid_map_ignores_pages_without_a_mapped_uid(self):
        importer = OstImporter(None)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [
                    {"Name": "no uid"},
                    {"UID": " 7 "},
                    {"UID": "8"},
                    {"UID": "9"},
                ]
            },
        )
        self.assertEqual(
            importer._build_page_uid_map(raw_data, {"7": "17", "9": "19"}),
            {"7": "17", "9": "19"},
        )

    def test_validate_page_references_returns_exact_booleans_and_logs_issues(self):
        importer = OstImporter(None)
        good = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"UID": "20", "BidUID": "1"}]},
        )
        with self.assertNoLogs(_OST_LOGGER, level="ERROR"):
            self.assertIs(importer._validate_page_references(good), True)
        bad = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1", "MasterPageUID": "99"}]
            },
        )
        with self.assertLogs(_OST_LOGGER, level="ERROR") as logs:
            self.assertIs(importer._validate_page_references(bad), False)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Rejecting OST import because it contains invalid database references: "
            "BidPages.UID=20 MasterPageUID=99 missing BidPages.UID",
        )

    def test_skipped_takeoff_warning_lists_roots_and_only_then_descendants(self):
        def xml(rows):
            return (
                '<XML_ROOT><Bid UID="1"><BidConditions>'
                '<BidCondition UID="10" BidUID="1"/></BidConditions>'
                '<BidPages><BidPage UID="20" BidUID="1"><BidTakeoffs>'
                f"{rows}</BidTakeoffs></BidPage></BidPages></Bid></XML_ROOT>"
            )

        def takeoff(uid, parent):
            return (
                f'<BidTakeoff UID="{uid}" BidUID="1" BidPageUID="20" '
                f'BidConditionUID="10" ParentUID="{parent}"/>'
            )

        with self.assertLogs(_OST_LOGGER, level="WARNING") as logs:
            self._validated(xml(takeoff("32", "999")))
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Skipping 1 invalid takeoff(s) during OST import; missing-parent "
                "roots: BidTakeoffs.UID=32 ParentUID=999 missing BidTakeoffs.UID"
            ],
        )
        with self.assertLogs(_OST_LOGGER, level="WARNING") as logs:
            self._validated(xml(takeoff("32", "999") + takeoff("33", "32")))
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Skipping 2 invalid takeoff(s) during OST import; missing-parent "
                "roots: BidTakeoffs.UID=32 ParentUID=999 missing BidTakeoffs.UID; "
                "skipped dependent descendants: "
                "BidTakeoffs.UID=33 ParentUID=32 missing BidTakeoffs.UID"
            ],
        )

    def test_non_ascii_or_uidless_named_view_references_are_never_discarded(self):
        def xml(view_attributes):
            return (
                '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
                f"</BidPages><BidNamedViews><BidNamedView {view_attributes}/>"
                "</BidNamedViews></Bid></XML_ROOT>"
            )

        for label, attributes, diagnostic in (
            (
                "non-ascii digits",
                'UID="30" BidUID="1" BidPageUID="٢٣"',
                "BidNamedViews.UID=30 BidPageUID=٢٣ missing BidPages.UID",
            ),
            (
                "row without uid",
                'BidUID="1" BidPageUID="99"',
                "BidNamedViews.UID=<no UID> has malformed UID=<missing>",
            ),
        ):
            with self.subTest(case=label):
                with self.assertLogs(_OST_LOGGER, level="ERROR") as logs:
                    with self.assertRaisesRegex(
                        ValueError,
                        "^The imported project contains invalid references[.]$",
                    ):
                        self._validated(xml(attributes))
                self.assertEqual(len(logs.records), 1)
                self.assertIn(diagnostic, logs.records[0].getMessage())

    def test_a_named_view_for_missing_page_one_is_discarded_as_stale(self):
        xml = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1" BidPageUID="1"/>'
            '<BidNamedView UID="31" BidUID="1" BidPageUID="20"/>'
            "</BidNamedViews></Bid></XML_ROOT>"
        )
        with self.assertLogs(_OST_LOGGER, level="WARNING") as logs:
            raw = self._validated(xml)
        self.assertEqual(
            [row["UID"] for row in raw.bid_tables["BidNamedViews"]], ["31"]
        )
        self.assertIn(
            "Discarded 1 stale Named View(s) and 0 dependent Hot Link(s)",
            logs.records[0].getMessage(),
        )
        self.assertIn(
            "BidNamedViews.UID=30 BidPageUID=1 missing BidPages.UID",
            logs.records[0].getMessage(),
        )


class OstImporterSeverityAndBlankReferenceTests(unittest.TestCase):
    def _validated(self, xml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "source.ost"
        path.write_text(xml, encoding="utf-8")
        return OstImporter(None)._validated_raw_data(str(path))

    def test_cleared_reference_warnings_have_exact_messages_and_warning_severity(self):
        selected = (
            '<XML_ROOT><Bid UID="1"><BidSettings>'
            '<BidSetting UID="30" BidUID="1" BidPageSelectedUID="999"/>'
            '</BidSettings><BidPages><BidPage UID="20" BidUID="1"/></BidPages>'
            "</Bid></XML_ROOT>"
        )
        attachment = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1">'
            '<BidDimensions><BidDimension UID="31" BidUID="1" BidPageUID="20" '
            'BidTakeoffFromUID="901" BidTakeoffToUID="0"/></BidDimensions>'
            "</BidPage></BidPages></Bid></XML_ROOT>"
        )
        for label, xml, expected in (
            (
                "selected page",
                selected,
                "Cleared 1 missing selected-page reference(s) during OST import: "
                "BidSettings.UID=30 BidPageSelectedUID=999 missing BidPages.UID",
            ),
            (
                "annotation attachment",
                attachment,
                "Cleared 1 missing annotation takeoff attachment reference(s) "
                "during OST import: "
                "BidDimensions.UID=31 BidTakeoffFromUID=901 missing BidTakeoffs.UID",
            ),
        ):
            with self.subTest(case=label):
                with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
                    self._validated(xml)
                self.assertEqual(
                    [(record.levelno, record.getMessage()) for record in logs.records],
                    [(logging.WARNING, expected)],
                )

    def test_skipped_takeoff_and_stale_view_warnings_are_warning_severity(self):
        takeoff = (
            '<XML_ROOT><Bid UID="1"><BidConditions>'
            '<BidCondition UID="10" BidUID="1"/></BidConditions>'
            '<BidPages><BidPage UID="20" BidUID="1"><BidTakeoffs>'
            '<BidTakeoff UID="32" BidUID="1" BidPageUID="20" '
            'BidConditionUID="10" ParentUID="999"/>'
            "</BidTakeoffs></BidPage></BidPages></Bid></XML_ROOT>"
        )
        stale_view = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1" BidPageUID="1"/>'
            "</BidNamedViews></Bid></XML_ROOT>"
        )
        for label, xml in (("takeoff", takeoff), ("named view", stale_view)):
            with self.subTest(case=label):
                with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
                    self._validated(xml)
                self.assertEqual(
                    [record.levelno for record in logs.records], [logging.WARNING]
                )

    def test_rejections_and_failed_imports_are_error_severity(self):
        bad = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1", "MasterPageUID": "99"}]
            },
        )
        with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
            OstImporter(None)._validate_page_references(bad)
        self.assertEqual([record.levelno for record in logs.records], [logging.ERROR])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "no_bid.ost"
            path.write_text("<XML_ROOT/>", encoding="utf-8")
            with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
                OstImporter(_RecordingImportWriter()).import_ost(str(path), "t.mdb")
        self.assertEqual([record.levelno for record in logs.records], [logging.ERROR])

    def test_blank_references_stay_blank_for_every_remapped_field_family(self):
        # Characterisation of the current contract: an empty or missing value is
        # returned untouched whichever mapping family the field belongs to
        # (only the page-selection field turns blank into NULL).
        importer = OstImporter(None)
        maps = ({"": "1"}, {"": "2"}, {"": "3"}, {"": "4"}, {"": "5"}, {"": "6"})
        for field in (
            "UID",
            "BidUID",
            "ParentUID",
            "CdnTypeUID",
            "JobStatusUID",
            "PayClassUID",
            "EstimatorUID",
            "PrManagerUID",
            "JobSiteManagerUID",
            "EmployeeUID",
            "BidProjectUID",
            "OCRUID",
            "SomethingElseUID",
        ):
            for value in ("", None):
                with self.subTest(field=field, value=value):
                    self.assertEqual(
                        importer._remap_uid_value(field, value, *maps), value
                    )

    def test_page_uid_map_never_maps_a_page_without_a_uid_even_if_the_map_has_a_blank_key(
        self,
    ):
        importer = OstImporter(None)
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"Name": "no uid"}, {"UID": ""}, {"UID": "  "}]},
        )
        self.assertEqual(
            importer._build_page_uid_map(
                raw_data, {"": "5", "  ": "6", " ": "7", "0": "8"}
            ),
            {},
        )

    def test_import_ost_does_not_swallow_interrupts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.ost"
            path.write_text('<XML_ROOT><Bid UID="1"/></XML_ROOT>', encoding="utf-8")
            writer = _RecordingImportWriter(error=KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                OstImporter(writer).import_ost(str(path), "t.mdb")
        self.assertEqual(len(writer.calls), 1)

    def test_rejected_named_view_diagnostics_still_report_the_stale_page_reference(
        self,
    ):
        xml = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1" BidPageUID="20"/>'
            '<BidNamedView UID="31" BidUID="1" BidPageUID="99"/>'
            '<BidNamedView UID="32" BidUID="2" BidPageUID="20"/>'
            "</BidNamedViews></Bid></XML_ROOT>"
        )
        with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
            with self.assertRaisesRegex(
                ValueError, "^The imported project contains invalid references[.]$"
            ):
                self._validated(xml)
        self.assertEqual(
            [(record.levelno, record.getMessage()) for record in logs.records],
            [
                (
                    logging.ERROR,
                    "Rejecting OST import because it contains invalid database "
                    "references: BidNamedViews.UID=32 BidUID=2 missing Bids.UID; "
                    "BidNamedViews.UID=31 BidPageUID=99 missing BidPages.UID",
                )
            ],
        )
        self.assertIsNone(logs.records[0].exc_info)

    def test_ascii_non_decimal_named_view_page_references_are_rejected_not_parsed(
        self,
    ):
        for value in ("abc", "1.5", "+7", "1e3"):
            with self.subTest(value=value):
                xml = (
                    '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
                    "</BidPages><BidNamedViews>"
                    f'<BidNamedView UID="30" BidUID="1" BidPageUID="{value}"/>'
                    "</BidNamedViews></Bid></XML_ROOT>"
                )
                with self.assertLogs(_OST_LOGGER, level="ERROR") as logs:
                    with self.assertRaisesRegex(
                        ValueError,
                        "^The imported project contains invalid references[.]$",
                    ):
                        self._validated(xml)
                self.assertIn(
                    f"BidNamedViews.UID=30 BidPageUID={value} missing BidPages.UID",
                    logs.records[0].getMessage(),
                )

    def test_remap_data_applies_every_map_to_the_bid_row_and_both_table_families(self):
        def mapped_fields(uid):
            return {
                "UID": uid,
                "BidUID": "1",
                "CdnTypeUID": "4",
                "JobStatusUID": "5",
                "EstimatorUID": "7",
                "PayClassUID": "9",
                "BidPageSelectedUID": "20",
            }

        raw_data = RawBidData(
            bid_row={**mapped_fields("1")},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1"}],
                "BidSettings": [mapped_fields("30")],
            },
            page_tables={"BidTakeoffs": [mapped_fields("60")]},
        )
        remapped = OstImporter(None)._transform(
            raw_data,
            100,
            {"4": "400"},
            {"5": "500"},
            {"7": "700"},
            {"9": "900"},
        )
        self.assertEqual(
            [
                remapped.bid_row,
                remapped.bid_tables["BidSettings"][0],
                remapped.page_tables["BidTakeoffs"][0],
            ],
            [
                {
                    "UID": "101",
                    "BidUID": "101",
                    "CdnTypeUID": "400",
                    "JobStatusUID": "500",
                    "EstimatorUID": "700",
                    "PayClassUID": "900",
                    "BidPageSelectedUID": "102",
                },
                {
                    "UID": "103",
                    "BidUID": "101",
                    "CdnTypeUID": "400",
                    "JobStatusUID": "500",
                    "EstimatorUID": "700",
                    "PayClassUID": "900",
                    "BidPageSelectedUID": "102",
                },
                {
                    "UID": "104",
                    "BidUID": "101",
                    "CdnTypeUID": "400",
                    "JobStatusUID": "500",
                    "EstimatorUID": "700",
                    "PayClassUID": "900",
                    "BidPageSelectedUID": "102",
                },
            ],
        )


class OstImporterStaleNamedViewCountAndMissingPageTests(unittest.TestCase):
    def _validated(self, xml):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "source.ost"
        path.write_text(xml, encoding="utf-8")
        return OstImporter(None)._validated_raw_data(str(path))

    def test_the_discard_warning_counts_every_dependent_hot_link_removed(self):
        xml = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1" BidPageUID="99"/>'
            '<BidNamedView UID="31" BidUID="1" BidPageUID="20"/>'
            "</BidNamedViews><BidHotLinks>"
            '<BidHotLink UID="40" BidUID="1" BidPageViewUID="30"/>'
            '<BidHotLink UID="41" BidUID="1" BidPageViewUID="30"/>'
            '<BidHotLink UID="42" BidUID="1" BidPageViewUID="31"/>'
            "</BidHotLinks></Bid></XML_ROOT>"
        )
        with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
            raw = self._validated(xml)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Discarded 1 stale Named View(s) and 2 dependent Hot Link(s) during "
                "OST import for Bid 1; absent Page references: "
                "BidNamedViews.UID=30 BidPageUID=99 missing BidPages.UID"
            ],
        )
        self.assertEqual(
            [record.levelno for record in logs.records],
            [logging.WARNING],
        )
        self.assertEqual(
            [row["UID"] for row in raw.bid_tables["BidNamedViews"]], ["31"]
        )
        self.assertEqual([row["UID"] for row in raw.bid_tables["BidHotLinks"]], ["42"])

    def test_a_named_view_without_a_page_attribute_is_kept_and_not_logged(self):
        xml = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1"/>'
            "</BidNamedViews></Bid></XML_ROOT>"
        )
        with self.assertNoLogs(_OST_LOGGER, level="DEBUG"):
            raw = self._validated(xml)
        self.assertEqual(
            raw.bid_tables["BidNamedViews"], [{"UID": "30", "BidUID": "1"}]
        )

    def test_only_the_stale_sibling_of_a_page_less_named_view_is_discarded(self):
        xml = (
            '<XML_ROOT><Bid UID="1"><BidPages><BidPage UID="20" BidUID="1"/>'
            "</BidPages><BidNamedViews>"
            '<BidNamedView UID="30" BidUID="1"/>'
            '<BidNamedView UID="31" BidUID="1" BidPageUID="99"/>'
            "</BidNamedViews></Bid></XML_ROOT>"
        )
        with self.assertLogs(_OST_LOGGER, level="DEBUG") as logs:
            raw = self._validated(xml)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Discarded 1 stale Named View(s) and 0 dependent Hot Link(s) during "
                "OST import for Bid 1; absent Page references: "
                "BidNamedViews.UID=31 BidPageUID=99 missing BidPages.UID"
            ],
        )
        self.assertEqual(
            raw.bid_tables["BidNamedViews"], [{"UID": "30", "BidUID": "1"}]
        )
