import os
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from copy import deepcopy
from pathlib import Path
from unittest import mock
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.dtos.collaboration_dtos import DatabaseMutationResult
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
)
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_REFERENCE_TABLES,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.dialogs.cover_sheet.header_state import (
    load_cover_sheet_plan_header_state,
    save_cover_sheet_plan_header_state,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _FakeSchema:
    def column_exists(self, table, column):
        return table == "Bids" and column == "MeasureBase"

    def optional_table_missing(self, _table):
        return False


class _FakeCursor:
    def __init__(self):
        self.connection = object()
        self.last_query = None
        self.calls = []
        self.current_overlay_path = ""

    def execute(self, query, *args):
        self.last_query = query
        self.calls.append((query, args))
        return None

    def fetchone(self):
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

    def __exit__(self, *args):
        self.exit_count += 1
        self.exit_args.append(args)
        return False

    def cursor(self):
        return self.cursor_obj


class _CoverSheetSettingsOps(SettingsOperationsMixin, PageOperationsMixin):
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
        return None

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
        return None

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
        return None

    def warning(self, *_args):
        return None


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
    ):
        super().__init__()
        self.current_overlay_path = current_overlay_path
        self.scale_factor1 = scale_factor1
        self.scale_factor2 = scale_factor2
        self.overlay_rect = overlay_rect

    def fetchone(self):
        if (
            self.last_query
            and "SELECT [Width], [Height], [ScaleFactor1], [ScaleFactor2], "
            "[OverlayImagePath]" in self.last_query
        ):
            return SimpleNamespace(
                Width=42.0,
                Height=30.0,
                ScaleFactor1=self.scale_factor1,
                ScaleFactor2=self.scale_factor2,
                OverlayImagePath=self.current_overlay_path,
            )
        if (
            self.last_query
            and "SELECT [ScaleFactor1], [ScaleFactor2]" in self.last_query
        ):
            return [self.scale_factor1, self.scale_factor2]
        if self.last_query and "SELECT [OverlayRect]" in self.last_query:
            return [self.overlay_rect]
        return super().fetchone()


class _OverlayRectConnection(_FakeConnection):
    def __init__(self, **cursor_options):
        super().__init__()
        self.cursor_obj = _OverlayRectCursor(**cursor_options)


class _PageOverlayOps(PageOperationsMixin):
    def __init__(self, current_overlay_path=""):
        self.conn = _OverlayRectConnection(current_overlay_path=current_overlay_path)
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
        return None

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
        return None


class _FakeMouseEvent:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True


class _FakeWorkspaceStateModel:
    def __init__(self, state=None):
        self._state = deepcopy(state or WorkspaceState())

    @property
    def state(self):
        return deepcopy(self._state)

    def update_state(self, state):
        self._state = deepcopy(state)


def _cover_sheet_data(
    *,
    image_path="",
    overlay_image_path="",
    scale_factor1=0.125,
    scale_factor2=12.0,
    page_index=1,
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
                show_mode=0,
            )
        ],
    )


