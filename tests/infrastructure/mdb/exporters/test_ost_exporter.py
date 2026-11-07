import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.application.dtos.export_dto import ExportErrorCode
from ost_visualizer.application.interfaces.i_uom_service import IUOMService
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb.exporters import (
    ost_exporter as ost_exporter_module,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.parsers.ost_serializer import serialize_value
from tests.helpers.mdb import ost_attribute_order_golden as golden
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

    def test_ost_export_skips_an_unsupported_condition_type_and_keeps_the_rest(self):
        conditions = [
            {
                "UID": "foreign",
                "Type": "7",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
            {
                "UID": "area",
                "Type": "1",
                "Quantity1": str(CALC_AREA),
                "UOM1": str(UOM_SQUARE_INCHES),
            },
        ]
        takeoffs = [
            {
                "UID": "1",
                "BidConditionUID": "foreign",
                "ParentUID": "0",
                "Position": "0;0;10;0;10;10;0;10",
            },
            {
                "UID": "2",
                "BidConditionUID": "area",
                "ParentUID": "0",
                "Position": "0;0;10;0;10;10;0;10",
            },
        ]
        root = Element("Bid")
        with self.assertLogs(
            "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
            level="WARNING",
        ) as logged:
            OstExporter(uom_service)._build_conditions_section(
                root, conditions, {}, {"BidTakeoffs": takeoffs}
            )
        quantities = {
            row.get("UID"): float(
                row.find("./BidAreaConditions/BidAreaCondition").get("Quantity1")
            )
            for row in root.findall("./BidConditions/BidCondition")
        }
        self.assertEqual(quantities, {"foreign": 0.0, "area": 100.0})
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(len(messages), 1)
        self.assertIn("foreign", messages[0])
        self.assertIn("7", messages[0])

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


class OstExporterHelperContractTests(unittest.TestCase):
    """Direct pins of the pure helpers that decide the exact OST byte layout."""

    def test_escape_xml_attr_escapes_each_special_character_once(self):
        escape = ost_exporter_module._escape_xml_attr
        for raw, expected in (
            ("", ""),
            ("plain text", "plain text"),
            ("a&b", "a&amp;b"),
            ("&lt;", "&amp;lt;"),
            ("<tag>", "&lt;tag&gt;"),
            ('say "hi"', "say &quot;hi&quot;"),
            ("it's", "it&apos;s"),
            ("line1\r\nline2", "line1&#xd;&#xa;line2"),
            ("a\rb\nc", "a&#xd;b&#xa;c"),
            ("&<>\"'\r\n", "&amp;&lt;&gt;&quot;&apos;&#xd;&#xa;"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(escape(raw), expected)

    def test_write_element_layout_uses_crlf_and_self_closes_empty_elements(self):
        def render(element):
            buffer = io.StringIO()
            ost_exporter_module._write_element(buffer, element)
            return buffer.getvalue()

        self.assertEqual(
            render(Element("A", {"k": "v&1", "z": ""})), '<A k="v&amp;1" z=""/>\r\n'
        )
        self.assertEqual(render(Element("A")), "<A/>\r\n")
        whitespace_only = Element("A")
        whitespace_only.text = "  \n "
        self.assertEqual(render(whitespace_only), "<A/>\r\n")
        with_text = Element("A", {"n": "1"})
        with_text.text = "x < y\n"
        self.assertEqual(render(with_text), '<A n="1">x &lt; y&#xa;</A>\r\n')
        parent = Element("R", {"a": "1", "b": "2"})
        parent.text = "ignored when children exist"
        ET.SubElement(parent, "C", {"x": "1"})
        child = ET.SubElement(parent, "D")
        ET.SubElement(child, "E")
        self.assertEqual(
            render(parent),
            '<R a="1" b="2">\r\n<C x="1"/>\r\n<D>\r\n<E/>\r\n</D>\r\n</R>\r\n',
        )

    def test_sort_attrs_follows_the_element_specific_native_order(self):
        sort_attrs = ost_exporter_module._sort_attrs
        for element_type, shuffled, expected in (
            (
                "BidCondition",
                ["ShowTakeoff", "UID", "Name", "BidUID"],
                ["UID", "BidUID", "Name", "ShowTakeoff"],
            ),
            (
                "BidPage",
                ["Sequence", "Name", "UID", "BidPageFolderUID"],
                ["UID", "BidPageFolderUID", "Name", "Sequence"],
            ),
            (
                "BidTakeoff",
                ["Position", "UID", "Quantity", "BidPageUID"],
                ["UID", "BidPageUID", "Quantity", "Position"],
            ),
            (
                "Bid",
                ["JobName", "BidProjectUID", "UID", "GUID"],
                ["UID", "BidProjectUID", "JobName", "GUID"],
            ),
            (
                "BidLayer",
                ["Sequence", "Name", "UID", "IsTemplate"],
                ["UID", "IsTemplate", "Name", "Sequence"],
            ),
            ("CdnType", ["ExpandState", "Name", "UID"], ["UID", "Name", "ExpandState"]),
            (
                "Employee",
                ["LastName", "FirstName", "UID"],
                ["UID", "FirstName", "LastName"],
            ),
            ("PayClass", ["Name", "UID"], ["UID", "Name"]),
            (
                "AccessLevel",
                ["Privileges", "Description", "UID"],
                ["UID", "Description", "Privileges"],
            ),
            (
                "BidSetting",
                ["STSGUID", "BidPageSelectedUID", "UID"],
                ["UID", "BidPageSelectedUID", "STSGUID"],
            ),
            (
                "BidConditionFolder",
                ["ExpandState", "Name", "ParentUID", "UID"],
                ["UID", "ParentUID", "Name", "ExpandState"],
            ),
            (
                "BidArea",
                ["GUID", "Sequence", "Name", "UID"],
                ["UID", "Name", "Sequence", "GUID"],
            ),
            (
                "BidPageFolder",
                ["ExpandState", "Description", "Name", "UID"],
                ["UID", "Name", "Description", "ExpandState"],
            ),
            (
                "BidZone",
                ["GUID", "Sequence", "Name", "BidLayerUID", "UID"],
                ["UID", "BidLayerUID", "Name", "Sequence", "GUID"],
            ),
            (
                "BidLegend",
                ["MoveToCorner", "Rotation", "UID", "BidPageUID"],
                ["UID", "BidPageUID", "Rotation", "MoveToCorner"],
            ),
            (
                "BidNamedView",
                ["Position", "Name", "BidPageUID", "UID"],
                ["UID", "BidPageUID", "Name", "Position"],
            ),
            (
                "BidHotLink",
                ["Position", "Color", "BidPageViewUID", "UID"],
                ["UID", "BidPageViewUID", "Color", "Position"],
            ),
            (
                "BidDimension",
                ["FontName", "Position", "BidTakeoffToUID", "UID"],
                ["UID", "BidTakeoffToUID", "Position", "FontName"],
            ),
            (
                "BidALine",
                ["Width", "Color", "Position", "UID"],
                ["UID", "Position", "Color", "Width"],
            ),
            (
                "BidText",
                ["Position", "Name", "BidLayerUID", "UID"],
                ["UID", "BidLayerUID", "Name", "Position"],
            ),
        ):
            with self.subTest(element_type=element_type):
                ordered = sort_attrs({key: "1" for key in shuffled}, element_type)
                self.assertEqual(list(ordered), expected)

    def test_sort_attrs_for_other_elements_uses_priority_keys_then_alphabetical(self):
        ordered = ost_exporter_module._sort_attrs(
            {
                key: "1"
                for key in (
                    "Zeta",
                    "CdnTypeUID",
                    "ParentUID",
                    "TypAreaUID",
                    "AreaUID",
                    "BidTypAreaUID",
                    "BidAreaUID",
                    "BidZoneUID",
                    "BidLayerUID",
                    "BidConditionUID",
                    "BidPageUID",
                    "BidUID",
                    "UID",
                    "Alpha",
                    "Middle",
                )
            },
            "BidHighlight",
        )
        self.assertEqual(
            list(ordered),
            [
                "UID",
                "BidUID",
                "BidPageUID",
                "BidConditionUID",
                "BidLayerUID",
                "BidZoneUID",
                "BidAreaUID",
                "BidTypAreaUID",
                "AreaUID",
                "TypAreaUID",
                "ParentUID",
                "CdnTypeUID",
                "Alpha",
                "Middle",
                "Zeta",
            ],
        )
        self.assertEqual(
            list(ost_exporter_module._sort_attrs({"b": "1", "a": "2"})), ["a", "b"]
        )

    def test_normalize_nulls_maps_null_and_blank_by_column_kind(self):
        normalized = ost_exporter_module._normalize_nulls(
            {
                "UID": "NULL",
                "ParentUID": "",
                "BidUID": "5",
                "OCRState": "NULL",
                "Name": "NULL",
                "Notes": "",
                "Color": "7",
                "TextNullish": "null",
            }
        )
        self.assertEqual(
            normalized,
            {
                "UID": "",
                "ParentUID": "0",
                "BidUID": "5",
                "OCRState": "0",
                "Name": "",
                "Notes": "",
                "Color": "7",
                "TextNullish": "null",
            },
        )

    def test_filter_empty_attrs_drops_only_configured_empty_fields(self):
        filter_attrs = ost_exporter_module._filter_empty_attrs
        row = {
            "UID": "1",
            "BFperLF": "",
            "ALState": "NULL",
            "Color": "",
            "Origin": "NULL",
            "Name": "",
        }
        self.assertEqual(
            filter_attrs(row, "BidCondition"),
            {"UID": "1", "Color": "", "Origin": "NULL", "Name": ""},
        )
        self.assertEqual(filter_attrs(row, "BidNamedView"), {"UID": "1", "Name": ""})
        self.assertEqual(
            filter_attrs(
                {"BFperLF": "2.5", "ALState": "0", "Color": "5"}, "BidNamedView"
            ),
            {"BFperLF": "2.5", "ALState": "0", "Color": "5"},
        )

    def test_normalize_column_names_renames_only_known_database_columns(self):
        self.assertEqual(
            ost_exporter_module._normalize_column_names(
                {"CopyTimeStamp": "t", "CopyTimestamp": "u", "Other": "o"}
            ),
            {"CopyTimestamp": "u", "Other": "o"},
        )
        self.assertEqual(
            ost_exporter_module._normalize_column_names({"CopyTimeStamp": "t"}),
            {"CopyTimestamp": "t"},
        )

    def test_group_by_key_groups_rows_and_uses_blank_for_missing_key(self):
        rows = [
            {"UID": "1", "BidPageUID": "9"},
            {"UID": "2", "BidPageUID": "8"},
            {"UID": "3", "BidPageUID": "9"},
            {"UID": "4"},
        ]
        grouped = ost_exporter_module._group_by_key(rows, "BidPageUID")
        self.assertEqual(
            {key: [row["UID"] for row in value] for key, value in grouped.items()},
            {"9": ["1", "3"], "8": ["2"], "": ["4"]},
        )

    def test_accumulate_raw_quantities_sums_per_area_key(self):
        totals = {}
        accumulate = ost_exporter_module._accumulate_raw_quantities
        accumulate(totals, ("1", "0"), (1.0, 2.0, 3.0))
        accumulate(totals, ("1", "0"), (0.5, 0.25, -1.0))
        accumulate(totals, ("2", "0"), (7.0, 0.0, 0.0))
        self.assertEqual(
            totals, {("1", "0"): [1.5, 2.25, 2.0], ("2", "0"): [7.0, 0.0, 0.0]}
        )

    def test_build_section_names_items_by_singular_table_and_orders_attributes(self):
        parent = Element("Bid")
        ost_exporter_module._build_section(
            parent,
            "BidLayers",
            [{"Name": "Image", "UID": "3", "BidUID": "1", "Extra": "x"}],
        )
        ost_exporter_module._build_section(
            parent, "JobStatuses", [{"Name": "Open", "UID": "79"}]
        )
        ost_exporter_module._build_section(
            parent, "PayClasses", [{"UID": "2", "Name": "Regular"}]
        )
        ost_exporter_module._build_section(
            parent, "BidAreas", [{"UID": "4", "Name": "Area", "BFperLF": ""}]
        )
        self.assertEqual(
            [child.tag for child in parent],
            ["BidLayers", "JobStatuses", "PayClasses", "BidAreas"],
        )
        layer = parent.find("./BidLayers/BidLayer")
        self.assertEqual(list(layer.attrib), ["UID", "BidUID", "Name", "Extra"])
        self.assertIsNotNone(parent.find("./JobStatuses/JobStatuse"))
        self.assertIsNotNone(parent.find("./PayClasses/PayClass"))
        # BidAreas always carries one extra self-closing child with its own name.
        self.assertEqual(
            [child.tag for child in parent.find("./BidAreas")],
            ["BidArea", "BidAreas"],
        )
        self.assertEqual(
            dict(parent.find("./BidAreas/BidArea").attrib),
            {"UID": "4", "Name": "Area"},
        )

    def test_sort_rows_orders_each_table_the_native_way_without_mutating_input(self):
        exporter = OstExporter(SimpleNamespace())

        def uids(table, rows, key="UID"):
            original = [dict(row) for row in rows]
            result = [row[key] for row in exporter._sort_rows(table, rows)]
            self.assertEqual(rows, original)
            return result

        numeric = [{"UID": "9"}, {"UID": "10"}, {"UID": "2"}]
        for table in (
            "BidLayers",
            "BidAreas",
            "BidPageFolders",
            "BidTakeoffs",
            "BidHighlights",
            "BidALines",
            "BidArrows",
            "BidTexts",
            "BidCallOuts",
            "BidDimensions",
            "BidAnnotationRects",
            "BidAnnotationOvals",
            "BidAnnotationPolygons",
            "BidAnnotationClouds",
            "BidAnnoInk",
            "BidLegends",
            "BidComments",
            "BidNamedViews",
            "BidHotLinks",
        ):
            with self.subTest(table=table):
                self.assertEqual(uids(table, numeric), ["10", "9", "2"])
        self.assertEqual(uids("BidConditions", numeric), ["2", "9", "10"])
        self.assertEqual(uids("BidZones", numeric), ["9", "10", "2"])
        self.assertEqual(
            uids(
                "BidPages",
                [
                    {"UID": "1", "Sequence": "10"},
                    {"UID": "2", "Sequence": "2"},
                    {"UID": "3", "Sequence": "7"},
                ],
            ),
            ["2", "3", "1"],
        )
        self.assertEqual(
            uids(
                "BidPageSettings",
                [
                    {"UID": "31", "BidAreaSelected": "0"},
                    {"UID": "30", "BidAreaSelected": "1"},
                    {"UID": "32", "BidAreaSelected": "1"},
                    {"UID": "5", "BidAreaSelected": ""},
                    {"UID": "40"},
                ],
            ),
            ["32", "30", "40", "31", "5"],
        )
        self.assertEqual(exporter._sort_rows("BidLayers", []), [])


class OstExporterSectionLayoutTests(unittest.TestCase):
    def _export_root(self, raw_data, uom_service=None):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "layout.ost"
            result = OstExporter(uom_service or SimpleNamespace()).export(
                raw_data, str(output_path)
            )
            self.assertTrue(result.success, result.error_message)
            return ET.parse(output_path).getroot()

    def test_empty_bid_writes_every_native_section_in_native_order(self):
        root = self._export_root(
            RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={"BidConditions": [], "BidPages": []},
            )
        )
        self.assertEqual(root.tag, "XML_ROOT")
        self.assertEqual([child.tag for child in root], ["OST", "Bid"])
        self.assertEqual(dict(root.find("./OST").attrib), {"Version": "3.2.0"})
        self.assertEqual(
            [child.tag for child in root.find("./Bid")],
            [
                "BidPlanRooms",
                "BidAreas",
                "BidTypAreas",
                "BidConditionFolders",
                "BidPageFolders",
                "BidSettings",
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
            ],
        )
        for container in ("BidAreas", "BidTypAreas", "BidTypAreaCounts"):
            with self.subTest(container=container):
                self.assertEqual(
                    [child.tag for child in root.find(f"./Bid/{container}")],
                    [container],
                )
        for container in ("BidPlanRooms", "BidLayers", "BidNamedViews", "BidHotLinks"):
            with self.subTest(container=container):
                self.assertEqual(list(root.find(f"./Bid/{container}")), [])

    def test_pages_are_ordered_by_sequence_and_own_only_their_page_rows(self):
        root = self._export_root(
            RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidConditions": [],
                    "BidPages": [
                        {"UID": "20", "BidUID": "1", "Name": "Second", "Sequence": "2"},
                        {"UID": "10", "BidUID": "1", "Name": "First", "Sequence": "1"},
                    ],
                },
                page_tables={
                    "BidTexts": [
                        {
                            "UID": "1",
                            "BidUID": "1",
                            "BidPageUID": "20",
                            "BidLayerUID": "0",
                            "Name": "on second",
                            "Position": "1;2;3;4",
                        },
                    ],
                    "BidALines": [
                        {
                            "UID": "5",
                            "BidUID": "1",
                            "BidPageUID": "10",
                            "BidTakeoffFromUID": "0",
                            "BidTakeoffToUID": "0",
                            "Position": "1;2;3;4",
                            "Color": "255",
                            "Width": "2",
                        },
                        {
                            "UID": "6",
                            "BidUID": "1",
                            "BidPageUID": "10",
                            "BidTakeoffFromUID": "0",
                            "BidTakeoffToUID": "0",
                            "Position": "1;2;3;4",
                            "Color": "255",
                            "Width": "2",
                        },
                    ],
                },
            )
        )
        pages = root.findall("./Bid/BidPages/BidPage")
        self.assertEqual([page.get("Name") for page in pages], ["First", "Second"])
        page_section_order = [
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
        for page in pages:
            self.assertEqual([child.tag for child in page], page_section_order)
        first, second = pages
        self.assertEqual(
            [line.get("UID") for line in first.findall("./BidALines/BidALine")],
            ["6", "5"],
        )
        self.assertEqual(first.findall("./BidTexts/BidText"), [])
        self.assertEqual(second.findall("./BidALines/BidALine"), [])
        self.assertEqual(
            [text.get("Name") for text in second.findall("./BidTexts/BidText")],
            ["on second"],
        )

    def test_global_sections_keep_only_rows_referenced_by_the_bid(self):
        root = self._export_root(
            RawBidData(
                bid_row={"UID": "1", "JobName": "Bid", "JobStatusUID": "79"},
                bid_tables={
                    "BidConditions": [
                        {"UID": "10", "BidUID": "1", "CdnTypeUID": "5"},
                        {"UID": "11", "BidUID": "1", "CdnTypeUID": "0"},
                    ],
                    "BidPages": [],
                },
                global_tables={
                    "CdnTypes": [
                        {"UID": "5", "Name": "Used"},
                        {"UID": "6", "Name": "Unused"},
                    ],
                    "JobStatuses": [
                        {"UID": "79", "Name": "Open"},
                        {"UID": "80", "Name": "Closed"},
                    ],
                },
            )
        )
        self.assertEqual([child.tag for child in root][2:], ["CdnTypes", "JobStatuses"])
        self.assertEqual(
            [(e.get("UID"), e.get("Name")) for e in root.findall("./CdnTypes/CdnType")],
            [("5", "Used")],
        )
        self.assertEqual(
            [
                (e.get("UID"), e.get("Name"))
                for e in root.findall("./JobStatuses/JobStatuse")
            ],
            [("79", "Open")],
        )


class OstExporterResultContractTests(unittest.TestCase):
    def test_invalid_references_fail_with_message_and_write_nothing(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidLayers": [
                    {"UID": "5", "BidUID": "1", "Name": "A"},
                    {"UID": "5", "BidUID": "1", "Name": "B"},
                ],
                "BidConditions": [],
                "BidPages": [],
            },
        )
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "invalid.ost"
            result = OstExporter(SimpleNamespace()).export(
                raw_data, str(output_path), lambda *args: progress.append(args)
            )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
        self.assertIs(result.success, False)
        self.assertEqual(result.format_name, "OST")
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(
            result.error_message,
            "Cannot export OST because database references are invalid: "
            "BidLayers.UID=5 occurs 2 times",
        )
        self.assertEqual(progress, [])

    def test_successful_export_reports_progress_once_and_no_error(self):
        progress = []
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ok.ost"
            result = OstExporter(SimpleNamespace()).export(
                RawBidData(
                    bid_row={"UID": "1", "JobName": "Bid"},
                    bid_tables={"BidConditions": [], "BidPages": []},
                ),
                str(output_path),
                lambda *args: progress.append(args),
            )
            self.assertTrue(output_path.is_file())
        self.assertIs(result.success, True)
        self.assertEqual(result.format_name, "OST")
        self.assertIsNone(result.error_message)
        self.assertIsNone(result.error_code)
        self.assertEqual(progress, [(1, 1, "Writing OST")])

    def test_unwritable_destination_directory_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "missing" / "out.ost"
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
                level="ERROR",
            ) as logs:
                result = OstExporter(SimpleNamespace()).export(
                    RawBidData(
                        bid_row={"UID": "1", "JobName": "Bid"},
                        bid_tables={"BidConditions": [], "BidPages": []},
                    ),
                    str(output_path),
                )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
        self.assertIs(result.success, False)
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertTrue(result.error_message)
        self.assertIn(str(output_path), logs.output[0])


