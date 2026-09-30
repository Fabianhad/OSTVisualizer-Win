import os
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    DatabaseMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
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
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CHILD_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
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
from ost_visualizer.presentation.dtos.picker_dialog_result_dto import PickerDialogResult
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.utils.overlay_context_menu import (
    add_overlay_submenu_with_select,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import (
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
        employee_usage_fn=None,
        pay_class_usage_fn=None,
        job_status_usage_fn=None,
        event_bus=None,
        database_id="",
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
