from tests.presentation.dialogs.cover_sheet.path_support import (
    CoverSheetDialog as _path_support_CoverSheetDialog,
    _FakeIconProvider as _path_support__FakeIconProvider,
    _FakeMouseEvent as _path_support__FakeMouseEvent,
    _FakeWorkspaceStateModel as _path_support__FakeWorkspaceStateModel,
    _ManualRunnablePool as _path_support__ManualRunnablePool,
    _app as _path_support__app,
    _child_labels as _path_support__child_labels,
    _combo_editor as _path_support__combo_editor,
    _cover_sheet_data as _path_support__cover_sheet_data,
    _cover_sheet_data_with_pages as _path_support__cover_sheet_data_with_pages,
    _first_page_update as _path_support__first_page_update,
    _index_combo as _path_support__index_combo,
    _path_buttons as _path_support__path_buttons,
    _path_editor as _path_support__path_editor,
    _select_combo as _path_support__select_combo,
    _top_level_labels as _path_support__top_level_labels,
)
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from shiboken6 import delete
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.dtos.picker_dialog_result_dto import PickerDialogResult
from ost_visualizer.presentation.dialogs.cover_sheet.pdf_metadata_loader import (
    PdfMetadataSnapshot,
)
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from unittest import mock
from pathlib import Path
from copy import deepcopy
import unittest
import time
import threading
import tempfile
import os
from unittest.mock import Mock, patch
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.infrastructure.events.event_bus import EventBus
from PySide6 import QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _DialogCoverSheetPathFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()


class DialogCoverSheetPathTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog: lifecycle and combined contracts."""

    def test_cover_sheet_plan_header_uses_default_layout_without_saved_state(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, _path_support__cover_sheet_data()
        )
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
            data = _path_support__cover_sheet_data(image_path=pdf_path, page_index=2)
            data.pages_without_folder[0].width = 30.0
            data.pages_without_folder[0].height = 42.0
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda _path: page_sizes,
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                combo = _path_support__index_combo(dialog, item)
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
                self.assertEqual(_path_support__first_page_update(dialog)["index"], 2)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_pdf_index_change_updates_page_index_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [
                    (24.0, 36.0, "Cover"),
                    (30.0, 42.0, "Floor Plan"),
                    (35.0, 47.0, "Details"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                combo = _path_support__select_combo(dialog, item, 6, 2)
                QtWidgets.QApplication.processEvents()
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["index"], 3)
                self.assertEqual(page["width"], 35.0)
                self.assertEqual(page["height"], 47.0)
                self.assertEqual(item.text(6), "3")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_metadata_loads_on_demand_without_changing_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _path_support__ManualRunnablePool()
            calls = []
            workspace = _path_support__FakeWorkspaceStateModel()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(
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
                self.assertEqual(
                    _path_support__first_page_update(dialog)["width"], 42.0
                )
                self.assertEqual(
                    _path_support__first_page_update(dialog)["height"], 30.0
                )
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
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["index"], 2)
                self.assertEqual((page["width"], page["height"]), (30.0, 42.0))
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_single_click_starts_one_metadata_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
                pool = _path_support__ManualRunnablePool()
                dialog = _path_support_CoverSheetDialog(
                    _path_support__FakeIconProvider(),
                    None,
                    _path_support__cover_sheet_data(image_path=pdf_path),
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
                pdf_metadata_pool=FailingPool(),
            )
            try:
                combo = _path_support__index_combo(
                    dialog, dialog.plan_tree.topLevelItem(0)
                )
                self.assertIsInstance(combo, QtWidgets.QComboBox)
                self.assertEqual(combo.currentData()[0], 1)
                self.assertEqual(calls, [])
                self.assertIsNone(dialog._page_rows["p1"].pending_metadata_request)
            finally:
                dialog.reject()
                dialog.deleteLater()

    def test_cover_sheet_uses_explicit_falsey_metadata_pool(self):
        class FalseyPool(_path_support__ManualRunnablePool):
            @staticmethod
            def __bool__():
                return False

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = FalseyPool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
            overlay_editor = _path_support__path_editor(dialog, item, 5)
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
            _path_support__path_buttons(dialog, item, 5)[-1].click()
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
        class InstrumentedDialog(_path_support_CoverSheetDialog):
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
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
            _path_support_CoverSheetDialog._replace_combo_items(
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
            data = _path_support__cover_sheet_data(
                image_path=pdf_path,
                multi_page_count=2,
            )
            second = deepcopy(data.pages_without_folder[0])
            second.uid = "p2"
            second.index = 2
            data.pages_without_folder.append(second)
            pool = _path_support__ManualRunnablePool()
            calls = []
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
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
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=old_path),
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
                editor = _path_support__path_editor(dialog, item, 4)
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
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
            data = _path_support__cover_sheet_data(image_path=pdf_path)
            second_page = deepcopy(data.pages_without_folder[0])
            second_page.uid = "p2"
            data.pages_without_folder.append(second_page)
            pool = _path_support__ManualRunnablePool()
            calls = []
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
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
            pool = _path_support__ManualRunnablePool()
            calls = []
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
            pool = _path_support__ManualRunnablePool()

            def fail(_path):
                raise ValueError("invalid PDF")

            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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

            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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

    def test_cover_sheet_uses_persisted_multi_page_count_without_pdf_read(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(multi_page_count=7),
            pdf_page_sizes_fn=lambda _path: self.fail(
                "Persisted multipage count must not require PDF metadata"
            ),
        )
        try:
            self.assertEqual(
                _path_support__first_page_update(dialog)["multi_page_count"], 7
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_rows_have_independent_index_combos_and_share_pdf_metadata(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            data = _path_support__cover_sheet_data(image_path=pdf_path)
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                data,
                pdf_page_sizes_fn=lambda path: calls.append(path) or page_sizes,
            )
            try:
                first_combo = _path_support__index_combo(
                    dialog, dialog.plan_tree.topLevelItem(0)
                )
                second_combo = _path_support__index_combo(
                    dialog, dialog.plan_tree.topLevelItem(1)
                )
                self.assertIsNot(first_combo, second_combo)
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(first_combo.currentData()[0], 1)
                self.assertEqual(second_combo.currentData()[0], 2)
                _path_support__select_combo(
                    dialog, dialog.plan_tree.topLevelItem(0), 6, 1
                )
                first_combo = _path_support__index_combo(
                    dialog, dialog.plan_tree.topLevelItem(0)
                )
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 2)
                _path_support__select_combo(
                    dialog, dialog.plan_tree.topLevelItem(1), 6, 0
                )
                second_combo = _path_support__index_combo(
                    dialog, dialog.plan_tree.topLevelItem(1)
                )
                self.assertEqual(first_combo.currentData()[0], 2)
                self.assertEqual(second_combo.currentData()[0], 1)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_index_and_row_drag_follow_lock_state(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, _path_support__cover_sheet_data()
        )
        try:
            dialog._update_lock_state(True)
            item = dialog.plan_tree.topLevelItem(0)
            self.assertIsNone(_path_support__index_combo(dialog, item))
            self.assertFalse(dialog.plan_tree.dragEnabled())
            self.assertFalse(dialog.plan_tree.acceptDrops())
            dialog._update_lock_state(False)
            self.assertIsInstance(
                _path_support__index_combo(dialog, item), QtWidgets.QComboBox
            )
            self.assertTrue(dialog.plan_tree.dragEnabled())
            self.assertTrue(dialog.plan_tree.acceptDrops())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_moved_page_preserves_row_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "indexed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
                pdf_page_sizes_fn=lambda _path: [
                    (24.0, 36.0, "Cover"),
                    (30.0, 42.0, "Floor Plan"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                _path_support__select_combo(dialog, item, 6, 1)
                before = _path_support__first_page_update(dialog)
                moved_item = dialog.plan_tree.takeTopLevelItem(0)
                dialog.plan_tree.addTopLevelItem(moved_item)
                dialog._on_tree_items_moved([moved_item])
                after = _path_support__first_page_update(dialog)
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
        model = _path_support__FakeWorkspaceStateModel()
        source = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = source.plan_tree.header()
            header.resizeSection(0, 222)
            header.moveSection(0, 2)
        finally:
            source.deleteLater()
        restored = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = restored.plan_tree.header()
            self.assertEqual(header.sectionSize(0), 222)
            self.assertEqual(header.visualIndex(0), 2)
        finally:
            restored.deleteLater()

    def test_cover_sheet_initial_size_comes_from_layout_and_has_window_controls(self):
        model = _path_support__FakeWorkspaceStateModel()
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        model = _path_support__FakeWorkspaceStateModel()
        source = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        restored = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            workspace_state_model=_path_support__FakeWorkspaceStateModel(state),
        )
        try:
            self.assertEqual(dialog.size(), dialog.screen().availableGeometry().size())
        finally:
            dialog.deleteLater()

    def test_cover_sheet_persists_and_restores_maximized_state(self):
        model = _path_support__FakeWorkspaceStateModel()
        source = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        restored = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        windowed = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        model = _path_support__FakeWorkspaceStateModel(state)
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            header = dialog.plan_tree.header()
            self.assertEqual(header.sectionSize(0), 140)
            self.assertEqual(header.visualIndex(0), 0)
        finally:
            dialog.deleteLater()

    def test_cover_sheet_plan_header_reject_saves_state_to_workspace_key(self):
        model = _path_support__FakeWorkspaceStateModel()
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
        restored = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            workspace_state_model=model,
        )
        try:
            self.assertEqual(restored.plan_tree.header().sectionSize(0), 233)
        finally:
            restored.deleteLater()

    def test_new_project_cover_sheet_uses_same_plan_header_state(self):
        model = _path_support__FakeWorkspaceStateModel()
        source = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            create_mode=True,
            workspace_state_model=model,
        )
        try:
            source.plan_tree.header().resizeSection(0, 244)
            source.reject()
        finally:
            source.deleteLater()
        restored = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            create_mode=True,
            workspace_state_model=model,
        )
        try:
            self.assertEqual(restored.plan_tree.header().sectionSize(0), 244)
        finally:
            restored.deleteLater()

    def test_cover_sheet_image_path_cells_highlight_missing_files(self):
        missing_image = str(Path(tempfile.gettempdir()) / "missing-cover-page.pdf")
        missing_overlay = str(Path(tempfile.gettempdir()) / "missing-overlay.pdf")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(
                image_path=missing_image,
                overlay_image_path=missing_overlay,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            image_editor = _path_support__path_editor(dialog, item, 4)
            overlay_editor = _path_support__path_editor(dialog, item, 5)
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
        data = _path_support__cover_sheet_data()
        data.folders["f1"] = CoverSheetFolder(uid="f1", name="Plans")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_renamed_folder_reorders_before_reopen(self):
        data = _path_support__cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        data.folders["c1"] = CoverSheetFolder(uid="c1", name="Charlie")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            beta_item = dialog.plan_tree.topLevelItem(0)
            zulu_item = dialog.plan_tree.topLevelItem(2)
            beta_item.setText(0, "Yankee")
            self.assertEqual(
                _path_support__top_level_labels(dialog),
                ["Charlie", "Yankee", "Zulu", "A101"],
            )
            zulu_item.setText(0, "Alpha")
            self.assertEqual(
                _path_support__top_level_labels(dialog),
                ["Alpha", "Charlie", "Yankee", "A101"],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_folder_reorder_preserves_existing_signal_block(self):
        data = _path_support__cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            zulu_item = dialog.plan_tree.topLevelItem(1)
            dialog.plan_tree.blockSignals(True)
            zulu_item.setText(0, "Alpha")
            dialog._reinsert_folder_item(zulu_item)
            self.assertTrue(dialog.plan_tree.signalsBlocked())
            self.assertEqual(
                _path_support__top_level_labels(dialog), ["Alpha", "Beta", "A101"]
            )
        finally:
            dialog.plan_tree.blockSignals(False)
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_moved_folder_reorders_to_persisted_position(self):
        data = _path_support__cover_sheet_data()
        data.folders["b1"] = CoverSheetFolder(uid="b1", name="Beta")
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            folder_item = dialog.plan_tree.takeTopLevelItem(0)
            dialog.plan_tree.addTopLevelItem(folder_item)
            dialog._on_tree_items_moved([folder_item])
            self.assertEqual(
                _path_support__top_level_labels(dialog), ["Beta", "Zulu", "A101"]
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_next_sheet_number_uses_deep_tree_pages(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            self.assertEqual(dialog._next_sheet_no(), "00101")
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_cover_sheet_duplicate_inserts_after_selected_page(self):
        data = _path_support__cover_sheet_data_with_pages()
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_duplicate_reuses_external_reference_without_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "drawing.pdf"
            original = b"%PDF-1.4\nuser-owned drawing\n"
            source.write_bytes(original)
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=str(source)),
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

    def test_cover_sheet_multipage_expansion_uses_same_ordered_insertion_path(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data_with_pages(),
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
        data = _path_support__cover_sheet_data_with_pages()
        source_path = "C:/Plans/Expanded.pdf"
        data.pages_without_folder[0].image_path = source_path
        data.pages_without_folder[0].index = 1
        data.pages_without_folder[1].image_path = source_path
        data.pages_without_folder[1].index = 2
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_page_scale_combo_includes_known_non_architectural_scales(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(scale_factor1=1.0, scale_factor2=120.0),
        )
        try:
            page_item = dialog.plan_tree.topLevelItem(0)
            scale_combo = _path_support__combo_editor(dialog, page_item, 3)
            self.assertEqual(tuple(scale_combo.currentData()), (1.0, 120.0))
            self.assertEqual(scale_combo.currentText(), '1" = 10\' 0"')
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

            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=str(source)),
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

    def test_cover_sheet_path_cell_double_click_edits_full_path(self):
        image_path = r"C:\Plans\A101.pdf"
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(image_path=image_path),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            editor = _path_support__path_editor(dialog, item, 4)
            event = _path_support__FakeMouseEvent()
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_support__path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(f'"{pdf_path}"')
                editor.editingFinished.emit()
                page = _path_support__first_page_update(dialog)
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(image_path=missing_path, page_index=2),
            pdf_page_sizes_fn=lambda _path: self.fail(
                "A missing PDF must not invoke the metadata provider"
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            editor = _path_support__path_editor(dialog, item, 4)
            editor.begin_path_edit()
            editor.setText(missing_path)
            editor.editingFinished.emit()
            self.assertEqual(_path_support__first_page_update(dialog)["index"], 2)
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

            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: self.fail(
                    "Raster images must not use the PDF page-size provider"
                ),
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_support__path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(image_path)
                with mock.patch("sys.excepthook") as exception_hook:
                    editor.editingFinished.emit()
                    QtWidgets.QApplication.processEvents()
                exception_hook.assert_not_called()
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertAlmostEqual(page["width"], 10.0, delta=0.01)
                self.assertAlmostEqual(page["height"], 5.0, delta=0.01)
                combo = _path_support__index_combo(dialog, item)
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_support__path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(pdf_path)
                editor.editingFinished.emit()
                self.assertEqual(calls, [pdf_path])
                self.assertEqual(
                    _path_support__first_page_update(dialog)["image_path"], pdf_path
                )
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_directory_path_is_missing_image_not_pdf(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            pasted_path = str(Path(tmp)) + os.sep
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda path: calls.append(path) or [],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_support__path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(f'"{pasted_path}"')
                editor.editingFinished.emit()
                self.assertEqual(
                    _path_support__first_page_update(dialog)["image_path"], pasted_path
                )
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                image_browse, image_clear = _path_support__path_buttons(dialog, item, 4)
                overlay_browse, overlay_clear = _path_support__path_buttons(
                    dialog, item, 5
                )
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
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(page["overlay_path"], overlay_path)
                self.assertEqual(
                    _path_support__path_editor(dialog, item, 4).text(), "drawing.pdf"
                )
                self.assertEqual(
                    _path_support__path_editor(dialog, item, 5).text(), "overlay.pdf"
                )
                overlay_clear.click()
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(page["overlay_path"], "")
                self.assertEqual(_path_support__path_editor(dialog, item, 5).text(), "")
                image_clear.click()
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["image_path"], "")
                self.assertEqual(page["overlay_path"], "")
                self.assertEqual(_path_support__path_editor(dialog, item, 4).text(), "")
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_overlay_on_page_without_original_owns_overlay_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay_path = str(Path(tmp) / "overlay.pdf")
            Path(overlay_path).write_bytes(b"%PDF-1.4\n")
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                overlay_browse, _overlay_clear = _path_support__path_buttons(
                    dialog, item, 5
                )
                with mock.patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    return_value=(overlay_path, ""),
                ):
                    overlay_browse.click()
                page_update = _path_support__first_page_update(dialog)
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(
                image_path=r"C:\Plans\original.pdf",
                overlay_image_path=r"C:\Plans\overlay.pdf",
                show_mode=2,
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            _image_browse, image_clear = _path_support__path_buttons(dialog, item, 4)
            image_clear.click()
            page_update = _path_support__first_page_update(dialog)
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=image_path),
                pdf_page_sizes_fn=lambda _path: [(25.0, 37.0, "")],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                image_browse, _image_clear = _path_support__path_buttons(
                    dialog, item, 4
                )
                with mock.patch.object(
                    QtWidgets.QFileDialog,
                    "getOpenFileName",
                    return_value=("", ""),
                ):
                    image_browse.click()
                page = _path_support__first_page_update(dialog)
                self.assertEqual(page["image_path"], image_path)
                self.assertEqual(
                    _path_support__path_editor(dialog, item, 4).text(), "drawing.pdf"
                )
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
                    data = _path_support__cover_sheet_data_with_pages(50)
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

                    dialog = _path_support_CoverSheetDialog(
                        _path_support__FakeIconProvider(),
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
                        # processEvents() alone does not deliver DeferredDelete in
                        # this synchronous test runner. Release this dialog's
                        # children too, including the nested picker's focus owner.
                        QtCore.QCoreApplication.sendPostedEvents(
                            dialog, QtCore.QEvent.Type.DeferredDelete
                        )

    def test_nested_picker_cancel_preserves_cover_sheet_combo_and_page_drafts(self):
        for kind in ("employee", "job_status"):
            for draft in ("Typed unsaved value", ""):
                with self.subTest(kind=kind, draft=draft):
                    data = _path_support__cover_sheet_data_with_pages(50)
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
                    dialog = _path_support_CoverSheetDialog(
                        _path_support__FakeIconProvider(),
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
                        QtCore.QCoreApplication.sendPostedEvents(
                            dialog, QtCore.QEvent.Type.DeferredDelete
                        )

    def test_job_status_picker_reselects_duplicate_name_by_uid(self):
        data = _path_support__cover_sheet_data()
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
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

    def test_cover_sheet_rejects_typed_ambiguous_master_name(self):
        data = _path_support__cover_sheet_data()
        data.job_statuses = [
            JobStatus(uid="1", name="Open"),
            JobStatus(uid="2", name="Open"),
        ]
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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


class CoverSheetDialogGetUpdatesTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog.get_updates."""

    def test_cover_sheet_startup_virtualizes_combo_columns_without_pdf_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "shared.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            for page_count in (10, 100, 500, 1000):
                data = _path_support__cover_sheet_data(
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
                workspace = _path_support__FakeWorkspaceStateModel()
                dialog = _path_support_CoverSheetDialog(
                    _path_support__FakeIconProvider(),
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

    def test_cover_sheet_image_path_signal_accepts_multi_page_size_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "multi-page.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [
                    (25.0, 37.0, "Sheet A"),
                    (31.0, 43.0, "Sheet B"),
                ],
            )
            try:
                item = dialog.plan_tree.topLevelItem(0)
                editor = _path_support__path_editor(dialog, item, 4)
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
                    combo = _path_support__index_combo(
                        dialog, dialog.plan_tree.topLevelItem(row)
                    )
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
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(),
                pdf_page_sizes_fn=lambda _path: [
                    (25.0, 37.0, "Sheet A"),
                    (31.0, 43.0, "Sheet B"),
                ],
            )
            try:
                editor = _path_support__path_editor(
                    dialog, dialog.plan_tree.topLevelItem(0), 4
                )
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

    def test_cover_sheet_save_preserves_selected_duplicate_master_uids(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            updates = dialog.get_updates()
            self.assertEqual(updates["job_status_uid"], 2)
            self.assertEqual(updates["estimator_uid"], 12)
        finally:
            dialog.close()
            dialog.deleteLater()


class CoverSheetDialogDeleteSelectedTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._delete_selected."""

    def test_cover_sheet_removed_row_rejects_pending_pdf_metadata_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = str(Path(tmp) / "removed.pdf")
            Path(pdf_path).write_bytes(b"%PDF-1.4\n")
            pool = _path_support__ManualRunnablePool()
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(),
                None,
                _path_support__cover_sheet_data(image_path=pdf_path),
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

    def test_cover_sheet_page_and_folder_with_same_uid_remain_typed(self):
        data = _path_support__cover_sheet_data()
        page = data.pages_without_folder[0]
        page.uid = "shared"
        data.folders["shared"] = CoverSheetFolder(uid="shared", name="Folder")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_page_delete_decline_skips_page_and_continues(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
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
            data = _path_support__cover_sheet_data_with_pages(2)
            for page in data.pages_without_folder:
                page.image_path = str(source)
            dialog = _path_support_CoverSheetDialog(
                _path_support__FakeIconProvider(), None, data
            )
            try:
                dialog.plan_tree.setCurrentItem(dialog._page_items["p1"])
                dialog._delete_selected()
                self.assertEqual(dialog._deleted_page_uids, ["p1"])
                self.assertTrue(source.is_file())
                self.assertEqual(source.read_bytes(), original)
            finally:
                dialog.close()
                dialog.deleteLater()

    def test_cover_sheet_bulk_delete_closes_without_modal_or_input_residue(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), parent, data
        )

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


class CoverSheetDialogAddNewFolderTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._add_new_folder."""

    def test_cover_sheet_new_folder_node_uses_folder_icon(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, _path_support__cover_sheet_data()
        )
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
        data = _path_support__cover_sheet_data()
        data.folders["z1"] = CoverSheetFolder(uid="z1", name="Zulu")
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            self.assertEqual(_path_support__top_level_labels(dialog), ["Zulu", "A101"])
            dialog._add_new_folder()
            self.assertEqual(
                _path_support__top_level_labels(dialog), ["New Folder", "Zulu", "A101"]
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_cover_sheet_new_child_folder_stays_before_child_pages(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            folder_item = dialog.plan_tree.topLevelItem(0)
            dialog.plan_tree.setCurrentItem(folder_item)
            folder_item.setSelected(True)
            dialog._add_new_folder()
            self.assertEqual(
                _path_support__child_labels(folder_item), ["New Folder", "A102"]
            )
        finally:
            dialog.close()
            dialog.deleteLater()


class CoverSheetDialogPopulateImportedPagesTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._populate_imported_pages."""

    def test_cover_sheet_imported_image_pages_keep_visual_sequence(self):
        data = _path_support__cover_sheet_data()
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_import_inserts_ordered_block_after_selected_page(self):
        data = _path_support__cover_sheet_data_with_pages()
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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

    def test_cover_sheet_import_skips_empty_sources_without_reordering_successes(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data_with_pages(),
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


class CoverSheetDialogAddNewPageTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._add_new_page."""

    def test_cover_sheet_new_page_inserts_after_selected_root_page(self):
        data = _path_support__cover_sheet_data_with_pages(5)
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
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
                data = _path_support__cover_sheet_data_with_pages()
                dialog = _path_support_CoverSheetDialog(
                    _path_support__FakeIconProvider(), None, data
                )
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

    def test_cover_sheet_multiple_selection_inserts_after_explicit_current_page(self):
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data_with_pages(),
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data_with_pages(),
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

    def test_cover_sheet_folder_selection_appends_and_nested_page_inserts_after(self):
        data = _path_support__cover_sheet_data()
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
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(), None, data
        )
        try:
            root_folder = dialog._folder_items["f1"]
            dialog.plan_tree.setCurrentItem(root_folder)
            dialog._add_new_page()
            self.assertEqual(
                _path_support__child_labels(root_folder),
                ["Nested", "A101", "A102", "00001"],
            )
            nested_folder = dialog._folder_items["f2"]
            dialog.plan_tree.setCurrentItem(dialog._page_items["p3"])
            dialog._add_new_page()
            self.assertEqual(
                _path_support__child_labels(nested_folder),
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


class CoverSheetDialogOpenBidAreasDialogTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._open_bid_areas_dialog."""

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
                used_uids_fn=None,
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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
                used_uids_fn=None,
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
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


class CoverSheetDialogOpenEmployeesDialogTests(_DialogCoverSheetPathFixture):
    """CoverSheetDialog._open_employees_dialog."""

    def test_employee_picker_cancel_restores_existing_estimator_selection(self):
        data = _path_support__cover_sheet_data()
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
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

    def test_employee_picker_reselects_duplicate_display_name_by_uid(self):
        data = _path_support__cover_sheet_data()
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

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
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

    def test_employee_picker_return_stops_after_cover_sheet_is_destroyed(self):
        data = _path_support__cover_sheet_data()
        reloads = []

        class DestroyingEmployeesDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_call_options):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
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


class CoverSheetMasterDataProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_remote_rename_delete_preserves_uid_and_parent_drafts(self):
        bus = EventBus()
        employees = [Employee("1", first_name="Old"), Employee("2", first_name="New")]
        statuses = [JobStatus("1", "Old"), JobStatus("2", "New")]
        pay_classes = [PayClass("1", "Old")]
        employee_reload = Mock(side_effect=lambda: (list(employees), list(pay_classes)))
        status_reload = Mock(side_effect=lambda: list(statuses))
        data = CoverSheetData(
            "bid",
            "1",
            "Job",
            "1",
            "",
            "",
            "1",
            "",
            employees=list(employees),
            job_statuses=list(statuses),
            pay_classes=list(pay_classes),
        )
        dialog = CoverSheetDialog(
            Mock(),
            None,
            data,
            make_workspace_state_model(),
            reload_employees_fn=employee_reload,
            reload_job_statuses_fn=status_reload,
            event_bus=bus,
            database_id="db",
        )
        try:
            dialog.edit_project_name.setText("Unsaved")
            employees[0] = Employee("1", first_name="New")
            statuses[0] = JobStatus("1", "New")
            with patch.object(dialog, "_populate") as rebuild:
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees", "pay_classes", "job_statuses"],
                )
                self.assertEqual(dialog.combo_estimator.currentText(), "New")
                self.assertEqual(dialog.combo_job_status.currentText(), "New")
                self.assertEqual(dialog.combo_estimator.currentData(), "1")
                self.assertEqual(dialog.combo_job_status.currentData(), "1")
                with patch.object(
                    dialog, "_replace_combo_items", wraps=dialog._replace_combo_items
                ) as replace_items:
                    bus.publish(
                        AppEvents.REMOTE_MASTER_DATA_CHANGED,
                        database_id="other",
                        families=["employees", "job_statuses"],
                    )
                    self.assertEqual(employee_reload.call_count, 1)
                    # Replayed notifications query current state; matching combos are untouched.
                    bus.publish(
                        AppEvents.REMOTE_MASTER_DATA_CHANGED,
                        database_id="db",
                        families=["employees", "pay_classes", "job_statuses"],
                    )
                    replace_items.assert_not_called()
                self.assertEqual(employee_reload.call_count, 2)
                self.assertEqual(status_reload.call_count, 2)
                dialog.combo_estimator.setEditText("Typed draft")
                employees[0] = Employee("1", first_name="Newest")
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees"],
                )
                self.assertEqual(dialog.combo_estimator.currentText(), "Typed draft")
                self.assertEqual(
                    dialog.combo_estimator.itemText(
                        dialog.combo_estimator.findData("1")
                    ),
                    "Newest",
                )
                statuses.pop(0)
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["job_statuses"],
                )
                self.assertEqual(dialog.combo_job_status.currentIndex(), -1)
                self.assertEqual(dialog.combo_job_status.currentText(), "")
                self.assertEqual(dialog.edit_project_name.text(), "Unsaved")
                rebuild.assert_not_called()
        finally:
            dialog.reject()
            employee_reload.reset_mock()
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees"],
            )
            employee_reload.assert_not_called()
            delete(dialog)