class ConditionQuantityContractTests(unittest.TestCase):
    """Pins how _build_conditions_section feeds the UOM service and lays out rows."""

    SQUARE = "0;0;10;0;10;10;0;10"

    @staticmethod
    def _stub(result=(0.0, 0.0, 0.0)):
        service = create_autospec(IUOMService, instance=True)
        service.calculate_condition_quantities.return_value = result
        return service

    @staticmethod
    def _build(service, conditions, takeoffs):
        root = Element("Bid")
        OstExporter(service)._build_conditions_section(
            root, conditions, {}, {"BidTakeoffs": takeoffs}
        )
        return root

    def test_non_area_takeoff_passes_every_condition_dimension_to_the_service(self):
        service = self._stub()
        self._build(
            service,
            [
                {
                    "UID": "10",
                    "Type": "0",
                    "Width": "1.5",
                    "Height": "2.5",
                    "Depth": "3.5",
                    "Rise": "4.5",
                    "Run": "5.5",
                    "GridSize1": "6.5",
                    "GridSize2": "7.5",
                    "Gap": "8.5",
                    "Thickness": "9.5",
                    "Quantity1": "3",
                    "Quantity2": "4",
                    "Quantity3": "5",
                    "UOM1": "6",
                    "UOM2": "7",
                    "UOM3": "8",
                    "RoundQuantity": "1",
                    "RoundUp": "6",
                }
            ],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "Position": "1;2;3;4",
                    "Curve": "7",
                },
                {"UID": "2", "BidConditionUID": "10", "Position": "5;6", "Curve": ""},
                {"UID": "3", "BidConditionUID": "10", "Position": "7;8"},
            ],
        )
        calls = service.calculate_condition_quantities.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            calls[0].kwargs,
            {
                "condition_type": 0,
                "calc_type1": 3,
                "calc_type2": 4,
                "calc_type3": 5,
                "uom1": 0,
                "uom2": 0,
                "uom3": 0,
                "width": 1.5,
                "height": 2.5,
                "depth": 3.5,
                "thickness": 9.5,
                "position": [1.0, 2.0, 3.0, 4.0],
                "rise": 4.5,
                "run": 5.5,
                "grid_size1": 6.5,
                "grid_size2": 7.5,
                "gap": 8.5,
                "curve": 7,
                "round_quantity": False,
                "round_up": 0.0,
            },
        )
        self.assertEqual([call.kwargs["curve"] for call in calls], [7, -1, -1])
        self.assertEqual(
            [call.kwargs["position"] for call in calls],
            [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0], [7.0, 8.0]],
        )

    def test_area_takeoff_passes_holes_and_attachment_totals_for_main_takeoffs_only(
        self,
    ):
        service = self._stub()
        self._build(
            service,
            [
                {"UID": "10", "Type": "1", "Quantity1": "12", "Width": "1.5"},
                {"UID": "11", "Type": "1"},
                {"UID": "12", "Type": "3", "Width": "2", "Depth": "3"},
                {"UID": "13", "Type": "3", "Width": "1", "Depth": "1"},
                {"UID": "14", "Type": "2"},
            ],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "ParentUID": "0",
                    "Position": self.SQUARE,
                },
                {
                    "UID": "2",
                    "BidConditionUID": "11",
                    "ParentUID": "1",
                    "Position": "2;2;4;2;4;4;2;4",
                },
                {
                    "UID": "3",
                    "BidConditionUID": "11",
                    "ParentUID": "1",
                    "Position": "",
                },
                {
                    "UID": "4",
                    "BidConditionUID": "12",
                    "ParentUID": "1",
                    "Position": "5;5",
                },
                {
                    "UID": "5",
                    "BidConditionUID": "13",
                    "ParentUID": "1",
                    "Position": "6;6",
                },
                {
                    "UID": "6",
                    "BidConditionUID": "14",
                    "ParentUID": "1",
                    "Position": "7;7",
                },
            ],
        )
        area_calls = [
            call.kwargs
            for call in service.calculate_condition_quantities.call_args_list
            if call.kwargs["condition_type"] == 1
        ]
        # Only the main takeoff (ParentUID 0) of condition 10 is calculated; the
        # two children of condition 11 are not main takeoffs.
        self.assertEqual(len(area_calls), 1)
        self.assertEqual(
            area_calls[0],
            {
                "condition_type": 1,
                "calc_type1": 12,
                "calc_type2": 0,
                "calc_type3": 0,
                "uom1": 0,
                "uom2": 0,
                "uom3": 0,
                "width": 1.5,
                "height": 0.0,
                "depth": 0.0,
                "thickness": 0.0,
                "position": [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
                "hole_positions": [[2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]],
                "attachment_footprint": 7.0,
                "attachment_perimeter": 14.0,
                "rise": 0.0,
                "run": 0.0,
                "grid_size1": 0.0,
                "grid_size2": 0.0,
                "gap": 0.0,
                "round_quantity": False,
                "round_up": 0.0,
            },
        )

    def test_area_takeoff_without_children_passes_no_hole_positions(self):
        service = self._stub()
        self._build(
            service,
            [{"UID": "10", "Type": "1"}],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "ParentUID": "",
                    "Position": self.SQUARE,
                },
                {"UID": "2", "BidConditionUID": "10", "Position": self.SQUARE},
            ],
        )
        calls = service.calculate_condition_quantities.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIsNone(call.kwargs["hole_positions"])
            self.assertEqual(call.kwargs["attachment_footprint"], 0.0)
            self.assertEqual(call.kwargs["attachment_perimeter"], 0.0)

    def test_negative_quantity_flag_values_flip_the_sign_of_all_three_quantities(self):
        for flag, sign in (
            ("1", -1),
            ("-1", -1),
            ("true", -1),
            ("True", -1),
            ("TRUE", -1),
            ("0", 1),
            ("", 1),
            ("false", 1),
            ("2", 1),
            (None, 1),
        ):
            with self.subTest(flag=flag):
                takeoff = {"UID": "1", "BidConditionUID": "10", "Position": "0;0;1;1"}
                if flag is not None:
                    takeoff["IsNegativeQuantity"] = flag
                for condition_type in ("0", "1"):
                    service = self._stub((10.0, 20.0, 30.0))
                    root = self._build(
                        service,
                        [{"UID": "10", "Type": condition_type}],
                        [dict(takeoff, ParentUID="0")],
                    )
                    row = root.find(
                        "./BidConditions/BidCondition/BidAreaConditions/BidAreaCondition"
                    )
                    self.assertEqual(
                        (
                            row.get("Quantity1"),
                            row.get("Quantity2"),
                            row.get("Quantity3"),
                        ),
                        (str(10 * sign), str(20 * sign), str(30 * sign)),
                    )

    def test_area_conditions_are_grouped_per_area_pair_numbered_then_emitted_reversed(
        self,
    ):
        def stub(**kwargs):
            return kwargs["position"][0], 0.0, 0.0

        service = create_autospec(IUOMService, instance=True)
        service.calculate_condition_quantities.side_effect = stub
        root = self._build(
            service,
            [
                {"UID": "10", "Type": "0", "ExternalID": ""},
                {"UID": "11", "Type": "0", "ExternalID": "77"},
                {"UID": "12", "Type": "0"},
            ],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "BidAreaUID": "10",
                    "BidTypAreaUID": "2",
                    "Position": "1;0;1;0",
                },
                {
                    "UID": "2",
                    "BidConditionUID": "10",
                    "BidAreaUID": "10",
                    "BidTypAreaUID": "11",
                    "Position": "2;0;2;0",
                },
                {
                    "UID": "3",
                    "BidConditionUID": "10",
                    "BidAreaUID": "9",
                    "BidTypAreaUID": "",
                    "Position": "3;0;3;0",
                },
                {
                    "UID": "4",
                    "BidConditionUID": "10",
                    "BidAreaUID": "",
                    "Position": "4;0;4;0",
                },
                {
                    "UID": "5",
                    "BidConditionUID": "10",
                    "BidAreaUID": "9",
                    "Position": "5;0;5;0",
                },
            ],
        )
        conditions = root.findall("./BidConditions/BidCondition")
        self.assertEqual([c.get("UID") for c in conditions], ["10", "11", "12"])
        self.assertEqual([c.get("ExternalID") for c in conditions], ["0", "77", "0"])

        def area_rows(condition):
            return [
                (
                    row.get("UID"),
                    row.get("BidConditionUID"),
                    row.get("AreaUID"),
                    row.get("TypAreaUID"),
                    row.get("Quantity1"),
                    row.get("Quantity2"),
                    row.get("Quantity3"),
                )
                for row in condition.findall("./BidAreaConditions/BidAreaCondition")
            ]

        self.assertEqual(
            area_rows(conditions[0]),
            [
                ("4", "10", "10", "11", "2", "0", "0"),
                ("3", "10", "10", "2", "1", "0", "0"),
                ("2", "10", "9", "0", "8", "0", "0"),
                ("1", "10", "0", "0", "4", "0", "0"),
            ],
        )
        self.assertEqual(
            area_rows(conditions[1]), [("5", "11", "0", "0", "0", "0", "0")]
        )
        self.assertEqual(
            area_rows(conditions[2]), [("6", "12", "0", "0", "0", "0", "0")]
        )
        for row in conditions[0].findall("./BidAreaConditions/BidAreaCondition"):
            self.assertEqual(
                list(row.attrib),
                [
                    "UID",
                    "BidConditionUID",
                    "AreaUID",
                    "TypAreaUID",
                    "Quantity1",
                    "Quantity2",
                    "Quantity3",
                ],
            )

    def test_round_quantity_flag_accepts_only_the_documented_truthy_spellings(self):
        for flag, rounded in (
            ("1", True),
            ("True", True),
            ("true", True),
            ("0", False),
            ("", False),
        ):
            with self.subTest(flag=flag):
                service = self._stub((4.0, 0.0, 0.0))
                root = self._build(
                    service,
                    [
                        {
                            "UID": "10",
                            "Type": "0",
                            "UOM1": "2",
                            "RoundQuantity": flag,
                            "RoundUp": "6",
                        }
                    ],
                    [{"UID": "1", "BidConditionUID": "10", "Position": "0;0;4;0"}],
                )
                row = root.find(
                    "./BidConditions/BidCondition/BidAreaConditions/BidAreaCondition"
                )
                # 4 inches = 0.333.. ft; rounding up to the 6 inch increment gives 0.5.
                self.assertAlmostEqual(
                    float(row.get("Quantity1")), 0.5 if rounded else 1 / 3, places=9
                )
                self.assertEqual(row.get("Quantity2"), "0")


