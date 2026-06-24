import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryGrouping,
)
from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportResultDto,
)
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.handlers import export_handler as export_handler_module
from ost_visualizer.presentation.handlers.export_handler import ExportHandler
from ost_visualizer.presentation.visualization.exporters import osp_exporter
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter


class _FakeProjectData:
    def __init__(self, page_names):
        self._pages = {
            f"page-{index}": Page(
                uid=f"page-{index}",
                name=name,
                width_pts=612.0,
                height_pts=792.0,
            )
            for index, name in enumerate(page_names, start=1)
        }

    def get_bid_conditions(self):
        return {}

    def get_page(self, page_uid):
        return self._pages[page_uid]

    def get_page_takeoffs(self, _page_uid):
        return []

    def get_current_bid(self):
        return SimpleNamespace(name="25-051 Marriott Element, Capel Hill, NC")


class _FakeDeferredPersistence:
    def __init__(self, result=True):
        self.result = result
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1
        return self.result


def _make_export_handler(**overrides):
    kwargs = {
        "window": None,
        "config_model": SimpleNamespace(),
        "export_service": SimpleNamespace(),
        "summary_csv_export_service": SimpleNamespace(),
        "project_data_service": SimpleNamespace(),
        "pdf_exporter": SimpleNamespace(),
        "ost_exporter": SimpleNamespace(),
        "osp_exporter": SimpleNamespace(),
        "mdb_file_parser": SimpleNamespace(),
        "deferred_persistence_manager": _FakeDeferredPersistence(),
    }
    kwargs.update(overrides)
    return ExportHandler(**kwargs)


def _capture_pdf_default_filename(page_names):
    captured = {}
    original_get_save = export_handler_module.QtWidgets.QFileDialog.getSaveFileName

    def fake_get_save_file_name(_window, _title, default_filename, _filter):
        captured["default_filename"] = default_filename
        return "", ""

    export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
        fake_get_save_file_name
    )
    try:
        handler = _make_export_handler(
            project_data_service=_FakeProjectData(page_names),
        )
        handler.export_as_pdf(
            [f"page-{index}" for index in range(1, len(page_names) + 1)]
        )
    finally:
        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = original_get_save
    return captured["default_filename"]


class ExportHandlerPdfFilenameTests(unittest.TestCase):
    def test_pdf_export_stops_when_deferred_persistence_flush_fails(self):
        deferred = _FakeDeferredPersistence(result=False)
        handler = _make_export_handler(
            project_data_service=SimpleNamespace(
                get_bid_conditions=lambda: self.fail(
                    "export should not read project data after failed flush"
                )
            ),
            deferred_persistence_manager=deferred,
        )
        handler.export_as_pdf(["page-1"])
        self.assertEqual(deferred.flush_calls, 1)

    def test_osp_export_stops_when_deferred_persistence_flush_fails(self):
        deferred = _FakeDeferredPersistence(result=False)
        handler = _make_export_handler(
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: self.fail(
                    "export should not read bid data after failed flush"
                )
            ),
            deferred_persistence_manager=deferred,
        )
        handler.export_as_osp()
        self.assertEqual(deferred.flush_calls, 1)

    def test_single_page_pdf_default_filename_keeps_existing_pdf_extension(self):
        filename = _capture_pdf_default_filename(["S-100.pdf"])
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.pdf"
        )

    def test_single_page_pdf_default_filename_keeps_existing_pdf_extension_case_insensitive(
        self,
    ):
        filename = _capture_pdf_default_filename(["S-100.PDF"])
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.PDF"
        )

    def test_single_page_pdf_default_filename_appends_pdf_when_missing(self):
        filename = _capture_pdf_default_filename(["S-100"])
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.pdf"
        )

    def test_multi_page_pdf_default_filename_has_one_pdf_extension(self):
        filename = _capture_pdf_default_filename(["S-100.pdf", "S-101.pdf"])
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - 2 Pages.pdf"
        )

    def test_summary_csv_export_uses_current_grouping_and_appends_extension(self):
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        calls = []
        infos = []
        original_get_save = export_handler_module.QtWidgets.QFileDialog.getSaveFileName
        original_show_info = export_handler_module.show_info

        def fake_get_save_file_name(_window, title, default_filename, filter_str):
            self.assertEqual(title, "Export Summary as CSV")
            self.assertEqual(default_filename, "Bid Summary.csv")
            self.assertEqual(filter_str, "CSV Files (*.csv);;All Files (*.*)")
            return r"C:\tmp\summary", ""

        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
            fake_get_save_file_name
        )
        export_handler_module.show_info = lambda _window, title, message: infos.append(
            (title, message)
        )
        try:
            service = SimpleNamespace(
                default_filename=lambda: "Bid Summary.csv",
                export_current_summary=lambda used_grouping, filename: calls.append(
                    (used_grouping, filename)
                )
                or ExportResultDto(success=True, format_name="Summary CSV"),
            )
            handler = _make_export_handler(
                window=SimpleNamespace(get_summary_grouping=lambda: grouping),
                summary_csv_export_service=service,
            )
            handler.export_summary_csv()
        finally:
            export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
                original_get_save
            )
            export_handler_module.show_info = original_show_info
        self.assertEqual(calls, [(grouping, r"C:\tmp\summary.csv")])
        self.assertEqual(infos[0][0], "Export Complete")

    def test_summary_csv_export_reports_empty_data_as_warning(self):
        warnings = []
        original_get_save = export_handler_module.QtWidgets.QFileDialog.getSaveFileName
        original_show_warning = export_handler_module.show_warning
        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = lambda *_args: (
            r"C:\tmp\summary.csv",
            "",
        )
        export_handler_module.show_warning = (
            lambda _window, title, message: warnings.append((title, message))
        )
        try:
            service = SimpleNamespace(
                default_filename=lambda: "Bid Summary.csv",
                export_current_summary=lambda _grouping, _filename: ExportResultDto(
                    success=False,
                    format_name="Summary CSV",
                    error_message="No summary rows are available to export.",
                    error_code=ExportErrorCode.NO_DATA,
                ),
            )
            handler = _make_export_handler(
                window=SimpleNamespace(
                    get_summary_grouping=lambda: ConditionSummaryGrouping()
                ),
                summary_csv_export_service=service,
            )
            handler.export_summary_csv()
        finally:
            export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
                original_get_save
            )
            export_handler_module.show_warning = original_show_warning
        self.assertEqual(
            warnings,
            [("No Data", "No summary rows are available to export.")],
        )


