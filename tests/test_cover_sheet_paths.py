import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
)
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.workspace_state import WorkspaceState
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

    def execute(self, query, *_args):
        self.last_query = query
        return None

    def fetchone(self):
        return [0]


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
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
        self.cursor_obj = _ScaleCursor(old_sf1, old_sf2)


class _ScaleCoverSheetOps(_CoverSheetSettingsOps):
    def __init__(self, old_sf1, old_sf2):
        super().__init__()
        self.conn = _ScaleConnection(old_sf1, old_sf2)
        self.rescale_calls = []

    def _rescale_page_positions(self, _cursor, _schema, page_uid, factor):
        self.rescale_calls.append((page_uid, factor))


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

    def _rescale_page_positions(self, _cursor, _schema, page_uid, factor):
        self.rescale_calls.append((page_uid, factor))


class _FakeLogger:
    def exception(self, *_args):
        return None


class _OverlayRectSchema:
    def column_exists(self, table, column):
        return table == "BidPages" and column in ("OverlayImagePath", "OverlayRect")

    def require_table(self, _table):
        return None

    def require_column(self, _table, _column):
        return None


class _OverlayRectRow:
    Width = 42.0
    Height = 30.0


class _OverlayRectCursor(_FakeCursor):
    def __init__(self):
        super().__init__()
        self.last_query = None

    def execute(self, query, *_args):
        self.last_query = query
        return None

    def fetchone(self):
        if self.last_query and "SELECT [Width], [Height]" in self.last_query:
            return _OverlayRectRow()
        return [0]


class _OverlayRectConnection(_FakeConnection):
    def __init__(self):
        self.cursor_obj = _OverlayRectCursor()


class _PageOverlayOps(PageOperationsMixin):
    def __init__(self):
        self.conn = _OverlayRectConnection()
        self.schema = _OverlayRectSchema()
        self.updates = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

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
    *, image_path="", overlay_image_path="", scale_factor1=0.125, scale_factor2=12.0
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
                index=1,
                show_mode=0,
            )
        ],
    )


def _path_editor(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChild(QtWidgets.QLineEdit)


def _path_buttons(dialog, item, column):
    return dialog.plan_tree.itemWidget(item, column).findChildren(QtWidgets.QPushButton)


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
