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
from shiboken6 import delete, isValid


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


_CANCELLED_WARNING = (
    "Export Cancelled",
    "The selected bid or page changed while the save dialog was open. "
    "Please start the export again.",
)
_INVALID_SAVE_LOCATION = (
    "Invalid Save Location",
    "Cannot save over a selected base or overlay source file.\n"
    "Please choose a different filename or location.",
)


class _ForbiddenProjectData:
    def __getattr__(self, name):
        raise AssertionError(f"project data must not be read: {name}")


class _ImmediateProgressDialog:
    """Runs the worker eagerly; subclasses choose the dialog outcome."""

    outcome = export_handler_module.QtWidgets.QDialog.DialogCode.Accepted

    def __init__(self, _filename, run, parent=None, reporter=None):
        self.result = run()
        self.error = None

    def exec(self):
        return self.outcome

    def cleanup(self):
        pass

    def deleteLater(self):
        pass


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
        "config_model": SimpleNamespace(snapshot=lambda: Config()),
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
        self.assertFalse(isValid(window))
        self.assertEqual(critical_messages, [])

    def test_bid_file_export_reads_through_backend_neutral_reader(self):
        calls = []
        exported = []
        bid = SimpleNamespace(name="Bid")
        raw_data = RawBidData()
        database_reader = SimpleNamespace(
            get_raw_bid_data=lambda locator, bid_uid: calls.append((locator, bid_uid))
            or raw_data
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

        def make_export(raw, filename, bid_name, _reporter):
            return lambda: exported.append((raw, filename, bid_name)) or (
                SimpleNamespace(success=True)
            )

        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.ost", ""),
            ) as save_dialog,
            patch.object(
                export_handler_module, "ProgressDialog", _ImmediateProgressDialog
            ),
            patch.object(export_handler_module, "show_info") as info,
        ):
            handler._export_bid_file("OST", "ost", "Export", make_export)
        self.assertEqual(calls, [("sql-database-id", "42")])
        save_dialog.assert_called_once_with(
            None, "Export", "Bid.ost", "OST Files (*.ost);;All Files (*.*)"
        )
        self.assertEqual(len(exported), 1)
        self.assertIs(exported[0][0], raw_data)
        self.assertEqual(exported[0][1:], ("output.ost", "Bid"))
        info.assert_called_once_with(
            None, "Export Complete", "Successfully exported bid to output.ost"
        )

    def test_bid_file_export_reports_worker_failure_message_and_default(self):
        default_message = (
            "Failed to export OST file. Please ensure you have write "
            "permissions to the destination folder and try again."
        )
        bid = SimpleNamespace(name="Bid")
        for label, worker_result, expected in (
            (
                "worker message",
                ExportResultDto(
                    success=False, format_name="OST", error_message="disk is full"
                ),
                "disk is full",
            ),
            ("no result", None, default_message),
            (
                "failed without message",
                ExportResultDto(success=False, format_name="OST"),
                default_message,
            ),
        ):
            with self.subTest(label):
                handler = _make_export_handler(
                    project_data_service=SimpleNamespace(
                        get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
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
                        _ImmediateProgressDialog,
                    ),
                    patch.object(export_handler_module, "show_info") as info,
                    patch.object(export_handler_module, "show_critical") as critical,
                    patch.object(export_handler_module.logger, "error"),
                ):
                    handler._export_bid_file(
                        "OST",
                        "ost",
                        "Export",
                        lambda *_args, result=worker_result: lambda: result,
                    )
                info.assert_not_called()
                critical.assert_called_once_with(None, "Export Error", expected)

    def test_bid_file_export_does_not_report_success_when_dialog_is_rejected(self):
        class RejectedDialog(_ImmediateProgressDialog):
            outcome = export_handler_module.QtWidgets.QDialog.DialogCode.Rejected

        handler = _make_export_handler(
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
            patch.object(export_handler_module, "ProgressDialog", RejectedDialog),
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_critical") as critical,
            patch.object(export_handler_module.logger, "error"),
        ):
            handler._export_bid_file(
                "OST",
                "ost",
                "Export",
                lambda _raw, _filename, _name, _reporter: lambda: SimpleNamespace(
                    success=True, error_message=None
                ),
            )
        info.assert_not_called()
        critical.assert_called_once()
        self.assertEqual(critical.call_args.args[1], "Export Error")

    def test_bid_file_export_reports_unexpected_reader_failure(self):
        def broken_reader(_path, _uid):
            raise OSError("database vanished")

        handler = _make_export_handler(
            database_reader=SimpleNamespace(get_raw_bid_data=broken_reader),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.osp", ""),
            ),
            patch.object(
                export_handler_module,
                "ProgressDialog",
                side_effect=AssertionError("no progress without bid data"),
            ),
            patch.object(export_handler_module, "show_critical") as critical,
            self.assertLogs(export_handler_module.logger, level="ERROR"),
        ):
            handler._export_bid_file(
                "OSP",
                "osp",
                "Export",
                lambda *_args: self.fail("exporter must not be built"),
            )
        critical.assert_called_once_with(
            None,
            "Export Error",
            "An unexpected error occurred while exporting the OSP file. "
            "Please try again or choose a different destination.",
        )

    def test_bid_file_export_warns_without_bid_and_stops_on_cancelled_dialog(self):
        for label, bid_ref, bid in (
            ("no bid ref", None, SimpleNamespace(name="Bid")),
            ("no bid", BidRef("bid.mdb", "bid-1"), None),
        ):
            with self.subTest(label):
                handler = _make_export_handler(
                    project_data_service=SimpleNamespace(
                        get_current_bid_ref=lambda bid_ref=bid_ref: bid_ref,
                        get_current_bid=lambda bid=bid: bid,
                    ),
                )
                with (
                    patch.object(
                        export_handler_module.QtWidgets.QFileDialog,
                        "getSaveFileName",
                        side_effect=AssertionError("no dialog without a bid"),
                    ),
                    patch.object(export_handler_module, "show_warning") as warning,
                ):
                    handler._export_bid_file(
                        "OST", "ost", "Export", lambda *_args: self.fail("no export")
                    )
                warning.assert_called_once_with(
                    None,
                    "No Bid Selected",
                    "Please load a database and select a bid before exporting.",
                )
        handler = _make_export_handler(
            database_reader=SimpleNamespace(
                get_raw_bid_data=lambda *_args: self.fail("no read after cancel")
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("", ""),
            ),
            patch.object(export_handler_module, "show_warning") as warning,
        ):
            handler._export_bid_file(
                "OST", "ost", "Export", lambda *_args: self.fail("no export")
            )
        warning.assert_not_called()

    def test_pdf_export_stops_when_deferred_persistence_flush_fails(self):
        deferred = _FakeDeferredPersistence(result=False)
        handler = _make_export_handler(
            project_data_service=_ForbiddenProjectData(),
            deferred_persistence_manager=deferred,
        )
        with patch.object(
            export_handler_module.QtWidgets.QFileDialog,
            "getSaveFileName",
            side_effect=AssertionError("no save dialog after failed flush"),
        ):
            handler.export_as_pdf(["page-1"])
        self.assertEqual(deferred.flush_calls, 1)

    def test_osp_export_stops_when_deferred_persistence_flush_fails(self):
        deferred = _FakeDeferredPersistence(result=False)
        handler = _make_export_handler(
            project_data_service=_ForbiddenProjectData(),
            deferred_persistence_manager=deferred,
        )
        with patch.object(
            export_handler_module.QtWidgets.QFileDialog,
            "getSaveFileName",
            side_effect=AssertionError("no save dialog after failed flush"),
        ):
            handler.export_as_osp()
        self.assertEqual(deferred.flush_calls, 1)

    def test_every_export_entry_point_stops_when_deferred_flush_fails(self):
        entry_points = (
            ("ost", lambda handler: handler.export_as_ost()),
            ("format", lambda handler: handler.export_format("html", ["page-1"])),
            ("summary csv", lambda handler: handler.export_summary_csv()),
        )
        for label, run in entry_points:
            with self.subTest(label):
                deferred = _FakeDeferredPersistence(result=False)
                handler = _make_export_handler(
                    project_data_service=_ForbiddenProjectData(),
                    export_service=_ForbiddenProjectData(),
                    summary_csv_export_service=_ForbiddenProjectData(),
                    deferred_persistence_manager=deferred,
                )
                with patch.object(
                    export_handler_module.QtWidgets.QFileDialog,
                    "getSaveFileName",
                    side_effect=AssertionError("no save dialog after failed flush"),
                ):
                    run(handler)
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

    def test_pdf_save_dialog_title_and_filter_follow_page_count(self):
        for page_names, expected_title in (
            (["A1"], "Export Page as PDF"),
            (["A1", "A2", "A3"], "Export 3 Pages as PDF"),
        ):
            with self.subTest(page_names=page_names):
                handler = _make_export_handler(
                    project_data_service=_FakeProjectData(page_names)
                )
                with patch.object(
                    export_handler_module.QtWidgets.QFileDialog,
                    "getSaveFileName",
                    return_value=("", ""),
                ) as save_dialog:
                    handler.export_as_pdf(
                        [f"page-{index}" for index in range(1, len(page_names) + 1)]
                    )
                self.assertEqual(save_dialog.call_args.args[1], expected_title)
                self.assertEqual(
                    save_dialog.call_args.args[3],
                    "PDF Files (*.pdf);;All Files (*.*)",
                )

    def test_single_page_pdf_default_filename_falls_back_for_blank_page_name(self):
        filename = _capture_pdf_default_filename([""])
        self.assertEqual(filename, "25-051 Marriott Element, Capel Hill, NC - Page.pdf")

    def test_pdf_export_warns_when_no_selected_page_has_a_valid_size(self):
        project_data = _FakeProjectData(["A1", "A2"])
        for page in project_data._pages.values():
            page.width_pts = 0.0
        handler = _make_export_handler(project_data_service=project_data)
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=AssertionError("no save dialog without a valid page"),
            ),
            patch.object(export_handler_module, "show_warning") as warning,
        ):
            handler.export_as_pdf(["page-1", "page-2"])
        warning.assert_called_once_with(
            None, "No Valid Pages", "No valid pages selected for export."
        )

    def test_pdf_export_counts_only_valid_pages_and_reports_destination(self):
        project_data = _FakeProjectData(["A1", "A2", "Broken"])
        project_data._pages["page-3"].height_pts = 0.0
        exported_page_uids = []
        infos = []

        def export(pages_data, filename, *_args, **_kwargs):
            exported_page_uids.append([data.page.uid for data in pages_data])
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
                return_value=(r"C:\tmp\out.pdf", ""),
            ) as save_dialog,
            patch.object(
                export_handler_module, "ProgressDialog", _ImmediateProgressDialog
            ),
            patch.object(
                export_handler_module,
                "show_info",
                side_effect=lambda _window, title, message: infos.append(
                    (title, message)
                ),
            ),
        ):
            handler.export_as_pdf(["page-1", "page-2", "page-3"])
        self.assertEqual(
            save_dialog.call_args.args[1:3],
            (
                "Export 2 Pages as PDF",
                "25-051 Marriott Element, Capel Hill, NC - 2 Pages.pdf",
            ),
        )
        self.assertEqual(exported_page_uids, [["page-1", "page-2"]])
        self.assertEqual(
            infos,
            [("Export Complete", r"Successfully exported 2 pages to C:\tmp\out.pdf")],
        )

    def test_pdf_export_reports_exporter_failure_and_unexpected_errors(self):
        for label, export, expected in (
            (
                "reported failure",
                lambda *_args, **_kwargs: ExportResultDto(
                    success=False, format_name="PDF", error_message="Disk is full"
                ),
                "Disk is full",
            ),
            (
                "unexpected error",
                None,
                "An unexpected error occurred while exporting the PDF. "
                "Please try again or choose a different destination.",
            ),
        ):
            with self.subTest(label):
                project_data = _FakeProjectData(["A1"])
                if export is None:
                    project_data.get_all_annotations = lambda: (_ for _ in ()).throw(
                        RuntimeError("annotation snapshot failed")
                    )
                    export = lambda *_args, **_kwargs: self.fail("must not export")
                handler = _make_export_handler(
                    config_model=SimpleNamespace(snapshot=Config),
                    project_data_service=project_data,
                    pdf_exporter=SimpleNamespace(export=export),
                )
                with (
                    patch.object(
                        export_handler_module.QtWidgets.QFileDialog,
                        "getSaveFileName",
                        return_value=(r"C:\tmp\out.pdf", ""),
                    ),
                    patch.object(
                        export_handler_module,
                        "ProgressDialog",
                        _ImmediateProgressDialog,
                    ),
                    patch.object(export_handler_module, "show_info") as info,
                    patch.object(export_handler_module, "show_critical") as critical,
                    patch.object(export_handler_module.logger, "exception"),
                ):
                    handler.export_as_pdf(["page-1"])
                info.assert_not_called()
                critical.assert_called_once_with(None, "Export Error", expected)

    def test_pdf_export_uses_2d_display_mode(self):
        calls = []
        filenames = []
        infos = []
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
            filenames.append(filename)
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
        export_handler_module.show_info = lambda _window, title, message: infos.append(
            (title, message)
        )
        try:
            handler = _make_export_handler(
                config_model=SimpleNamespace(
                    snapshot=lambda: Config(
                        display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
                        grayscale_enabled=True,
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
        self.assertEqual(calls[0][:3], (Config.DISPLAY_MODE_TRANSPARENT, True, 1))
        self.assertEqual(filenames, [r"C:\tmp\out.pdf"])
        self.assertEqual(
            infos,
            [("Export Complete", r"Successfully exported page to C:\tmp\out.pdf")],
        )
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
        snapshot_is_detached = []
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
            # The handler swallows exceptions raised by the worker, so record the
            # identity facts here and assert them after the export returns.
            snapshot_is_detached.extend(
                page_data.page is not project_data._pages[page_data.page.uid]
                for page_data in pages_data
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
            patch.object(export_handler_module, "show_info") as info,
            patch.object(
                export_handler_module,
                "show_critical",
                side_effect=AssertionError("export must not fail"),
            ),
        ):
            for _transition in transitions:
                handler.export_as_pdf(selected_page_uids)
        self.assertEqual(captured_modes, list(transitions))
        self.assertEqual(snapshot_is_detached, [True] * 6)
        self.assertEqual(info.call_count, 3)
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
        self.assertEqual(warnings, [_CANCELLED_WARNING])

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
        self.assertEqual(warnings, [_CANCELLED_WARNING])

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
        self.assertEqual(warnings, [_CANCELLED_WARNING])

    def test_pdf_export_stops_if_window_closes_inside_native_save_dialog(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QDialog()
        project_data = _FakeProjectData(["Original Page"])
        exports = []
        handler = _make_export_handler(
            window=window,
            config_model=SimpleNamespace(snapshot=Config),
            project_data_service=project_data,
            pdf_exporter=SimpleNamespace(
                export=lambda *_args, **_kwargs: exports.append("export")
            ),
        )
        handler._build_pdf_export_snapshot = (
            lambda _page_uids: exports.append("snapshot") or []
        )

        def close_window_while_dialog_is_open(*_args):
            delete(window)
            return r"C:\tmp\out.pdf", ""

        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=close_window_while_dialog_is_open,
            ),
            patch.object(export_handler_module, "show_warning") as warning,
            patch.object(export_handler_module, "show_critical") as critical,
        ):
            handler.export_as_pdf(["page-1"])
        self.assertIsNotNone(app)
        self.assertFalse(isValid(window))
        self.assertEqual(exports, [])
        warning.assert_not_called()
        critical.assert_not_called()

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
        self.assertEqual(errors, [_INVALID_SAVE_LOCATION])

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
        self.assertEqual(
            export_handler_module._path_identity(unc_path),
            export_handler_module._path_identity(
                "\\\\?\\unc\\" + unc_path.removeprefix("\\\\")
            ),
        )
        self.assertEqual(
            export_handler_module._path_identity(local_path),
            export_handler_module._path_identity(local_path.upper()),
        )
        self.assertEqual(
            export_handler_module._path_identity(local_path), local_path.casefold()
        )
        self.assertNotEqual(
            export_handler_module._path_identity(local_path),
            export_handler_module._path_identity(r"C:\Projects\Bid; A\Sheet 02.pdf"),
        )
        self.assertNotEqual(
            export_handler_module._path_identity(local_path),
            export_handler_module._path_identity(
                "\\\\?\\" + r"D:\Projects\Bid; A\Sheet 01.pdf"
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
        self.assertEqual(errors, [_INVALID_SAVE_LOCATION])

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

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=snapshot),
            export_service=SimpleNamespace(export=export),
        )
        request = ExportRequestDto(["page-1"], "html", "out.html")
        with patch.object(export_handler_module, "show_info") as info:
            handler._execute_export(request)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(len(export_calls), 1)
        self.assertIs(export_calls[0][0], config)
        self.assertIs(export_calls[0][1], request)
        info.assert_called_once_with(
            None, "Export Complete", "Successfully exported 1 page(s) to out.html"
        )

    def test_general_export_reports_service_failure(self):
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            export_service=SimpleNamespace(
                export=lambda _config, _request: ExportResultDto(
                    success=False,
                    format_name="HTML",
                    error_message="template missing",
                )
            ),
        )
        with (
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_critical") as critical,
        ):
            handler._execute_export(ExportRequestDto(["page-1"], "html", "out.html"))
        info.assert_not_called()
        critical.assert_called_once_with(
            None, "Export Error", "Error creating HTML export: template missing"
        )

    def test_general_export_cancels_when_bid_changes_in_native_save_dialog(self):
        current_bid = [BidRef("database-1", "bid-1")]
        bid = SimpleNamespace(name="Bid")
        page = Page(uid="page-1", name="Page")
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
                get_current_bid_ref=lambda: current_bid[0],
                get_current_bid=lambda: bid,
                get_page=lambda _uid: page,
            ),
        )

        def switch_bid(_dialog_info):
            current_bid[0] = BidRef("database-1", "bid-2")
            return "out.html"

        handler._show_save_dialog = switch_bid
        with patch.object(
            export_handler_module,
            "show_warning",
            side_effect=lambda _window, title, message: warnings.append(
                (title, message)
            ),
        ):
            handler.export_format("html", ["page-1"])
        self.assertEqual(export_calls, [])
        self.assertEqual(warnings, [_CANCELLED_WARNING])

    def test_general_export_runs_service_for_unchanged_context(self):
        bid = SimpleNamespace(name="Bid")
        page = Page(uid="page-1", name="Page")
        requests = []
        dialog_calls = []
        service = SimpleNamespace(
            get_export_dialog_info=lambda pages, format_key: dialog_calls.append(
                (pages, format_key)
            )
            or SimpleNamespace(
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
                get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                get_current_bid=lambda: bid,
                get_page=lambda _uid: page,
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("out.html", ""),
            ) as save_dialog,
            patch.object(export_handler_module, "show_info") as info,
            patch.object(
                export_handler_module,
                "show_warning",
                side_effect=AssertionError("unchanged context must not warn"),
            ),
        ):
            handler.export_format("html", ["page-1"], active_page_uid="page-1")
        self.assertEqual(dialog_calls, [(["page-1"], "html")])
        save_dialog.assert_called_once_with(
            None, "Export", "bid.html", "HTML (*.html);;All files (*.*)"
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            (
                requests[0].page_uids,
                requests[0].format_key,
                requests[0].filename,
                requests[0].active_page_uid,
            ),
            (["page-1"], "html", "out.html", "page-1"),
        )
        info.assert_called_once_with(
            None, "Export Complete", "Successfully exported 1 page(s) to out.html"
        )

    def test_general_export_stops_for_empty_selection_cancelled_dialog_or_bad_prep(
        self,
    ):
        bid = SimpleNamespace(name="Bid")
        page = Page(uid="page-1", name="Page")
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
            get_current_bid=lambda: bid,
            get_page=lambda _uid: page,
        )

        def dialog_info(**overrides):
            values = dict(
                success=True,
                dialog_title="Export",
                default_filename="bid.html",
                format_name="HTML",
                extension="html",
                valid_pages=["page-1"],
                error=None,
                error_code=None,
            )
            values.update(overrides)
            return SimpleNamespace(**values)

        cases = (
            ("empty selection", [], dialog_info(), "", None),
            ("cancelled dialog", ["page-1"], dialog_info(), "", None),
            (
                "no data",
                ["page-1"],
                dialog_info(
                    success=False,
                    error=None,
                    error_code=ExportErrorCode.NO_DATA,
                ),
                "out.html",
                (
                    "warning",
                    "No Data",
                    "No takeoffs found for any of the selected pages.",
                ),
            ),
            (
                "preparation error",
                ["page-1"],
                dialog_info(
                    success=False,
                    error="Unknown format",
                    error_code=ExportErrorCode.UNKNOWN_FORMAT,
                ),
                "out.html",
                ("critical", "Export Error", "Unknown format"),
            ),
        )
        for label, page_uids, info, filename, expected_message in cases:
            with self.subTest(label):
                export_calls = []
                handler = _make_export_handler(
                    config_model=SimpleNamespace(snapshot=Config),
                    export_service=SimpleNamespace(
                        get_export_dialog_info=lambda _pages, _format, info=info: info,
                        export=lambda _config, _request: export_calls.append(True),
                    ),
                    project_data_service=project_data,
                )
                handler._show_save_dialog = lambda _info, filename=filename: (
                    filename or None
                )
                with (
                    patch.object(export_handler_module, "show_warning") as warning,
                    patch.object(export_handler_module, "show_critical") as critical,
                ):
                    handler.export_format("html", page_uids)
                self.assertEqual(export_calls, [])
                if expected_message is None:
                    warning.assert_not_called()
                    critical.assert_not_called()
                elif expected_message[0] == "warning":
                    warning.assert_called_once_with(None, *expected_message[1:])
                    critical.assert_not_called()
                else:
                    critical.assert_called_once_with(None, *expected_message[1:])
                    warning.assert_not_called()

    def test_general_export_warns_when_a_valid_page_vanishes_before_save_dialog(self):
        bid = SimpleNamespace(name="Bid")
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=Config),
            export_service=SimpleNamespace(
                get_export_dialog_info=lambda _pages, _format: SimpleNamespace(
                    success=True, valid_pages=["page-1", "page-2"]
                ),
                export=lambda _config, _request: self.fail("must not export"),
            ),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                get_current_bid=lambda: bid,
                get_page=lambda uid: (
                    Page(uid=uid, name=uid) if uid == "page-1" else None
                ),
            ),
        )
        handler._show_save_dialog = lambda _info: self.fail("no save dialog")
        with patch.object(export_handler_module, "show_warning") as warning:
            handler.export_format("html", ["page-1", "page-2"])
        warning.assert_called_once_with(
            None,
            "Export Cancelled",
            "A selected page changed before the save dialog opened. "
            "Please start the export again.",
        )

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
        self.assertEqual(warnings, [_CANCELLED_WARNING])

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
                export_current_summary=lambda used_grouping, filename, **_options: calls.append(
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
        self.assertEqual(
            infos,
            [
                (
                    "Export Complete",
                    r"Successfully exported Summary to C:\tmp\summary.csv",
                )
            ],
        )

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
                export_current_summary=lambda _grouping, _filename, **_options: ExportResultDto(
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
                export_current_summary=lambda _grouping, _filename, **_options: calls.append(
                    True
                )
                or ExportResultDto(success=True, format_name="Summary CSV"),
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                side_effect=choose_output,
            ),
            patch.object(export_handler_module, "show_warning") as warning,
            patch.object(export_handler_module, "show_info") as info,
        ):
            handler.export_summary_csv()
        self.assertEqual(calls, [])
        warning.assert_called_once_with(handler.window, *_CANCELLED_WARNING)
        info.assert_not_called()

    def test_summary_csv_export_normalizes_default_and_chosen_extension(self):
        for label, default_name, chosen, expected_default, expected_path in (
            (
                "missing both",
                "Bid Summary",
                r"C:\tmp\summary",
                "Bid Summary.csv",
                r"C:\tmp\summary.csv",
            ),
            (
                "uppercase kept",
                "Bid Summary.CSV",
                r"C:\tmp\SUMMARY.CSV",
                "Bid Summary.CSV",
                r"C:\tmp\SUMMARY.CSV",
            ),
        ):
            with self.subTest(label):
                calls = []
                bid = SimpleNamespace(name="Bid")
                handler = _make_export_handler(
                    window=SimpleNamespace(
                        get_summary_grouping=lambda: ConditionSummaryGrouping()
                    ),
                    project_data_service=SimpleNamespace(
                        get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                        get_current_bid=lambda bid=bid: bid,
                    ),
                    summary_csv_export_service=SimpleNamespace(
                        default_filename=lambda name=default_name: name,
                        export_current_summary=lambda _grouping, filename, **_options: calls.append(
                            filename
                        )
                        or ExportResultDto(success=True, format_name="Summary CSV"),
                    ),
                )
                with (
                    patch.object(
                        export_handler_module.QtWidgets.QFileDialog,
                        "getSaveFileName",
                        return_value=(chosen, ""),
                    ) as save_dialog,
                    patch.object(export_handler_module, "show_info"),
                ):
                    handler.export_summary_csv()
                self.assertEqual(save_dialog.call_args.args[2], expected_default)
                self.assertEqual(calls, [expected_path])

    def test_summary_csv_export_reports_failure_and_ignores_cancelled_dialog(self):
        bid = SimpleNamespace(name="Bid")

        def make_handler(result, calls):
            return _make_export_handler(
                window=SimpleNamespace(
                    get_summary_grouping=lambda: ConditionSummaryGrouping()
                ),
                project_data_service=SimpleNamespace(
                    get_current_bid_ref=lambda: BidRef("database-1", "bid-1"),
                    get_current_bid=lambda: bid,
                ),
                summary_csv_export_service=SimpleNamespace(
                    default_filename=lambda: "Bid Summary.csv",
                    export_current_summary=lambda _grouping, _filename, **_options: calls.append(
                        True
                    )
                    or result,
                ),
            )

        calls = []
        handler = make_handler(
            ExportResultDto(
                success=False,
                format_name="Summary CSV",
                error_message="file is locked",
                error_code=ExportErrorCode.WRITE_FAILED,
            ),
            calls,
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=(r"C:\tmp\summary.csv", ""),
            ),
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_warning") as warning,
            patch.object(export_handler_module, "show_critical") as critical,
        ):
            handler.export_summary_csv()
        self.assertEqual(calls, [True])
        info.assert_not_called()
        warning.assert_not_called()
        critical.assert_called_once_with(
            handler.window,
            "Export Error",
            "Error creating Summary CSV export: file is locked",
        )
        cancelled_calls = []
        cancelled = make_handler(
            ExportResultDto(success=True, format_name="Summary CSV"), cancelled_calls
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("", ""),
            ),
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_warning") as warning,
        ):
            cancelled.export_summary_csv()
        self.assertEqual(cancelled_calls, [])
        info.assert_not_called()
        warning.assert_not_called()