class OspExporterProgressTests(unittest.TestCase):
    def _unused_ost_exporter_factory(self, _uom_service):
        self.fail("OST exporter should not be constructed")

    def test_collect_images_reports_each_included_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.pdf"
            second = Path(tmp) / "second.tif"
            ignored = Path(tmp) / "ignored.jpg"
            first.write_bytes(b"pdf")
            second.write_bytes(b"tif")
            ignored.write_bytes(b"jpg")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [
                        {"ImagePath": str(first), "OverlayImagePath": ""},
                        {"ImagePath": str(ignored), "OverlayImagePath": str(second)},
                        {"ImagePath": str(first), "OverlayImagePath": ""},
                    ]
                }
            )
            exporter = OspExporter(
                SimpleNamespace(),
                "1.0",
                self._unused_ost_exporter_factory,
            )
            source_files = []
            archive_names = []
            progress = []
            exporter._collect_images(
                raw_data,
                source_files,
                archive_names,
                lambda current, total, description: progress.append(
                    (current, total, description)
                ),
            )
        self.assertEqual(source_files, [str(first), str(second)])
        self.assertEqual(
            archive_names,
            ["TempImages!.tmp\\first.pdf", "TempImages!.tmp\\second.tif"],
        )
        self.assertEqual(
            [description for _current, _total, description in progress],
            ["Collecting first.pdf", "Collecting second.tif"],
        )

    def test_osp_export_reports_image_progress_before_packaging(self):
        class FakeOstExporter:
            def __init__(self, _uom_service):
                pass

            def export(self, _raw_data, output_path):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sheet.pdf"
            output = Path(tmp) / "out.osp"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [{"ImagePath": str(image), "OverlayImagePath": ""}]
                }
            )
            cab_calls = []
            progress = []
            original_create_cab = osp_exporter.ost_cab.create_cab_with_names
            try:
                osp_exporter.ost_cab.create_cab_with_names = (
                    lambda source_files, archive_names, output_file: cab_calls.append(
                        (list(source_files), list(archive_names), output_file)
                    )
                    or True
                )
                exporter = OspExporter(
                    SimpleNamespace(),
                    "1.0",
                    lambda uom_service: FakeOstExporter(uom_service),
                )
                result = exporter.export(
                    raw_data,
                    str(output),
                    "Bid",
                    on_progress=lambda current, total, description: progress.append(
                        (current, total, description)
                    ),
                )
            finally:
                osp_exporter.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        self.assertEqual(
            [description for _current, _total, description in progress],
            [
                "Building OST",
                "Writing metadata",
                "Collecting images",
                "Collecting sheet.pdf",
                "Packaging archive",
            ],
        )
        self.assertEqual(len(cab_calls), 1)
        self.assertIn("TempImages!.tmp\\sheet.pdf", cab_calls[0][1])


if __name__ == "__main__":
    unittest.main()
