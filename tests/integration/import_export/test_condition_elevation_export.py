import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.application.interfaces.i_uom_service import IUOMService
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.presentation.handlers import export_handler as export_handler_module
from ost_visualizer.presentation.visualization.exporters import (
    osp_exporter as osp_exporter_module,
)
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter
from tests.presentation.handlers.test_export_handler import (
    _ImmediateProgressDialog,
    _make_export_handler,
)

STORED_NAMES = (
    "(PC5__3K) (7150) (NoPiles20_Detail#) 100 098 14.5 X 11.5 @T 745' 0\"",
    "(PC5__3K) (7150) (NoPiles20_Detail#) 100 098 14.5 X 11.5 @B 12' 6 1/2\"",
    "Wall @T 5&apos; 0&quot;",
    "Plain",
    "Meeting @T later",
)
EXPORTED_NAMES = (
    "(PC5__3K) (7150) (NoPiles20_Detail#) 100 098 14.5 X 11.5",
    "(PC5__3K) (7150) (NoPiles20_Detail#) 100 098 14.5 X 11.5",
    "Wall",
    "Plain",
    "Meeting @T later",
)


def _raw_bid_data():
    return RawBidData(
        bid_row={"UID": "1", "JobName": "Exported"},
        bid_tables={
            "BidConditions": [
                {"UID": str(10 + index), "BidUID": "1", "Name": name}
                for index, name in enumerate(STORED_NAMES)
            ],
            "BidPages": [{"UID": "20", "BidUID": "1"}],
        },
        page_tables={},
        global_tables={},
    )


def _condition_names(ost_path):
    root = ET.parse(ost_path).getroot()
    return [
        element.get("Name")
        for element in root.findall("./Bid/BidConditions/BidCondition")
    ]


class ConditionElevationExportEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.raw = _raw_bid_data()
        uom_service = create_autospec(IUOMService, instance=True)
        uom_service.calculate_condition_quantities.return_value = (0.0, 0.0, 0.0)
        self.uom_service = uom_service

    def export(self, method, *, config, osp_member_sink=None):
        bid = SimpleNamespace(name="Bid")
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=lambda: config),
            database_reader=SimpleNamespace(get_raw_bid_data=lambda *_args: self.raw),
            ost_exporter=OstExporter(self.uom_service),
            osp_exporter=OspExporter(self.uom_service, "1.0", OstExporter),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: SimpleNamespace(
                    file_path="bid.mdb", bid_uid="1"
                ),
                get_current_bid=lambda: bid,
            ),
        )
        extension = "osp" if method == "export_as_osp" else "ost"
        destination = self.temp / f"out.{extension}"

        def capture_cab(source_files, archive_names, output):
            for source, name in zip(source_files, archive_names):
                if name.endswith(".ost"):
                    osp_member_sink.append(Path(source).read_bytes())
            Path(output).write_bytes(b"cab")
            return True

        patches = [
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=(str(destination), ""),
            ),
            patch.object(
                export_handler_module, "ProgressDialog", _ImmediateProgressDialog
            ),
            patch.object(export_handler_module, "show_info"),
            patch.object(export_handler_module, "show_critical"),
        ]
        if osp_member_sink is not None:
            patches.append(
                patch.object(
                    osp_exporter_module.ost_cab,
                    "create_cab_with_names",
                    side_effect=capture_cab,
                )
            )
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        getattr(handler, method)()
        return destination

    def test_ost_export_keeps_every_name_exactly_when_the_option_is_off(self):
        destination = self.export("export_as_ost", config=Config())
        self.assertEqual(_condition_names(destination), list(STORED_NAMES))

    def test_ost_export_writes_names_without_elevations_when_on(self):
        destination = self.export(
            "export_as_ost",
            config=Config(ost_osp_export_drop_condition_elevation=True),
        )
        self.assertEqual(_condition_names(destination), list(EXPORTED_NAMES))

    def test_the_csv_option_does_not_change_the_ost_export(self):
        destination = self.export(
            "export_as_ost", config=Config(csv_export_drop_condition_elevation=True)
        )
        self.assertEqual(_condition_names(destination), list(STORED_NAMES))

    def test_osp_package_carries_the_stripped_names_inside_its_ost(self):
        members = []
        self.export(
            "export_as_osp",
            config=Config(ost_osp_export_drop_condition_elevation=True),
            osp_member_sink=members,
        )
        self.assertEqual(len(members), 1)
        member = self.temp / "member.ost"
        member.write_bytes(members[0])
        self.assertEqual(_condition_names(member), list(EXPORTED_NAMES))

    def test_osp_package_keeps_names_when_the_option_is_off(self):
        members = []
        self.export("export_as_osp", config=Config(), osp_member_sink=members)
        member = self.temp / "member.ost"
        member.write_bytes(members[0])
        self.assertEqual(_condition_names(member), list(STORED_NAMES))

    def test_source_rows_are_unchanged_after_every_export(self):
        for method, sink in (("export_as_ost", None), ("export_as_osp", [])):
            self.export(
                method,
                config=Config(ost_osp_export_drop_condition_elevation=True),
                osp_member_sink=sink,
            )
        self.assertEqual(
            [row["Name"] for row in self.raw.bid_tables["BidConditions"]],
            list(STORED_NAMES),
        )

    def test_colliding_conditions_are_both_exported_with_their_own_uids(self):
        destination = self.export(
            "export_as_ost",
            config=Config(ost_osp_export_drop_condition_elevation=True),
        )
        root = ET.parse(destination).getroot()
        conditions = root.findall("./Bid/BidConditions/BidCondition")
        collided = [c for c in conditions if c.get("Name") == EXPORTED_NAMES[0]]
        self.assertEqual(len(collided), 2)
        self.assertEqual(len({c.get("UID") for c in collided}), 2)
        self.assertEqual(len(conditions), len(STORED_NAMES))


if __name__ == "__main__":
    unittest.main()