def _condition_rows():
    return [
        {"UID": "1", "Name": "Wall @T 5' 0\"", "Type": "0"},
        {"UID": "2", "Name": "Wall @B 2&apos; 0&quot;", "Type": "0"},
        {"UID": "3", "Name": "Plain", "Type": "0"},
    ]


def _raw_with(rows):
    return RawBidData(
        bid_row={"UID": "bid-1", "Name": "Bid"},
        bid_tables={"BidConditions": rows},
        page_tables={},
        global_tables={},
    )


class ConditionElevationOstOspExportTests(unittest.TestCase):
    def run_export(self, method, *, config, raw_data, locator="bid.mdb"):
        seen = []
        bid = SimpleNamespace(name="Bid")
        reader_calls = []
        database_reader = SimpleNamespace(
            get_raw_bid_data=lambda file_path, bid_uid: reader_calls.append(
                (file_path, bid_uid)
            )
            or raw_data
        )

        class _Exporter:
            def export(self_inner, raw, filename, *args, **kwargs):
                seen.append(raw)
                return SimpleNamespace(success=True)

        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=lambda: config),
            database_reader=database_reader,
            ost_exporter=_Exporter(),
            osp_exporter=_Exporter(),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: SimpleNamespace(
                    file_path=locator, bid_uid="bid-1"
                ),
                get_current_bid=lambda: bid,
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.file", ""),
            ),
            patch.object(
                export_handler_module, "ProgressDialog", _ImmediateProgressDialog
            ),
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_critical") as critical,
        ):
            getattr(handler, method)()
        critical.assert_not_called()
        return seen, info, reader_calls

    @staticmethod
    def names(raw):
        return [row.get("Name") for row in raw.bid_tables["BidConditions"]]

    def test_option_off_passes_the_exact_raw_data_through_for_ost_and_osp(self):
        for method in ("export_as_ost", "export_as_osp"):
            with self.subTest(method=method):
                raw = _raw_with(_condition_rows())
                seen, info, _calls = self.run_export(
                    method, config=Config(), raw_data=raw
                )
                self.assertEqual(len(seen), 1)
                self.assertIs(seen[0], raw)
                self.assertEqual(
                    info.call_args.args[2], "Successfully exported bid to output.file"
                )

    def test_option_on_exports_stripped_names_for_ost_and_osp(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        for method in ("export_as_ost", "export_as_osp"):
            with self.subTest(method=method):
                seen, _info, _calls = self.run_export(
                    method, config=config, raw_data=_raw_with(_condition_rows())
                )
                self.assertEqual(self.names(seen[0]), ["Wall", "Wall", "Plain"])
                self.assertEqual(
                    [row["UID"] for row in seen[0].bid_tables["BidConditions"]],
                    ["1", "2", "3"],
                )

    def test_the_raw_data_read_from_the_database_is_never_modified(self):
        raw = _raw_with(_condition_rows())
        config = Config(ost_osp_export_drop_condition_elevation=True)
        seen, _info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=raw
        )
        self.assertIsNot(seen[0], raw)
        self.assertEqual(raw.bid_tables["BidConditions"], _condition_rows())

    def test_the_csv_option_does_not_change_ost_or_osp_exports(self):
        config = Config(csv_export_drop_condition_elevation=True)
        raw = _raw_with(_condition_rows())
        seen, _info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=raw
        )
        self.assertIs(seen[0], raw)

    def test_access_and_sql_locators_produce_identical_exports(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        exported = {}
        for label, locator in (
            ("access", "C:/bids/one.mdb"),
            ("sql", "sql-database-id"),
        ):
            seen, _info, calls = self.run_export(
                "export_as_ost",
                config=config,
                raw_data=_raw_with(_condition_rows()),
                locator=locator,
            )
            self.assertEqual(calls, [(locator, "bid-1")])
            exported[label] = seen[0]
        self.assertEqual(exported["access"], exported["sql"])

    def test_colliding_names_stay_separate_and_are_reported_in_the_success_note(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(_condition_rows())
        )
        self.assertEqual(len(seen[0].bid_tables["BidConditions"]), 3)
        message = info.call_args.args[2]
        self.assertTrue(message.startswith("Successfully exported bid to output.file"))
        self.assertIn("1 condition name became identical", message)
        self.assertIn('"Wall" (2)', message)

    def test_no_note_is_added_without_collisions_or_with_the_option_off(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        distinct = _raw_with(
            [
                {"UID": "1", "Name": "A @T 5' 0\"", "Type": "0"},
                {"UID": "2", "Name": "B @T 5' 0\"", "Type": "0"},
            ]
        )
        _seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=distinct
        )
        self.assertEqual(
            info.call_args.args[2], "Successfully exported bid to output.file"
        )
        _seen, info, _calls = self.run_export(
            "export_as_ost", config=Config(), raw_data=_raw_with(_condition_rows())
        )
        self.assertEqual(
            info.call_args.args[2], "Successfully exported bid to output.file"
        )

    def test_the_collision_note_is_capped_at_three_names_plus_a_count(self):
        rows = []
        for index, name in enumerate(("A", "B", "C", "D", "E"), start=1):
            rows.append({"UID": f"{index}a", "Name": f"{name} @T 5' 0\"", "Type": "0"})
            rows.append({"UID": f"{index}b", "Name": f"{name} @B 2' 0\"", "Type": "0"})
        config = Config(ost_osp_export_drop_condition_elevation=True)
        _seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(rows)
        )
        message = info.call_args.args[2]
        self.assertIn("5 condition names became identical", message)
        for shown in ('"A" (2)', '"B" (2)', '"C" (2)'):
            self.assertIn(shown, message)
        for hidden in ('"D"', '"E"'):
            self.assertNotIn(hidden, message)
        self.assertIn("and 2 more", message)

    def test_names_with_newlines_tabs_and_quotes_keep_the_note_on_one_line(self):
        rows = [
            {"UID": "1", "Name": "A\nB @T 5' 0\"", "Type": "0"},
            {"UID": "2", "Name": "A\nB @B 2' 0\"", "Type": "0"},
            {"UID": "3", "Name": "C\tD @T 5' 0\"", "Type": "0"},
            {"UID": "4", "Name": "C\tD @B 2' 0\"", "Type": "0"},
            {"UID": "5", "Name": 'Say "hi" @T 5\' 0"', "Type": "0"},
            {"UID": "6", "Name": 'Say "hi" @B 2\' 0"', "Type": "0"},
        ]
        config = Config(ost_osp_export_drop_condition_elevation=True)
        seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(rows)
        )
        message = info.call_args.args[2]
        self.assertIn("3 condition names became identical", message)
        note = message.split("Note:", 1)[1]
        self.assertNotIn("\t", note)
        self.assertEqual(note.count("\n"), 0)
        for shown in ('"A B" (2)', '"C D" (2)', '"Say "hi"" (2)'):
            self.assertIn(shown, note)
        self.assertEqual(self.names(seen[0])[0], "A\nB")
        self.assertEqual(self.names(seen[0])[2], "C\tD")

    def test_three_way_collision_counts_every_condition_once(self):
        rows = [
            {"UID": "1", "Name": "Wall @T 5' 0\"", "Type": "0"},
            {"UID": "2", "Name": "Wall @B 2' 0\"", "Type": "0"},
            {"UID": "3", "Name": "Wall", "Type": "0"},
            {"UID": "4", "Name": "wall @T 1' 0\"", "Type": "0"},
            {"UID": "5", "Name": "Wall  @T 9' 0\"", "Type": "0"},
        ]
        config = Config(ost_osp_export_drop_condition_elevation=True)
        _seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(rows)
        )
        message = info.call_args.args[2]
        self.assertIn("1 condition name became identical", message)
        self.assertIn('"Wall" (4)', message)
        self.assertNotIn('"wall"', message)

    def test_a_collision_note_never_turns_a_successful_export_into_a_failure(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(_condition_rows())
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(info.call_count, 1)
        self.assertEqual(info.call_args.args[1], "Export Complete")
        self.assertIn("became identical", info.call_args.args[2])

    def test_condition_rows_without_a_name_do_not_break_the_export(self):
        rows = _condition_rows() + [{"UID": "9", "Type": "0"}]
        config = Config(ost_osp_export_drop_condition_elevation=True)
        seen, info, _calls = self.run_export(
            "export_as_ost", config=config, raw_data=_raw_with(rows)
        )
        self.assertEqual(self.names(seen[0]), ["Wall", "Wall", "Plain", None])
        self.assertIn("became identical", info.call_args.args[2])

    def test_a_failed_export_reports_the_failure_without_a_collision_note(self):
        config = Config(ost_osp_export_drop_condition_elevation=True)
        raw = _raw_with(_condition_rows())
        bid = SimpleNamespace(name="Bid")
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=lambda: config),
            database_reader=SimpleNamespace(get_raw_bid_data=lambda *_args: raw),
            ost_exporter=SimpleNamespace(
                export=lambda *_args, **_kwargs: ExportResultDto(
                    success=False, format_name="OST", error_message="disk is full"
                )
            ),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
                get_current_bid=lambda: bid,
            ),
        )
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("output.ost", ""),
            ),
            patch.object(
                export_handler_module, "ProgressDialog", _ImmediateProgressDialog
            ),
            patch.object(export_handler_module, "show_info") as info,
            patch.object(export_handler_module, "show_critical") as critical,
            patch.object(export_handler_module, "show_warning") as warning,
        ):
            handler.export_as_ost()
        info.assert_not_called()
        shown = [
            call.args[2] for call in critical.call_args_list + warning.call_args_list
        ]
        self.assertTrue(shown)
        self.assertTrue(all("became identical" not in text for text in shown))


