"""A disposable mixed project through real Access, Summary and OST reconstruction."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services import uom_service
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.parsers.ost_serializer import (
    serialize_row,
    serialize_value,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests import test_mdb_schema_compatibility as access


class CrossSystemMdbWorkflowTests(unittest.TestCase):
    def test_mixed_project_scale_edit_reload_export_import(self):
        if not access._access_available():
            self.skipTest("Access ODBC/ADOX unavailable")
        # Access's process-wide task ceiling requires isolation from other MDB tests.
        if os.environ.get("OSTV_CROSS_SYSTEM_ACCESS_CHILD") != "1":
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "faulthandler",
                    "-m",
                    "unittest",
                    "tests." + self.id().removeprefix("tests."),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=dict(os.environ, OSTV_CROSS_SYSTEM_ACCESS_CHILD="1"),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            source = str(Path(directory) / "mixed.mdb")
            self.assertTrue(
                access.DatabaseCreator().create_database(Path(source), "Workflow")
            )
            connections = access.MdbConnectionManager()
            writer, reader = access.MdbWriter(connections), access.MdbReader(
                connections
            )
            self.addCleanup(connections.close)
            bid = writer.create_bid(
                source,
                None,
                {
                    "job_name": "Mixed workflow",
                    "pages": [
                        dict(
                            name=name,
                            width=42,
                            height=30,
                            scale_factor1=1,
                            scale_factor2=48,
                        )
                        for name in ("Plan A", "Plan B")
                    ],
                },
            )
            self.assertIsNotNone(bid)
            pages = reader.get_bid_data(source, bid)[3]
            page_a, page_b = sorted(pages, key=lambda uid: pages[uid].name)
            areas = writer.save_bid_areas(
                source,
                bid,
                BidAreaChangeset(
                    new=[BidArea("draft", bid, "0", "Level 1", 1)],
                    updated=[],
                    deleted_uids=[],
                ),
            )
            area = str(areas["draft"])
            self.assertTrue(writer.save_page_area(source, page_a, area))
            conditions = {}
            for name, kind, calc, uom in (
                ("Floor", Condition.TYPE_AREA, 11, 4),
                ("Wall", Condition.TYPE_LINEAR, 1, 1),
                ("Count", Condition.TYPE_COUNT, 0, 0),
                ("Opening", Condition.TYPE_ATTACHMENT, 0, 0),
            ):
                conditions[name] = writer.insert_condition(
                    source,
                    bid,
                    CreateConditionSpec(
                        name=name,
                        condition_type=kind,
                        width=2,
                        depth=2,
                        height=8,
                        calc_type1=calc,
                        uom1=uom,
                    ),
                )
                self.assertIsNotNone(conditions[name])
            root = writer.insert_takeoffs(
                source,
                bid,
                [
                    InsertTakeoffSpec(
                        conditions["Floor"],
                        page_a,
                        area,
                        [0.25, 0.25, 96.25, 0.25, 96.25, 96.25, 0.25, 96.25],
                        raw_extras={"NameFontSize": 13, "NameFontName": "Arial"},
                    )
                ],
            )[0]
            specs = [
                InsertTakeoffSpec(
                    conditions["Floor"],
                    page_a,
                    area,
                    [4, 4, 8, 4, 8, 8, 4, 8],
                    parent_uid=root,
                ),
                InsertTakeoffSpec(
                    conditions["Opening"],
                    page_a,
                    area,
                    [48.25, 48.25],
                    parent_uid=root,
                    rotation=17.5,
                ),
                InsertTakeoffSpec(
                    conditions["Wall"], page_a, area, [0.25, 110.5, 24.25, 110.5]
                ),
                InsertTakeoffSpec(
                    conditions["Count"], page_b, None, [12.25, 18.5], rotation=33.125
                ),
            ]
            self.assertEqual(len(writer.insert_takeoffs(source, bid, specs)), 4)
            annotations = [
                InsertAnnotationSpec(
                    page_a,
                    "text",
                    [12.25, 12.5, 48.25, 24.5],
                    "#123456",
                    1,
                    properties={
                        "Text": "Room café / Ã©\n  end ",
                        "FontName": "Arial",
                        "FontSize": 12,
                    },
                ),
                InsertAnnotationSpec(
                    page_a,
                    "callout",
                    [60.25, 12.5, 72.25, 24.5],
                    "#123456",
                    1,
                    properties={"Text": "Entrée", "FontName": "Arial", "FontSize": 12},
                ),
                InsertAnnotationSpec(
                    page_a, "dimension", [0.25, 100.5, 96.25, 100.5], "#123456", 1
                ),
                InsertAnnotationSpec(
                    page_a,
                    "polygon",
                    [20.25, 20.5, 25.25, 20.5, 25.25, 25.5],
                    "#123456",
                    1,
                ),
                InsertAnnotationSpec(
                    page_b, "line", [1.25, 2.5, 7.25, 8.5], "#123456", 1
                ),
            ]
            self.assertEqual(
                len(writer.insert_annotations(source, bid, annotations)), 5
            )

            def reload(path=source, target_bid=bid):
                connections.close_database(path)
                return reader.get_bid_data(path, target_bid)

            before = reload()
            self.assertEqual(len(before[1]), 5)
            self.assertEqual(before[4][page_a], area)
            self.assertEqual(sum(t.parent_uid == root for t in before[1]), 2)
            self.assert_summary(before)
            page_b_before = self.semantic_snapshot(before, only_page=page_b)
            self.assertTrue(writer.save_page_scale(source, page_a, 1, 24))
            scaled = reload()
            for old, new in zip(before[1], scaled[1]):
                expected = (
                    [value / 2 for value in old.position]
                    if old.page_uid == page_a
                    else old.position
                )
                self.assertEqual(new.position, expected)
                self.assertEqual(new.rotation, old.rotation)
                self.assertEqual(new.parent_uid, old.parent_uid)
            self.assertEqual(
                self.semantic_snapshot(scaled, only_page=page_b), page_b_before
            )
            self.assert_summary(scaled)
            self.assertTrue(
                writer.update_condition(
                    source,
                    bid,
                    conditions["Opening"],
                    UpdateConditionDto({"width": 3, "notes": "Résumé / 東京"}),
                )
            )
            self.assertTrue(writer.save_page_name(source, page_a, "Plan A revised"))
            edited = reload()
            self.assertEqual(edited[0][conditions["Opening"]].width, 3)
            self.assertEqual(edited[3][page_a].name, "Plan A revised")
            self.assert_summary(edited)
            # A rejected mixed geometry batch cannot alter the successful member.
            self.assertFalse(
                writer.save_takeoff_positions(
                    source, [(root, [1, 1, 2, 1, 2, 2]), ("9999999", [1, 1])]
                )
            )
            self.assertEqual(
                self.semantic_snapshot(reload()), self.semantic_snapshot(edited)
            )
            for scale in (48, 24, 48, 24):
                self.assertTrue(writer.save_page_scale(source, page_a, 1, scale))
            self.assertEqual(
                self.semantic_snapshot(reload()), self.semantic_snapshot(edited)
            )
            ost = str(Path(directory) / "mixed.ost")
            exported = OstExporter(uom_service).export(
                reader.get_raw_bid_data(source, bid), ost
            )
            self.assertTrue(exported.success, exported.error_message)
            expected_quantities = compute_page_quantities(edited[0], edited[1])
            for condition_element in (
                ET.parse(ost).getroot().findall("./Bid/BidConditions/BidCondition")
            ):
                quantity = sum(
                    float(row.get("Quantity1"))
                    for row in condition_element.findall(
                        "./BidAreaConditions/BidAreaCondition"
                    )
                )
                self.assertEqual(
                    quantity, expected_quantities[condition_element.get("UID")][0]
                )
            target = str(Path(directory) / "imported.mdb")
            self.assertTrue(
                access.DatabaseCreator().create_database(Path(target), "Imported")
            )
            self.assertTrue(OstImporter(writer).import_ost(ost, target))
            hierarchy, _ = reader.parse_file(target)
            imported_bid = next(
                b.uid for b in hierarchy.orphan_bids if b.name == "Mixed workflow"
            )
            imported = reload(target, imported_bid)
            self.assertEqual(
                self.semantic_snapshot(imported), self.semantic_snapshot(edited)
            )
            self.assert_summary(imported)
            self.assertEqual(len(imported[1]), 5)
            self.assertEqual(len(imported[6]), 5)
            connections.close()

    def assert_summary(self, data):
        conditions, takeoffs, areas, pages = data[:4]
        expected = compute_page_quantities(conditions, takeoffs)
        summary = ConditionSummaryService().build_summary(
            conditions=conditions,
            takeoffs=takeoffs,
            areas=list(areas.values()),
            folders=data[7],
            pages=[Page(uid, info.name) for uid, info in pages.items()],
        )
        nodes = list(summary.children)
        actual = {}
        while nodes:
            node = nodes.pop()
            nodes.extend(node.children)
            if node.kind == "condition":
                actual[node.condition_uid] = (
                    node.values.quantity1,
                    node.values.quantity2,
                    node.values.quantity3,
                )
        self.assertEqual(actual, expected)

    @staticmethod
    def semantic_snapshot(data, only_page=None):
        conditions, takeoffs, areas, pages = data[:4]
        by_uid = {takeoff.uid: takeoff for takeoff in takeoffs}
        area_names = {area.uid: area.name for area in areas.values()}

        def owner(uid):
            return conditions[by_uid[uid].condition_uid].name if uid in by_uid else None

        return (
            sorted(
                (
                    info.name,
                    info.scale_factor1,
                    info.scale_factor2,
                    area_names.get(data[4].get(uid)),
                )
                for uid, info in pages.items()
                if only_page is None or uid == only_page
            ),
            sorted(
                (
                    conditions[t.condition_uid].name,
                    pages[t.page_uid].name,
                    tuple(t.position),
                    t.rotation,
                    t.curve,
                    t.is_negative,
                    area_names.get(t.area_uid),
                    owner(t.parent_uid),
                    t.name_font_size,
                )
                for t in takeoffs
                if only_page is None or t.page_uid == only_page
            ),
            sorted(
                (
                    a.annotation_type,
                    pages[a.page_uid].name,
                    tuple(a.position),
                    a.color,
                    a.properties.get("Text"),
                )
                for a in data[6]
                if only_page is None or a.page_uid == only_page
            ),
            sorted(
                (
                    c.name,
                    c.condition_type,
                    c.width,
                    c.depth,
                    c.calc_type1,
                    c.uom1,
                    c.notes,
                )
                for c in conditions.values()
            ),
        )


class CrossSystemRawTextWorkflowTests(unittest.TestCase):
    def test_raw_export_import_mapping_uses_storage_encoding_on_both_backends(self):
        for table, column, content, encoding in (
            ("BidTexts", "Name", "café / Ã©\n  end ", "latin-1"),
            ("BidCallOuts", "Name", "Entrée", "latin-1"),
            ("BidConditions", "Notes", "Résumé / 東京", "utf-8"),
        ):
            with self.subTest(table=table):
                stored = content.encode(encoding)
                raw = serialize_row((stored,), [(column, bytes)], table=table)[column]
                self.assertEqual(raw, content)
                mdb = access.MdbWriter.__new__(access.MdbWriter)
                sql = SqlProjectWriter.__new__(SqlProjectWriter)
                self.assertEqual(
                    mdb._convert_access_value(
                        raw, "longbinary", table=table, column=column
                    ),
                    stored,
                )
                self.assertEqual(
                    sql._convert_sql_import_value(
                        raw, "varbinary", table=table, column=column
                    ),
                    stored,
                )

    def test_unknown_invalid_text_encoding_fails_instead_of_silently_losing_bytes(self):
        with self.assertRaises(UnicodeDecodeError):
            serialize_value(b"legacy\xff")