def _path_editor(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChild(QtWidgets.QLineEdit)


def _path_buttons(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChildren(QtWidgets.QPushButton)


def _index_combo(dialog, item):
    return dialog.plan_tree.itemWidget(item, 6)


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
        self.assertIs(result, True)

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
                self.assertEqual(item.text(6), "")
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
                combo = _index_combo(dialog, item)
                combo.setCurrentIndex(2)
                QtWidgets.QApplication.processEvents()
                page = _first_page_update(dialog)
                self.assertEqual(page["index"], 3)
                self.assertEqual(page["width"], 35.0)
                self.assertEqual(page["height"], 47.0)
                self.assertEqual(item.text(6), "")
            finally:
                dialog.close()
                dialog.deleteLater()

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
                first_combo.setCurrentIndex(1)
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 2)
                second_combo.setCurrentIndex(0)
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 1)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_and_row_drag_follow_lock_state(self):
        dialog = CoverSheetDialog(_FakeIconProvider(), None, _cover_sheet_data())
        try:
            combo = _index_combo(dialog, dialog.plan_tree.topLevelItem(0))
            dialog._update_lock_state(True)
            self.assertFalse(combo.isEnabled())
            self.assertFalse(dialog.plan_tree.dragEnabled())
            self.assertFalse(dialog.plan_tree.acceptDrops())
            dialog._update_lock_state(False)
            self.assertTrue(combo.isEnabled())
            self.assertTrue(dialog.plan_tree.dragEnabled())
            self.assertTrue(dialog.plan_tree.acceptDrops())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_moved_page_preserves_index_and_widget_state(self):
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
                _index_combo(dialog, item).setCurrentIndex(1)
                before = _first_page_update(dialog)
                dialog._on_tree_items_about_to_move([item])
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
                self.assertEqual(moved_item.text(6), "")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_plan_header_state_restores_width_and_order(self):
        model = _FakeWorkspaceStateModel()
        source = CoverSheetDialog(_FakeIconProvider(), None, _cover_sheet_data())
        try:
            header = source.plan_tree.header()
            header.resizeSection(0, 222)
            header.moveSection(0, 2)
            save_cover_sheet_plan_header_state(model, source.save_plan_header_state())
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

    def test_cover_sheet_plan_header_invalid_state_keeps_default_layout(self):
        state = WorkspaceState()
        state.cover_sheet.plan_header_state_b64 = "not valid base64"
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
            self.assertFalse(
                dialog.restore_plan_header_state(
                    QtCore.QByteArray(b"not a qt header state")
                )
            )
        finally:
            dialog.deleteLater()

    def test_cover_sheet_plan_header_reject_saves_state_to_workspace_key(self):
        model = _FakeWorkspaceStateModel()
        self.assertTrue(load_cover_sheet_plan_header_state(model).isEmpty())
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
        self.assertIsNotNone(model.state.cover_sheet.plan_header_state_b64)
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
        self.assertEqual(page_update["values"]["SheetNo"], "S-100")

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

    def test_cover_sheet_bid_areas_dialog_refreshes_once_after_saved_changes(self):
        captured = {}
        refresh_calls = []

        class CapturingAreasDialog:
            def __init__(self, *_args, **kwargs):
                captured.update(kwargs)

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

    def test_cover_sheet_page_scale_combo_includes_known_non_architectural_scales(self):
        dialog = CoverSheetDialog(
            _FakeIconProvider(),
            None,
            _cover_sheet_data(scale_factor1=1.0, scale_factor2=120.0),
        )
        try:
            page_item = dialog.plan_tree.topLevelItem(0)
            scale_combo = dialog.plan_tree.itemWidget(page_item, 3)
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
            1  # BidPercents
            + len(TAKEOFF_REFERENCE_TABLES)
            + len(PAGE_DELETE_CHILD_TABLES)
            + 1  # BidTakeoffs
            + 2  # BidHotLinks
            + 1  # BidNamedViews
            + 2  # aggregate tables
            + 1  # selected-page reference
            + 1  # BidPages
        )
        self.assertTrue(success)
        self.assertEqual(ops.conn.enter_count, 1)
        self.assertEqual(ops.conn.exit_count, 1)
        self.assertEqual(
            len(ops.conn.cursor_obj.calls),
            1 + page_count * per_page_statement_count,
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

            def get_estimator_uids_in_use(self, _file_path):
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

        class FakeDialog:
            instance = None

            def __init__(self, *_args, **_kwargs):
                self.deleted = False
                FakeDialog.instance = self

            def get_updates(self):
                return {"deleted_page_uids": [str(index) for index in range(1, 226)]}

            def deleteLater(self):
                self.deleted = True

        event_bus = EventBus()
        write_service = ProjectWriteService.__new__(ProjectWriteService)
        write_service._bid_write_guard = WriteGuard()
        write_service._save_cover_sheet = SaveCoverSheet()
        write_service._reload_database = (
            lambda file_path: calls.append(("reload", file_path)) or True
        )
        write_service._event_bus = event_bus
        write_service.logger = mock.Mock()
        write_service._mutation_executor = SimpleNamespace(
            execute=lambda _request, operation: DatabaseMutationResult(
                success=True,
                value=operation(SimpleNamespace(record=lambda *_args, **_kwargs: None)),
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
            is_editable=lambda *_args: True
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
            workspace_state_model=None,
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
            self.assertEqual(_index_combo(dialog, item).currentData()[0], 2)
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
                self.assertIs(dialog._read_pdf_page_sizes(pdf_path), first)
                Path(pdf_path).write_bytes(b"%PDF-1.4\nupdated\n")
                second = dialog._read_pdf_page_sizes(pdf_path)
                self.assertEqual(len(calls), 2)
                self.assertNotEqual(first, second)
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
            from ost_visualizer.presentation.dialogs.cover_sheet import dialog as module

            old_dialog = module.EmployeesDialog
            module.EmployeesDialog = CancelEmployeesDialog
            try:
                dialog._open_employees_dialog()
            finally:
                module.EmployeesDialog = old_dialog
            self.assertEqual(dialog.combo_estimator.currentData(), "emp-1")
            self.assertEqual(dialog.combo_estimator.currentText(), "Alice Estimator")
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
