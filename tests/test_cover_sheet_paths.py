import os
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from copy import deepcopy
from pathlib import Path
from unittest import mock
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    DatabaseMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
    TAKEOFF_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.dialogs.cover_sheet.pdf_metadata_loader import (
    PdfMetadataSnapshot,
)
from ost_visualizer.presentation.dtos.picker_dialog_result_dto import (
    PickerDialogResult,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.utils.overlay_context_menu import (
    add_overlay_submenu_with_select,
)
from tests.workspace_state_test_support import (
    make_workspace_state_model,
    with_workspace_state,
)

CoverSheetDialog = with_workspace_state(CoverSheetDialog)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _FakeSchema:
    def column_exists(self, table, column):
        return (
            (
                table == "Bids"
                and column in {"MeasureBase", "JobStatusUID", "EstimatorUID"}
            )
            or (
                table == "BidAreas"
                and column in {"UID", "BidUID", "ParentUID", "Name", "Sequence", "GUID"}
            )
            or (
                table == "BidPageFolders"
                and column in {"UID", "BidUID", "ParentUID", "Name"}
            )
        )

    def require_column(self, table, column):
        if not self.column_exists(table, column):
            raise RuntimeError(f"Missing {table}.{column}")

    def optional_table_missing(self, _table):
        return False


class _FakeCursor:
    def __init__(self):
        self.connection = object()
        self.last_query = None
        self.calls = []
        self.current_overlay_path = ""
        self.last_args = ()

    def execute(self, query, *args):
        self.last_query = query
        self.last_args = args
        self.calls.append((query, args))
        return None

    def fetchall(self):
        if self.last_query and self.last_query.startswith(
            "SELECT [UID], [BidUID] FROM [BidPages]"
        ):
            return [(value, 7) for value in self.last_args]
        if self.last_query and "FROM [BidAreas] WHERE [BidUID]" in self.last_query:
            return [(5, None)]
        if (
            self.last_query
            and "FROM [BidPageFolders] WHERE [BidUID]" in self.last_query
        ):
            return [(5, None)]
        if self.last_query and "SELECT [UID] FROM [BidComments]" in self.last_query:
            return []
        if self.last_query and "SELECT [UID] FROM [BidTakeoffs]" in self.last_query:
            return []
        return [(value,) for value in self.last_args]

    def fetchone(self):
        if self.last_query and "SELECT [BidUID] FROM [BidPages]" in self.last_query:
            return [7]
        if self.last_query and "SELECT [OverlayImagePath]" in self.last_query:
            return [self.current_overlay_path]
        if (
            self.last_query
            and "SELECT [ScaleFactor1], [ScaleFactor2]" in self.last_query
        ):
            return [0.125, 12.0]
        return [0]


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.enter_count = 0
        self.exit_count = 0
        self.exit_args = []

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_count += 1
        self.exit_args.append((exc_type, exc_value, traceback))
        return False

    def cursor(self):
        return self.cursor_obj


class _CoverSheetSettingsOps(
    AccessBulkWriteMixin,
    SettingsOperationsMixin,
    PageOperationsMixin,
):
    def __init__(self):
        self.conn = _FakeConnection()
        self.schema = _FakeSchema()
        self.updates = []
        self.inserts = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

    def _require_write_columns(self, *_args):
        pass

    def _next_uid(self, _cursor, _table):
        return 99

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _execute_update_values(
        self,
        _cursor,
        _schema,
        table,
        values,
        _required_columns,
        _where_clause,
        _where_values,
        _operation,
    ):
        self.updates.append(
            {
                "table": table,
                "values": dict(values),
            }
        )
        return True

    def _execute_insert_values(
        self,
        _cursor,
        _schema,
        table,
        values,
        _required_columns,
        _operation,
    ):
        self.inserts.append(
            {
                "table": table,
                "values": dict(values),
            }
        )
        return True


class _ScaleCursor(_FakeCursor):
    def __init__(self, old_sf1, old_sf2):
        super().__init__()
        self.old_sf1 = old_sf1
        self.old_sf2 = old_sf2

    def fetchone(self):
        if (
            self.last_query
            and "SELECT [ScaleFactor1], [ScaleFactor2]" in self.last_query
        ):
            return [self.old_sf1, self.old_sf2]
        return super().fetchone()


class _ScaleConnection(_FakeConnection):
    def __init__(self, old_sf1, old_sf2):
        super().__init__()
        self.cursor_obj = _ScaleCursor(old_sf1, old_sf2)


class _ScaleCoverSheetOps(_CoverSheetSettingsOps):
    def __init__(self, old_sf1, old_sf2):
        super().__init__()
        self.conn = _ScaleConnection(old_sf1, old_sf2)
        self.rescale_calls = []
        self.overlay_rescale_calls = []

    def _rescale_page_positions(self, _cursor, _schema, page_uid, factor):
        self.rescale_calls.append((page_uid, factor))

    def _rescale_page_overlay_rect(self, _cursor, _schema, page_uid, factor):
        self.overlay_rescale_calls.append((page_uid, factor))


class _PageScaleOps(PageOperationsMixin):
    def __init__(self, old_sf1, old_sf2):
        self.conn = _ScaleConnection(old_sf1, old_sf2)
        self.schema = _FakeSchema()
        self.rescale_calls = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

    def _require_write_columns(self, *_args):
        pass

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _rescale_page_positions(self, _cursor, _schema, page_uid, factor):
        self.rescale_calls.append((page_uid, factor))


class _FailingPositionScaleOps(_PageScaleOps):
    def _rescale_page_positions(self, _cursor, _schema, _page_uid, _factor):
        raise pyodbc.Error("position update failed")


class _FakeLogger:
    def exception(self, *_args):
        pass

    def warning(self, *_args):
        pass


class _AllDeleteColumnsSchema:
    def column_exists(self, _table, _column):
        return True

    def optional_table_missing(self, _table):
        return False


class _BulkDeleteCoverSheetOps(_CoverSheetSettingsOps):
    def __init__(self):
        super().__init__()
        self.schema = _AllDeleteColumnsSchema()


class _OverlayRectCursor(_FakeCursor):
    def __init__(
        self,
        current_overlay_path="",
        scale_factor1=0.125,
        scale_factor2=12.0,
        overlay_rect="-1.103146,0.000000,2686.161423,1919.474692",
        page_exists=True,
        original_image_path=r"C:\Plans\original.pdf",
    ):
        super().__init__()
        self.current_overlay_path = current_overlay_path
        self.scale_factor1 = scale_factor1
        self.scale_factor2 = scale_factor2
        self.overlay_rect = overlay_rect
        self.page_exists = page_exists
        self.original_image_path = original_image_path

    def fetchone(self):
        if (
            self.last_query
            and "SELECT [Width], [Height], [ScaleFactor1], [ScaleFactor2], "
            in self.last_query
        ):
            return SimpleNamespace(
                Width=42.0,
                Height=30.0,
                ScaleFactor1=self.scale_factor1,
                ScaleFactor2=self.scale_factor2,
                OverlayImagePath=self.current_overlay_path,
                ImagePath=self.original_image_path,
            )
        if (
            self.last_query
            and "SELECT [ScaleFactor1], [ScaleFactor2]" in self.last_query
        ):
            if not self.page_exists:
                return None
            return [self.scale_factor1, self.scale_factor2]
        if self.last_query and "SELECT [OverlayRect]" in self.last_query:
            return [self.overlay_rect]
        return super().fetchone()


class _OverlayRectConnection(_FakeConnection):
    def __init__(self, **cursor_options):
        super().__init__()
        self.cursor_obj = _OverlayRectCursor(**cursor_options)


class _PageOverlayOps(PageOperationsMixin):
    def __init__(self, current_overlay_path="", **cursor_options):
        self.conn = _OverlayRectConnection(
            current_overlay_path=current_overlay_path,
            **cursor_options,
        )
        self.schema = _FakeSchema()
        self.updates = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _execute_update_values(
        self,
        _cursor,
        _schema,
        table,
        values,
        _required_columns,
        _where_clause,
        _where_values,
        _operation,
        allow_empty=False,
    ):
        self.updates.append(
            {
                "table": table,
                "values": dict(values),
                "allow_empty": allow_empty,
            }
        )
        return True


class _OverlayScaleSchema:
    @staticmethod
    def column_exists(table, column):
        return table == "BidPages" and column in (
            "OverlayRect",
            "OverlayOffsetX",
            "OverlayOffsetY",
        )


class _OverlayScaleOps(PageOperationsMixin):
    def __init__(self, overlay_rect="-1.103146,0.000000,2686.161423,1919.474692"):
        self.conn = _OverlayRectConnection(
            scale_factor1=0.1875,
            overlay_rect=overlay_rect,
        )
        self.schema = _OverlayScaleSchema()
        self.updates = []
        self.position_rescales = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

    @staticmethod
    def _require_write_columns(*_args):
        pass

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _rescale_page_positions(self, _cursor, _schema, page_uid, factor):
        self.position_rescales.append((page_uid, factor))

    def _execute_update_values(
        self,
        _cursor,
        _schema,
        table,
        values,
        _required_columns,
        _where_clause,
        _where_values,
        operation,
    ):
        self.updates.append((table, dict(values), operation))
        return True


class _FakeIconProvider:
    def set_window_icon(self, _window):
        pass


class _FakeCoverSheetDialog:
    instance = None

    def __init__(
        self,
        icon_provider,
        parent,
        cover_sheet_data,
        workspace_state_model,
        used_employee_uids=None,
        has_license=True,
        context=None,
        save_job_statuses_fn=None,
        save_job_statuses_async_fn=None,
        reload_job_statuses_fn=None,
        save_employees_fn=None,
        save_employees_async_fn=None,
        save_pay_classes_fn=None,
        save_pay_classes_async_fn=None,
        reload_employees_fn=None,
        save_bid_areas_fn=None,
        save_bid_areas_async_fn=None,
        reload_bid_areas_fn=None,
        refresh_fn=None,
        save_cover_sheet_async_fn=None,
        get_used_area_uids_fn=None,
        pdf_page_sizes_fn=None,
        bid_ref=None,
        create_mode=False,
        pages_with_takeoffs=None,
        pages_requiring_delete_confirmation=None,
        pdf_metadata_pool=None,
    ):
        self.deleted = False
        self.save_async = save_cover_sheet_async_fn
        self.async_save_functions = {
            "save_job_statuses_async_fn": save_job_statuses_async_fn,
            "save_employees_async_fn": save_employees_async_fn,
            "save_pay_classes_async_fn": save_pay_classes_async_fn,
            "save_bid_areas_async_fn": save_bid_areas_async_fn,
            "save_cover_sheet_async_fn": save_cover_sheet_async_fn,
        }
        type(self).instance = self

    def deleteLater(self):
        self.deleted = True


class _FakeMouseEvent:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True


class _FakeWorkspaceStateModel:
    def __init__(self, state=None):
        self._state = deepcopy(state or WorkspaceState())
        self.update_count = 0

    @property
    def state(self):
        return deepcopy(self._state)

    def update_state(self, state):
        self.update_count += 1
        self._state = deepcopy(state)


def _cover_sheet_data(
    *,
    image_path="",
    overlay_image_path="",
    scale_factor1=0.125,
    scale_factor2=12.0,
    page_index=1,
    multi_page_count=0,
    show_mode=0,
):
    return CoverSheetData(
        bid_uid="7",
        job_status_uid="",
        job_name="Project",
        estimator_uid="",
        notes="",
        bid_date="2026 01 01 08 00 00",
        bid_no="1",
        job_id="",
        pages_without_folder=[
            CoverSheetPage(
                uid="p1",
                sheet_no="A101",
                name="Level 1",
                width=42.0,
                height=30.0,
                scale_factor1=scale_factor1,
                scale_factor2=scale_factor2,
                image_path=image_path,
                overlay_image_path=overlay_image_path,
                index=page_index,
                show_mode=show_mode,
                multi_page_count=multi_page_count,
            )
        ],
    )


def _cover_sheet_data_with_pages(count=3):
    data = _cover_sheet_data()
    template = data.pages_without_folder[0]
    data.pages_without_folder = []
    for index in range(1, count + 1):
        page = deepcopy(template)
        page.uid = f"p{index}"
        page.sheet_no = f"A10{index}"
        page.name = f"Page {index}"
        data.pages_without_folder.append(page)
    return data


class _ManualRunnablePool:
    def __init__(self):
        self.runnables = []

    def start(self, runnable):
        self.runnables.append(runnable)

    def run_next(self, *, process_events=True):
        runnable = self.runnables.pop(0)
        runnable.run()
        if process_events:
            QtWidgets.QApplication.processEvents()


def _path_editor(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChild(QtWidgets.QLineEdit)


def _path_buttons(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChildren(QtWidgets.QPushButton)


def _index_combo(dialog, item):
    return _combo_editor(dialog, item, 6)


def _combo_editor(dialog, item, column):
    model_index = dialog.plan_tree.indexFromItem(item, column)
    delegate = dialog.plan_tree.itemDelegateForColumn(column)
    option = QtWidgets.QStyleOptionViewItem()
    editor = delegate.createEditor(dialog.plan_tree.viewport(), option, model_index)
    deadline = time.monotonic() + 2.0
    page_data = item.data(0, dialog._ITEM_ROLE) or ()
    page_uid = str(page_data[1]) if len(page_data) > 1 else ""
    while (
        editor is None
        and column == 6
        and page_uid in dialog._page_rows
        and dialog._page_rows[page_uid].pending_metadata_request is not None
        and time.monotonic() < deadline
    ):
        QtWidgets.QApplication.processEvents()
        time.sleep(0.005)
        editor = delegate.createEditor(
            dialog.plan_tree.viewport(),
            option,
            model_index,
        )
    if editor is not None:
        delegate.setEditorData(editor, model_index)
    return editor


def _select_combo(dialog, item, column, combo_index):
    combo = _combo_editor(dialog, item, column)
    if combo is None:
        raise AssertionError("Expected an editable Cover Sheet combo")
    combo.setCurrentIndex(combo_index)
    model_index = dialog.plan_tree.indexFromItem(item, column)
    dialog.plan_tree.itemDelegateForColumn(column).setModelData(
        combo,
        dialog.plan_tree.model(),
        model_index,
    )
    return combo


def _first_page_update(dialog):
    return dialog.get_updates()["pages"][0]


def _top_level_labels(dialog):
    return [
        dialog.plan_tree.topLevelItem(index).text(0)
        for index in range(dialog.plan_tree.topLevelItemCount())
    ]


def _child_labels(item):
    return [item.child(index).text(0) for index in range(item.childCount())]


def _cover_sheet_page_update(
    *,
    uid="11",
    scale_factor1=0.125,
    scale_factor2=12.0,
    sheet_no="S-100",
    name="Level 1",
    image_path="",
    overlay_path="",
):
    return {
        "uid": uid,
        "width": 42.0,
        "height": 30.0,
        "scale_factor1": scale_factor1,
        "scale_factor2": scale_factor2,
        "show_mode": 0,
        "sheet_no": sheet_no,
        "index": 1,
        "sequence": 1,
        "multi_page_count": 0,
        "name": name,
        "image_path": image_path,
        "overlay_path": overlay_path,
    }


class CoverSheetPathSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def test_empty_pay_class_changes_report_success(self):
        operations = _CoverSheetSettingsOps()
        result = operations.save_pay_classes(
            "test.mdb",
            {"new": [], "updated": [], "deleted_uids": []},
        )
        self.assertEqual(result, {})

    def test_cover_sheet_normalizes_nullable_access_column_values(self):
        operations = _CoverSheetSettingsOps()
        self.assertTrue(
            operations.save_cover_sheet(
                "test.mdb",
                "7",
                {
                    "job_status_uid": "",
                    "job_name": "Bid",
                    "estimator_uid": None,
                    "bid_date": "",
                    "bid_no": "42",
                    "measure_base": 0,
                },
            )
        )
        bid_values = next(
            update["values"]
            for update in operations.updates
            if update["table"] == "Bids"
        )
        self.assertIsNone(bid_values["JobStatusUID"])
        self.assertIsNone(bid_values["EstimatorUID"])
        self.assertIsNone(bid_values["BidDate"])
        self.assertEqual(bid_values["BidNo"], 42)

    def test_cover_sheet_rejects_silent_noninteger_identifier_coercion(self):
        for invalid_value in (True, 7.5):
            with self.subTest(value=invalid_value):
                operations = _CoverSheetSettingsOps()
                self.assertFalse(
                    operations.save_cover_sheet(
                        "test.mdb",
                        "7",
                        {
                            "job_status_uid": invalid_value,
                            "job_name": "Bid",
                            "measure_base": 0,
                        },
                    )
                )
                self.assertEqual(operations.updates, [])

    def test_job_status_update_uses_none_instead_of_textual_null_sentinel(self):
        operations = _CoverSheetSettingsOps()
        self.assertTrue(operations.update_bid_job_status("test.mdb", "7", None))
        self.assertIsNone(operations.updates[-1]["values"]["JobStatusUID"])
        operations = _CoverSheetSettingsOps()
        self.assertFalse(operations.update_bid_job_status("test.mdb", "7", "NULL"))
        self.assertEqual(operations.updates, [])

    def test_new_master_data_returns_authoritative_uid_maps(self):
        operations = _CoverSheetSettingsOps()
        job_statuses = operations.save_job_statuses(
            "test.mdb",
            {
                "new": [{"uid": "new_status", "name": "Open"}],
                "updated": [],
                "deleted_uids": [],
            },
        )
        pay_classes = operations.save_pay_classes(
            "test.mdb",
            {
                "new": [{"uid": "new_pay", "name": "Field"}],
                "updated": [],
                "deleted_uids": [],
            },
        )
        self.assertEqual(job_statuses, {"new_status": "99"})
        self.assertEqual(pay_classes, {"new_pay": "99"})

    def test_existing_bid_area_can_move_under_new_area(self):
        operations = _CoverSheetSettingsOps()
        result = operations.save_bid_areas(
            "test.mdb",
            "7",
            BidAreaChangeset(
                new=[
                    BidArea(
                        uid="new_0",
                        bid_uid="7",
                        parent_uid="",
                        name="New Parent",
                        sequence=1,
                    )
                ],
                updated=[
                    BidArea(
                        uid="5",
                        bid_uid="7",
                        parent_uid="new_0",
                        name="Existing Child",
                        sequence=1,
                    )
                ],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {"new_0": "99"})
        area_update = next(
            update for update in operations.updates if update["table"] == "BidAreas"
        )
        self.assertEqual(area_update["values"]["ParentUID"], 99)

    def test_cover_sheet_plan_header_uses_default_layout_without_saved_state(self):
        dialog = CoverSheetDialog(_FakeIconProvider(), None, _cover_sheet_data())
        try:
            header = dialog.plan_tree.header()
            self.assertEqual(header.sectionSize(0), 140)
            self.assertEqual(header.sectionSize(2), 120)
            self.assertEqual(header.sectionSize(6), 45)
            self.assertEqual(header.visualIndex(0), 0)
        finally:
            dialog.deleteLater()

    def test_cover_sheet_pdf_index_combo_lists_every_page_and_preserves_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            page_sizes = [
                (24.0, 36.0, "11 TRAFFIC CONTROL DETAILS"),
                (30.0, 42.0, "Floor Plan"),
                (36.0, 48.0, ""),
            ]
            data = _cover_sheet_data(image_path=pdf_path, page_index=2)
            data.pages_without_folder[0].width = 30.0
            data.pages_without_folder[0].height = 42.0
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda _path: page_sizes,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                combo = _index_combo(dialog, item)
                self.assertIsInstance(combo, QtWidgets.QComboBox)
                self.assertEqual(
                    [combo.itemText(index) for index in range(combo.count())],
                    ["1", "2", "3"],
                )
                self.assertEqual(
                    [
                        combo.itemData(index, QtCore.Qt.ItemDataRole.ToolTipRole)
                        for index in range(combo.count())
                    ],
                    ["11 TRAFFIC CONTROL DETAILS", "Floor Plan", None],
                )
                self.assertEqual(combo.currentData(), (2, 30.0, 42.0))
                self.assertEqual(item.text(6), "2")
                self.assertEqual(_first_page_update(dialog)["index"], 2)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_pdf_index_change_updates_page_index_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [
                    (24.0, 36.0, "Cover"),
                    (30.0, 42.0, "Floor Plan"),
                    (35.0, 47.0, "Details"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                combo = _select_combo(dialog, item, 6, 2)
                QtWidgets.QApplication.processEvents()
                page = _first_page_update(dialog)
                self.assertEqual(page["index"], 3)
                self.assertEqual(page["width"], 35.0)
                self.assertEqual(page["height"], 47.0)
                self.assertEqual(item.text(6), "3")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_startup_virtualizes_combo_columns_without_pdf_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "shared.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            for page_count in (10, 100, 500, 1000):
                data = _cover_sheet_data(
                    image_path=pdf_path,
                    multi_page_count=1,
                )
                template = data.pages_without_folder[0]
                data.pages_without_folder = []
                for index in range(page_count):
                    page = deepcopy(template)
                    page.uid = f"p{index}"
                    page.sheet_no = str(index + 1)
                    data.pages_without_folder.append(page)
                workspace = _FakeWorkspaceStateModel()
                dialog = CoverSheetDialog(
                    _FakeIconProvider(),
                    None,
                    data,
                    pdf_page_sizes_fn=lambda _path: self.fail(
                        "Dialog startup must not read PDF metadata"
                    ),
                    workspace_state_model=workspace,
                )
                try:
                    self.assertLessEqual(
                        len(dialog.findChildren(QtWidgets.QComboBox)),
                        10,
                    )
                    for row in (0, page_count - 1):
                        item = dialog.plan_tree.topLevelItem(row)
                        for column in (2, 3, 6, 7):
                            self.assertIsNone(dialog.plan_tree.itemWidget(item, column))
                    self.assertEqual(
                        len(dialog.get_updates()["pages"]),
                        page_count,
                    )
                    self.assertEqual(workspace.update_count, 0)
                finally:
                    dialog.close()
                    dialog.deleteLater()
                    QtWidgets.QApplication.processEvents()

    def test_cover_sheet_index_metadata_loads_on_demand_without_changing_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            calls = []
            workspace = _FakeWorkspaceStateModel()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(
                    image_path=pdf_path,
                    page_index=1,
                    multi_page_count=2,
                ),
                pdf_page_sizes_fn=lambda path: calls.append(path)
                or [
                    (24.0, 36.0, "Cover"),
                    (30.0, 42.0, "Plan"),
                ],
                pdf_metadata_pool=pool,
                workspace_state_model=workspace,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                editor = delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    model_index,
                )
                self.assertIsNone(editor)
                self.assertEqual(calls, [])
                self.assertEqual(len(pool.runnables), 1)
                pool.run_next()
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(workspace.update_count, 0)
                self.assertEqual(_first_page_update(dialog)["width"], 42.0)
                self.assertEqual(_first_page_update(dialog)["height"], 30.0)
                editor = delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    model_index,
                )
                self.assertIsInstance(editor, QtWidgets.QComboBox)
                delegate.setEditorData(editor, model_index)
                self.assertEqual(editor.count(), 2)
                self.assertEqual(
                    [
                        editor.itemData(
                            index,
                            QtCore.Qt.ItemDataRole.ToolTipRole,
                        )
                        for index in range(editor.count())
                    ],
                    ["Cover", "Plan"],
                )
                editor.setCurrentIndex(1)
                delegate.setModelData(
                    editor,
                    dialog.plan_tree.model(),
                    model_index,
                )
                page = _first_page_update(dialog)
                self.assertEqual(page["index"], 2)
                self.assertEqual((page["width"], page["height"]), (30.0, 42.0))
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_single_click_starts_one_metadata_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(42.0, 30.0, "Page 1")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                dialog.plan_tree.setCurrentItem(item, 6)
                dialog.plan_tree.clicked.emit(model_index)
                self.assertEqual(len(pool.runnables), 1)
                dialog.plan_tree.clicked.emit(model_index)
                self.assertEqual(len(pool.runnables), 1)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_locked_and_unlicensed_rows_do_not_request_pdf_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "restricted.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            for has_license, lock_dialog in ((True, True), (False, False)):
                pool = _ManualRunnablePool()
                dialog = CoverSheetDialog(
                    _FakeIconProvider(),
                    None,
                    _cover_sheet_data(image_path=pdf_path),
                    has_license=has_license,
                    pdf_page_sizes_fn=lambda _path: [(42.0, 30.0, "Page 1")],
                    pdf_metadata_pool=pool,
                )
                try:
                    if lock_dialog:
                        dialog._update_lock_state(True)
                    item = dialog.plan_tree.topLevelItem(0)
                    index = dialog.plan_tree.indexFromItem(item, 6)
                    dialog._on_plan_cell_clicked(index)
                    self.assertEqual(pool.runnables, [])
                    delegate = dialog.plan_tree.itemDelegateForColumn(6)
                    self.assertIsNone(
                        delegate.createEditor(
                            dialog.plan_tree.viewport(),
                            QtWidgets.QStyleOptionViewItem(),
                            index,
                        )
                    )
                finally:
                    dialog.reject()
                    dialog.deleteLater()

    def test_cover_sheet_worker_start_failure_leaves_index_editable(self):
        class FailingPool:
            @staticmethod
            def start(_runnable):
                raise RuntimeError("pool is shutting down")

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            calls = []
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
                pdf_metadata_pool=FailingPool(),
            )
            try:
                combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(0))
                self.assertIsInstance(combo, QtWidgets.QComboBox)
                self.assertEqual(combo.currentData()[0], 1)
                self.assertEqual(calls, [])
                self.assertIsNone(dialog._page_rows["p1"].pending_metadata_request)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_uses_explicit_falsey_metadata_pool(self):
        class FalseyPool(_ManualRunnablePool):
            @staticmethod
            def __bool__():
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = FalseyPool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(42.0, 30.0, "Page 1")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                dialog.plan_tree.clicked.emit(dialog.plan_tree.indexFromItem(item, 6))
                self.assertEqual(len(pool.runnables), 1)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_path_changes_update_page_size_editability(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            size_delegate = dialog.plan_tree.itemDelegateForColumn(2)
            size_index = dialog.plan_tree.indexFromItem(item, 2)
            self.assertIsInstance(
                size_delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    size_index,
                ),
                QtWidgets.QComboBox,
            )
            overlay_editor = _path_editor(dialog, item, 5)
            overlay_editor.begin_path_edit()
            overlay_editor.setText("missing-overlay.pdf")
            overlay_editor.editingFinished.emit()
            self.assertIsNone(
                size_delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    size_index,
                )
            )
            _path_buttons(dialog, item, 5)[-1].click()
            self.assertIsInstance(
                size_delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    size_index,
                ),
                QtWidgets.QComboBox,
            )
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_cover_sheet_initialization_blocks_user_change_handlers(self):
        class InstrumentedDialog(CoverSheetDialog):
            def __init__(self, *args, **kwargs):
                self.change_counts = {
                    "measure": 0,
                    "scale_style": 0,
                    "job_status": 0,
                }
                super().__init__(*args, **kwargs)

            def _on_measure_base_changed(self, inches_checked):
                self.change_counts["measure"] += 1
                super()._on_measure_base_changed(inches_checked)

            def _on_pref_scale_style_changed(self):
                self.change_counts["scale_style"] += 1
                super()._on_pref_scale_style_changed()

            def _on_job_status_changed(self):
                self.change_counts["job_status"] += 1
                super()._on_job_status_changed()

        dialog = InstrumentedDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
        )
        try:
            self.assertEqual(
                dialog.change_counts,
                {
                    "measure": 0,
                    "scale_style": 0,
                    "job_status": 1,
                },
            )
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_preference_scale_population_preserves_existing_signal_block(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
        )
        try:
            dialog.combo_pref_scale.blockSignals(True)
            dialog._populate_pref_scale_combo(1)
            self.assertTrue(dialog.combo_pref_scale.signalsBlocked())
        finally:
            dialog.combo_pref_scale.blockSignals(False)
            dialog.reject()
            dialog.deleteLater()

    def test_combo_item_replacement_preserves_existing_signal_block(self):
        combo = QtWidgets.QComboBox()
        combo.blockSignals(True)
        try:
            CoverSheetDialog._replace_combo_items(
                combo,
                [("One", 1), ("Two", 2)],
            )
            self.assertTrue(combo.signalsBlocked())
            self.assertEqual(
                [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())],
                [("One", 1), ("Two", 2)],
            )
        finally:
            combo.blockSignals(False)
            combo.deleteLater()

    def test_cover_sheet_duplicate_rows_coalesce_pending_pdf_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "shared.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            data = _cover_sheet_data(
                image_path=pdf_path,
                multi_page_count=2,
            )
            second = deepcopy(data.pages_without_folder[0])
            second.uid = "p2"
            second.index = 2
            data.pages_without_folder.append(second)
            pool = _ManualRunnablePool()
            calls = []
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda path: calls.append(path)
                or [(42.0, 30.0, "One"), (42.0, 30.0, "Two")],
                pdf_metadata_pool=pool,
            )
            try:
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                for row in range(2):
                    item = dialog.plan_tree.topLevelItem(row)
                    self.assertIsNone(
                        delegate.createEditor(
                            dialog.plan_tree.viewport(),
                            QtWidgets.QStyleOptionViewItem(),
                            dialog.plan_tree.indexFromItem(item, 6),
                        )
                    )
                self.assertEqual(len(pool.runnables), 1)
                pool.run_next()
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(
                    [dialog._page_rows[uid].multi_page_count for uid in ("p1", "p2")],
                    [2, 2],
                )
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_stale_pdf_metadata_is_rejected_after_path_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = str(Path(tmp) / "old.pdf")
            missing_path = str(Path(tmp) / "missing.pdf")
            Path(old_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=old_path),
                pdf_page_sizes_fn=lambda _path: [(24.0, 36.0, "Old")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(missing_path)
                editor.editingFinished.emit()
                pool.run_next()
                row = dialog._page_rows["p1"]
                self.assertEqual(row.image_path, missing_path)
                self.assertEqual(row.pdf_page_sizes, ())
                self.assertEqual(row.page_index, 1)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_changed_pdf_signature_rejects_result_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "changing.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(24.0, 36.0, "Changed")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                Path(pdf_path).write_bytes(b"%PDF-1.4\nupdated\n")
                pool.run_next()
                row = dialog._page_rows["p1"]
                self.assertIsNone(row.pdf_page_sizes)
                self.assertIsNone(row.pending_metadata_request)
                retry_editor = delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    model_index,
                )
                self.assertIsNone(retry_editor)
                self.assertEqual(len(pool.runnables), 1)
                pool.run_next()
                retry_editor = delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    model_index,
                )
                self.assertIsInstance(retry_editor, QtWidgets.QComboBox)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_does_not_coalesce_different_file_signatures(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "changing.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            data = _cover_sheet_data(image_path=pdf_path)
            second_page = deepcopy(data.pages_without_folder[0])
            second_page.uid = "p2"
            data.pages_without_folder.append(second_page)
            pool = _ManualRunnablePool()
            calls = []
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda path: calls.append(path)
                or [(42.0, 30.0, "Current")],
                pdf_metadata_pool=pool,
            )
            try:
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                first = dialog.plan_tree.topLevelItem(0)
                second_item = dialog.plan_tree.topLevelItem(1)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(first, 6),
                    )
                )
                Path(pdf_path).write_bytes(b"%PDF-1.4\nupdated\n")
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(second_item, 6),
                    )
                )
                self.assertEqual(len(pool.runnables), 2)
                pool.run_next()
                pool.run_next()
                self.assertEqual(calls, [pdf_path])
                self.assertIsNone(dialog._page_rows["p1"].pdf_page_sizes)
                self.assertEqual(
                    dialog._page_rows["p2"].pdf_page_sizes,
                    ((42.0, 30.0, "Current"),),
                )
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_same_row_supersedes_pending_old_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "superseded.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            calls = []
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda path: calls.append(path)
                or [(42.0, 30.0, "Current")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                first_pending = dialog._page_rows["p1"].pending_metadata_request
                Path(pdf_path).write_bytes(b"%PDF-1.4\nnew\n")
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                second_pending = dialog._page_rows["p1"].pending_metadata_request
                self.assertNotEqual(first_pending, second_pending)
                self.assertEqual(len(pool.runnables), 2)
                pool.run_next()
                self.assertEqual(
                    dialog._page_rows["p1"].pending_metadata_request,
                    second_pending,
                )
                pool.run_next()
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(
                    dialog._page_rows["p1"].pdf_page_sizes,
                    ((42.0, 30.0, "Current"),),
                )
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_rejects_file_change_before_queued_result_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "queued.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(42.0, 30.0, "Old")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(item, 6),
                    )
                )
                pool.run_next(process_events=False)
                Path(pdf_path).write_bytes(b"%PDF-1.4\nnew content\n")
                QtWidgets.QApplication.processEvents()
                row = dialog._page_rows["p1"]
                self.assertIsNone(row.pdf_page_sizes)
                self.assertIsNone(row.pending_metadata_request)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_current_metadata_failure_is_reported_and_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "failed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()

            def fail(_path):
                raise ValueError("invalid PDF")

            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=fail,
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                model_index = dialog.plan_tree.indexFromItem(item, 6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                with self.assertLogs(
                    "ost_visualizer.presentation.dialogs.cover_sheet.dialog",
                    level="WARNING",
                ) as captured:
                    pool.run_next()
                self.assertIn("invalid PDF", captured.output[0])
                row = dialog._page_rows["p1"]
                self.assertIsNone(row.pending_metadata_request)
                self.assertIsNone(row.pdf_page_sizes)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        model_index,
                    )
                )
                self.assertEqual(len(pool.runnables), 1)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_close_rejects_pending_pdf_metadata_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "pending.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(24.0, 36.0, "Late")],
                pdf_metadata_pool=pool,
            )
            item = dialog.plan_tree.topLevelItem(0)
            delegate = dialog.plan_tree.itemDelegateForColumn(6)
            self.assertIsNone(
                delegate.createEditor(
                    dialog.plan_tree.viewport(),
                    QtWidgets.QStyleOptionViewItem(),
                    dialog.plan_tree.indexFromItem(item, 6),
                )
            )
            signature = dialog._metadata_loader.file_signature(pdf_path)
            path_identity = dialog._path_identity(pdf_path)
            dialog.reject()
            pool.run_next()
            self.assertTrue(dialog._closed)
            self.assertIsNone(dialog._page_rows["p1"].pdf_page_sizes)
            self.assertIsNone(dialog._metadata_loader.cached(path_identity, signature))
            with self.assertRaisesRegex(RuntimeError, "loader is closed"):
                dialog._metadata_loader.load(pdf_path, path_identity)
            dialog.deleteLater()

    def test_cover_sheet_close_during_real_worker_drops_late_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "worker.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            worker_started = threading.Event()
            release_worker = threading.Event()
            pool = QtCore.QThreadPool()
            pool.setMaxThreadCount(1)

            def page_sizes(_path):
                worker_started.set()
                release_worker.wait(2.0)
                return [(42.0, 30.0, "Late")]

            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=page_sizes,
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(item, 6),
                    )
                )
                self.assertTrue(worker_started.wait(1.0))
                dialog.reject()
                release_worker.set()
                self.assertTrue(pool.waitForDone(2000))
                QtWidgets.QApplication.processEvents()
                self.assertIsNone(dialog._page_rows["p1"].pdf_page_sizes)
            finally:
                release_worker.set()
                pool.waitForDone(2000)
                dialog.deleteLater()

    def test_cover_sheet_removed_row_rejects_pending_pdf_metadata_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "removed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _ManualRunnablePool()
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [(42.0, 30.0, "Late")],
                pdf_metadata_pool=pool,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                delegate = dialog.plan_tree.itemDelegateForColumn(6)
                self.assertIsNone(
                    delegate.createEditor(
                        dialog.plan_tree.viewport(),
                        QtWidgets.QStyleOptionViewItem(),
                        dialog.plan_tree.indexFromItem(item, 6),
                    )
                )
                item.setSelected(True)
                dialog._delete_selected()
                self.assertNotIn("p1", dialog._page_rows)
                pool.run_next()
                self.assertNotIn("p1", dialog._page_rows)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_uses_persisted_multi_page_count_without_pdf_read(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(multi_page_count=7),
            pdf_page_sizes_fn=lambda _path: self.fail(
                "Persisted multipage count must not require PDF metadata"
            ),
        )
        try:
            self.assertEqual(_first_page_update(dialog)["multi_page_count"], 7)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_reader_loads_persisted_multi_page_count(self):
        class Schema:
            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def optional_table_missing(table):
                return table == "BidPageFolders"

            @staticmethod
            def optional_column(_table, column, _fallback):
                return f"[{column}]"

            @staticmethod
            def order_by_existing(_table, _columns, fallback):
                return fallback

        class Cursor:
            def __init__(self):
                self.query = ""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, *_args):
                self.query = query

            def fetchall(self):
                return [
                    SimpleNamespace(
                        UID=1,
                        Name="Plan",
                        SheetNo="A1",
                        Width=42.0,
                        Height=30.0,
                        ScaleFactor1=0.125,
                        ScaleFactor2=12.0,
                        ImagePath="plan.pdf",
                        OverlayImagePath=None,
                        Index1=3,
                        MultiPageCount=7,
                        Show=0,
                        BidPageFolderUID=None,
                    )
                ]

        class Connection:
            def __init__(self):
                self.cursors = []

            def cursor(self):
                cursor = Cursor()
                self.cursors.append(cursor)
                return cursor

        class Reader(SettingsReaderMixin):
            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _record_caught_read_error(_error):
                return False

        connection = Connection()
        _folders, pages = Reader()._query_cover_sheet_pages(connection, "7")
        self.assertEqual(pages[0].multi_page_count, 7)
        self.assertIn("[MultiPageCount]", connection.cursors[-1].query)

    def test_cover_sheet_reader_rejects_page_folder_cycle(self):
        class Schema:
            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def optional_column(_table, column, _fallback):
                return f"[{column}]"

            @staticmethod
            def order_by_existing(_table, _columns, fallback):
                return fallback

        class Cursor:
            def __init__(self):
                self.query = ""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, *_args):
                self.query = query

            def fetchall(self):
                if "FROM [BidPageFolders]" in self.query:
                    return [
                        SimpleNamespace(UID=7, Name="A", ParentUID=8),
                        SimpleNamespace(UID=8, Name="B", ParentUID=7),
                    ]
                return []

        class Connection:
            def cursor(self):
                return Cursor()

        class Reader(SettingsReaderMixin):
            @staticmethod
            def _schema(_connection):
                return Schema()

            @staticmethod
            def _record_caught_read_error(_error):
                return False

        with self.assertRaisesRegex(RuntimeError, "ParentUID cycle"):
            Reader()._query_cover_sheet_pages(Connection(), "7")

    def test_cover_sheet_rows_have_independent_index_combos_and_share_pdf_metadata(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            data = _cover_sheet_data(image_path=pdf_path)
            second_page = deepcopy(data.pages_without_folder[0])
            second_page.uid = "p2"
            second_page.index = 2
            second_page.width = 30.0
            second_page.height = 42.0
            second_page.image_path = pdf_path.replace("\\", "/")
            data.pages_without_folder.append(second_page)
            calls = []
            page_sizes = [
                (24.0, 36.0, "Cover"),
                (30.0, 42.0, "Floor Plan"),
            ]
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda path: calls.append(path) or page_sizes,
            )
            try:
                first_combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(0))
                second_combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(1))
                self.assertIsNot(first_combo, second_combo)
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(first_combo.currentData()[0], 1)
                self.assertEqual(second_combo.currentData()[0], 2)
                _select_combo(dialog, dialog.plan_tree.topLevelItem(0), 6, 1)
                first_combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(0))
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 2)
                _select_combo(dialog, dialog.plan_tree.topLevelItem(1), 6, 0)
                second_combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(1))
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 1)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_and_row_drag_follow_lock_state(self):
        dialog = CoverSheetDialog(_FakeIconProvider(), None, _cover_sheet_data())
        try:
            dialog._update_lock_state(True)
            item = dialog.plan_tree.topLevelItem(0)
            self.assertIsNone(_index_combo(dialog, item))
            self.assertFalse(dialog.plan_tree.dragEnabled())
            self.assertFalse(dialog.plan_tree.acceptDrops())
            dialog._update_lock_state(False)
            self.assertIsInstance(_index_combo(dialog, item), QtWidgets.QComboBox)
            self.assertTrue(dialog.plan_tree.dragEnabled())
            self.assertTrue(dialog.plan_tree.acceptDrops())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_moved_page_preserves_row_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [
                    (24.0, 36.0, "Cover"),
                    (30.0, 42.0, "Floor Plan"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                _select_combo(dialog, item, 6, 1)
                before = _first_page_update(dialog)
                moved_item = dialog.plan_tree.takeTopLevelItem(0)
                dialog.plan_tree.addTopLevelItem(moved_item)
                dialog._on_tree_items_moved([moved_item])
                after = _first_page_update(dialog)
                for field in (
                    "index",
                    "width",
                    "height",
                    "scale_factor1",
                    "scale_factor2",
                    "show_mode",
                    "image_path",
                    "overlay_path",
                ):
                    self.assertEqual(after[field], before[field])
                self.assertEqual(moved_item.text(6), "2")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_plan_header_state_restores_width_and_order(self):
        model = _FakeWorkspaceStateModel()
        source = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = source.plan_tree.header()
            header.resizeSection(0, 222)
            header.moveSection(0, 2)
        finally:
            source.deleteLater()
        restored = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = restored.plan_tree.header()
            self.assertEqual(header.sectionSize(0), 222)
            self.assertEqual(header.visualIndex(0), 2)
        finally:
            restored.deleteLater()

    def test_cover_sheet_initial_size_comes_from_layout_and_has_window_controls(self):
        model = _FakeWorkspaceStateModel()
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            self.assertEqual(
                dialog.size(),
                dialog._window_state._bounded_size(dialog.sizeHint()),
            )
            self.assertGreater(dialog.maximumWidth(), dialog.minimumWidth())
            self.assertGreater(dialog.maximumHeight(), dialog.minimumHeight())
            flags = dialog.windowFlags()
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
            )
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint))
            self.assertTrue(bool(flags & QtCore.Qt.WindowType.WindowCloseButtonHint))
            self.assertNotIn("cover_sheet", model.state.dialog_sizes)
            self.assertNotIn("cover_sheet", model.state.dialog_maximized)
        finally:
            dialog.deleteLater()

    def test_cover_sheet_persists_and_restores_resized_window(self):
        model = _FakeWorkspaceStateModel()
        source = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            source.resize(760, 560)
            saved_size = [source.width(), source.height()]
            source.reject()
        finally:
            source.deleteLater()
        self.assertEqual(model.state.dialog_sizes["cover_sheet"], saved_size)
        self.assertFalse(model.state.dialog_maximized["cover_sheet"])
        restored = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            self.assertEqual(
                restored.size(),
                restored._window_state._bounded_size(QtCore.QSize(*saved_size)),
            )
        finally:
            restored.deleteLater()

    def test_cover_sheet_bounds_oversized_saved_window_to_available_screen(self):
        state = WorkspaceState(
            dialog_sizes={"cover_sheet": [100_000, 100_000]},
        )
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=_FakeWorkspaceStateModel(state),
        )
        try:
            self.assertEqual(dialog.size(), dialog.screen().availableGeometry().size())
        finally:
            dialog.deleteLater()

    def test_cover_sheet_persists_and_restores_maximized_state(self):
        model = _FakeWorkspaceStateModel()
        source = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            source.resize(760, 560)
            source.show()
            self.app.processEvents()
            source.showMaximized()
            self.app.processEvents()
            self.assertTrue(source.isMaximized())
            source.reject()
        finally:
            source.deleteLater()
        self.assertEqual(model.state.dialog_sizes["cover_sheet"], [760, 560])
        self.assertTrue(model.state.dialog_maximized["cover_sheet"])
        restored = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            restored.show()
            self.app.processEvents()
            self.assertTrue(restored.isMaximized())
            restored.showNormal()
            self.app.processEvents()
            self.assertFalse(restored.isMaximized())
        finally:
            restored.reject()
            restored.deleteLater()
        self.assertFalse(model.state.dialog_maximized["cover_sheet"])
        windowed = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            windowed.show()
            self.app.processEvents()
            self.assertFalse(windowed.isMaximized())
        finally:
            windowed.reject()
            windowed.deleteLater()

    def test_cover_sheet_plan_header_invalid_state_keeps_default_layout(self):
        state = WorkspaceState()
        state.header_layouts["cover_sheet_pages"] = HeaderLayoutState(
            widths={"sheet_number": 9999},
            order=["removed_column"],
        )
        model = _FakeWorkspaceStateModel(state)
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = dialog.plan_tree.header()
            self.assertEqual(header.sectionSize(0), 140)
            self.assertEqual(header.visualIndex(0), 0)
        finally:
            dialog.deleteLater()

    def test_cover_sheet_plan_header_reject_saves_state_to_workspace_key(self):
        model = _FakeWorkspaceStateModel()
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            dialog.plan_tree.header().resizeSection(0, 233)
            dialog.reject()
        finally:
            dialog.deleteLater()
        self.assertEqual(
            model.state.header_layouts["cover_sheet_pages"].widths["sheet_number"],
            233,
        )
        restored = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            self.assertEqual(restored.plan_tree.header().sectionSize(0), 233)
        finally:
            restored.deleteLater()

    def test_new_project_cover_sheet_uses_same_plan_header_state(self):
        model = _FakeWorkspaceStateModel()
        source = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            create_mode=True,
            workspace_state_model=model,
        )
        try:
            source.plan_tree.header().resizeSection(0, 244)
            source.reject()
        finally:
            source.deleteLater()
        restored = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            create_mode=True,
            workspace_state_model=model,
        )
        try:
            self.assertEqual(restored.plan_tree.header().sectionSize(0), 244)
        finally:
            restored.deleteLater()

    def test_cover_sheet_save_writes_page_image_paths_with_windows_separators(self):
        ops = _CoverSheetSettingsOps()
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _cover_sheet_page_update(
                        image_path=(
                            "C:/OCS Documents/OST/25-051 Marriott Element, "
                            "Capel Hill, NC/S-100.pdf"
                        ),
                        overlay_path="C:/OCS Documents/OST/overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(
            [update["table"] for update in ops.updates],
            ["Bids", "BidPages"],
        )
        bid_update = next(update for update in ops.updates if update["table"] == "Bids")
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertNotIn("ImageFolder", bid_update["values"])
        self.assertEqual(
            page_update["values"]["ImagePath"],
            (
                r"C:\OCS Documents\OST\25-051 Marriott Element, "
                r"Capel Hill, NC\S-100.pdf"
            ),
        )
        self.assertEqual(
            page_update["values"]["OverlayImagePath"],
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertEqual(
            page_update["values"]["OverlayRect"],
            "0.000000,0.000000,4032.000000,2880.000000",
        )
        self.assertEqual(page_update["values"]["OverlayOffsetX"], 0.0)
        self.assertEqual(page_update["values"]["OverlayOffsetY"], 0.0)
        self.assertEqual(page_update["values"]["OverlayRotation"], 0.0)
        self.assertEqual(page_update["values"]["OverlayResized"], 0)
        self.assertEqual(page_update["values"]["DeskewRotationOverlay"], 0.0)
        self.assertEqual(page_update["values"]["SheetNo"], "S-100")

    def test_cover_sheet_overlay_only_removal_restores_original_and_clears_metadata(
        self,
    ):
        ops = _CoverSheetSettingsOps()
        ops.conn.cursor_obj.current_overlay_path = r"C:\Plans\overlay.pdf"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    {
                        **_cover_sheet_page_update(
                            image_path=r"C:\Plans\original.pdf",
                            overlay_path="",
                        ),
                        "show_mode": 1,
                    }
                ],
            },
        )
        self.assertTrue(success)
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            {
                key: page_update["values"][key]
                for key in (
                    "OverlayImagePath",
                    "Show",
                    "OverlayRect",
                    "OverlayOffsetX",
                    "OverlayOffsetY",
                    "OverlayRotation",
                    "OverlayResized",
                    "DeskewRotationOverlay",
                )
            },
            {
                "OverlayImagePath": "",
                "Show": 0,
                "OverlayRect": "",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_cover_sheet_page_scale_change_rescales_existing_page_positions(self):
        ops = _ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [_cover_sheet_page_update(scale_factor1=0.25)],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [(11, 0.5)])
        self.assertEqual(ops.overlay_rescale_calls, [(11, 0.5)])

    def test_cover_sheet_unchanged_page_scale_does_not_rescale_positions(self):
        ops = _ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [_cover_sheet_page_update()],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [])
        self.assertEqual(ops.overlay_rescale_calls, [])

    def test_cover_sheet_overlay_replacement_uses_new_calibration_once(self):
        ops = _ScaleCoverSheetOps(old_sf1=0.1875, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _cover_sheet_page_update(
                        scale_factor1=0.125,
                        overlay_path=r"C:\Plans\overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.overlay_rescale_calls, [])
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            page_update["values"]["OverlayRect"],
            "0.000000,0.000000,4032.000000,2880.000000",
        )

    def test_cover_sheet_separator_only_overlay_path_change_preserves_rectangle(self):
        ops = _CoverSheetSettingsOps()
        ops.conn.cursor_obj.current_overlay_path = "C:/Plans/overlay.pdf"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _cover_sheet_page_update(
                        overlay_path=r"C:\Plans\overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            page_update["values"]["OverlayImagePath"],
            r"C:\Plans\overlay.pdf",
        )
        self.assertNotIn("OverlayRect", page_update["values"])
        self.assertNotIn("OverlayOffsetX", page_update["values"])
        self.assertNotIn("OverlayOffsetY", page_update["values"])

    def test_cover_sheet_new_page_scale_does_not_rescale_positions(self):
        ops = _ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _cover_sheet_page_update(
                        uid=None,
                        scale_factor1=0.25,
                        sheet_no="S-101",
                        name="Level 2",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [])
        self.assertEqual([insert["table"] for insert in ops.inserts], ["BidPages"])

    def test_cover_sheet_existing_page_can_move_into_new_folder(self):
        ops = _CoverSheetSettingsOps()
        page = _cover_sheet_page_update()
        page["folder_uid"] = "new_folder_0"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "new_folders": [
                    {
                        "local_uid": "new_folder_0",
                        "name": "New Folder",
                        "parent_uid": None,
                    }
                ],
                "pages": [page],
            },
        )
        self.assertTrue(success)
        folder_insert = next(
            insert for insert in ops.inserts if insert["table"] == "BidPageFolders"
        )
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(folder_insert["values"]["UID"], 99)
        self.assertEqual(page_update["values"]["BidPageFolderUID"], 99)

    def test_cover_sheet_existing_folder_can_move_into_new_folder(self):
        ops = _CoverSheetSettingsOps()
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "new_folders": [
                    {
                        "local_uid": "new_folder_0",
                        "name": "New Parent",
                        "parent_uid": None,
                    }
                ],
                "folders": [
                    {
                        "uid": "5",
                        "name": "Existing Child",
                        "parent_uid": "new_folder_0",
                    }
                ],
                "pages": [],
            },
        )
        self.assertTrue(success)
        folder_update = next(
            update for update in ops.updates if update["table"] == "BidPageFolders"
        )
        self.assertEqual(folder_update["values"]["ParentUID"], 99)

    def test_page_scale_save_uses_shared_content_rescale(self):
        ops = _PageScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0))
        self.assertEqual(ops.rescale_calls, [(11, 0.5)])

    def test_page_scale_save_rejects_invalid_overlay_calibration(self):
        cases = (
            (_PageScaleOps(old_sf1=0.0, old_sf2=12.0), 0.125, 12.0),
            (_PageScaleOps(old_sf1=0.125, old_sf2=12.0), 0.0, 12.0),
        )
        for ops, scale_factor1, scale_factor2 in cases:
            with self.subTest(
                old_scale=(
                    ops.conn.cursor_obj.old_sf1,
                    ops.conn.cursor_obj.old_sf2,
                ),
                new_scale=(scale_factor1, scale_factor2),
            ):
                self.assertFalse(
                    ops.save_page_scale(
                        "bid.mdb",
                        "11",
                        scale_factor1,
                        scale_factor2,
                    )
                )
                self.assertEqual(ops.rescale_calls, [])

    def test_page_scale_change_rescales_overlay_rect_and_offsets(self):
        ops = _OverlayScaleOps()
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
        self.assertEqual(ops.position_rescales, [(11, 1.5)])
        self.assertEqual(
            ops.updates,
            [
                (
                    "BidPages",
                    {
                        "OverlayRect": ("-1.654719,0.000000,4029.242135,2879.212038"),
                        "OverlayOffsetX": -1.654719,
                        "OverlayOffsetY": 0.0,
                    },
                    "rescale_page_overlay_rect",
                )
            ],
        )

    def test_page_scale_change_preserves_native_empty_overlay_marker(self):
        ops = _OverlayScaleOps(overlay_rect="*")
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
        self.assertEqual(ops.position_rescales, [(11, 1.5)])
        self.assertEqual(ops.updates, [])

    def test_page_scale_position_failure_aborts_scale_update(self):
        ops = _FailingPositionScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertFalse(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0))
        self.assertFalse(
            any(
                "UPDATE [BidPages] SET [ScaleFactor1]" in query
                for query, _args in ops.conn.cursor_obj.calls
            )
        )
        self.assertIs(ops.conn.exit_args[-1][0], pyodbc.Error)

    def test_saving_page_overlay_image_generates_full_page_overlay_rect(self):
        ops = _PageOverlayOps()
        success = ops.save_page_overlay_image(
            "bid.mdb",
            "11",
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertTrue(success)
        self.assertEqual(len(ops.updates), 1)
        self.assertEqual(ops.updates[0]["table"], "BidPages")
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayImagePath": r"C:\OCS Documents\OST\overlay.pdf",
                "OverlayRect": "0.000000,0.000000,4032.000000,2880.000000",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_adding_overlay_without_original_selects_the_only_available_source(self):
        ops = _PageOverlayOps(original_image_path="")
        self.assertTrue(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            )
        )
        self.assertEqual(ops.updates[0]["values"]["Show"], 1)

    def test_removing_page_overlay_image_clears_all_overlay_owned_storage(self):
        ops = _PageOverlayOps(current_overlay_path=r"C:\Plans\overlay.pdf")
        self.assertTrue(ops.save_page_overlay_image("bid.mdb", "11", ""))
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayImagePath": "",
                "OverlayRect": "",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
                "Show": 0,
            },
        )

    def test_saving_same_overlay_image_preserves_existing_rectangle(self):
        path = r"C:\OCS Documents\OST\overlay.pdf"
        ops = _PageOverlayOps(current_overlay_path=path)
        self.assertTrue(ops.save_page_overlay_image("bid.mdb", "11", path))
        self.assertEqual(ops.updates, [])

    def test_saving_same_overlay_image_with_other_separators_preserves_rectangle(self):
        ops = _PageOverlayOps(current_overlay_path="C:/OCS Documents/OST/overlay.pdf")
        self.assertTrue(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            )
        )
        self.assertEqual(ops.updates, [])

    def test_saving_overlay_rect_mirrors_native_translation_fields(self):
        ops = _PageOverlayOps()
        self.assertTrue(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (-1.103146, -2.5, 2686.161423, 1919.474692),
            )
        )
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayRect": "-1.103146,-2.500000,2686.161423,1919.474692",
                "OverlayOffsetX": -1.103146,
                "OverlayOffsetY": -2.5,
            },
        )

    def test_saving_overlay_rect_rejects_invalid_page_calibration(self):
        cases = (
            {"scale_factor1": 0.0},
            {"scale_factor1": -0.125},
            {"scale_factor2": float("nan")},
        )
        for cursor_options in cases:
            with self.subTest(cursor_options=cursor_options):
                ops = _PageOverlayOps(**cursor_options)
                self.assertFalse(
                    ops.save_page_overlay_rect(
                        "bid.mdb",
                        "11",
                        (0.0, 0.0, 100.0, 100.0),
                    )
                )
                self.assertEqual(ops.updates, [])

    def test_saving_overlay_rect_rejects_missing_page(self):
        ops = _PageOverlayOps(page_exists=False)
        self.assertFalse(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (0.0, 0.0, 100.0, 100.0),
            )
        )
        self.assertEqual(ops.updates, [])

    def test_cover_sheet_image_path_cells_highlight_missing_files(self):
        missing_image = str(Path(tempfile.gettempdir()) / "missing-cover-page.pdf")
        missing_overlay = str(Path(tempfile.gettempdir()) / "missing-overlay.pdf")
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(
                image_path=missing_image,
                overlay_image_path=missing_overlay,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            image_editor = _path_editor(dialog, item, 4)
            overlay_editor = _path_editor(dialog, item, 5)
            self.assertEqual(image_editor.text(), Path(missing_image).name)
            self.assertEqual(overlay_editor.text(), Path(missing_overlay).name)
            self.assertIn("color:", image_editor.styleSheet())
            self.assertIn("Image File was not found", image_editor.toolTip())
            self.assertIn("color:", overlay_editor.styleSheet())
            self.assertIn("Overlay Image was not found", overlay_editor.toolTip())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_folder_nodes_use_folder_icon(self):
        data = _cover_sheet_data()
        data.folders["f1"] = CoverSheetFolder(uid="f1", name="Plans")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            folder_item = dialog.plan_tree.topLevelItem(0)
            self.assertEqual(
                tuple(folder_item.data(0, dialog._ITEM_ROLE)), ("folder", "f1")
            )
            self.assertFalse(folder_item.icon(0).isNull())
            self.assertEqual(
                folder_item.icon(0).cacheKey(),
                IconManager.icon(IconId.FOLDER).cacheKey(),
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_folder_node_uses_folder_icon(self):
        dialog = CoverSheetDialog(_FakeIconProvider(), None, _cover_sheet_data())
        try:
            dialog._add_new_folder()
            folder_item = dialog.plan_tree.topLevelItem(0)
            data = folder_item.data(0, dialog._ITEM_ROLE)
            self.assertEqual(data[0], "new_folder")
            self.assertFalse(folder_item.icon(0).isNull())
            self.assertEqual(
                folder_item.icon(0).cacheKey(),
                IconManager.icon(IconId.FOLDER).cacheKey(),
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_root_folder_uses_reopen_folder_order(self):
        data = _cover_sheet_data()
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            self.assertEqual(_top_level_labels(dialog), ["Zulu", "A101"])
            dialog._add_new_folder()
            self.assertEqual(_top_level_labels(dialog), ["New Folder", "Zulu", "A101"])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_renamed_folder_reorders_before_reopen(self):
        data = _cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        data.folders["c1"] = CoverSheetFolder(uid="c1", name="Charlie")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            beta_item = dialog.plan_tree.topLevelItem(0)
            zulu_item = dialog.plan_tree.topLevelItem(2)
            beta_item.setText(0, "Yankee")
            self.assertEqual(
                _top_level_labels(dialog), ["Charlie", "Yankee", "Zulu", "A101"]
            )
            zulu_item.setText(0, "Alpha")
            self.assertEqual(
                _top_level_labels(dialog), ["Alpha", "Charlie", "Yankee", "A101"]
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_folder_reorder_preserves_existing_signal_block(self):
        data = _cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            zulu_item = dialog.plan_tree.topLevelItem(1)
            dialog.plan_tree.blockSignals(True)
            zulu_item.setText(0, "Alpha")
            dialog._reinsert_folder_item(zulu_item)
            self.assertTrue(dialog.plan_tree.signalsBlocked())
            self.assertEqual(_top_level_labels(dialog), ["Alpha", "Beta", "A101"])
        finally:
            dialog.plan_tree.blockSignals(False)
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_moved_folder_reorders_to_persisted_position(self):
        data = _cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            folder_item = dialog.plan_tree.takeTopLevelItem(0)
            dialog.plan_tree.addTopLevelItem(folder_item)
            dialog._on_tree_items_moved([folder_item])
            self.assertEqual(_top_level_labels(dialog), ["Beta", "Zulu", "A101"])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_child_folder_stays_before_child_pages(self):
        data = _cover_sheet_data()
        parent = CoverSheetFolder(uid="f1", name="Plans")
        parent.pages.append(
            CoverSheetPage(
                uid="p2",
                sheet_no="A102",
                name="Level 2",
                width=42.0,
                height=30.0,
                scale_factor1=0.125,
                scale_factor2=12.0,
                image_path="",
                overlay_image_path="",
                index=2,
                show_mode=0,
            )
        )
        data.folders["f1"] = parent
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            folder_item = dialog.plan_tree.topLevelItem(0)
            dialog.plan_tree.setCurrentItem(folder_item)
            folder_item.setSelected(True)
            dialog._add_new_folder()
            self.assertEqual(_child_labels(folder_item), ["New Folder", "A102"])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_next_sheet_number_uses_deep_tree_pages(self):
        data = _cover_sheet_data()
        page = data.pages_without_folder.pop()
        page.sheet_no = "00100"
        deepest = CoverSheetFolder(uid="f3", name="Deep", pages=[page])
        middle = CoverSheetFolder(
            uid="f2",
            name="Middle",
            subfolders={"f3": deepest},
        )
        data.folders["f1"] = CoverSheetFolder(
            uid="f1",
            name="Root",
            subfolders={"f2": middle},
        )
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            self.assertEqual(dialog._next_sheet_no(), "00101")
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_cover_sheet_imported_image_pages_keep_visual_sequence(self):
        data = _cover_sheet_data()
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog._populate_imported_pages(
                [("C:/Plans/A102.pdf", [(42.0, 30.0, ""), (42.0, 30.0, "")])]
            )
            labels = [
                dialog.plan_tree.topLevelItem(index).text(1)
                for index in range(dialog.plan_tree.topLevelItemCount())
            ]
            self.assertEqual(labels, ["Level 1", "A102.pdf (1)", "A102.pdf (2)"])
            self.assertEqual(
                [
                    (page["name"], page["sequence"])
                    for page in dialog.get_updates()["pages"]
                ],
                [("Level 1", 1), ("A102.pdf (1)", 2), ("A102.pdf (2)", 3)],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_page_inserts_after_selected_root_page(self):
        data = _cover_sheet_data_with_pages(5)
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog.plan_tree.setCurrentItem(dialog._page_items["p2"])
            dialog._add_new_page()
            tree_order = [
                dialog.plan_tree.topLevelItem(index).data(0, dialog._ITEM_ROLE)[1]
                for index in range(dialog.plan_tree.topLevelItemCount())
            ]
            self.assertEqual(tree_order, ["p1", "p2", "new_0", "p3", "p4", "p5"])
            self.assertEqual(
                [
                    (page["uid"], page["sequence"])
                    for page in dialog.get_updates()["pages"]
                ],
                [
                    ("p1", 1),
                    ("p2", 2),
                    (None, 3),
                    ("p3", 4),
                    ("p4", 5),
                    ("p5", 6),
                ],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_page_handles_first_last_and_no_selection(self):
        for selected_uid, expected_order in (
            ("p1", ["p1", "new_0", "p2", "p3"]),
            ("p3", ["p1", "p2", "p3", "new_0"]),
            (None, ["p1", "p2", "p3", "new_0"]),
        ):
            with self.subTest(selected_uid=selected_uid):
                data = _cover_sheet_data_with_pages()
                dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
                try:
                    if selected_uid is not None:
                        dialog.plan_tree.setCurrentItem(
                            dialog._page_items[selected_uid]
                        )
                    dialog._add_new_page()
                    self.assertEqual(
                        [
                            dialog.plan_tree.topLevelItem(index).data(
                                0, dialog._ITEM_ROLE
                            )[1]
                            for index in range(dialog.plan_tree.topLevelItemCount())
                        ],
                        expected_order,
                    )
                finally:
                    dialog.close()
                    dialog.deleteLater()

    def test_cover_sheet_import_inserts_ordered_block_after_selected_page(self):
        data = _cover_sheet_data_with_pages()
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog.plan_tree.setCurrentItem(dialog._page_items["p2"])
            dialog._populate_imported_pages(
                [
                    ("C:/Plans/A.pdf", [(42.0, 30.0, ""), (42.0, 30.0, "")]),
                    ("C:/Plans/B.png", [(42.0, 30.0, "")]),
                ]
            )
            names = [page["name"] for page in dialog.get_updates()["pages"]]
            self.assertEqual(
                names,
                [
                    "Page 1",
                    "Page 2",
                    "A.pdf (1)",
                    "A.pdf (2)",
                    "B.png",
                    "Page 3",
                ],
            )
            self.assertEqual(
                [page["sequence"] for page in dialog.get_updates()["pages"]],
                [1, 2, 3, 4, 5, 6],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_duplicate_inserts_after_selected_page(self):
        data = _cover_sheet_data_with_pages()
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog.plan_tree.setCurrentItem(dialog._page_items["p2"])
            dialog._duplicate_page()
            self.assertEqual(
                [page["name"] for page in dialog.get_updates()["pages"]],
                ["Page 1", "Page 2", "Copy of Page 2", "Page 3"],
            )
            self.assertEqual(
                [
                    dialog.plan_tree.topLevelItem(index).data(0, dialog._ITEM_ROLE)[1]
                    for index in range(dialog.plan_tree.topLevelItemCount())
                ],
                ["p1", "p2", "new_0", "p3"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_page_and_folder_with_same_uid_remain_typed(self):
        data = _cover_sheet_data()
        page = data.pages_without_folder[0]
        page.uid = "shared"
        data.folders["shared"] = CoverSheetFolder(uid="shared", name="Folder")
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            page_item = dialog._page_items["shared"]
            folder_item = dialog._folder_items["shared"]
            self.assertEqual(page_item.data(0, dialog._ITEM_ROLE), ("page", "shared"))
            self.assertEqual(
                folder_item.data(0, dialog._ITEM_ROLE), ("folder", "shared")
            )
            dialog.plan_tree.setCurrentItem(page_item)
            dialog._delete_selected()
            self.assertIn("shared", dialog._folder_items)
            self.assertNotIn("shared", dialog._page_items)
            self.assertEqual(dialog.get_updates()["deleted_page_uids"], ["shared"])
            self.assertEqual(dialog.get_updates()["deleted_folder_uids"], [])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_duplicate_reuses_external_reference_without_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "drawing.pdf"
            original = b"%PDF-1.4\nuser-owned drawing\n"
            source.write_bytes(original)
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=str(source)),
            )
            try:
                dialog.plan_tree.setCurrentItem(dialog._page_items["p1"])
                dialog._duplicate_page()
                self.assertEqual(
                    [page["image_path"] for page in dialog.get_updates()["pages"]],
                    [str(source), str(source)],
                )
                self.assertEqual(tuple(Path(tmp).iterdir()), (source,))
                self.assertEqual(source.read_bytes(), original)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_multiple_selection_inserts_after_explicit_current_page(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(), None, _cover_sheet_data_with_pages()
        )
        try:
            first = dialog._page_items["p1"]
            last = dialog._page_items["p3"]
            first.setSelected(True)
            last.setSelected(True)
            dialog.plan_tree.setCurrentItem(first)
            last.setSelected(True)
            self.assertEqual(len(dialog.plan_tree.selectedItems()), 2)
            dialog._add_new_page()
            self.assertEqual(
                [
                    dialog.plan_tree.topLevelItem(index).data(0, dialog._ITEM_ROLE)[1]
                    for index in range(dialog.plan_tree.topLevelItemCount())
                ],
                ["p1", "new_0", "p2", "p3"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_ambiguous_multiple_selection_falls_back_to_root_append(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(), None, _cover_sheet_data_with_pages()
        )
        try:
            dialog.plan_tree.setCurrentItem(None)
            dialog._page_items["p1"].setSelected(True)
            dialog._page_items["p3"].setSelected(True)
            self.assertEqual(len(dialog.plan_tree.selectedItems()), 2)
            dialog._add_new_page()
            self.assertEqual(
                [
                    dialog.plan_tree.topLevelItem(index).data(0, dialog._ITEM_ROLE)[1]
                    for index in range(dialog.plan_tree.topLevelItemCount())
                ],
                ["p1", "p2", "p3", "new_0"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_import_skips_empty_sources_without_reordering_successes(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(), None, _cover_sheet_data_with_pages()
        )
        try:
            dialog.plan_tree.setCurrentItem(dialog._page_items["p2"])
            dialog._populate_imported_pages(
                [
                    ("C:/Plans/Skipped.pdf", []),
                    ("C:/Plans/A.png", [(42.0, 30.0, "")]),
                    ("C:/Plans/AlsoSkipped.pdf", []),
                    ("C:/Plans/B.png", [(42.0, 30.0, "")]),
                ]
            )
            self.assertEqual(
                [page["name"] for page in dialog.get_updates()["pages"]],
                ["Page 1", "Page 2", "A.png", "B.png", "Page 3"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_multipage_expansion_uses_same_ordered_insertion_path(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(), None, _cover_sheet_data_with_pages()
        )
        try:
            source = dialog._page_items["p2"]
            dialog._add_missing_multipage_rows(
                source,
                "C:/Plans/Expanded.pdf",
                [
                    (42.0, 30.0, ""),
                    (42.0, 30.0, ""),
                    (42.0, 30.0, ""),
                ],
            )
            self.assertEqual(
                [page["name"] for page in dialog.get_updates()["pages"]],
                [
                    "Page 1",
                    "Page 2",
                    "Expanded.pdf (2)",
                    "Expanded.pdf (3)",
                    "Page 3",
                ],
            )
            self.assertEqual(
                [page["sequence"] for page in dialog.get_updates()["pages"]],
                [1, 2, 3, 4, 5],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_multipage_expansion_keeps_existing_indexes_in_order(self):
        data = _cover_sheet_data_with_pages()
        source_path = "C:/Plans/Expanded.pdf"
        data.pages_without_folder[0].image_path = source_path
        data.pages_without_folder[0].index = 1
        data.pages_without_folder[1].image_path = source_path
        data.pages_without_folder[1].index = 2
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog._add_missing_multipage_rows(
                dialog._page_items["p1"],
                source_path,
                [
                    (42.0, 30.0, ""),
                    (42.0, 30.0, ""),
                    (42.0, 30.0, ""),
                ],
            )
            pages = dialog.get_updates()["pages"]
            self.assertEqual(
                [page["name"] for page in pages],
                ["Page 1", "Page 2", "Expanded.pdf (3)", "Page 3"],
            )
            self.assertEqual([page["index"] for page in pages], [1, 2, 3, 1])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_folder_selection_appends_and_nested_page_inserts_after(self):
        data = _cover_sheet_data()
        template = data.pages_without_folder.pop()
        page_1 = deepcopy(template)
        page_1.uid = "p1"
        page_1.sheet_no = "A101"
        page_1.name = "Page 1"
        page_2 = deepcopy(template)
        page_2.uid = "p2"
        page_2.sheet_no = "A102"
        page_2.name = "Page 2"
        nested_page_1 = deepcopy(template)
        nested_page_1.uid = "p3"
        nested_page_1.sheet_no = "A103"
        nested_page_1.name = "Nested 1"
        nested_page_2 = deepcopy(template)
        nested_page_2.uid = "p4"
        nested_page_2.sheet_no = "A104"
        nested_page_2.name = "Nested 2"
        nested = CoverSheetFolder(
            uid="f2",
            name="Nested",
            pages=[nested_page_1, nested_page_2],
        )
        data.folders["f1"] = CoverSheetFolder(
            uid="f1",
            name="Plans",
            subfolders={"f2": nested},
            pages=[page_1, page_2],
        )
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            root_folder = dialog._folder_items["f1"]
            dialog.plan_tree.setCurrentItem(root_folder)
            dialog._add_new_page()
            self.assertEqual(
                _child_labels(root_folder),
                ["Nested", "A101", "A102", "00001"],
            )
            nested_folder = dialog._folder_items["f2"]
            dialog.plan_tree.setCurrentItem(dialog._page_items["p3"])
            dialog._add_new_page()
            self.assertEqual(
                _child_labels(nested_folder),
                ["A103", "00002", "A104"],
            )
            page_updates = dialog.get_updates()["pages"]
            self.assertEqual(
                [
                    page["folder_uid"]
                    for page in page_updates
                    if page["sheet_no"] == "00002"
                ],
                ["f2"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_bid_areas_dialog_refreshes_once_after_saved_changes(self):
        captured = {}
        refresh_calls = []

        class CapturingAreasDialog:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                on_saved_fn=None,
                has_license=True,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                captured.update(
                    icon_provider=icon_provider,
                    workspace_state_model=workspace_state_model,
                    parent=parent,
                    bid_areas=bid_areas,
                    save_fn=save_fn,
                    used_uids=used_uids,
                    has_license=has_license,
                    bid_ref=bid_ref,
                    save_async_fn=save_async_fn,
                )
                if on_saved_fn is not None:
                    captured["on_saved_fn"] = on_saved_fn

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

            def has_saved_changes(self):
                return True

            def deleteLater(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            reload_bid_areas_fn=lambda: [],
            save_bid_areas_fn=lambda _changes: {},
            get_used_area_uids_fn=lambda: set(),
            refresh_fn=lambda: refresh_calls.append("refresh") or True,
        )
        try:
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            old_dialog = module.BidAreasDialog
            module.BidAreasDialog = CapturingAreasDialog
            try:
                dialog._open_bid_areas_dialog()
            finally:
                module.BidAreasDialog = old_dialog
            self.assertNotIn("on_saved_fn", captured)
            self.assertEqual(refresh_calls, ["refresh"])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_async_cover_sheet_bid_areas_uses_authoritative_projection(self):
        refresh_calls = []

        class SavedAreasDialog:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                on_saved_fn=None,
                has_license=True,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                del (
                    icon_provider,
                    workspace_state_model,
                    parent,
                    bid_areas,
                    save_fn,
                    used_uids,
                    on_saved_fn,
                    has_license,
                    bid_ref,
                    save_async_fn,
                )

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

            def has_saved_changes(self):
                return True

            def deleteLater(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            reload_bid_areas_fn=lambda: [],
            save_bid_areas_async_fn=lambda _changes, _completed: True,
            get_used_area_uids_fn=lambda: set(),
            refresh_fn=lambda: refresh_calls.append("refresh") or True,
        )
        try:
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            old_dialog = module.BidAreasDialog
            module.BidAreasDialog = SavedAreasDialog
            try:
                dialog._open_bid_areas_dialog()
            finally:
                module.BidAreasDialog = old_dialog
            self.assertEqual(refresh_calls, [])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_bid_area_reload_failure_does_not_open_empty_editor(self):
        warnings = []

        def fail_reload():
            raise RuntimeError("database unavailable")

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(),
            reload_bid_areas_fn=fail_reload,
            save_bid_areas_fn=lambda _changes: {},
        )
        try:
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            with mock.patch.object(
                module, "BidAreasDialog"
            ) as areas_dialog, mock.patch.object(
                module,
                "show_warning",
                side_effect=lambda _parent, title, message: warnings.append(
                    (title, message)
                ),
            ), self.assertLogs(
                module.logger, level="ERROR"
            ) as logs:
                dialog._open_bid_areas_dialog()
            areas_dialog.assert_not_called()
            self.assertEqual(warnings[0][0], "Bid Areas Unavailable")
            self.assertIn("Could not reload bid areas", logs.output[0])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_page_scale_combo_includes_known_non_architectural_scales(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(scale_factor1=1.0, scale_factor2=120.0),
        )
        try:
            page_item = dialog.plan_tree.topLevelItem(0)
            scale_combo = _combo_editor(dialog, page_item, 3)
            self.assertEqual(tuple(scale_combo.currentData()), (1.0, 120.0))
            self.assertEqual(scale_combo.currentText(), '1" = 10\' 0"')
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_page_delete_decline_skips_page_and_continues(self):
        data = _cover_sheet_data()
        data.pages_without_folder.extend(
            [
                CoverSheetPage(
                    uid="p2",
                    sheet_no="A102",
                    name="Level 2",
                    width=42.0,
                    height=30.0,
                    scale_factor1=0.125,
                    scale_factor2=12.0,
                    image_path="",
                    overlay_image_path="",
                    index=2,
                    show_mode=0,
                ),
                CoverSheetPage(
                    uid="p3",
                    sheet_no="A103",
                    name="Level 3",
                    width=42.0,
                    height=30.0,
                    scale_factor1=0.125,
                    scale_factor2=12.0,
                    image_path="",
                    overlay_image_path="",
                    index=3,
                    show_mode=0,
                ),
            ]
        )
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            data,
            pages_requiring_delete_confirmation={"p2"},
        )
        try:
            for idx in range(3):
                dialog.plan_tree.topLevelItem(idx).setSelected(True)
            with mock.patch(
                "ost_visualizer.presentation.dialogs.cover_sheet.dialog."
                "confirm_delete_page_with_contents",
                return_value=False,
            ) as confirm:
                dialog._delete_selected()
            self.assertEqual(confirm.call_count, 1)
            self.assertEqual(dialog._deleted_page_uids, ["p1", "p3"])
            remaining = [
                dialog.plan_tree.topLevelItem(idx).data(0, dialog._ITEM_ROLE)[1]
                for idx in range(dialog.plan_tree.topLevelItemCount())
            ]
            self.assertEqual(remaining, ["p2"])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_page_delete_never_deletes_external_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "drawing.pdf"
            original = b"%PDF-1.4\nuser-owned drawing\n"
            source.write_bytes(original)
            data = _cover_sheet_data_with_pages(2)
            for page in data.pages_without_folder:
                page.image_path = str(source)
            dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
            try:
                dialog.plan_tree.setCurrentItem(dialog._page_items["p1"])
                dialog._delete_selected()
                self.assertEqual(dialog._deleted_page_uids, ["p1"])
                self.assertTrue(source.is_file())
                self.assertEqual(source.read_bytes(), original)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_database_failure_does_not_compensate_external_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "drawing.pdf"
            original = b"%PDF-1.4\nuser-owned drawing\n"
            source.write_bytes(original)
            submissions = []

            def fail_save(updates, completed):
                submissions.append(updates)
                completed(False)
                return True

            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=str(source)),
                save_cover_sheet_async_fn=fail_save,
            )
            try:
                dialog.accept()
                self.assertEqual(len(submissions), 1)
                self.assertFalse(dialog._operation_pending)
                self.assertTrue(source.is_file())
                self.assertEqual(source.read_bytes(), original)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_async_save_waits_for_recovered_terminal_result(self):
        queued = {}
        completions = []
        errors = []

        class WriteService:
            @staticmethod
            def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                queued.update(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    updates=updates,
                    callback=callback,
                )
                return 1

        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = None
        handler._write_service = WriteService()
        handler._ui_event_coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda database_id, title, result: (
                errors.append((database_id, title, result))
            )
        )
        self.assertTrue(
            handler._save_cover_sheet_async(
                BidRef("database", "7"),
                {"notes": "updated"},
                completions.append,
            )
        )
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            queued["callback"](
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=status,
                    commit_attempted=True,
                )
            )
        self.assertEqual(completions, [])
        self.assertEqual(errors, [])
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(completions, [True])
        self.assertEqual(errors, [])

    def test_original_source_rejection_keeps_cover_sheet_draft_retryable_and_snapshot_unchanged(
        self,
    ):
        queued = []
        errors = []
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = None
        handler._write_service = SimpleNamespace(
            queue_cover_sheet_save=lambda database_id, bid_uid, updates, callback: queued.append(
                (updates, callback)
            )
            or 1
        )
        handler._ui_event_coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda database_id, title, result: errors.append(
                (title, result.message)
            )
        )
        original = _cover_sheet_data(
            image_path="original.tif", overlay_image_path="overlay.tif"
        )
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            original,
            save_cover_sheet_async_fn=lambda updates, completed: handler._save_cover_sheet_async(
                BidRef("database", "7"), updates, completed
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            for path in ("replacement.tif", ""):
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(path)
                editor.editingFinished.emit()
                dialog.accept()
                self.assertTrue(dialog._operation_pending)
                before = len(errors)
                queued[-1][1](
                    QueuedMutationResult(
                        database_id="database",
                        runtime_generation=1,
                        operation_id="00000000-0000-0000-0000-000000000001",
                        outcome_status=MutationOutcomeStatus.REJECTED,
                        message="Original source save rejected",
                    )
                )
                self.assertFalse(dialog._operation_pending)
                self.assertFalse(dialog._save_done)
                self.assertEqual(_first_page_update(dialog)["image_path"], path)
                self.assertEqual(
                    original.pages_without_folder[0].image_path, "original.tif"
                )
                self.assertEqual(len(errors), before + 1)
                self.assertEqual(
                    errors[-1], ("Cover Sheet", "Original source save rejected")
                )
            dialog.accept()
            queued[-1][1](
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(len(errors), 2)
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_cover_sheet_bulk_delete_closes_without_modal_or_input_residue(self):
        data = _cover_sheet_data()
        data.pages_without_folder = [
            CoverSheetPage(
                uid=str(index),
                sheet_no=f"A{index:03d}",
                name=f"Page {index}",
                width=42.0,
                height=30.0,
                scale_factor1=0.125,
                scale_factor2=12.0,
                image_path=f"C:/Plans/{index}.pdf",
                overlay_image_path="",
                index=1,
                show_mode=0,
            )
            for index in range(1, 226)
        ]
        parent = QtWidgets.QWidget()
        parent.show()
        dialog = CoverSheetDialog(_FakeIconProvider(), parent, data)

        def delete_and_accept():
            dialog.plan_tree.selectAll()
            dialog._delete_selected()
            dialog.accept()

        try:
            QtCore.QTimer.singleShot(0, delete_and_accept)
            result = dialog.exec()
            self.app.processEvents()
            visible_modals = [
                widget
                for widget in self.app.topLevelWidgets()
                if widget.isModal() and widget.isVisible()
            ]
            self.assertEqual(result, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(len(dialog._deleted_page_uids), 225)
            self.assertEqual(dialog.plan_tree.topLevelItemCount(), 1)
            self.assertTrue(parent.isEnabled())
            self.assertIsNone(self.app.activeModalWidget())
            self.assertEqual(visible_modals, [])
            self.assertIsNone(self.app.overrideCursor())
        finally:
            dialog.deleteLater()
            parent.close()
            parent.deleteLater()

    def test_cover_sheet_bulk_delete_uses_one_transaction_and_linear_cascade(self):
        ops = _BulkDeleteCoverSheetOps()
        page_count = 225
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "deleted_page_uids": [str(index) for index in range(1, page_count + 1)],
                "pages": [],
            },
        )
        per_page_statement_count = (
            4  # owner lookup plus MasterPage, comment, and takeoff reference scans
            + 1  # BidPercents
            + len(TAKEOFF_REFERENCE_TABLES) * len(TAKEOFF_ANNOTATION_REFERENCE_COLUMNS)
            + len(PAGE_DELETE_CHILD_TABLES)
            + 1  # BidTakeoffs
            + 2  # BidHotLinks
            + 1  # BidNamedViews
            + 1  # indirect typical-group-view dependents
            + 1  # selected-page reference
            + 1  # page-typed Cover Sheet selection
            + 1  # BidPages
        )
        self.assertTrue(success)
        self.assertEqual(ops.conn.enter_count, 1)
        self.assertEqual(ops.conn.exit_count, 1)
        self.assertEqual(
            len(ops.conn.cursor_obj.calls),
            4 + page_count * per_page_statement_count,
        )

    def test_cover_sheet_close_publishes_one_refresh_for_bulk_delete(self):
        calls = []

        class WriteGuard:
            def blocks_active_locked_bid_write(self, *_args):
                return False

        class SaveCoverSheet:
            def execute(self, db_path, bid_uid, updates):
                calls.append(("save", db_path, bid_uid, updates))
                return True

        class EventBus:
            def publish(self, event_type, **payload):
                calls.append(("publish", event_type, payload))

        class ReadService:
            def get_cover_sheet_data(self, _file_path, _bid_uid):
                return _cover_sheet_data()

            def get_employee_uids_in_use(self, _file_path):
                return set()

            def get_pages_with_takeoffs(self, _file_path, _bid_uid):
                return set()

            def get_pages_with_delete_content(self, _file_path, _bid_uid):
                return set()

        class ProjectData:
            def is_current_bid_locked(self):
                return False

            def get_assigned_area_uids_with_stored_takeoff(self):
                return set()

        class UiState:
            def get_selected_bid_ref(self):
                return BidRef("bid.mdb", "7")

        class Access:
            def is_allowed(self, _feature):
                return True

            def has_license(self):
                return True

        class DeferredPersistence:
            def flush_for_file(self, file_path):
                calls.append(("flush", file_path))
                return True

        class Infrastructure:
            def get_pdf_page_sizes(self, _path):
                return []

        class FakeDialog(_FakeCoverSheetDialog):
            def get_updates(self):
                return {"deleted_page_uids": [str(index) for index in range(1, 226)]}

        event_bus = EventBus()
        write_service = ProjectWriteService.__new__(ProjectWriteService)
        write_service.uses_sql_collaboration_mutations = lambda _database_id: False
        write_service._bid_write_guard = WriteGuard()
        write_service._save_cover_sheet = SaveCoverSheet()
        write_service._reload_database = (
            lambda file_path: calls.append(("reload", file_path)) or True
        )
        write_service._event_bus = event_bus
        write_service.logger = mock.Mock()
        write_service._mutation_executor = SimpleNamespace(
            execute=lambda request, operation: DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(
                    SimpleNamespace(
                        record=lambda resource, change_operation, *, changed_fields=(), payload="": None
                    )
                ),
            )
        )
        write_service._session_registry = SimpleNamespace(
            get=lambda _database_id: "",
            lock_tokens=lambda _database_id, _resources: (),
        )
        write_service._concurrency_tokens = SimpleNamespace(
            mutation_scope=lambda _database_id: nullcontext(),
            ensure_resources_loaded=lambda _database_id, _resources: None,
            expected_versions=lambda _database_id, _resources: (),
            apply_result=lambda _database_id, _versions: None,
        )
        write_service._database_capability_service = SimpleNamespace(
            is_editable=lambda _locator, resource=None: True
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=write_service,
            infrastructure_provider=Infrastructure(),
            event_bus=event_bus,
            ui_state_manager=UiState(),
            ui_access_manager=Access(),
            deferred_persistence_manager=DeferredPersistence(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(
            module, "CoverSheetDialog", FakeDialog
        ), mock.patch.object(
            module,
            "exec_with_ost_blocking",
            return_value=QtWidgets.QDialog.DialogCode.Accepted,
        ):
            handler.open_cover_sheet()
        self.assertEqual([call[0] for call in calls].count("save"), 1)
        self.assertEqual([call[0] for call in calls].count("flush"), 1)
        self.assertEqual([call[0] for call in calls].count("reload"), 1)
        publish_calls = [call for call in calls if call[0] == "publish"]
        self.assertEqual(len(publish_calls), 1)
        self.assertIs(publish_calls[0][1], AppEvents.DATABASE_REFRESHED)
        self.assertEqual(publish_calls[0][2], {"file_path": "bid.mdb"})
        self.assertTrue(
            all(
                value is None
                for value in FakeDialog.instance.async_save_functions.values()
            )
        )
        self.assertTrue(FakeDialog.instance.deleted)

    def test_cover_sheet_path_cell_double_click_edits_full_path(self):
        image_path = r"C:\Plans\A101.pdf"
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(image_path=image_path),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            editor = _path_editor(dialog, item, 4)
            event = _FakeMouseEvent()
            self.assertEqual(editor.text(), "A101.pdf")
            editor.mouseDoubleClickEvent(event)
            self.assertTrue(event.accepted)
            self.assertEqual(editor.text(), image_path)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_sql_add_blank_page_uses_hydrated_cover_sheet_without_qt_thread_read(self):
        queued = []
        data = _cover_sheet_data()

        class ProjectData:
            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_cover_sheet_snapshot(database_id, bid_uid):
                self.assertEqual((database_id, bid_uid), ("sql-database", "7"))
                return data

        class ReadService:
            @staticmethod
            def get_cover_sheet_data(*_args):
                raise AssertionError("SQL cover-sheet reads must use hydrated state")

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                queued.append((database_id, bid_uid, updates, callback))
                return 1

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(),
            event_bus=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("sql-database", "7")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(module, "confirm", return_value=True):
            self.assertTrue(handler.add_blank_page_from_takeoff_tab())
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][:2], ("sql-database", "7"))
        self.assertEqual(len(queued[0][2]["pages"]), 1)

    def test_mdb_add_blank_page_uses_cover_sheet_save_workflow(self):
        saved = []
        data = _cover_sheet_data()
        data.job_status_uid = ""
        data.estimator_uid = ""
        data.bid_date = ""
        data.bid_no = ""

        class ProjectData:
            @staticmethod
            def is_current_bid_locked():
                return False

        class ReadService:
            @staticmethod
            def get_cover_sheet_data(database_id, bid_uid):
                self.assertEqual((database_id, bid_uid), ("bid.mdb", "7"))
                return data

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def save_cover_sheet(database_id, bid_uid, updates):
                saved.append((database_id, bid_uid, updates))
                return True

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(),
            event_bus=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _database_id: True
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(module, "confirm", return_value=True):
            self.assertTrue(handler.add_blank_page_from_takeoff_tab())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][:2], ("bid.mdb", "7"))
        self.assertEqual(saved[0][2]["job_status_uid"], "")
        self.assertEqual(len(saved[0][2]["pages"]), 1)

    def test_unlocked_sql_cover_sheet_invokes_async_save_instead_of_returning_it(self):
        queued = []
        callback_results = []
        nested_results = []
        requested_leases = []
        released_leases = []
        data = _cover_sheet_data()

        class ProjectData:
            @staticmethod
            def get_cover_sheet_snapshot(_database_id, _bid_uid):
                return data

            @staticmethod
            def get_job_status_snapshot(_database_id):
                return data.job_statuses

            @staticmethod
            def get_employee_snapshot(_database_id):
                return data.employees

            @staticmethod
            def get_pay_class_snapshot(_database_id):
                return data.pay_classes

            @staticmethod
            def get_used_job_status_uids(_database_id):
                return set()

            @staticmethod
            def get_used_employee_uids(_database_id):
                return set()

            @staticmethod
            def get_bid_area_snapshot():
                return []

            @staticmethod
            def get_all_pages():
                return []

            @staticmethod
            def get_page_delete_content_snapshot(_database_id, _bid_uid):
                return set()

            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_assigned_area_uids_with_stored_takeoff():
                return set()

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_cover_sheet_save(
                database_id,
                bid_uid,
                updates,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append(
                    (database_id, bid_uid, updates, callback, edit_lease_handle)
                )
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="49350e91-a3b8-42fa-b6f4-9a30dd997516",
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        authoritative_result=AuthoritativeMutationResult(),
                    )
                )
                return 1

            @staticmethod
            def queue_job_statuses_save(
                database_id,
                changes,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append((database_id, None, changes, callback, edit_lease_handle))
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="28ff5cd9-3cdb-4af0-9d6a-6ea5097ea887",
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        authoritative_result=AuthoritativeMutationResult(
                            affected_families=("job_statuses",)
                        ),
                    )
                )
                return 1

        class FakeDialog(_FakeCoverSheetDialog):
            pass

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=SimpleNamespace(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(
                get_pdf_page_sizes=lambda _path: []
            ),
            event_bus=EventBus(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("sql-database", "7")
            ),
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True,
                has_license=lambda: True,
            ),
            deferred_persistence_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )

        class LeaseCoordinator:
            @staticmethod
            def request_collaboration_edit(
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id=f"draft-{len(requested_leases) + 1}",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=resources,
                    dependency_resources=dependency_resources,
                )
                requested_leases.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(handle):
                released_leases.append(handle)

        handler.set_ui_event_coordinator(LeaseCoordinator())
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        def execute_dialog(dialog, _event_bus):
            nested_save = dialog.async_save_functions["save_job_statuses_async_fn"]
            callback_results.append(
                nested_save(
                    {
                        "new": [],
                        "updated": [],
                        "deleted_uids": ["status-1"],
                    },
                    lambda success, mapping: nested_results.append((success, mapping)),
                )
            )
            callback_results.append(
                dialog.save_async({"notes": "Updated"}, lambda _success: None)
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with (
            mock.patch.object(module, "CoverSheetDialog", FakeDialog),
            mock.patch.object(
                module, "exec_with_ost_blocking", side_effect=execute_dialog
            ),
        ):
            handler.open_cover_sheet()
        self.assertEqual(callback_results, [True, True])
        self.assertEqual(nested_results, [(True, {})])
        self.assertEqual(len(queued), 2)
        self.assertEqual(queued[1][:3], ("sql-database", "7", {"notes": "Updated"}))
        self.assertEqual(len(requested_leases), 3)
        self.assertIs(queued[0][4], requested_leases[0])
        self.assertIs(queued[1][4], requested_leases[1])
        self.assertEqual(released_leases, [requested_leases[2]])
        self.assertIn(
            "cover_sheet",
            {resource.resource_type for resource in requested_leases[0].resources},
        )

    def test_new_project_cover_sheet_lease_owns_target_and_nested_master_data(self):
        requested = []
        released = []

        class LeaseCoordinator:
            @staticmethod
            def request_collaboration_edit(
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id="new-project-dialog",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=resources,
                    dependency_resources=dependency_resources,
                )
                requested.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(handle):
                released.append(handle)

        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler._ui_event_coordinator = LeaseCoordinator()
        handler._event_bus = EventBus()
        data = _cover_sheet_data()
        data.job_statuses = [SimpleNamespace(uid="status-1")]
        data.employees = [SimpleNamespace(uid="employee-1")]
        data.pay_classes = [SimpleNamespace(uid="pay-class-1")]
        session = handler.create_new_bid_lease_session(
            "sql-database", "project-1", data
        )
        session.request_initial(lambda result: self.assertTrue(result.granted))
        session.close()
        self.assertEqual(len(requested), 1)
        resource_keys = {
            (resource.resource_type, resource.resource_id)
            for resource in requested[0].resources
        }
        self.assertTrue(
            {
                ("project_bids", "project-1"),
                ("job_statuses_collection", "database"),
                ("employees_collection", "database"),
                ("pay_classes_collection", "database"),
                ("job_status", "status-1"),
                ("employee", "employee-1"),
                ("pay_class", "pay-class-1"),
            }.issubset(resource_keys)
        )
        self.assertEqual(
            set(requested[0].dependency_resources),
            {
                ResourceRef("default_layers_collection", "database"),
                ResourceRef("project", "project-1"),
            },
        )
        self.assertEqual(released, requested)

    def test_cover_sheet_image_path_cell_accepts_pasted_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "drawing.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(f'"{pdf_path}"')
                editor.editingFinished.emit()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], pdf_path)
                self.assertEqual(page["width"], 25.0)
                self.assertEqual(page["height"], 37.0)
                self.assertEqual(editor.styleSheet(), "")
                self.assertEqual(editor.text(), "drawing.pdf")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_unchanged_missing_pdf_path_preserves_page_index(self):
        missing_path = str(Path(tempfile.gettempdir()) / "missing-indexed-page.pdf")
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(image_path=missing_path, page_index=2),
            pdf_page_sizes_fn=lambda _path: self.fail(
                "A missing PDF must not invoke the metadata provider"
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            editor = _path_editor(dialog, item, 4)
            editor.begin_path_edit()
            editor.setText(missing_path)
            editor.editingFinished.emit()
            self.assertEqual(_first_page_update(dialog)["index"], 2)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_image_path_signal_accepts_multi_page_size_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "multi-page.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [
                    (25.0, 37.0, "Sheet A"),
                    (31.0, 43.0, "Sheet B"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(pdf_path)
                with mock.patch("sys.excepthook") as exception_hook:
                    editor.editingFinished.emit()
                    QtWidgets.QApplication.processEvents()
                exception_hook.assert_not_called()
                pages = dialog.get_updates()["pages"]
                self.assertEqual(
                    [
                        (
                            page["name"],
                            page["index"],
                            page["width"],
                            page["height"],
                            page["image_path"],
                        )
                        for page in pages
                    ],
                    [
                        ("Level 1", 1, 25.0, 37.0, pdf_path),
                        ("multi-page.pdf (2)", 2, 31.0, 43.0, pdf_path),
                    ],
                )
                for row in range(dialog.plan_tree.topLevelItemCount()):
                    combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(row))
                    self.assertEqual(combo.count(), 2)
                    self.assertEqual(
                        [combo.itemText(index) for index in range(combo.count())],
                        ["1", "2"],
                    )
                    self.assertEqual(
                        [
                            combo.itemData(
                                index,
                                QtCore.Qt.ItemDataRole.ToolTipRole,
                            )
                            for index in range(combo.count())
                        ],
                        ["Sheet A", "Sheet B"],
                    )
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_reselecting_same_pdf_does_not_duplicate_page_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "multi-page.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [
                    (25.0, 37.0, "Sheet A"),
                    (31.0, 43.0, "Sheet B"),
                ],
            )
            try:
                editor = _path_editor(dialog, dialog.plan_tree.topLevelItem(0), 4)
                for _ in range(2):
                    editor.begin_path_edit()
                    editor.setText(pdf_path)
                    editor.editingFinished.emit()
                pages = dialog.get_updates()["pages"]
                self.assertEqual(len(pages), 2)
                self.assertEqual(
                    [(page["index"], page["image_path"]) for page in pages],
                    [(1, pdf_path), (2, pdf_path)],
                )
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_pdf_metadata_cache_tracks_file_signature(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "cached.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")

            def page_sizes(path):
                calls.append(Path(path).stat().st_size)
                return [(float(calls[-1]), 30.0, "")]

            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=page_sizes,
            )
            try:
                first = dialog._read_pdf_page_sizes(pdf_path)
                self.assertEqual(dialog._read_pdf_page_sizes(pdf_path), first)
                self.assertEqual(len(calls), 1)
                Path(pdf_path).write_bytes(b"%PDF-1.4\nupdated\n")
                second = dialog._read_pdf_page_sizes(pdf_path)
                self.assertEqual(len(calls), 2)
                self.assertNotEqual(first, second)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_sync_metadata_keeps_exact_loaded_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "drawing.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [],
            )
            loaded = PdfMetadataSnapshot(
                signature=(123, 456),
                page_sizes=((24.0, 36.0, "Page 1"),),
            )
            try:
                with mock.patch.object(
                    dialog._metadata_loader,
                    "load",
                    return_value=loaded,
                ):
                    dialog._on_page_image_changed(
                        "p1",
                        "image_path",
                        pdf_path,
                    )
                row = dialog._page_rows["p1"]
                self.assertEqual(row.metadata_signature, loaded.signature)
                self.assertEqual(row.pdf_page_sizes, loaded.page_sizes)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_raster_path_signal_uses_image_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = str(Path(tmp) / "drawing.png")
            image = QtGui.QImage(960, 480, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtCore.Qt.GlobalColor.white)
            self.assertTrue(image.save(image_path))
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: self.fail(
                    "Raster images must not use the PDF page-size provider"
                ),
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(image_path)
                with mock.patch("sys.excepthook") as exception_hook:
                    editor.editingFinished.emit()
                    QtWidgets.QApplication.processEvents()
                exception_hook.assert_not_called()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertAlmostEqual(page["width"], 10.0, delta=0.01)
                self.assertAlmostEqual(page["height"], 5.0, delta=0.01)
                combo = _index_combo(dialog, item)
                self.assertEqual(combo.count(), 1)
                page_index, width, height = combo.currentData()
                self.assertEqual(page_index, 1)
                self.assertAlmostEqual(width, 10.0, delta=0.01)
                self.assertAlmostEqual(height, 5.0, delta=0.01)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_raster_import_uses_image_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = str(Path(tmp) / "drawing.png")
            image = QtGui.QImage(960, 480, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtCore.Qt.GlobalColor.white)
            self.assertTrue(image.save(image_path))
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: self.fail(
                    "Raster imports must not use the PDF page-size provider"
                ),
            )
            try:
                sizes = dialog._read_import_page_sizes(image_path)
                self.assertEqual(len(sizes), 1)
                self.assertAlmostEqual(sizes[0][0], 10.0, delta=0.01)
                self.assertAlmostEqual(sizes[0][1], 5.0, delta=0.01)
                self.assertEqual(sizes[0][2], "")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_pdf_provider_signature_errors_are_not_hidden(self):
        def invalid_provider(_path, _obsolete_page_index):
            return []

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "drawing.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=invalid_provider,
            )
            try:
                with self.assertRaises(TypeError):
                    dialog._read_pdf_page_sizes(pdf_path)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_empty_pdf_result_does_not_retry_same_provider(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "unreadable.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(pdf_path)
                editor.editingFinished.emit()
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(_first_page_update(dialog)["image_path"], pdf_path)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_directory_path_is_missing_image_not_pdf(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            pasted_path = str(Path(tmp)) + os.sep
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(f'"{pasted_path}"')
                editor.editingFinished.emit()
                self.assertEqual(_first_page_update(dialog)["image_path"], pasted_path)
                self.assertIn("color:", editor.styleSheet())
                self.assertEqual(editor.text(), Path(pasted_path).name)
                self.assertEqual(calls, [])
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_path_browse_and_clear_keep_image_paths_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = str(Path(tmp) / "drawing.pdf")
            overlay_path = str(Path(tmp) / "overlay.pdf")
            Path(image_path).write_bytes(b"%PDF-1.4\n")
            Path(overlay_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                image_browse, image_clear = _path_buttons(dialog, item, 4)
                overlay_browse, overlay_clear = _path_buttons(dialog, item, 5)
                with mock.patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    side_effect=[
                        (image_path, ""),
                        (overlay_path, ""),
                    ],
                ):
                    image_browse.click()
                    overlay_browse.click()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(page["overlay_path"], overlay_path)
                self.assertEqual(_path_editor(dialog, item, 4).text(), "drawing.pdf")
                self.assertEqual(_path_editor(dialog, item, 5).text(), "overlay.pdf")
                overlay_clear.click()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(page["overlay_path"], "")
                self.assertEqual(_path_editor(dialog, item, 5).text(), "")
                image_clear.click()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], "")
                self.assertEqual(page["overlay_path"], "")
                self.assertEqual(_path_editor(dialog, item, 4).text(), "")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_clearing_overlay_only_cover_sheet_row_immediately_owns_original_mode(
        self,
    ):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(
                image_path=r"C:\Plans\original.pdf",
                overlay_image_path=r"C:\Plans\overlay.pdf",
                show_mode=1,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            _overlay_browse, overlay_clear = _path_buttons(dialog, item, 5)
            overlay_clear.click()
            page_update = _first_page_update(dialog)
            self.assertEqual(page_update["overlay_path"], "")
            self.assertEqual(page_update["show_mode"], 0)
            self.assertEqual(item.text(dialog._SHOW_COLUMN), "Original")
            self.assertEqual(
                dialog._show_options("p1"),
                [("Original", 0, None)],
            )
            page = Page(
                uid="p1",
                name="Level 1",
                image_path=page_update["image_path"],
                overlay_image_path=None,
                image_show_mode=page_update["show_mode"],
                width_pts=3024.0,
                height_pts=2160.0,
            )
            strategy = PageLoadStrategyService(
                SimpleNamespace(get_page_size=lambda _path, _index: (3024.0, 2160.0))
            ).determine_load_strategy(page)
            self.assertTrue(strategy.load_main)
            self.assertFalse(strategy.load_overlay)
            self.assertFalse(strategy.load_composite)
            menu = QtWidgets.QMenu(dialog)
            _select_action, overlay_action, original_action = (
                add_overlay_submenu_with_select(
                    menu,
                    page.image_show_mode,
                    lambda: None,
                    True,
                    page.has_overlay,
                )
            )
            self.assertFalse(overlay_action.isEnabled())
            self.assertTrue(original_action.isChecked())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_overlay_on_page_without_original_owns_overlay_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay_path = str(Path(tmp) / "overlay.pdf")
            Path(overlay_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                overlay_browse, _overlay_clear = _path_buttons(dialog, item, 5)
                with mock.patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    return_value=(overlay_path, ""),
                ):
                    overlay_browse.click()
                page_update = _first_page_update(dialog)
                self.assertEqual(page_update["image_path"], "")
                self.assertEqual(page_update["overlay_path"], overlay_path)
                self.assertEqual(page_update["show_mode"], 1)
                self.assertEqual(item.text(dialog._SHOW_COLUMN), "Overlay")
                self.assertEqual(
                    dialog._show_options("p1"),
                    [("Overlay", 1, None)],
                )
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_clearing_original_from_show_both_row_owns_overlay_mode(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(
                image_path=r"C:\Plans\original.pdf",
                overlay_image_path=r"C:\Plans\overlay.pdf",
                show_mode=2,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            _image_browse, image_clear = _path_buttons(dialog, item, 4)
            image_clear.click()
            page_update = _first_page_update(dialog)
            self.assertEqual(page_update["image_path"], "")
            self.assertEqual(page_update["overlay_path"], r"C:\Plans\overlay.pdf")
            self.assertEqual(page_update["show_mode"], 1)
            self.assertEqual(item.text(dialog._SHOW_COLUMN), "Overlay")
            self.assertEqual(
                dialog._show_options("p1"),
                [("Overlay", 1, None)],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_cancelled_browse_preserves_current_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = str(Path(tmp) / "drawing.pdf")
            Path(image_path).write_bytes(b"%PDF-1.4\n")
            dialog = CoverSheetDialog(
                _FakeIconProvider(),
                None,
                _cover_sheet_data(image_path=image_path),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                image_browse, _image_clear = _path_buttons(dialog, item, 4)
                with mock.patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    return_value=("", ""),
                ):
                    image_browse.click()
                page = _first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(_path_editor(dialog, item, 4).text(), "drawing.pdf")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_nested_authoritative_master_changes_preserve_cover_sheet_context(self):
        for kind in ("employee", "job_status"):
            for operation in (
                "rename",
                "delete_current",
                "delete_sibling",
                "delete_unrelated",
            ):
                with self.subTest(kind=kind, operation=operation):
                    data = _cover_sheet_data_with_pages(50)
                    data.employees = [
                        Employee(uid=uid, first_name=name)
                        for uid, name in (("1", "Same"), ("2", "Same"), ("3", "Other"))
                    ]
                    data.job_statuses = [
                        JobStatus(uid=uid, name=name)
                        for uid, name in (("1", "Same"), ("2", "Same"), ("3", "Other"))
                    ]
                    data.estimator_uid = data.job_status_uid = "2"
                    authoritative = (
                        data.employees if kind == "employee" else data.job_statuses
                    )
                    saves, reloads, errors = [], [], []

                    def save(changes):
                        saves.append(changes)
                        authoritative[:] = [
                            row
                            for row in authoritative
                            if row.uid not in changes["deleted_uids"]
                        ]
                        for update in changes["updated"]:
                            uid = update.uid if kind == "employee" else update["uid"]
                            row = next(row for row in authoritative if row.uid == uid)
                            if kind == "employee":
                                row.first_name = update.first_name
                            else:
                                row.name = update["name"]
                        return {}

                    dialog = CoverSheetDialog(
                        _FakeIconProvider(),
                        None,
                        data,
                        save_employees_fn=save,
                        save_job_statuses_fn=save,
                        reload_employees_fn=lambda: reloads.append(kind)
                        or (list(authoritative), data.pay_classes),
                        reload_job_statuses_fn=lambda: reloads.append(kind)
                        or list(authoritative),
                    )

                    def edit_nested():
                        child = dialog._active_sub_dialog
                        try:
                            if operation == "rename":
                                if kind == "employee":
                                    record = next(
                                        row
                                        for row in child._employees
                                        if row.uid == "2"
                                    )
                                    record.first_name = "Renamed"
                                    child._populate(select_uid="2")
                                else:
                                    child.tree.currentItem().setText(1, "Renamed")
                                child.accept()
                            else:
                                uid = {
                                    "delete_current": "2",
                                    "delete_sibling": "1",
                                    "delete_unrelated": "3",
                                }[operation]
                                column = 0 if kind == "employee" else 1
                                item = next(
                                    child.tree.topLevelItem(i)
                                    for i in range(child.tree.topLevelItemCount())
                                    if child.tree.topLevelItem(i).data(
                                        column, child._UID_ROLE
                                    )
                                    == uid
                                )
                                child.tree.setCurrentItem(item)
                                module = (
                                    "employees_dialog" if kind == "employee" else None
                                )
                                confirm_path = (
                                    f"ost_visualizer.presentation.dialogs.{module}.confirm_multi_delete"
                                    if module
                                    else "ost_visualizer.presentation.utils.dialog.confirm_multi_delete"
                                )
                                with mock.patch(
                                    confirm_path,
                                    return_value=[(item.text(column), uid)],
                                ):
                                    child._on_delete()
                                child.reject()
                        except BaseException as exc:
                            errors.append(exc)
                        finally:
                            if child.isVisible():
                                child.reject()

                    try:
                        dialog.show()
                        self.app.processEvents()
                        dialog.edit_project_name.setText("Unsaved project")
                        dialog.edit_notes.setPlainText("Unsaved notes")
                        dialog.plan_tree.setCurrentItem(
                            dialog.plan_tree.topLevelItem(20)
                        )
                        dialog.plan_tree.topLevelItem(22).setSelected(True)
                        dialog.plan_tree.verticalScrollBar().setValue(10)
                        selected = list(dialog.plan_tree.selectedItems())
                        current = dialog.plan_tree.currentItem()
                        scroll = dialog.plan_tree.verticalScrollBar().value()
                        QtCore.QTimer.singleShot(0, edit_nested)
                        if kind == "employee":
                            dialog._btn_employees.click()
                            combo = dialog.combo_estimator
                        else:
                            dialog._btn_job_status_picker.click()
                            combo = dialog.combo_job_status
                        if errors:
                            raise errors[0]
                        expected_uid = "" if operation == "delete_current" else "2"
                        expected_label = (
                            "Renamed"
                            if operation == "rename"
                            else "Same" if expected_uid else ""
                        )
                        self.assertEqual(combo.currentData() or "", expected_uid)
                        self.assertEqual(combo.currentText(), expected_label)
                        self.assertEqual(
                            dialog.edit_project_name.text(), "Unsaved project"
                        )
                        self.assertEqual(
                            dialog.edit_notes.toPlainText(), "Unsaved notes"
                        )
                        self.assertEqual(dialog.plan_tree.selectedItems(), selected)
                        self.assertIs(dialog.plan_tree.currentItem(), current)
                        self.assertEqual(
                            dialog.plan_tree.verticalScrollBar().value(), scroll
                        )
                        self.assertEqual(len(saves), 1)
                        self.assertEqual(reloads, [kind])
                    finally:
                        dialog.close()
                        dialog.deleteLater()

    def test_nested_picker_cancel_preserves_cover_sheet_combo_and_page_drafts(self):
        for kind in ("employee", "job_status"):
            for draft in ("Typed unsaved value", ""):
                with self.subTest(kind=kind, draft=draft):
                    data = _cover_sheet_data_with_pages(50)
                    data.employees = [
                        Employee(uid="e1", first_name="Alice"),
                        Employee(uid="e2", first_name="Alice"),
                    ]
                    data.estimator_uid = "e2"
                    data.job_statuses = [
                        JobStatus(uid="s1", name="Open"),
                        JobStatus(uid="s2", name="Open"),
                    ]
                    data.job_status_uid = "s2"
                    reloads = []
                    dialog = CoverSheetDialog(
                        _FakeIconProvider(),
                        None,
                        data,
                        reload_employees_fn=lambda: reloads.append("employee")
                        or (list(data.employees), data.pay_classes),
                        reload_job_statuses_fn=lambda: reloads.append("job_status")
                        or list(data.job_statuses),
                    )
                    errors = []

                    def cancel_nested():
                        child = dialog._active_sub_dialog
                        try:
                            child.tree.setCurrentItem(child.tree.topLevelItem(0))
                        except BaseException as exc:
                            errors.append(exc)
                        finally:
                            child.reject()

                    try:
                        dialog.show()
                        self.app.processEvents()
                        combo = (
                            dialog.combo_estimator
                            if kind == "employee"
                            else dialog.combo_job_status
                        )
                        combo.setEditText(draft)
                        original_uid = combo.currentData()
                        dialog.edit_project_name.setText("Unsaved project")
                        dialog.edit_notes.setPlainText("Unsaved notes")
                        dialog.plan_tree.setCurrentItem(
                            dialog.plan_tree.topLevelItem(20)
                        )
                        dialog.plan_tree.topLevelItem(22).setSelected(True)
                        dialog.plan_tree.verticalScrollBar().setValue(10)
                        selected = list(dialog.plan_tree.selectedItems())
                        current = dialog.plan_tree.currentItem()
                        scroll = dialog.plan_tree.verticalScrollBar().value()
                        QtCore.QTimer.singleShot(0, cancel_nested)
                        if kind == "employee":
                            dialog._btn_employees.click()
                        else:
                            dialog._btn_job_status_picker.click()
                        if errors:
                            raise errors[0]
                        self.assertEqual(combo.currentText(), draft)
                        self.assertEqual(combo.currentData(), original_uid)
                        self.assertEqual(
                            dialog.edit_project_name.text(), "Unsaved project"
                        )
                        self.assertEqual(
                            dialog.edit_notes.toPlainText(), "Unsaved notes"
                        )
                        self.assertEqual(dialog.plan_tree.selectedItems(), selected)
                        self.assertIs(dialog.plan_tree.currentItem(), current)
                        self.assertEqual(
                            dialog.plan_tree.verticalScrollBar().value(), scroll
                        )
                        self.assertEqual(reloads, [kind])
                    finally:
                        dialog.close()
                        dialog.deleteLater()

    def test_employee_picker_cancel_restores_existing_estimator_selection(self):
        data = _cover_sheet_data()
        data.estimator_uid = "emp-1"
        data.employees = [
            Employee(uid="emp-1", first_name="Alice", last_name="Estimator"),
            Employee(uid="emp-2", first_name="Bob", last_name="Estimator"),
        ]

        class CancelEmployeesDialog:
            def __init__(self, *_args, **_call_options):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            data,
            reload_employees_fn=lambda: (list(data.employees), data.pay_classes),
        )
        try:
            dialog.combo_estimator.blockSignals(True)
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            old_dialog = module.EmployeesDialog
            module.EmployeesDialog = CancelEmployeesDialog
            try:
                dialog._open_employees_dialog()
            finally:
                module.EmployeesDialog = old_dialog
            self.assertEqual(dialog.combo_estimator.currentData(), "emp-1")
            self.assertEqual(dialog.combo_estimator.currentText(), "Alice Estimator")
            self.assertTrue(dialog.combo_estimator.signalsBlocked())
        finally:
            dialog.combo_estimator.blockSignals(False)
            dialog.close()
            dialog.deleteLater()

    def test_job_status_picker_reselects_duplicate_name_by_uid(self):
        data = _cover_sheet_data()
        data.job_status_uid = "status-1"
        data.job_statuses = [
            JobStatus(uid="status-1", name="Open"),
            JobStatus(uid="status-2", name="Open"),
        ]

        class AcceptedJobStatusesDialog:
            def __init__(self, *_args, **_call_options):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_result(self):
                return PickerDialogResult(
                    selected_uid="status-2",
                    items=list(data.job_statuses),
                )

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            data,
            reload_job_statuses_fn=lambda: list(data.job_statuses),
        )
        try:
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            with mock.patch.object(
                module,
                "JobStatusesDialog",
                AcceptedJobStatusesDialog,
            ):
                dialog._open_job_statuses_dialog()
            self.assertEqual(dialog.combo_job_status.currentData(), "status-2")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_employee_picker_reselects_duplicate_display_name_by_uid(self):
        data = _cover_sheet_data()
        data.estimator_uid = "emp-1"
        data.employees = [
            Employee(uid="emp-1", first_name="Alex", last_name="Smith"),
            Employee(uid="emp-2", first_name="Alex", last_name="Smith"),
        ]

        class AcceptedEmployeesDialog:
            def __init__(self, *_args, **_call_options):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_result(self):
                return PickerDialogResult(
                    selected_uid="emp-2",
                    items=list(data.employees),
                )

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            data,
            reload_employees_fn=lambda: (list(data.employees), data.pay_classes),
        )
        try:
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            with mock.patch.object(
                module,
                "EmployeesDialog",
                AcceptedEmployeesDialog,
            ):
                dialog._open_employees_dialog()
            self.assertEqual(dialog.combo_estimator.currentData(), "emp-2")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_save_preserves_selected_duplicate_master_uids(self):
        data = _cover_sheet_data()
        data.job_status_uid = "2"
        data.estimator_uid = "12"
        data.job_statuses = [
            JobStatus(uid="1", name="Open"),
            JobStatus(uid="2", name="Open"),
        ]
        data.employees = [
            Employee(uid="11", first_name="Alex", last_name="Smith"),
            Employee(uid="12", first_name="Alex", last_name="Smith"),
        ]
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            updates = dialog.get_updates()
            self.assertEqual(updates["job_status_uid"], 2)
            self.assertEqual(updates["estimator_uid"], 12)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_rejects_typed_ambiguous_master_name(self):
        data = _cover_sheet_data()
        data.job_statuses = [
            JobStatus(uid="1", name="Open"),
            JobStatus(uid="2", name="Open"),
        ]
        dialog = CoverSheetDialog(_FakeIconProvider(), None, data)
        try:
            dialog.combo_job_status.setCurrentIndex(-1)
            dialog.combo_job_status.setEditText("Open")
            with mock.patch(
                "ost_visualizer.presentation.dialogs.cover_sheet.dialog.show_warning"
            ) as warning:
                dialog._on_ok()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            warning.assert_called_once()
            self.assertIn("matches more than one item", warning.call_args.args[2])
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_employee_picker_return_stops_after_cover_sheet_is_destroyed(self):
        data = _cover_sheet_data()
        reloads = []

        class DestroyingEmployeesDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_call_options):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            data,
            reload_employees_fn=lambda: reloads.append(True)
            or (list(data.employees), data.pay_classes),
        )
        from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

        with mock.patch.object(
            module,
            "EmployeesDialog",
            DestroyingEmployeesDialog,
        ):
            dialog._open_employees_dialog()
        self.assertEqual(reloads, [])


if __name__ == "__main__":
    unittest.main()
