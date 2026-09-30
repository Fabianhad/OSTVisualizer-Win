import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch
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
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.handlers import export_handler as export_handler_module
from ost_visualizer.presentation.handlers.export_handler import ExportHandler
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from PySide6 import QtWidgets
from shiboken6 import delete


class _FakeProjectData:
    def __init__(self, page_names):
        self._bid_ref = BidRef("database-1", "bid-1")
        self._pages = {
            f"page-{index}": Page(
                uid=f"page-{index}",
                name=name,
                width_pts=612.0,
                height_pts=792.0,
            )
            for index, name in enumerate(page_names, start=1)
        }
        self._current_bid = SimpleNamespace(
            name="25-051 Marriott Element, Capel Hill, NC"
        )

    def get_bid_conditions(self):
        return {}

    def get_page(self, page_uid):
        return self._pages[page_uid]

    def get_page_takeoffs(self, _page_uid):
        return []

    def get_current_bid(self):
        return self._current_bid

    def get_current_bid_ref(self):
        return self._bid_ref

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
    default_bid = SimpleNamespace(name="Bid")
    constructor_options = {
        "window": None,
        "config_model": SimpleNamespace(),
        "export_service": SimpleNamespace(),
        "summary_csv_export_service": SimpleNamespace(),
        "pdf_exporter": SimpleNamespace(),
        "ost_exporter": SimpleNamespace(),
        "osp_exporter": SimpleNamespace(),
        "database_reader": SimpleNamespace(),
        "deferred_persistence_manager": _FakeDeferredPersistence(),
        "project_data_service": SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
            get_current_bid=lambda: default_bid,
        ),
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
    def test_bid_export_stops_after_progress_parent_is_destroyed(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QDialog()
        bid = SimpleNamespace(name="Bid")
        bid_ref = BidRef("bid.mdb", "bid-1")
        critical_messages = []

        class DestroyingProgressDialog(QtWidgets.QDialog):
            def __init__(self, _filename, run, parent=None, reporter=None):
                super().__init__(parent)
                self.result = run()
                self.error = None

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

        handler = _make_export_handler(
            window=window,
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: bid_ref,
                get_current_bid=lambda: bid,
            ),
            database_reader=SimpleNamespace(
                get_raw_bid_data=lambda _path, _uid: RawBidData()
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.ost", ""),
            ),
            patch.object(
                export_handler_module,
                "ProgressDialog",
                DestroyingProgressDialog,
            ),
            patch.object(
                export_handler_module,
                "show_info",
                side_effect=AssertionError("closed window must not receive success"),
            ),
            patch.object(
                export_handler_module,
                "show_critical",
                side_effect=lambda *_args: critical_messages.append(True),
            ),
        ):
            handler._export_bid_file(
                "OST",
                "ost",
                "Export",
                lambda _raw, _filename, _name, _reporter: lambda: SimpleNamespace(
                    success=True
                ),
            )
        self.assertIsNotNone(app)
        self.assertEqual(critical_messages, [])

    def test_bid_file_export_reads_through_backend_neutral_reader(self):
        calls = []
        bid = SimpleNamespace(name="Bid")
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
                get_current_bid=lambda: bid,
            ),
        )

        class _ProgressDialog:
            def __init__(self, _filename, run, parent=None, reporter=None):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.ost", ""),
            ),
            patch.object(export_handler_module, "ProgressDialog", _ProgressDialog),
            patch.object(export_handler_module, "show_info"),
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
            inactive_object_color,
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
                    inactive_object_color,
                )
            )
            return ExportResultDto(success=True, format_name="PDF", page_count=1)

        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
            fake_get_save_file_name
        )
        export_handler_module.ProgressDialog = FakeProgressDialog
        export_handler_module.show_info = lambda _window, _title, _message: None
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
                        inactive_object_color="#345678",
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
        self.assertEqual(calls[0][7], "#345678")

    def test_pdf_export_snapshots_latest_modes_for_retained_page_owners(self):
        project_data = _FakeProjectData(["A1", "A2"])
        selected_page_uids = ["page-1", "page-2"]
        for page in project_data._pages.values():
            page.image_show_mode = SHOW_BOTH
        transitions = (
            (SHOW_OVERLAY, SHOW_ORIGINAL),
            (SHOW_ORIGINAL, SHOW_BOTH),
            (SHOW_BOTH, SHOW_OVERLAY),
        )
        captured_modes = []
        dialog_count = 0

        class _ProgressDialog:
            def __init__(self, _filename, run, parent=None, reporter=None):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def choose_output(_window, _title, _default_filename, _filter):
            nonlocal dialog_count
            modes = transitions[dialog_count]
            dialog_count += 1
            for page_uid, mode in zip(selected_page_uids, modes):
                project_data._pages[page_uid].image_show_mode = mode
            return rf"C:\tmp\latest-modes-{dialog_count}.pdf", ""

        def export(
            pages_data,
            _filename,
            _display_mode,
            _grayscale_enabled,
            *,
            caption_settings,
            elevation_callouts_enabled,
            elevation_callout_settings,
            elevation_callout_color,
            inactive_object_color,
            page_area_selections,
            bid_annotations,
            on_progress=None,
        ):
            _ = (
                caption_settings,
                elevation_callouts_enabled,
                elevation_callout_settings,
                elevation_callout_color,
                inactive_object_color,
                page_area_selections,
                bid_annotations,
                on_progress,
            )
            captured_modes.append(
                tuple(page_data.page.image_show_mode for page_data in pages_data)
            )
            for page_data in pages_data:
                self.assertIsNot(
                    page_data.page,
                    project_data._pages[page_data.page.uid],
                )
            return ExportResultDto(success=True, format_name="PDF", page_count=2)

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(export=export),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "ProgressDialog", _ProgressDialog),
            patch.object(export_handler_module, "show_info"),
        ):
            for _transition in transitions:
                handler.export_as_pdf(selected_page_uids)
        self.assertEqual(captured_modes, list(transitions))
        self.assertEqual(selected_page_uids, ["page-1", "page-2"])

    def test_pdf_export_cancels_when_bid_changes_inside_native_save_dialog(self):
        project_data = _FakeProjectData(["Original Page"])
        current_bid_ref = [BidRef("first.mdb", "bid-1")]
        project_data.get_current_bid_ref = lambda: current_bid_ref[0]
        exports = []
        warnings = []

        class _ProgressDialog:
            def __init__(self, _filename, run, parent=None, reporter=None):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def choose_output(_window, _title, _default_filename, _filter):
            current_bid_ref[0] = BidRef("second.mdb", "bid-2")
            project_data._pages["page-1"] = Page(
                uid="page-1",
                name="Colliding Page",
                width_pts=612.0,
                height_pts=792.0,
            )
            return r"C:\tmp\out.pdf", ""

        def export(*_args, **_kwargs):
            exports.append(True)
            return ExportResultDto(success=True, format_name="PDF", page_count=1)

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(export=export),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "ProgressDialog", _ProgressDialog),
            patch.object(
                export_handler_module,
                "show_warning",
                side_effect=lambda _window, title, message: warnings.append(
                    (title, message)
                ),
            ),
            patch.object(export_handler_module, "show_info"),
        ):
            handler.export_as_pdf(["page-1"])
        self.assertEqual(exports, [])
        self.assertEqual(warnings[0][0], "Export Cancelled")

    def test_pdf_export_cancels_when_same_uid_bid_is_replaced_inside_save_dialog(
        self,
    ):
        project_data = _FakeProjectData(["Original Page"])
        original_bid_ref = project_data.get_current_bid_ref()
        exports = []
        warnings = []

        def choose_output(_window, _title, _default_filename, _filter):
            project_data._current_bid = SimpleNamespace(
                name="Replacement with reused UID"
            )
            self.assertEqual(project_data.get_current_bid_ref(), original_bid_ref)
            return r"C:\tmp\out.pdf", ""

        class _ProgressDialog:
            def __init__(self, _filename, run, parent=None, reporter=None):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(
                export=lambda *_args, **_kwargs: exports.append(True)
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "ProgressDialog", _ProgressDialog),
            patch.object(
                export_handler_module,
                "show_warning",
                side_effect=lambda _window, title, message: warnings.append(
                    (title, message)
                ),
            ),
            patch.object(export_handler_module, "show_critical"),
        ):
            handler.export_as_pdf(["page-1"])
        self.assertEqual(exports, [])
        self.assertEqual(warnings[0][0], "Export Cancelled")

    def test_pdf_export_cancels_when_same_uid_page_is_replaced_inside_save_dialog(
        self,
    ):
        project_data = _FakeProjectData(["Original Page"])
        exports = []
        warnings = []

        def choose_output(_window, _title, _default_filename, _filter):
            project_data._pages["page-1"] = Page(
                uid="page-1",
                name="Replacement Page",
                width_pts=612.0,
                height_pts=792.0,
            )
            return r"C:\tmp\out.pdf", ""

        class _ProgressDialog:
            def __init__(self, _filename, run, parent=None, reporter=None):
                self.result = run()
                self.error = None

            def exec(self):
                return export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(
                export=lambda *_args, **_kwargs: exports.append(True)
                or ExportResultDto(success=True, format_name="PDF", page_count=1)
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "ProgressDialog", _ProgressDialog),
            patch.object(
                export_handler_module,
                "show_warning",
                side_effect=lambda _window, title, message: warnings.append(
                    (title, message)
                ),
            ),
            patch.object(export_handler_module, "show_info"),
        ):
            handler.export_as_pdf(["page-1"])
        self.assertEqual(exports, [])
        self.assertEqual(warnings[0][0], "Export Cancelled")

    def test_pdf_export_stops_if_window_closes_inside_native_save_dialog(self):
        project_data = _FakeProjectData(["Original Page"])
        exports = []
        handler = _make_export_handler(
            window=object(),
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(),
        )
        handler._build_pdf_export_snapshot = (
            lambda _page_uids: exports.append("snapshot") or []
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=(r"C:\tmp\out.pdf", ""),
            ),
            patch.object(
                export_handler_module, "isValid", return_value=False, create=True
            ),
            patch.object(export_handler_module, "show_warning") as warning,
        ):
            handler.export_as_pdf(["page-1"])
        self.assertEqual(exports, [])
        warning.assert_not_called()

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
            bid = SimpleNamespace(name="Bid")
            project_data = SimpleNamespace(
                get_bid_conditions=lambda: {},
                get_page=lambda _uid: page,
                get_page_takeoffs=lambda _uid: [],
                get_current_bid=lambda: bid,
                get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
            )

            def unexpected_pdf_export(
                pages_data,
                filename,
                display_mode,
                grayscale_enabled,
                caption_settings,
                elevation_callouts_enabled,
                elevation_callout_settings,
                elevation_callout_color,
                inactive_object_color,
                page_area_selections,
                bid_annotations,
                on_progress=None,
            ):
                self.fail("source-overwrite guard must stop the exporter")

            pdf_exporter = SimpleNamespace(export=unexpected_pdf_export)
            errors = []
            handler = _make_export_handler(
                project_data_service=project_data,
                pdf_exporter=pdf_exporter,
            )
            with (
                patch.object(
                    export_handler_module.QtWidgets.QFileDialog,
                    "getSaveFileName",
                    return_value=(str(Path(temp_dir) / "source.pdf"), ""),
                ),
                patch.object(
                    export_handler_module,
                    "show_critical",
                    side_effect=lambda _window, title, message: errors.append(
                        (title, message)
                    ),
                ),
            ):
                handler.export_as_pdf(["page-1"])
        self.assertEqual(errors[0][0], "Invalid Save Location")

    def test_pdf_export_path_identity_normalizes_extended_local_and_unc_aliases(self):
        local_path = r"C:\Projects\Bid; A\Sheet 01.pdf"
        unc_path = r"\\server\share\Bid; A\Sheet 01.pdf"
        self.assertEqual(
            export_handler_module._path_identity(local_path),
            export_handler_module._path_identity("\\\\?\\" + local_path),
        )
        self.assertEqual(
            export_handler_module._path_identity(unc_path),
            export_handler_module._path_identity(
                "\\\\?\\UNC\\" + unc_path.removeprefix("\\")
            ),
        )

    def test_pdf_export_rejects_overlay_source_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            overlay_path = Path(temp_dir) / "Overlay Source.pdf"
            overlay_path.write_bytes(b"overlay")
            page = Page(
                uid="page-1",
                name="Overlay",
                overlay_image_path=str(overlay_path),
                width_pts=612.0,
                height_pts=792.0,
            )
            bid = SimpleNamespace(name="Bid")
            project_data = SimpleNamespace(
                get_bid_conditions=lambda: {},
                get_page=lambda _uid: page,
                get_page_takeoffs=lambda _uid: [],
                get_current_bid=lambda: bid,
                get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
            )

            def unexpected_pdf_export(
                pages_data,
                filename,
                display_mode,
                grayscale_enabled,
                caption_settings,
                elevation_callouts_enabled,
                elevation_callout_settings,
                elevation_callout_color,
                inactive_object_color,
                page_area_selections,
                bid_annotations,
                on_progress=None,
            ):
                self.fail("source-overwrite guard must stop the exporter")

            errors = []
            handler = _make_export_handler(
                project_data_service=project_data,
                pdf_exporter=SimpleNamespace(export=unexpected_pdf_export),
            )
            with (
                patch.object(
                    export_handler_module.QtWidgets.QFileDialog,
                    "getSaveFileName",
                    return_value=(str(overlay_path), ""),
                ),
                patch.object(
                    export_handler_module,
                    "show_critical",
                    side_effect=lambda _window, title, message: errors.append(
                        (title, message)
                    ),
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
        export_handler_module.show_info = lambda _window, _title, _message: None
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

    def test_general_export_cancels_when_bid_changes_in_native_save_dialog(self):
        current_bid = [BidRef("database-1", "bid-1")]
        bid = SimpleNamespace(name="Bid")
        export_calls = []
        service = SimpleNamespace(
            get_export_dialog_info=lambda _pages, _format: SimpleNamespace(
                success=True,
                dialog_title="Export",
                default_filename="bid.html",
                format_name="HTML",
                extension="html",
                valid_pages=["page-1"],
            ),
            export=lambda _config, _request: export_calls.append(True)
            or ExportResultDto(success=True, format_name="HTML", page_count=1),
        )
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            export_service=service,
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: current_bid[0],
                get_current_bid=lambda: bid,
                get_page=lambda _uid: Page(uid="page-1", name="Page"),
            ),
        )

        def switch_bid(_dialog_info):
            current_bid[0] = BidRef("database-1", "bid-2")
            return "out.html"

        handler._show_save_dialog = switch_bid
        with patch.object(export_handler_module, "show_warning"):
            handler.export_format("html", ["page-1"])
        self.assertEqual(export_calls, [])

    def test_general_export_cancels_when_same_uid_page_is_replaced_in_save_dialog(
        self,
    ):
        bid = SimpleNamespace(name="Bid")
        bid_ref = BidRef("database-1", "bid-1")
        pages = {"page-1": Page(uid="page-1", name="Original")}
        export_calls = []
        warnings = []
        service = SimpleNamespace(
            get_export_dialog_info=lambda _pages, _format: SimpleNamespace(
                success=True,
                dialog_title="Export",
                default_filename="bid.html",
                format_name="HTML",
                extension="html",
                valid_pages=["page-1"],
            ),
            export=lambda _config, _request: export_calls.append(True)
            or ExportResultDto(success=True, format_name="HTML", page_count=1),
        )
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            export_service=service,
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: bid_ref,
                get_current_bid=lambda: bid,
                get_page=lambda uid: pages.get(uid),
            ),
        )

        def replace_page(_dialog_info):
            pages["page-1"] = Page(uid="page-1", name="Replacement")
            return "out.html"

        handler._show_save_dialog = replace_page
        with (
            patch.object(
                export_handler_module,
                "show_warning",
                side_effect=lambda _window, title, message: warnings.append(
                    (title, message)
                ),
            ),
            patch.object(export_handler_module, "show_info"),
        ):
            handler.export_format("html", ["page-1"])
        self.assertEqual(export_calls, [])
        self.assertEqual(warnings[0][0], "Export Cancelled")

    def test_general_export_snapshots_page_uid_request_before_save_dialog(self):
        bid = SimpleNamespace(name="Bid")
        bid_ref = BidRef("database-1", "bid-1")
        pages = {"page-1": Page(uid="page-1", name="Original")}
        selected_page_uids = ["page-1"]
        requests = []
        service = SimpleNamespace(
            get_export_dialog_info=lambda _pages, _format: SimpleNamespace(
                success=True,
                dialog_title="Export",
                default_filename="bid.html",
                format_name="HTML",
                extension="html",
                valid_pages=["page-1"],
            ),
            export=lambda _config, request: requests.append(request)
            or ExportResultDto(success=True, format_name="HTML", page_count=1),
        )
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            export_service=service,
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: bid_ref,
                get_current_bid=lambda: bid,
                get_page=lambda uid: pages.get(uid),
            ),
        )

        def mutate_selection(_dialog_info):
            selected_page_uids.append("page-from-new-selection")
            return "out.html"

        handler._show_save_dialog = mutate_selection
        with patch.object(export_handler_module, "show_info"):
            handler.export_format("html", selected_page_uids)
        self.assertEqual(requests[0].page_uids, ["page-1"])

    def test_summary_csv_export_uses_current_grouping_and_appends_extension(self):
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        bid = SimpleNamespace(name="Bid")
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
                project_data_service=SimpleNamespace(
                    get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                    get_current_bid=lambda: bid,
                ),
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
        bid = SimpleNamespace(name="Bid")
        original_get_save = export_handler_module.QtWidgets.QFileDialog.getSaveFileName
        original_show_warning = export_handler_module.show_warning
        export_handler_module.QtWidgets.QFileDialog.getSaveFileName = (
            lambda _window, _title, _default_filename, _filter: (
                r"C:\tmp\summary.csv",
                "",
            )
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
                project_data_service=SimpleNamespace(
                    get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                    get_current_bid=lambda: bid,
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

    def test_summary_csv_export_cancels_when_bid_changes_in_native_save_dialog(self):
        current_bid = [BidRef("database-1", "bid-1")]
        bid = SimpleNamespace(name="Bid")
        calls = []

        def choose_output(_window, _title, _default_filename, _filter):
            current_bid[0] = BidRef("database-1", "bid-2")
            return r"C:\tmp\summary.csv", ""

        handler = _make_export_handler(
            window=SimpleNamespace(
                get_summary_grouping=lambda: ConditionSummaryGrouping()
            ),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: current_bid[0],
                get_current_bid=lambda: bid,
            ),
            summary_csv_export_service=SimpleNamespace(
                default_filename=lambda: "Bid Summary.csv",
                export_current_summary=lambda _grouping, _filename: calls.append(True)
                or ExportResultDto(success=True, format_name="Summary CSV"),
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "show_warning"),
        ):
            handler.export_summary_csv()
        self.assertEqual(calls, [])