class OstExporterNormalizationTests(unittest.TestCase):
    def _export_root(self, raw_data):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "normalized.ost"
            result = OstExporter(SimpleNamespace()).export(raw_data, str(output_path))
            self.assertTrue(result.success, result.error_message)
            return ET.parse(output_path).getroot()

    def test_condition_uoms_follow_the_bid_measurement_system_in_place(self):
        def rows():
            return [
                {"Quantity1": "1", "UOM1": "2"},
                {"Quantity1": "11", "UOM1": "5", "Quantity2": "20"},
                {"Quantity1": "0", "UOM1": "2"},
                {"UOM1": "13", "Quantity3": "1"},
                {"Quantity2": "0"},
                {},
                {"Quantity1": "", "UOM1": ""},
            ]

        for bid_row, expected in (
            (
                {"MeasureBase": "1"},
                [
                    {"Quantity1": "1", "UOM1": "13"},
                    {"Quantity1": "11", "UOM1": "14", "Quantity2": "20", "UOM2": "16"},
                    {"Quantity1": "0", "UOM1": "13"},
                    {"UOM1": "13", "Quantity3": "1", "UOM3": "13"},
                    {"Quantity2": "0"},
                    {},
                    {"Quantity1": "", "UOM1": "0"},
                ],
            ),
            (
                {"MeasureBase": "0"},
                [
                    {"Quantity1": "1", "UOM1": "2"},
                    {"Quantity1": "11", "UOM1": "5", "Quantity2": "20", "UOM2": "8"},
                    {"Quantity1": "0", "UOM1": "2"},
                    {"UOM1": "2", "Quantity3": "1", "UOM3": "2"},
                    {"Quantity2": "0"},
                    {},
                    {"Quantity1": "", "UOM1": "0"},
                ],
            ),
            ({}, None),
            ({"MeasureBase": ""}, None),
        ):
            with self.subTest(bid_row=bid_row):
                tables = {"BidConditions": rows()}
                ost_exporter_module._normalize_condition_uoms_for_bid_system(
                    bid_row, tables
                )
                if expected is None:
                    # blank or missing measurement system is imperial
                    expected = [
                        {"Quantity1": "1", "UOM1": "2"},
                        {
                            "Quantity1": "11",
                            "UOM1": "5",
                            "Quantity2": "20",
                            "UOM2": "8",
                        },
                        {"Quantity1": "0", "UOM1": "2"},
                        {"UOM1": "2", "Quantity3": "1", "UOM3": "2"},
                        {"Quantity2": "0"},
                        {},
                        {"Quantity1": "", "UOM1": "0"},
                    ]
                self.assertEqual(tables["BidConditions"], expected)
        untouched = {"Other": [{"UOM1": "2"}]}
        ost_exporter_module._normalize_condition_uoms_for_bid_system(
            {"MeasureBase": "1"}, untouched
        )
        self.assertEqual(untouched, {"Other": [{"UOM1": "2"}]})

    def test_condition_uom_normalization_reads_only_the_three_quantity_slots(self):
        # The reference schema has no fourth slot; stray Quantity4/UOM4 text must
        # neither be parsed (it is not numeric) nor rewritten.
        row = {"Quantity1": "1", "UOM1": "2", "Quantity4": "n/a", "UOM4": "n/a"}
        tables = {"BidConditions": [row]}
        ost_exporter_module._normalize_condition_uoms_for_bid_system(
            {"MeasureBase": "1"}, tables
        )
        self.assertEqual(
            tables["BidConditions"],
            [{"Quantity1": "1", "UOM1": "13", "Quantity4": "n/a", "UOM4": "n/a"}],
        )

    def test_null_markers_are_normalized_in_bid_page_global_and_table_rows(self):
        root = self._export_root(
            RawBidData(
                bid_row={
                    "UID": "1",
                    "JobName": "NULL",
                    "EstimatorUID": "NULL",
                    "PrManagerUID": "",
                    "Notes": "",
                },
                bid_tables={
                    "BidLayers": [
                        {
                            "UID": "3",
                            "BidUID": "1",
                            "Name": "NULL",
                            "IsLocked": "",
                            "ParentUID": "NULL",
                        }
                    ],
                    "BidConditions": [],
                    "BidPages": [],
                },
                page_tables={},
                global_tables={
                    "CdnTypes": [],
                    "Employees": [],
                },
            )
        )
        bid = root.find("./Bid")
        self.assertEqual(bid.get("JobName"), "")
        self.assertEqual(bid.get("EstimatorUID"), "0")
        self.assertEqual(bid.get("PrManagerUID"), "0")
        self.assertEqual(bid.get("Notes"), "")
        layer = root.find("./Bid/BidLayers/BidLayer")
        self.assertEqual(
            dict(layer.attrib),
            {"UID": "3", "BidUID": "1", "Name": "", "IsLocked": "", "ParentUID": "0"},
        )

    def test_null_markers_are_normalized_in_page_and_global_tables(self):
        root = self._export_root(
            RawBidData(
                bid_row={"UID": "1", "JobName": "Bid", "EstimatorUID": "7"},
                bid_tables={
                    "BidConditions": [],
                    "BidPages": [
                        {"UID": "20", "BidUID": "1", "Name": "Sheet", "Sequence": "1"}
                    ],
                },
                page_tables={
                    "BidTexts": [
                        {
                            "UID": "40",
                            "BidUID": "1",
                            "BidPageUID": "20",
                            "BidLayerUID": "NULL",
                            "Name": "NULL",
                            "FontName": "",
                            "Position": "1;2;3;4",
                        }
                    ]
                },
                global_tables={
                    "Employees": [
                        {
                            "UID": "7",
                            "PayClassUID": "NULL",
                            "AccessLevelUID": "",
                            "FirstName": "NULL",
                            "LastName": "",
                        }
                    ]
                },
            )
        )
        text = root.find("./Bid/BidPages/BidPage/BidTexts/BidText")
        self.assertEqual(text.get("BidLayerUID"), "0")
        self.assertEqual(text.get("Name"), "")
        self.assertEqual(text.get("FontName"), "")
        employee = root.find("./Employees/Employee")
        self.assertEqual(employee.get("PayClassUID"), "0")
        self.assertEqual(employee.get("AccessLevelUID"), "0")
        self.assertEqual(employee.get("FirstName"), "")
        self.assertEqual(employee.get("LastName"), "")

    def test_bid_external_id_defaults_to_zero_unless_a_value_is_present(self):
        for row_extra, expected in (
            ({}, "0"),
            ({"ExternalID": ""}, "0"),
            ({"ExternalID": "NULL"}, "0"),
            ({"ExternalID": "42"}, "42"),
        ):
            with self.subTest(row_extra=row_extra):
                root = self._export_root(
                    RawBidData(
                        bid_row={"UID": "1", "JobName": "Bid", **row_extra},
                        bid_tables={"BidConditions": [], "BidPages": []},
                    )
                )
                self.assertEqual(root.find("./Bid").get("ExternalID"), expected)

    def test_condition_and_page_elements_use_native_attribute_order_and_omit_empties(
        self,
    ):
        root = self._export_root(
            RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidConditions": [
                        {
                            "ShowTakeoff": "1",
                            "BFperLF": "NULL",
                            "ALState": "",
                            "Name": "Cond",
                            "BidUID": "1",
                            "UID": "10",
                            "Aardvark": "a",
                        }
                    ],
                    "BidPages": [
                        {
                            "Sequence": "1",
                            "BFperLF": "",
                            "Name": "Sheet",
                            "BidUID": "1",
                            "UID": "20",
                            "Aardvark": "a",
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            list(root.find("./Bid/BidConditions/BidCondition").attrib),
            ["UID", "BidUID", "ExternalID", "Name", "ShowTakeoff", "Aardvark"],
        )
        self.assertEqual(
            list(root.find("./Bid/BidPages/BidPage").attrib),
            ["UID", "BidUID", "Name", "Sequence", "Aardvark"],
        )

    def test_zero_references_do_not_select_global_rows(self):
        root = self._export_root(
            RawBidData(
                bid_row={
                    "UID": "1",
                    "JobName": "Bid",
                    "EstimatorUID": "0",
                    "PrManagerUID": "",
                },
                bid_tables={
                    "BidConditions": [],
                    "BidPages": [],
                    "BidEmployees": [
                        {
                            "UID": "5",
                            "BidUID": "1",
                            "EmployeeUID": "0",
                            "PayClassUID": "0",
                        }
                    ],
                },
                global_tables={
                    "Employees": [
                        {"UID": "0", "PayClassUID": "0", "AccessLevelUID": "0"},
                        {"UID": "8", "PayClassUID": "0", "AccessLevelUID": "0"},
                    ],
                    "PayClasses": [{"UID": "0", "Name": "Zero"}],
                    "AccessLevels": [{"UID": "0", "Description": "Zero"}],
                },
            )
        )
        self.assertEqual(root.findall("./Employees"), [])
        self.assertEqual(root.findall("./PayClasses"), [])
        self.assertEqual(root.findall("./AccessLevels"), [])


class OstExporterFileWriteTests(unittest.TestCase):
    RAW = RawBidData(
        bid_row={"UID": "1", "JobName": "Café ñ"},
        bid_tables={"BidConditions": [], "BidPages": []},
    )

    def test_output_is_utf8_with_crlf_and_no_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "utf8.ost"
            result = OstExporter(SimpleNamespace()).export(self.RAW, str(output_path))
            self.assertTrue(result.success, result.error_message)
            raw_bytes = output_path.read_bytes()
        self.assertIn('JobName="Café ñ"'.encode("utf-8"), raw_bytes)
        self.assertFalse(raw_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\r", raw_bytes)
        self.assertTrue(
            raw_bytes.startswith(b'<XML_ROOT>\r\n<OST Version="3.2.0"/>\r\n')
        )
        self.assertTrue(raw_bytes.endswith(b"</XML_ROOT>\r\n"))

    def test_temp_file_is_created_next_to_the_destination_and_hidden_by_prefix(self):
        seen = []
        original_mkstemp = ost_exporter_module.tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            seen.append(path)
            return fd, path

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "target.ost"
            with patch.object(
                ost_exporter_module.tempfile, "mkstemp", side_effect=recording_mkstemp
            ):
                result = OstExporter(SimpleNamespace()).export(
                    self.RAW, str(output_path)
                )
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(list(Path(temp_dir).iterdir()), [output_path])
        self.assertEqual(len(set(seen)), 1)
        temp_path = Path(seen[0])
        self.assertEqual(temp_path.parent.resolve(), Path(temp_dir).resolve())
        self.assertTrue(temp_path.name.startswith(".target.ost."), temp_path.name)
        self.assertTrue(temp_path.name.endswith(".tmp"), temp_path.name)

    def test_relative_destination_is_resolved_against_the_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous = os.getcwd()
            os.chdir(temp_dir)
            self.addCleanup(os.chdir, previous)
            result = OstExporter(SimpleNamespace()).export(self.RAW, "relative.ost")
            os.chdir(previous)
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(
                [p.name for p in Path(temp_dir).iterdir()], ["relative.ost"]
            )

    def test_failed_replace_removes_the_temp_file_and_reports_the_replace_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "target.ost"
            output_path.write_text("keep me", encoding="utf-8")
            with patch.object(
                ost_exporter_module.os, "replace", side_effect=OSError("replace failed")
            ):
                with self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
                    level="ERROR",
                ):
                    result = OstExporter(SimpleNamespace()).export(
                        self.RAW, str(output_path)
                    )
            self.assertIs(result.success, False)
            self.assertEqual(result.error_message, "replace failed")
            self.assertEqual(result.format_name, "OST")
            self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
            self.assertEqual(list(Path(temp_dir).iterdir()), [output_path])
            self.assertEqual(output_path.read_text(encoding="utf-8"), "keep me")

    def test_replace_error_is_not_masked_when_the_temp_file_already_vanished(self):
        def vanishing_replace(source, _destination):
            os.remove(source)
            raise OSError("replace failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "target.ost"
            with patch.object(
                ost_exporter_module.os, "replace", side_effect=vanishing_replace
            ):
                with self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
                    level="ERROR",
                ):
                    result = OstExporter(SimpleNamespace()).export(
                        self.RAW, str(output_path)
                    )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
        self.assertIs(result.success, False)
        self.assertEqual(result.format_name, "OST")
        self.assertEqual(result.error_message, "replace failed")

    def test_directory_at_destination_is_left_untouched_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "target.ost"
            destination.mkdir()
            (destination / "inner.txt").write_text("inner", encoding="utf-8")
            with self.assertLogs(
                "ost_visualizer.infrastructure.mdb.exporters.ost_exporter",
                level="ERROR",
            ):
                result = OstExporter(SimpleNamespace()).export(
                    self.RAW, str(destination)
                )
            self.assertIs(result.success, False)
            self.assertEqual(
                sorted(p.name for p in Path(temp_dir).iterdir()), ["target.ost"]
            )
            self.assertEqual(
                (destination / "inner.txt").read_text(encoding="utf-8"), "inner"
            )


class OstExporterGoldenTableTests(unittest.TestCase):
    """Pins the native attribute-order and null-default tables column by column."""

    def test_attribute_order_tables_match_the_golden_snapshot(self):
        self.assertEqual(
            list(ost_exporter_module._PRIORITY_ATTRS), list(golden.PRIORITY_ATTRS)
        )
        self.assertEqual(
            set(ost_exporter_module._ATTR_ORDER_MAP),
            set(golden.ATTRIBUTE_ORDER_BY_ELEMENT),
        )
        for element, expected in golden.ATTRIBUTE_ORDER_BY_ELEMENT.items():
            with self.subTest(element=element):
                self.assertEqual(
                    list(ost_exporter_module._ATTR_ORDER_MAP[element]), list(expected)
                )

    def test_sort_attrs_reproduces_the_golden_order_for_every_element(self):
        for element, expected in golden.ATTRIBUTE_ORDER_BY_ELEMENT.items():
            with self.subTest(element=element):
                attrs = {name: "1" for name in reversed(expected)}
                attrs["Zzz"] = "1"
                attrs["Aaa"] = "1"
                self.assertEqual(
                    list(ost_exporter_module._sort_attrs(attrs, element)),
                    list(expected) + ["Aaa", "Zzz"],
                )
        attrs = {name: "1" for name in reversed(golden.PRIORITY_ATTRS)}
        attrs["Zzz"] = "1"
        self.assertEqual(
            list(ost_exporter_module._sort_attrs(attrs, "BidHighlight")),
            list(golden.PRIORITY_ATTRS) + ["Zzz"],
        )

    def test_zero_default_columns_match_the_golden_snapshot(self):
        self.assertEqual(
            set(ost_exporter_module._ZERO_DEFAULT_FIELDS),
            set(golden.ZERO_DEFAULT_FIELDS),
        )
        for field in sorted(golden.ZERO_DEFAULT_FIELDS):
            with self.subTest(field=field):
                normalized = ost_exporter_module._normalize_nulls(
                    {field: "NULL", "Other" + field: "NULL"}
                )
                self.assertEqual(normalized, {field: "0", "Other" + field: ""})
                self.assertEqual(
                    ost_exporter_module._normalize_nulls({field: ""}), {field: "0"}
                )

    def test_bid_element_uses_the_native_bid_attribute_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bid_order.ost"
            result = OstExporter(SimpleNamespace()).export(
                RawBidData(
                    bid_row={
                        "GUID": "{G}",
                        "JobName": "Bid",
                        "BidProjectUID": "4",
                        "UID": "1",
                        "Alpha": "a",
                    },
                    bid_tables={"BidConditions": [], "BidPages": []},
                ),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            bid = ET.parse(output_path).getroot().find("./Bid")
        self.assertEqual(
            list(bid.attrib),
            ["UID", "BidProjectUID", "ExternalID", "JobName", "GUID", "Alpha"],
        )


class ConditionRowDefaultsTests(unittest.TestCase):
    @staticmethod
    def _stub(result):
        service = create_autospec(IUOMService, instance=True)
        service.calculate_condition_quantities.return_value = result
        return service

    @staticmethod
    def _rows(root):
        return [
            (row.get("UID"), row.get("AreaUID"), row.get("TypAreaUID"))
            + tuple(row.get(f"Quantity{i}") for i in (1, 2, 3))
            for row in root.findall(
                "./BidConditions/BidCondition/BidAreaConditions/BidAreaCondition"
            )
        ]

    def _build(self, service, conditions, takeoffs):
        root = Element("Bid")
        OstExporter(service)._build_conditions_section(
            root, conditions, {}, {"BidTakeoffs": takeoffs}
        )
        return root

    def test_blank_and_absent_condition_fields_are_treated_as_zero(self):
        numeric = (
            "Type",
            "Width",
            "Height",
            "Depth",
            "Rise",
            "Run",
            "GridSize1",
            "GridSize2",
            "Gap",
            "Thickness",
            "Quantity1",
            "Quantity2",
            "Quantity3",
            "UOM1",
            "UOM2",
            "UOM3",
            "RoundQuantity",
            "RoundUp",
        )
        for label, condition in (
            ("blank", {"UID": "10", **{name: "" for name in numeric}}),
            ("absent", {"UID": "10"}),
        ):
            with self.subTest(label):
                service = self._stub((3.0, 4.0, 5.0))
                root = self._build(
                    service,
                    [condition],
                    [{"UID": "1", "BidConditionUID": "10", "Position": "1;2"}],
                )
                (call,) = service.calculate_condition_quantities.call_args_list
                self.assertEqual(
                    call.kwargs,
                    {
                        "condition_type": 0,
                        "calc_type1": 0,
                        "calc_type2": 0,
                        "calc_type3": 0,
                        "uom1": 0,
                        "uom2": 0,
                        "uom3": 0,
                        "width": 0.0,
                        "height": 0.0,
                        "depth": 0.0,
                        "thickness": 0.0,
                        "position": [1.0, 2.0],
                        "rise": 0.0,
                        "run": 0.0,
                        "grid_size1": 0.0,
                        "grid_size2": 0.0,
                        "gap": 0.0,
                        "curve": -1,
                        "round_quantity": False,
                        "round_up": 0.0,
                    },
                )
                self.assertEqual(self._rows(root), [("1", "0", "0", "3", "4", "5")])

    def test_absent_fields_of_an_area_condition_use_zero_defaults(self):
        service = self._stub((3.0, 4.0, 5.0))
        root = self._build(
            service,
            [{"UID": "10", "Type": "1"}],
            [{"UID": "1", "BidConditionUID": "10"}],
        )
        (call,) = service.calculate_condition_quantities.call_args_list
        self.assertEqual(call.kwargs["condition_type"], 1)
        self.assertEqual(call.kwargs["position"], [])
        self.assertEqual(self._rows(root), [("1", "0", "0", "3", "4", "5")])

    def test_each_quantity_is_converted_with_its_own_unit(self):
        service = self._stub((12.0, 72.0, 288.0))
        root = self._build(
            service,
            [{"UID": "10", "Type": "0", "UOM1": "2", "UOM2": "3", "UOM3": "5"}],
            [{"UID": "1", "BidConditionUID": "10", "Position": "0;0;1;1"}],
        )
        # feet (/12), yards (/36), square feet (/144)
        self.assertEqual(self._rows(root), [("1", "0", "0", "1", "2", "2")])

    def test_area_branch_groups_by_area_and_typical_area_and_sorts_numerically(self):
        def stub(**kwargs):
            position = kwargs["position"]
            return (position[0] if position else 99.0), 0.0, 0.0

        service = create_autospec(IUOMService, instance=True)
        service.calculate_condition_quantities.side_effect = stub
        takeoffs = [
            ("1", "10", "11", "1;0;1;0"),
            ("2", "10", "2", "2;0;2;0"),
            ("3", "9", "7", "3;0;3;0"),
            ("4", "9", None, "4;0;4;0"),
            ("5", "", "", "5;0;5;0"),
            ("6", "9", "", None),
        ]
        rows = []
        for uid, area, typ, position in takeoffs:
            row = {"UID": uid, "BidConditionUID": "10", "ParentUID": "0"}
            row["BidAreaUID"] = area
            if typ is not None:
                row["BidTypAreaUID"] = typ
            if position is not None:
                row["Position"] = position
            rows.append(row)
        root = self._build(service, [{"UID": "10", "Type": "1"}], rows)
        # sorted ascending: (0,0)=1, (9,0)=2, (9,7)=3, (10,2)=4, (10,11)=5; written reversed
        self.assertEqual(
            self._rows(root),
            [
                ("5", "10", "11", "1", "0", "0"),
                ("4", "10", "2", "2", "0", "0"),
                ("3", "9", "7", "3", "0", "0"),
                ("2", "9", "0", "103", "0", "0"),
                ("1", "0", "0", "5", "0", "0"),
            ],
        )

    def test_typical_areas_of_one_area_are_ordered_numerically_not_by_input_order(
        self,
    ):
        def stub(**kwargs):
            return kwargs["position"][0], 0.0, 0.0

        service = create_autospec(IUOMService, instance=True)
        service.calculate_condition_quantities.side_effect = stub
        root = self._build(
            service,
            [{"UID": "10", "Type": "0"}],
            [
                {
                    "UID": "1",
                    "BidConditionUID": "10",
                    "BidAreaUID": "5",
                    "BidTypAreaUID": "11",
                    "Position": "1;0;1;0",
                },
                {
                    "UID": "2",
                    "BidConditionUID": "10",
                    "BidAreaUID": "5",
                    "BidTypAreaUID": "2",
                    "Position": "2;0;2;0",
                },
            ],
        )
        self.assertEqual(
            self._rows(root),
            [("2", "5", "11", "1", "0", "0"), ("1", "5", "2", "2", "0", "0")],
        )

    def test_fractional_quantities_keep_their_fraction_when_the_sign_is_applied(self):
        for condition_type in ("0", "1"):
            for flag, factor in (("0", 1), ("1", -1)):
                with self.subTest(condition_type=condition_type, flag=flag):
                    service = self._stub((1.5, 2.25, 3.75))
                    root = self._build(
                        service,
                        [{"UID": "10", "Type": condition_type}],
                        [
                            {
                                "UID": "1",
                                "BidConditionUID": "10",
                                "ParentUID": "0",
                                "IsNegativeQuantity": flag,
                                "Position": "0;0;1;1",
                            }
                        ],
                    )
                    self.assertEqual(
                        self._rows(root),
                        [
                            (
                                "1",
                                "0",
                                "0",
                                f"{1.5 * factor:g}",
                                f"{2.25 * factor:g}",
                                f"{3.75 * factor:g}",
                            )
                        ],
                    )

    def test_rows_without_the_required_condition_reference_or_uid_fail_the_export(
        self,
    ):
        takeoff = {
            "UID": "30",
            "BidUID": "1",
            "BidPageUID": "20",
            "BidConditionUID": "10",
        }
        for label, conditions, pages, takeoffs in (
            (
                "takeoff without BidConditionUID",
                [{"UID": "10", "BidUID": "1"}],
                [{"UID": "20", "BidUID": "1"}],
                [{"UID": "30", "BidUID": "1", "BidPageUID": "20"}],
            ),
            (
                "condition without UID",
                [{"BidUID": "1"}],
                [{"UID": "20", "BidUID": "1"}],
                [takeoff],
            ),
            (
                "page without UID",
                [{"UID": "10", "BidUID": "1"}],
                [{"BidUID": "1"}],
                [],
            ),
        ):
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    result = OstExporter(SimpleNamespace()).export(
                        RawBidData(
                            bid_row={"UID": "1", "JobName": "Bid"},
                            bid_tables={
                                "BidConditions": conditions,
                                "BidPages": pages,
                            },
                            page_tables={"BidTakeoffs": takeoffs},
                        ),
                        str(Path(temp_dir) / "invalid.ost"),
                    )
                    self.assertEqual(list(Path(temp_dir).iterdir()), [])
                self.assertIs(result.success, False)
                self.assertTrue(
                    result.error_message.startswith(
                        "Cannot export OST because database references are invalid: "
                    ),
                    result.error_message,
                )

    def test_takeoff_without_uid_fails_the_export_instead_of_being_grouped(self):
        # A UID-less takeoff would share the blank group key with every parentless
        # takeoff; the takeoff-graph validation rejects it before any grouping.
        with tempfile.TemporaryDirectory() as temp_dir:
            result = OstExporter(SimpleNamespace()).export(
                RawBidData(
                    bid_row={"UID": "1", "JobName": "Bid"},
                    bid_tables={
                        "BidConditions": [{"UID": "10", "BidUID": "1"}],
                        "BidPages": [{"UID": "20", "BidUID": "1"}],
                    },
                    page_tables={
                        "BidTakeoffs": [
                            {"BidUID": "1", "BidPageUID": "20", "BidConditionUID": "10"}
                        ]
                    },
                ),
                str(Path(temp_dir) / "invalid.ost"),
            )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
        self.assertIs(result.success, False)
        self.assertEqual(
            result.error_message,
            "Cannot export invalid takeoff graph: BidTakeoffs.UID=<no UID> has "
            "malformed UID=<missing>",
        )


class OstExporterSortRowsDefaultsTests(unittest.TestCase):
    def test_rows_without_the_sort_key_sort_as_zero(self):
        exporter = OstExporter(SimpleNamespace())

        def order(table, rows):
            return [row.get("tag") for row in exporter._sort_rows(table, rows)]

        for table in (
            "BidLayers",
            "BidTakeoffs",
            "BidNamedViews",
            "BidHotLinks",
            "BidAnnotationRects",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    order(table, [{"tag": "none"}, {"tag": "one", "UID": "1"}]),
                    ["one", "none"],
                )
        self.assertEqual(
            order("BidConditions", [{"tag": "one", "UID": "1"}, {"tag": "none"}]),
            ["none", "one"],
        )
        self.assertEqual(
            order(
                "BidPages",
                [{"tag": "one", "Sequence": "1"}, {"tag": "none"}],
            ),
            ["none", "one"],
        )
        self.assertEqual(
            order(
                "BidPageSettings",
                [
                    {"tag": "blank", "UID": "", "BidAreaSelected": ""},
                    {"tag": "one", "UID": "1", "BidAreaSelected": "0"},
                    {"tag": "missing"},
                ],
            ),
            ["one", "blank", "missing"],
        )


class OstExporterGlobalSelectionTests(unittest.TestCase):
    def _root(self, bid_row, **global_tables):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "global.ost"
            result = OstExporter(SimpleNamespace()).export(
                RawBidData(
                    bid_row={"UID": "1", "JobName": "Bid", **bid_row},
                    bid_tables={"BidConditions": [], "BidPages": []},
                    global_tables=global_tables,
                ),
                str(output_path),
            )
            self.assertTrue(result.success, result.error_message)
            return ET.parse(output_path).getroot()

    def test_unreferenced_rows_are_not_selected_by_missing_bid_references(self):
        root = self._root(
            {},
            Employees=[{"UID": "XX", "PayClassUID": "0", "AccessLevelUID": "0"}],
            JobStatuses=[{"UID": "XX", "Name": "Status"}],
        )
        self.assertEqual([child.tag for child in root], ["OST", "Bid"])

    def test_zero_and_blank_pay_class_and_access_level_references_select_nothing(self):
        root = self._root(
            {"EstimatorUID": "7", "PrManagerUID": "8"},
            Employees=[
                {"UID": "7", "PayClassUID": "0", "AccessLevelUID": "0"},
                {"UID": "8", "PayClassUID": "", "AccessLevelUID": ""},
            ],
            PayClasses=[
                {"UID": "0", "Name": "Zero"},
                {"UID": "", "Name": "Blank"},
            ],
            AccessLevels=[
                {"UID": "0", "Description": "Zero"},
                {"UID": "", "Description": "Blank"},
            ],
        )
        self.assertEqual(
            [e.get("UID") for e in root.findall("./Employees/Employee")], ["7", "8"]
        )
        self.assertEqual(root.findall("./PayClasses"), [])
        self.assertEqual(root.findall("./AccessLevels"), [])


class OstExporterDurableWriteTests(unittest.TestCase):
    RAW = RawBidData(
        bid_row={"UID": "1", "JobName": "Bid"},
        bid_tables={"BidConditions": [], "BidPages": []},
    )

    def test_content_is_flushed_and_synced_before_the_atomic_replace(self):
        events = []
        real_fsync = os.fsync
        real_replace = os.replace
        snapshots = []

        def recording_fsync(fd):
            events.append("fsync")
            # at sync time the temp file must already hold the complete document
            for path in Path(temp_dir).iterdir():
                snapshots.append(path.read_bytes())
            return real_fsync(fd)

        def recording_replace(source, destination):
            events.append("replace")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "durable.ost"
            with patch.object(ost_exporter_module.os, "fsync", recording_fsync):
                with patch.object(ost_exporter_module.os, "replace", recording_replace):
                    result = OstExporter(SimpleNamespace()).export(
                        self.RAW, str(output_path)
                    )
            self.assertTrue(result.success, result.error_message)
        self.assertEqual(events, ["fsync", "replace"])
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].endswith(b"</XML_ROOT>\r\n"))

    def test_success_does_not_remove_any_file_afterwards(self):
        removed = []
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "keep.ost"
            with patch.object(
                ost_exporter_module.os, "remove", side_effect=removed.append
            ):
                result = OstExporter(SimpleNamespace()).export(
                    self.RAW, str(output_path)
                )
            self.assertTrue(result.success, result.error_message)
        self.assertEqual(removed, [])
