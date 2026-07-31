import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Optional
from ost_visualizer.application.dtos.condition_summary_dtos import (
    ConditionSummaryGrouping,
)
from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportProgressCallback,
    ExportRequestDto,
    ExportResultDto,
)
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.config import Config
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

    def get_page_area_selections(self):
        return {}

    def get_all_annotations(self):
        return []


class _FakeDeferredPersistence:
    def __init__(self, result=True):
        self.result = result
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1
        return self.result


def _make_export_handler(**overrides):
    constructor_options = {
        "window": None,
        "config_model": SimpleNamespace(),
        "export_service": SimpleNamespace(),
        "summary_csv_export_service": SimpleNamespace(),
        "project_data_service": SimpleNamespace(),
        "pdf_exporter": SimpleNamespace(),
        "ost_exporter": SimpleNamespace(),
        "osp_exporter": SimpleNamespace(),
        "database_reader": SimpleNamespace(),
        "deferred_persistence_manager": _FakeDeferredPersistence(),
    }
    constructor_options.update(overrides)
    return ExportHandler(**constructor_options)


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
    def test_bid_file_export_reads_through_backend_neutral_reader(self):
        calls = []
        database_reader = SimpleNamespace(
            get_raw_bid_data=lambda locator, bid_uid: calls.append((locator, bid_uid))
            or RawBidData()
        )
        handler = _make_export_handler(
            database_reader=database_reader,
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: SimpleNamespace(
                    file_path="sql-database-id", bid_uid="42"
                ),
                get_current_bid=lambda: SimpleNamespace(name="Bid"),
            ),
        )

        class _ProgressDialog:
            def __init__(self, _filename, run, **_kwargs):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        with patch.object(
            export_handler_module.QtWidgets.QFileDialog,
            "getSaveFileName",
            return_value=("output.ost", ""),
        ), patch.object(
            export_handler_module, "ProgressDialog", _ProgressDialog
        ), patch.object(
            export_handler_module, "show_info"
        ):
            handler._export_bid_file(
                "OST",
                "ost",
                "Export",
                lambda _raw, _filename, _name, _reporter: lambda: SimpleNamespace(
                    success=True
                ),
            )
        self.assertEqual(calls, [("sql-database-id", "42")])

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

    def test_pdf_export_uses_2d_display_mode(self):
        calls = []
        original_get_save = export_handler_module.QtWidgets.QFileDialog.getSaveFileName
        original_progress_dialog = export_handler_module.ProgressDialog
        original_show_info = export_handler_module.show_info

        class FakeProgressDialog:
            def __init__(self, _filename, export_fn, parent=None, reporter=None):
                self.result = None
                self.error = None
                self._export_fn = export_fn

            def exec(self):
                self.result = self._export_fn()
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def fake_get_save_file_name(_window, _title, _default_filename, _filter):
            return r"C:\tmp\out.pdf", ""

        def fake_export(
            pages_data,
            filename,
            display_mode,
            grayscale_enabled,
            caption_settings,
            elevation_callouts_enabled,
            elevation_callout_settings,
            elevation_callout_color,
            page_area_selections,
            bid_annotations,
            on_progress: Optional[ExportProgressCallback] = None,
        ):
            calls.append(
                (
                    display_mode,
                    grayscale_enabled,
                    len(pages_data),
                    caption_settings,
                    elevation_callouts_enabled,
                    elevation_callout_settings,
                    elevation_callout_color,
                )
            )
            return ExportResultDto(success=True, format_name="PDF", page_count=1)

        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
            fake_get_save_file_name
        )
        export_handler_module.ProgressDialog = FakeProgressDialog
        export_handler_module.show_info = lambda *_args: None
        try:
            handler = _make_export_handler(
                config_model=SimpleNamespace(
                    snapshot=lambda: Config(
                        display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
                        grayscale_enabled=False,
                        pdf_annotation_captions_enabled=True,
                        pdf_annotation_caption_ids=("area", "volume"),
                        pdf_elevation_callouts_enabled=True,
                        elevation_callout_include_top=False,
                        pdf_elevation_callout_color="#abcdef",
                    )
                ),
                project_data_service=_FakeProjectData(["A1"]),
                pdf_exporter=SimpleNamespace(export=fake_export),
            )
            handler.export_as_pdf(["page-1"])
        finally:
            export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
                original_get_save
            )
            export_handler_module.ProgressDialog = original_progress_dialog
            export_handler_module.show_info = original_show_info
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], (Config.DISPLAY_MODE_TRANSPARENT, False, 1))
        self.assertTrue(calls[0][3].enabled)
        self.assertEqual(
            tuple(caption_id.value for caption_id in calls[0][3].selected_ids),
            ("area", "volume"),
        )
        self.assertTrue(calls[0][4])
        self.assertFalse(calls[0][5].include_top)
        self.assertEqual(calls[0][6], "#abcdef")

    def test_pdf_export_rejects_case_variant_of_source_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "Source.PDF"
            source_path.write_bytes(b"source")
            page = Page(
                uid="page-1",
                name="Source",
                image_path=str(source_path),
                width_pts=612.0,
                height_pts=792.0,
            )
            project_data = SimpleNamespace(
                get_bid_conditions=lambda: {},
                get_page=lambda _uid: page,
                get_page_takeoffs=lambda _uid: [],
                get_current_bid=lambda: SimpleNamespace(name="Bid"),
            )
            pdf_exporter = SimpleNamespace(
                export=lambda *_args, **_kwargs: self.fail(
                    "source-overwrite guard must stop the exporter"
                )
            )
            errors = []
            handler = _make_export_handler(
                project_data_service=project_data,
                pdf_exporter=pdf_exporter,
            )
            with patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=(str(Path(temp_dir) / "source.pdf"), ""),
            ), patch.object(
                export_handler_module,
                "show_critical",
                side_effect=lambda _window, title, message: errors.append(
                    (title, message)
                ),
            ):
                handler.export_as_pdf(["page-1"])
        self.assertEqual(errors[0][0], "Invalid Save Location")

    def test_general_export_uses_saved_config_snapshot(self):
        config = Config(html_elevation_callouts_enabled=False)
        snapshots = []
        export_calls = []

        def snapshot():
            snapshots.append(config)
            return config

        def export(used_config, request):
            export_calls.append((used_config, request))
            return ExportResultDto(success=True, format_name="HTML", page_count=1)

        original_show_info = export_handler_module.show_info
        export_handler_module.show_info = lambda *_args: None
        try:
            handler = _make_export_handler(
                config_model=SimpleNamespace(snapshot=snapshot),
                export_service=SimpleNamespace(export=export),
            )
            request = ExportRequestDto(["page-1"], "html", "out.html")
            handler._execute_export(request)
        finally:
            export_handler_module.show_info = original_show_info
        self.assertEqual(snapshots, [config])
        self.assertEqual(export_calls, [(config, request)])

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

    def _make_osp_exporter(self, ost_exporter_factory=None):
        return OspExporter(
            SimpleNamespace(),
            "1.0",
            ost_exporter_factory or self._unused_ost_exporter_factory,
        )

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
            exporter = self._make_osp_exporter()
            (
                _package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
            self.assertEqual(missing, [])
            source_files = []
            archive_names = []
            progress = []
            exporter._collect_images(
                image_sources,
                source_files,
                archive_names,
                lambda current, total, description: progress.append(
                    (current, total, description)
                ),
            )
        self.assertEqual(
            set(source_files), {str(first.resolve()), str(second.resolve())}
        )
        self.assertEqual(len(archive_names), 2)
        self.assertCountEqual(
            archive_names,
            ["TempImages!.tmp\\first.pdf", "TempImages!.tmp\\second.tif"],
        )
        self.assertCountEqual(
            [description for _current, _total, description in progress],
            ["Collecting first.pdf", "Collecting second.tif"],
        )

    def test_prepare_package_data_flattens_distinct_same_filename_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = Path(tmp) / "first"
            second_dir = Path(tmp) / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "sheet.pdf"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 2)
        self.assertEqual(set(image_sources.values()), {str(first), str(second)})
        self.assertEqual(len({path.casefold() for path in image_sources}), 2)
        self.assertTrue(
            all(
                path.startswith("TempImages!.tmp\\") and path.count("\\") == 1
                for path in image_sources
            )
        )
        self.assertEqual(len(set(page_paths)), 2)
        self.assertEqual(set(page_paths), set(image_sources))

    def test_prepare_package_data_preserves_database_paths_for_unique_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "A0.01.pdf"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Ignored"},
                bid_tables={
                    "BidPages": [{"UID": "10", "BidUID": "1", "ImagePath": str(image)}]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 1)
        package_member_path = next(iter(image_sources))
        self.assertEqual(package_member_path, "TempImages!.tmp\\A0.01.pdf")
        self.assertEqual(
            package_data.bid_tables["BidPages"][0]["ImagePath"],
            str(image),
        )
        self.assertFalse(
            package_data.bid_tables["BidPages"][0]["ImagePath"].startswith(
                "TempImages!.tmp"
            )
        )

    def test_prepare_package_data_maps_case_insensitive_filename_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = Path(tmp) / "first"
            second_dir = Path(tmp) / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "SHEET.PDF"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 2)
        self.assertEqual(set(image_sources.values()), {str(first), str(second)})
        self.assertEqual(len({path.casefold() for path in image_sources}), 2)
        self.assertTrue(all(path.count("\\") == 1 for path in image_sources))
        self.assertEqual(len(set(page_paths)), 2)
        self.assertEqual(set(page_paths), set(image_sources))

    def test_prepare_package_data_avoids_generated_and_direct_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first" / "sheet.pdf"
            second = root / "second" / "sheet.pdf"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            exporter = self._make_osp_exporter()
            generated_member = exporter._collision_package_image_member_path(
                str(first.resolve()).casefold(),
                first.name,
                "10",
            )
            third = root / "third" / PureWindowsPath(generated_member).name
            third.parent.mkdir()
            third.write_bytes(b"third")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "ImagePath": str(first)},
                        {"UID": "11", "ImagePath": str(second)},
                        {"UID": "12", "ImagePath": str(third)},
                    ]
                }
            )
            package_data, image_sources, missing = exporter._prepare_package_data(
                raw_data
            )
            repeated_data, repeated_sources, repeated_missing = (
                exporter._prepare_package_data(raw_data)
            )
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 3)
        self.assertEqual(len({name.casefold() for name in image_sources}), 3)
        self.assertEqual(
            set(image_sources.values()), {str(first), str(second), str(third)}
        )
        self.assertEqual(set(page_paths), set(image_sources))
        self.assertTrue(all(name.count("\\") == 1 for name in image_sources))
        self.assertEqual(repeated_missing, missing)
        self.assertEqual(repeated_sources, image_sources)
        self.assertEqual(
            [row["ImagePath"] for row in repeated_data.bid_tables["BidPages"]],
            page_paths,
        )

    def test_osp_export_writes_original_app_compatible_flat_image_member(self):
        class FakeOstExporter:
            def __init__(self, _uom_service):
                pass

            def export(self, _raw_data, output_path, on_progress=None):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sheet.pdf"
            image.write_bytes(b"pdf")
            output = Path(tmp) / "out.osp"
            raw_data = RawBidData(
                bid_tables={"BidPages": [{"UID": "10", "ImagePath": str(image)}]}
            )
            exporter = self._make_osp_exporter(FakeOstExporter)
            result = exporter.export(raw_data, str(output))
            archive_names = list(osp_exporter.ost_cab.list_cab(str(output)))
        self.assertTrue(result.success, result.error_message)
        self.assertIn("TempImages!.tmp\\sheet.pdf", archive_names)
        self.assertFalse(
            any(
                name.startswith("TempImages!.tmp\\") and name.count("\\") > 1
                for name in archive_names
            )
        )

    def test_prepare_package_data_reports_missing_drawing_files(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidPages": [
                    {
                        "UID": "10",
                        "BidUID": "1",
                        "ImagePath": r"C:\missing\sheet.pdf",
                    }
                ]
            },
        )
        exporter = self._make_osp_exporter()
        (
            _package_data,
            image_sources,
            missing,
        ) = exporter._prepare_package_data(raw_data)
        self.assertEqual(image_sources, {})
        self.assertEqual(missing, [r"C:\missing\sheet.pdf"])

    def test_osp_export_reports_image_progress_before_packaging(self):
        class FakeOstExporter:
            def __init__(self, _uom_service):
                pass

            def export(
                self,
                _raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
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
                exporter = self._make_osp_exporter(
                    lambda uom_service: FakeOstExporter(uom_service)
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

    def test_osp_export_preserves_database_image_paths_in_embedded_ost(self):
        class FakeOstExporter:
            captured_rows = []

            def __init__(self, _uom_service):
                pass

            def export(
                self,
                raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
                self.captured_rows = [
                    dict(row) for row in raw_data.bid_tables.get("BidPages", [])
                ]
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "A0.02.pdf"
            output = Path(tmp) / "out.osp"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [{"ImagePath": str(image), "OverlayImagePath": ""}]
                }
            )
            original_create_cab = osp_exporter.ost_cab.create_cab_with_names
            try:
                osp_exporter.ost_cab.create_cab_with_names = (
                    lambda _source_files, _archive_names, _output_file: True
                )
                fake_exporter = FakeOstExporter(SimpleNamespace())
                exporter = self._make_osp_exporter(
                    lambda _uom_service: fake_exporter,
                )
                result = exporter.export(
                    raw_data,
                    str(output),
                    "26-053 8201 Metcalf Overland Park, KS",
                )
            finally:
                osp_exporter.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        self.assertEqual(
            fake_exporter.captured_rows[0]["ImagePath"],
            str(image),
        )

    def test_osp_export_failure_preserves_existing_destination(self):
        class FakeOstExporter:
            def export(self, _raw_data, output_path):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing.osp"
            output.write_bytes(b"existing archive")
            cab_outputs = []

            def fail_after_partial_write(_source_files, _archive_names, temp_output):
                cab_outputs.append(Path(temp_output))
                Path(temp_output).write_bytes(b"partial archive")
                return False

            with patch.object(
                osp_exporter.ost_cab,
                "create_cab_with_names",
                side_effect=fail_after_partial_write,
            ):
                result = self._make_osp_exporter(
                    lambda _uom_service: FakeOstExporter()
                ).export(RawBidData(), str(output))
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, ExportErrorCode.WRITE_FAILED)
            self.assertEqual(output.read_bytes(), b"existing archive")
            self.assertEqual(len(cab_outputs), 1)
            self.assertNotEqual(cab_outputs[0], output)
            self.assertFalse(cab_outputs[0].exists())


if __name__ == "__main__":
    unittest.main()
