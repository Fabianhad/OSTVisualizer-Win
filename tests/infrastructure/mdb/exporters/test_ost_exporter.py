import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.application.interfaces.i_uom_service import IUOMService
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.parsers.ost_serializer import serialize_value
from tests.helpers.mdb.import_export_support import (
    _orphan_named_view_hotlink_raw_data as _import_export_support__orphan_named_view_hotlink_raw_data,
    _reference_shape_export_raw_data as _import_export_support__reference_shape_export_raw_data,
)
from xml.etree.ElementTree import Element
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_SQUARE_INCHES,
)
from ost_visualizer.domain.services import uom_service
import os
from PySide6 import QtWidgets
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_AREA,
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_VOLUME,
    UOM_CUBIC_FEET,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_SQUARE_FEET,
    UOM_SQUARE_ROOFING,
    get_uom_label,
    normalize_condition_uoms_for_system,
)
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from tests.integration.quantities.uom_support import (
    _app as _uom_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class OstExporterRelationshipTests(unittest.TestCase):
    def test_export_prunes_orphan_takeoff_graph_and_keeps_valid_graph(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Exported"},
            bid_tables={
                "BidConditions": [{"UID": "10", "BidUID": "1"}],
                "BidPages": [{"UID": "20", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "Name": "Parent",
                    },
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "30",
                        "Name": "Child",
                    },
                    {
                        "UID": "32",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "999",
                        "Name": "Orphan",
                    },
                    {
                        "UID": "33",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidConditionUID": "10",
                        "ParentUID": "32",
                        "Name": "Descendant",
                    },
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "takeoff_graph.ost"
            uom_service = create_autospec(IUOMService, instance=True)
            uom_service.calculate_condition_quantities.return_value = (0.0, 0.0, 0.0)
            result = OstExporter(uom_service).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            takeoffs = (
                ET.parse(output_path)
                .getroot()
                .findall("./Bid/BidPages/BidPage/BidTakeoffs/BidTakeoff")
            )
        self.assertEqual(
            {takeoff.get("Name") for takeoff in takeoffs}, {"Parent", "Child"}
        )
        by_name = {takeoff.get("Name"): takeoff for takeoff in takeoffs}
        self.assertEqual(by_name["Parent"].get("UID"), "30")
        self.assertEqual(by_name["Child"].get("UID"), "31")
        self.assertEqual(
            by_name["Child"].get("ParentUID"), by_name["Parent"].get("UID")
        )
        self.assertEqual(
            [row["Name"] for row in raw_data.page_tables["BidTakeoffs"]],
            ["Parent", "Child", "Orphan", "Descendant"],
        )

    def test_ost_export_includes_referenced_estimator_employee_and_pay_class(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "EstimatorUID": "7", "JobName": "Bid"},
            bid_tables={"BidConditions": [], "BidPages": []},
            global_tables={
                "Employees": [
                    {
                        "UID": "7",
                        "EmployeeNo": "E100",
                        "FirstName": "Alice",
                        "LastName": "Estimator",
                        "PayClassUID": "3",
                    },
                    {
                        "UID": "8",
                        "EmployeeNo": "E200",
                        "FirstName": "Unused",
                        "LastName": "Employee",
                        "PayClassUID": "4",
                    },
                ],
                "PayClasses": [
                    {"UID": "3", "Name": "Regular"},
                    {"UID": "4", "Name": "Unused"},
                ],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        employee_uids = [
            elem.get("UID") for elem in root.findall("./Employees/Employee")
        ]
        pay_class_uids = [
            elem.get("UID") for elem in root.findall("./PayClasses/PayClass")
        ]
        self.assertEqual(employee_uids, ["7"])
        self.assertEqual(pay_class_uids, ["3"])
        self.assertEqual(root.find("./Bid").get("EstimatorUID"), "7")

    def test_ost_export_includes_every_referenced_role_employee_and_access_level(self):
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "EstimatorUID": "7",
                "PrManagerUID": "8",
                "JobSiteManagerUID": "9",
                "JobName": "Bid",
            },
            bid_tables={
                "BidConditions": [],
                "BidPages": [],
                "BidEmployees": [
                    {"UID": "5", "BidUID": "1", "EmployeeUID": "10", "PayClassUID": "6"}
                ],
            },
            global_tables={
                "Employees": [
                    {"UID": "7", "PayClassUID": "3", "AccessLevelUID": "21"},
                    {"UID": "8", "PayClassUID": "4", "AccessLevelUID": "0"},
                    {"UID": "9", "PayClassUID": "0", "AccessLevelUID": "22"},
                    {"UID": "10", "PayClassUID": "0", "AccessLevelUID": "0"},
                    {"UID": "11", "PayClassUID": "99", "AccessLevelUID": "23"},
                ],
                "PayClasses": [
                    {"UID": uid, "Name": f"Class {uid}"}
                    for uid in ("3", "4", "5", "6", "99")
                ],
                "AccessLevels": [
                    {"UID": uid, "Description": f"Level {uid}"}
                    for uid in ("21", "22", "23")
                ],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "roles.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        self.assertEqual(
            [e.get("UID") for e in root.findall("./Employees/Employee")],
            ["7", "8", "9", "10"],
        )
        self.assertEqual(
            sorted(e.get("UID") for e in root.findall("./PayClasses/PayClass")),
            ["3", "4", "6"],
        )
        self.assertEqual(
            sorted(e.get("UID") for e in root.findall("./AccessLevels/AccessLevel")),
            ["21", "22"],
        )

    def test_ost_export_writes_bid_layers_by_descending_uid(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidLayers": [
                    {"UID": "12", "BidUID": "1", "Name": "High", "Sequence": "5"},
                    {"UID": "10", "BidUID": "1", "Name": "Low", "Sequence": "0"},
                    {"UID": "11", "BidUID": "1", "Name": "Mid", "Sequence": "9"},
                ],
                "BidConditions": [],
                "BidPages": [],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        layers = root.findall("./Bid/BidLayers/BidLayer")
        self.assertEqual([layer.get("UID") for layer in layers], ["12", "11", "10"])

    def test_ost_export_write_failure_preserves_existing_destination(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={"BidConditions": [], "BidPages": []},
        )

        def fail_after_partial_write(file_obj, _root):
            file_obj.write("<partial>")
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "existing.ost"
            output_path.write_text("existing export", encoding="utf-8")
            with patch(
                "ost_visualizer.infrastructure.mdb.exporters.ost_exporter._write_element",
                side_effect=fail_after_partial_write,
            ):
                with self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
                    level="ERROR",
                ):
                    result = OstExporter(SimpleNamespace()).export(
                        raw_data,
                        str(output_path),
                    )
            self.assertFalse(result.success)
            self.assertEqual(result.error_message, "disk full")
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "existing export",
            )
            self.assertEqual(list(Path(temp_dir).iterdir()), [output_path])

    def test_ost_export_success_replaces_existing_destination_without_temp_files(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Fresh"},
            bid_tables={"BidConditions": [], "BidPages": []},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "existing.ost"
            output_path.write_text("existing export", encoding="utf-8")
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(list(Path(temp_dir).iterdir()), [output_path])
            root = ET.parse(output_path).getroot()
        self.assertEqual(root.find("./Bid").get("JobName"), "Fresh")

    def test_ost_export_uses_native_area_page_setting_and_text_order(self):
        text_row = {
            "FontItalic": "0",
            "Position": "1;2;3;4",
            "Name": "Note",
            "UID": "40",
            "BidLayerUID": "5",
            "FontName": "Arial",
            "BidUID": "1",
            "FontBold": "1",
            "BidPageUID": "20",
            "TextAlign": "0",
            "FontColor": "255",
            "FontSize": "12",
            "FontUnderline": "0",
        }
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidAreas": [
                    {"UID": "10", "BidUID": "1", "Name": "Low"},
                    {"UID": "12", "BidUID": "1", "Name": "High"},
                    {"UID": "11", "BidUID": "1", "Name": "Mid"},
                ],
                "BidLayers": [
                    {"UID": "5", "BidUID": "1", "Name": "Annotation"},
                ],
                "BidConditions": [],
                "BidPages": [
                    {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"},
                ],
            },
            page_tables={
                "BidPageSettings": [
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "10",
                        "BidAreaSelected": "0",
                    },
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "11",
                        "BidAreaSelected": "1",
                    },
                    {
                        "UID": "32",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "BidAreaUID": "12",
                        "BidAreaSelected": "1",
                    },
                ],
                "BidTexts": [text_row],
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "native_order.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        areas = root.findall("./Bid/BidAreas/BidArea")
        self.assertEqual([row.get("UID") for row in areas], ["12", "11", "10"])
        page_settings = root.findall(
            "./Bid/BidPages/BidPage/BidPageSettings/BidPageSetting"
        )
        self.assertEqual(
            [row.get("UID") for row in page_settings],
            ["32", "30", "31"],
        )
        text = root.find("./Bid/BidPages/BidPage/BidTexts/BidText")
        self.assertIsNotNone(text)
        self.assertEqual(
            list(text.attrib),
            [
                "UID",
                "BidUID",
                "BidPageUID",
                "BidLayerUID",
                "Name",
                "FontName",
                "FontColor",
                "FontSize",
                "FontBold",
                "FontItalic",
                "FontUnderline",
                "TextAlign",
                "Position",
            ],
        )

    def test_ost_export_skips_named_views_and_hotlinks_for_missing_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid.ost"
            result = OstExporter(SimpleNamespace()).export(
                _import_export_support__orphan_named_view_hotlink_raw_data(),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        named_view_names = [
            elem.get("Name")
            for elem in root.findall("./Bid/BidNamedViews/BidNamedView")
        ]
        hotlink_names = [
            elem.get("Name") for elem in root.findall("./Bid/BidHotLinks/BidHotLink")
        ]
        self.assertEqual(named_view_names, ["Valid"])
        self.assertEqual(hotlink_names, ["Valid Link"])
        self.assertEqual(
            [elem.get("UID") for elem in root.findall("./Bid/BidNamedViews/*")],
            ["30"],
        )
        self.assertEqual(
            [elem.get("UID") for elem in root.findall("./Bid/BidHotLinks/*")],
            ["40"],
        )

    def test_ost_export_matches_reference_xml_shape_for_core_sections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "reference.ost"
            result = OstExporter(SimpleNamespace()).export(
                _import_export_support__reference_shape_export_raw_data(),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            raw_bytes = output_path.read_bytes()
            text = raw_bytes.decode("utf-8")
            root = ET.fromstring(text)
        self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(text.startswith("<?xml"))
        self.assertTrue(raw_bytes.endswith(b"\r\n"))
        self.assertIn(b"\r\n", raw_bytes)
        self.assertNotIn(b" />", raw_bytes)
        self.assertNotIn(b"\n", raw_bytes.replace(b"\r\n", b""))
        self.assertEqual(
            [child.tag for child in root],
            ["OST", "Bid", "Employees", "CdnTypes", "JobStatuses"],
        )
        self.assertNotIn("<AccessLevels", text)
        self.assertNotIn("<BidEmployees", text)
        self.assertIn('<JobStatuse UID="79"', text)
        self.assertNotIn('<JobStatus UID="79"', text)
        self.assertIn('PayClassUID="0" AccessLevelUID="0"', text)
        self.assertLess(text.index('LoginName=""'), text.index('Password="0"'))
        self.assertLess(text.index('Password="0"'), text.index('Address1=""'))
        self.assertNotIn('Color=""', text)
        self.assertNotIn('Origin=""', text)
        self.assertLess(
            text.index('BidNamedView UID="31"'), text.index('BidNamedView UID="30"')
        )
        self.assertLess(
            text.index('BidHotLink UID="41"'), text.index('BidHotLink UID="40"')
        )
        self.assertIn('CurrentX="2302.443986254299944"', text)
        self.assertIn('CurrentY="1725.017182130580068"', text)
        self.assertIn('Quantity1="0" Quantity2="0" Quantity3="0"', text)
        area_conditions = root.findall(
            "./Bid/BidConditions/BidCondition/BidAreaConditions/BidAreaCondition"
        )
        self.assertEqual(
            [dict(row.attrib) for row in area_conditions],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "AreaUID": "0",
                    "TypAreaUID": "0",
                    "Quantity1": "0",
                    "Quantity2": "0",
                    "Quantity3": "0",
                }
            ],
        )

    def test_ost_export_preserves_page_overlay_and_source_rows(self):
        overlay_fields = (
            "ImagePath",
            "OverlayImagePath",
            "OverlayRect",
            "OverlayOffsetX",
            "OverlayOffsetY",
            "OverlayRotation",
            "DeskewRotationOverlay",
            "OverlayResized",
            "Show",
            "RasterDrawMethod",
        )
        page_row = {
            "UID": "20",
            "BidUID": "1",
            "Name": "Overlay sheet",
            "Sequence": "1",
            "ImagePath": r"C:\plans\sheet.pdf",
            "OverlayImagePath": r"C:\plans\overlay.pdf",
            "OverlayRect": "-12.5,7.25,2688,1920",
            "OverlayOffsetX": "-12.5",
            "OverlayOffsetY": "7.25",
            "OverlayRotation": "90",
            "DeskewRotationOverlay": "0.125",
            "OverlayResized": "1",
            "Show": "3",
            "RasterDrawMethod": "2",
        }
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "JobName": "Overlay bid",
                "ExternalID": "",
                "GUID": "{ABCDEF01-2345-6789-ABCD-EF0123456789}",
                "CopyTimeStamp": "2026 7 19 0 39 2",
            },
            bid_tables={
                "BidSettings": [
                    {"UID": "2", "BidUID": "1", "BidPageSelectedUID": "999"}
                ],
                "BidPages": [page_row],
            },
        )
        original_bid_row = dict(raw_data.bid_row)
        original_settings_row = dict(raw_data.bid_tables["BidSettings"][0])
        original_page_row = dict(page_row)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "overlay.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            root = ET.parse(output_path).getroot()
        exported_bid = root.find("./Bid")
        exported_page = root.find("./Bid/BidPages/BidPage")
        self.assertIsNotNone(exported_bid)
        self.assertIsNotNone(exported_page)
        self.assertEqual(
            exported_bid.get("GUID"),
            "{ABCDEF01-2345-6789-ABCD-EF0123456789}",
        )
        self.assertEqual(exported_bid.get("CopyTimestamp"), "2026 7 19 0 39 2")
        self.assertIsNone(exported_bid.get("CopyTimeStamp"))
        self.assertEqual(exported_bid.get("ExternalID"), "0")
        exported_setting = root.find("./Bid/BidSettings/BidSetting")
        self.assertIsNotNone(exported_setting)
        self.assertEqual(exported_setting.get("BidPageSelectedUID"), "0")
        self.assertEqual(
            {name: exported_page.get(name) for name in overlay_fields},
            {name: page_row[name] for name in overlay_fields},
        )
        self.assertEqual(raw_data.bid_row, original_bid_row)
        self.assertEqual(raw_data.bid_tables["BidSettings"][0], original_settings_row)
        self.assertEqual(raw_data.bid_tables["BidPages"][0], original_page_row)

    def test_ost_export_preserves_non_empty_bid_employees_section(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid Employee"},
            bid_tables={
                "BidEmployees": [
                    {
                        "UID": "5",
                        "BidUID": "1",
                        "EmployeeUID": "2",
                        "PayClassUID": "0",
                    }
                ]
            },
            global_tables={
                "Employees": [
                    {
                        "UID": "2",
                        "PayClassUID": "",
                        "AccessLevelUID": "",
                        "FirstName": "Ada",
                    }
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid_employee.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            text = output_path.read_text(encoding="utf-8")
        self.assertIn("<BidEmployees>", text)
        self.assertIn('<BidEmployee UID="5" BidUID="1" EmployeeUID="2"', text)
        root = ET.fromstring(text)
        self.assertEqual(
            [
                dict(row.attrib)
                for row in root.findall("./Bid/BidEmployees/BidEmployee")
            ],
            [
                {
                    "UID": "5",
                    "BidUID": "1",
                    "EmployeeUID": "2",
                    "PayClassUID": "0",
                }
            ],
        )
        self.assertEqual(
            [row.get("UID") for row in root.findall("./Employees/Employee")], ["2"]
        )

    def test_ost_export_formats_calculated_area_condition_quantities(self):
        uom_service = create_autospec(IUOMService, instance=True)
        uom_service.calculate_condition_quantities.return_value = (734.012, 0.0, 1.25)
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Quantities"},
            bid_tables={
                "BidConditions": [
                    {
                        "UID": "10",
                        "BidUID": "1",
                        "Name": "Linear",
                        "Type": "1",
                        "Width": "0",
                        "Height": "0",
                        "Depth": "0",
                        "Quantity1": "0",
                        "Quantity2": "0",
                        "Quantity3": "0",
                        "UOM1": "0",
                        "UOM2": "0",
                        "UOM3": "0",
                    }
                ],
                "BidPages": [
                    {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidConditionUID": "10",
                        "BidPageUID": "20",
                        "Position": "1;2;3;4",
                    }
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "quantities.ost"
            result = OstExporter(uom_service).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            text = output_path.read_text(encoding="utf-8")
        self.assertIn(
            'Quantity1="734.011999999999944" Quantity2="0" Quantity3="1.25"',
            text,
        )
        uom_service.calculate_condition_quantities.assert_called_once()
        call_kwargs = uom_service.calculate_condition_quantities.call_args.kwargs
        self.assertEqual(call_kwargs["condition_type"], 1)
        self.assertEqual(call_kwargs["position"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(
            (
                call_kwargs["calc_type1"],
                call_kwargs["calc_type2"],
                call_kwargs["calc_type3"],
            ),
            (0, 0, 0),
        )
        self.assertEqual(
            (call_kwargs["uom1"], call_kwargs["uom2"], call_kwargs["uom3"]), (0, 0, 0)
        )
        self.assertFalse(call_kwargs["round_quantity"])
        self.assertIsNone(call_kwargs["hole_positions"])
        self.assertEqual(call_kwargs["attachment_footprint"], 0.0)

    def test_ost_export_converts_aggregated_area_condition_quantities_once(self):
        calculation_order = []

        def calculate_condition_quantities(**kwargs):
            x = kwargs["position"][0]
            calculation_order.append(int(x))
            self.assertEqual(
                (kwargs["uom1"], kwargs["uom2"], kwargs["uom3"]),
                (0, 0, 0),
            )
            return x, 0.0, 0.0

        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Area order"},
            bid_tables={
                "BidAreas": [
                    {"UID": "10", "BidUID": "1", "Name": "Low"},
                    {"UID": "20", "BidUID": "1", "Name": "High"},
                ],
                "BidConditions": [
                    {
                        "UID": "100",
                        "BidUID": "1",
                        "Name": "Linear",
                        "Type": "1",
                        "UOM1": "2",
                    }
                ],
                "BidPages": [
                    {"UID": "200", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "1",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "10",
                        "Position": "1;0;2;0",
                    },
                    {
                        "UID": "3",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "10",
                        "Position": "3;0;4;0",
                    },
                    {
                        "UID": "2",
                        "BidUID": "1",
                        "BidConditionUID": "100",
                        "BidPageUID": "200",
                        "BidAreaUID": "20",
                        "Position": "2;0;3;0",
                    },
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "area_order.ost"
            uom_service = create_autospec(IUOMService, instance=True)
            uom_service.calculate_condition_quantities.side_effect = (
                calculate_condition_quantities
            )
            result = OstExporter(uom_service).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            rows = (
                ET.parse(output_path)
                .getroot()
                .findall("./Bid/BidConditions/BidCondition/BidAreaConditions/*")
            )
        self.assertEqual(calculation_order, [1, 3, 2])
        self.assertEqual(
            [
                (row.get("UID"), row.get("AreaUID"), row.get("Quantity1"))
                for row in rows
            ],
            [
                ("2", "20", "0.166666666666667"),
                ("1", "10", "0.333333333333333"),
            ],
        )

    def test_ost_export_rounds_area_condition_totals_after_aggregating_takeoffs(self):
        def calculate_condition_quantities(**kwargs):
            return kwargs["position"][0], 0.0, 0.0

        def takeoff(uid, area_uid, x):
            return {
                "UID": uid,
                "BidUID": "1",
                "BidConditionUID": "100",
                "BidPageUID": "200",
                "BidAreaUID": area_uid,
                "Position": f"{x};0;{x + 1};0",
            }

        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Rounding"},
            bid_tables={
                "BidAreas": [
                    {"UID": "10", "BidUID": "1", "Name": "Low"},
                    {"UID": "20", "BidUID": "1", "Name": "High"},
                ],
                "BidConditions": [
                    {
                        "UID": "100",
                        "BidUID": "1",
                        "Name": "Linear",
                        "Type": "1",
                        "UOM1": "2",
                        "RoundQuantity": "1",
                        "RoundUp": "6",
                    }
                ],
                "BidPages": [
                    {"UID": "200", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    takeoff("1", "10", 1),
                    takeoff("3", "10", 3),
                    takeoff("2", "20", 2),
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "rounding.ost"
            uom_service = create_autospec(IUOMService, instance=True)
            uom_service.calculate_condition_quantities.side_effect = (
                calculate_condition_quantities
            )
            result = OstExporter(uom_service).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            rows = (
                ET.parse(output_path)
                .getroot()
                .findall("./Bid/BidConditions/BidCondition/BidAreaConditions/*")
            )
        # Area 10 totals 4 inches = 0.333 ft, which rounds up once to the 0.5 ft
        # increment; rounding each takeoff before summing would yield 1.0 ft.
        self.assertEqual(
            [(row.get("AreaUID"), float(row.get("Quantity1"))) for row in rows],
            [("20", 0.5), ("10", 0.5)],
        )


class TakeoffLifecycleQuantityTests(unittest.TestCase):
    def test_ost_export_matches_signed_quantities_and_cross_condition_backouts(self):
        conditions = [
            {
                "UID": "area",
                "Type": "1",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {
                "UID": "backout",
                "Type": "1",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {"UID": "point", "Type": "3", "Quantity1": str(CALC_COUNT)},
        ]
        takeoffs = [
            {
                "UID": "1",
                "BidConditionUID": "area",
                "ParentUID": "0",
                "Position": "0;0;10;0;10;10;0;10",
                "IsNegativeQuantity": "True",
            },
            {
                "UID": "2",
                "BidConditionUID": "backout",
                "ParentUID": "1",
                "Position": "1;1;3;1;3;3;1;3",
            },
            {
                "UID": "3",
                "BidConditionUID": "point",
                "ParentUID": "1",
                "Position": "5;5",
                "IsNegativeQuantity": "-1",
            },
        ]
        root = Element("Bid")
        OstExporter(uom_service)._build_conditions_section(
            root, conditions, {}, {"BidTakeoffs": takeoffs}
        )
        quantities = {
            row.get("UID"): float(
                row.find("./BidAreaConditions/BidAreaCondition").get("Quantity1")
            )
            for row in root.findall("./BidConditions/BidCondition")
        }
        self.assertEqual(quantities["area"], -96)
        self.assertEqual(quantities["backout"], 0)
        self.assertEqual(quantities["point"], -1)

    def test_ost_export_subtracts_attachment_footprint_only_for_net_area_quantity(self):
        net_area_calc = 12
        conditions = [
            {
                "UID": "net",
                "Type": str(Condition.TYPE_AREA),
                "Quantity1": str(net_area_calc),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {
                "UID": "gross",
                "Type": str(Condition.TYPE_AREA),
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {
                "UID": "attachment",
                "Type": str(Condition.TYPE_ATTACHMENT),
                "Width": "2",
                "Depth": "2",
                "Quantity1": str(CALC_COUNT),
            },
        ]
        square = "0;0;10;0;10;10;0;10"
        takeoffs = [
            {
                "UID": "1",
                "BidConditionUID": "net",
                "ParentUID": "0",
                "Position": square,
            },
            {
                "UID": "2",
                "BidConditionUID": "gross",
                "ParentUID": "0",
                "Position": square,
            },
            {
                "UID": "3",
                "BidConditionUID": "attachment",
                "ParentUID": "1",
                "Position": "5;5",
            },
            {
                "UID": "4",
                "BidConditionUID": "attachment",
                "ParentUID": "2",
                "Position": "5;5",
            },
        ]
        root = Element("Bid")
        OstExporter(uom_service)._build_conditions_section(
            root, conditions, {}, {"BidTakeoffs": takeoffs}
        )
        quantities = {
            row.get("UID"): float(
                row.find("./BidAreaConditions/BidAreaCondition").get("Quantity1")
            )
            for row in root.findall("./BidConditions/BidCondition")
        }
        self.assertEqual(quantities["net"], 96)
        self.assertEqual(quantities["gross"], 100)
        self.assertEqual(quantities["attachment"], 2)


class ConditionUomConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _uom_support__app()
        cls.quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_close)

    def tearDown(self):
        self.app.processEvents()

    def test_metric_raw_ost_export_normalizes_stale_condition_uom_and_quantity(self):
        for label, measure_base, stale_uom, expected_uom, expected_quantity in (
            ("metric bid with imperial uom", "1", UOM_LINEAR_FEET, UOM_M, 3.048),
            ("imperial bid with metric uom", "0", UOM_M, UOM_LINEAR_FEET, 10.0),
        ):
            with self.subTest(label):
                raw_data = RawBidData(
                    bid_row={
                        "UID": "1",
                        "JobName": "Metric",
                        "MeasureBase": measure_base,
                    },
                    bid_tables={
                        "BidConditions": [
                            {
                                "UID": "10",
                                "BidUID": "1",
                                "Name": "Line",
                                "Type": str(Condition.TYPE_LINEAR),
                                "Height": "12",
                                "Thickness": "6",
                                "Quantity1": str(CALC_LINEAR_LENGTH),
                                "UOM1": str(stale_uom),
                            }
                        ],
                        "BidPages": [
                            {
                                "UID": "20",
                                "BidUID": "1",
                                "Name": "Sheet",
                                "Sequence": "1",
                            }
                        ],
                    },
                    page_tables={
                        "BidTakeoffs": [
                            {
                                "UID": "30",
                                "BidUID": "1",
                                "BidConditionUID": "10",
                                "BidPageUID": "20",
                                "Position": "0;0;120;0",
                            }
                        ]
                    },
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    output_path = Path(temp_dir) / "metric.ost"
                    result = OstExporter(UOMDomainService()).export(
                        raw_data, str(output_path)
                    )
                    condition_element = (
                        ET.parse(output_path)
                        .getroot()
                        .find("./Bid/BidConditions/BidCondition")
                    )
                self.assertTrue(result.success, result.error_message)
                self.assertIsNotNone(condition_element)
                self.assertEqual(condition_element.get("UOM1"), str(expected_uom))
                self.assertEqual(
                    raw_data.bid_tables["BidConditions"][0]["UOM1"],
                    str(stale_uom),
                )
                quantity_element = condition_element.find(
                    "./BidAreaConditions/BidAreaCondition"
                )
                self.assertAlmostEqual(
                    float(quantity_element.get("Quantity1")), expected_quantity
                )


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_ost_export_preserves_raw_overlay_columns(self):
        exporter = OstExporter.__new__(OstExporter)
        bid_element = Element("Bid")
        raw_rect = "-1.103146,0,2686.161423,1919.474692"
        exporter._build_pages_section(
            bid_element,
            {
                "BidPages": [
                    {
                        "UID": "58227",
                        "BidUID": "57895",
                        "Sequence": "1",
                        "OverlayRect": raw_rect,
                        "OverlayOffsetX": "-1.103146",
                        "OverlayOffsetY": "0",
                    }
                ]
            },
            {},
        )
        page_element = bid_element.find("./BidPages/BidPage")
        self.assertIsNotNone(page_element)
        self.assertEqual(page_element.get("OverlayRect"), raw_rect)
        self.assertEqual(page_element.get("OverlayOffsetX"), "-1.103146")
        self.assertEqual(page_element.get("OverlayOffsetY"), "0")