class ConditionElevationSummaryCsvHandlerTests(unittest.TestCase):
    def run_export(self, *, config, result):
        calls = []
        bid = SimpleNamespace(name="Bid")
        handler = _make_export_handler(
            config_model=SimpleNamespace(snapshot=lambda: config),
            window=SimpleNamespace(
                get_summary_grouping=lambda: ConditionSummaryGrouping(by_type=True)
            ),
            summary_csv_export_service=SimpleNamespace(
                default_filename=lambda: "Bid Summary.csv",
                export_current_summary=lambda grouping, filename, **options: calls.append(
                    (grouping, filename, options)
                )
                or result,
            ),
            project_data_service=SimpleNamespace(
                get_current_bid_ref=lambda: BidRef("bid.mdb", "bid-1"),
                get_current_bid=lambda: bid,
            ),
        )
        handler._export_context_is_current = lambda *_args: True
        with (
            patch.object(
                export_handler_module.QtWidgets.QFileDialog,
                "getSaveFileName",
                return_value=("summary.csv", ""),
            ),
            patch.object(export_handler_module, "show_info") as info,
        ):
            handler.export_summary_csv()
        return calls, info

    def test_the_option_state_is_passed_to_the_service(self):
        result = ExportResultDto(True, page_count=1, format_name="Summary CSV")
        for flag in (False, True):
            with self.subTest(flag=flag):
                calls, _info = self.run_export(
                    config=Config(csv_export_drop_condition_elevation=flag),
                    result=result,
                )
                self.assertEqual(len(calls), 1)
                self.assertIs(calls[0][2]["strip_condition_elevations"], flag)

    def test_the_ost_option_does_not_reach_the_csv_service(self):
        result = ExportResultDto(True, page_count=1, format_name="Summary CSV")
        calls, _info = self.run_export(
            config=Config(ost_osp_export_drop_condition_elevation=True), result=result
        )
        self.assertIs(calls[0][2]["strip_condition_elevations"], False)

    def test_collisions_from_the_service_are_added_to_the_success_message(self):
        result = ExportResultDto(
            True,
            page_count=1,
            format_name="Summary CSV",
            elevation_name_collisions=(("Wall", 2), ("Slab", 3)),
        )
        _calls, info = self.run_export(
            config=Config(csv_export_drop_condition_elevation=True), result=result
        )
        message = info.call_args.args[2]
        self.assertTrue(
            message.startswith("Successfully exported Summary to summary.csv")
        )
        self.assertIn("2 condition names became identical", message)
        self.assertIn('"Wall" (2)', message)
        self.assertIn('"Slab" (3)', message)

    def test_the_message_is_unchanged_without_collisions(self):
        result = ExportResultDto(True, page_count=1, format_name="Summary CSV")
        _calls, info = self.run_export(
            config=Config(csv_export_drop_condition_elevation=True), result=result
        )
        self.assertEqual(
            info.call_args.args[2], "Successfully exported Summary to summary.csv"
        )
