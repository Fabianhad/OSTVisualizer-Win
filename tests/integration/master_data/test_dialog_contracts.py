import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.config import (
    BID_AREAS_WINDOW_HEIGHT,
    BID_AREAS_WINDOW_WIDTH,
    CDNTYPE_WINDOW_HEIGHT,
    CDNTYPE_WINDOW_WIDTH,
    EMPLOYEES_WINDOW_HEIGHT,
    EMPLOYEES_WINDOW_WIDTH,
    JOB_STATUSES_WINDOW_HEIGHT,
    JOB_STATUSES_WINDOW_WIDTH,
    LAYERS_WINDOW_HEIGHT,
    LAYERS_WINDOW_WIDTH,
    OPEN_FILE_HEIGHT,
    OPEN_FILE_WIDTH,
    PAYROLL_CLASS_WINDOW_HEIGHT,
    PAYROLL_CLASS_WINDOW_WIDTH,
)
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog as MasterBidAreaPickerDialog,
    BidAreasDialog as MasterBidAreasDialog,
)
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog as MasterConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import (
    EmployeesDialog as MasterEmployeesDialog,
)
from ost_visualizer.presentation.dialogs.job_statuses_dialog import (
    JobStatusesDialog as MasterJobStatusesDialog,
)
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog as MasterLayersDialog,
    LayersDialogMode,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import (
    OpenFilesDialog as MasterOpenFilesDialog,
)
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog as MasterPayrollClassListDialog,
)
from ost_visualizer.presentation.utils.tree_widget import DEFAULT_TREE_ROW_HEIGHT
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterBidAreasDialog as _master_data_support_MasterBidAreasDialog,
    MasterConditionTypesDialog as _master_data_support_MasterConditionTypesDialog,
    MasterEmployeesDialog as _master_data_support_MasterEmployeesDialog,
    MasterJobStatusesDialog as _master_data_support_MasterJobStatusesDialog,
    MasterLayersDialog as _master_data_support_MasterLayersDialog,
    MasterOpenFilesDialog as _master_data_support_MasterOpenFilesDialog,
    MasterPayrollClassListDialog as _master_data_support_MasterPayrollClassListDialog,
    _app as _master_data_support__app,
)


class MasterDataDialogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _employee_dialog(self, *, menu_mode=False):
        return _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[
                Employee(
                    uid="emp-1",
                    employee_no="1",
                    first_name="Ava",
                    last_name="Lee",
                )
            ],
            menu_mode=menu_mode,
        )

    def _employee_dialog_with_save(self, save_fn):
        return _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[
                Employee(
                    uid="emp-1",
                    employee_no="1",
                    first_name="Ava",
                    last_name="Lee",
                )
            ],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _condition_types_dialog(self, *, menu_mode=False):
        return _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
            menu_mode=menu_mode,
        )

    def _payroll_class_dialog_with_save(self, save_fn):
        return _master_data_support_MasterPayrollClassListDialog(
            _master_data_support_FakeIconProvider(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _job_status_dialog_with_save(self, save_fn):
        return _master_data_support_MasterJobStatusesDialog(
            _master_data_support_FakeIconProvider(),
            job_statuses=[
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _area(self) -> BidArea:
        return BidArea(
            uid="area-1",
            bid_uid="bid-1",
            parent_uid="",
            name="Main",
            sequence=1,
        )

    def _layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="bid-1",
            name=name,
            show=show,
            sequence=sequence,
        )

    def _assert_row_height(
        self, item: QtWidgets.QTreeWidgetItem, column_count: int
    ) -> None:
        for column in range(column_count):
            self.assertEqual(
                item.sizeHint(column).height(),
                DEFAULT_TREE_ROW_HEIGHT,
                f"column {column}",
            )

    def test_fixed_height_tree_rows_use_shared_metrics(self):
        dialogs = []
        sidebar = None
        try:
            areas = _master_data_support_MasterBidAreasDialog(
                _master_data_support_FakeIconProvider(), bid_areas=[self._area()]
            )
            dialogs.append(areas)
            self._assert_row_height(
                areas.tree.topLevelItem(0), areas.tree.columnCount()
            )
            condition_types = self._condition_types_dialog()
            dialogs.append(condition_types)
            self._assert_row_height(
                condition_types.tree.topLevelItem(0),
                condition_types.tree.columnCount(),
            )
            employees = self._employee_dialog()
            dialogs.append(employees)
            self._assert_row_height(
                employees.tree.topLevelItem(0), employees.tree.columnCount()
            )
            layers = _master_data_support_MasterLayersDialog(
                _master_data_support_FakeIconProvider(),
                layers=[self._layer("layer-1", "Layer 1", 1)],
            )
            dialogs.append(layers)
            self._assert_row_height(
                layers.tree.topLevelItem(0), layers.tree.columnCount()
            )
            sidebar = BidLayersSidebar(None)
            sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
            self._assert_row_height(
                sidebar._table.topLevelItem(0),
                sidebar._table.columnCount(),
            )
            job_statuses = self._job_status_dialog_with_save(lambda _changes: {})
            dialogs.append(job_statuses)
            self._assert_row_height(
                job_statuses.tree.topLevelItem(0),
                job_statuses.tree.columnCount(),
            )
            payroll = _master_data_support_MasterPayrollClassListDialog(
                _master_data_support_FakeIconProvider(),
                pay_classes=[PayClass(uid="pay-1", name="Regular")],
            )
            dialogs.append(payroll)
            self._assert_row_height(
                payroll.tree.topLevelItem(0), payroll.tree.columnCount()
            )
            open_files = _master_data_support_MasterOpenFilesDialog(
                _master_data_support_FakeIconProvider(),
                None,
                [FileEntry(__file__, is_checked=True)],
                object(),
            )
            dialogs.append(open_files)
            self._assert_row_height(
                open_files.table.topLevelItem(0),
                open_files.table.columnCount(),
            )
        finally:
            for dialog in dialogs:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()
            if sidebar is not None:
                sidebar.close()
                sidebar.deleteLater()

    def test_resizable_list_dialogs_persist_windowed_and_maximized_state(self):
        cases = (
            (
                "bid_areas",
                QtCore.QSize(BID_AREAS_WINDOW_WIDTH, BID_AREAS_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterBidAreasDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    bid_areas=[self._area()],
                ),
            ),
            (
                "condition_types",
                QtCore.QSize(CDNTYPE_WINDOW_WIDTH, CDNTYPE_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterConditionTypesDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    condition_types=[CdnType(uid="type-1", name="Concrete")],
                    save_fn=lambda _changes: {},
                    reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
                ),
            ),
            (
                "employees",
                QtCore.QSize(EMPLOYEES_WINDOW_WIDTH, EMPLOYEES_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterEmployeesDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    employees=[],
                ),
            ),
            (
                "job_statuses",
                QtCore.QSize(JOB_STATUSES_WINDOW_WIDTH, JOB_STATUSES_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterJobStatusesDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    job_statuses=[
                        JobStatus(
                            uid="status-1",
                            name="Bidding",
                            locked=False,
                            sequence=1,
                        )
                    ],
                ),
            ),
            (
                "layers",
                QtCore.QSize(LAYERS_WINDOW_WIDTH, LAYERS_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterLayersDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    layers=[self._layer("layer-1", "Layer 1", 1)],
                ),
            ),
            (
                "open_files",
                QtCore.QSize(OPEN_FILE_WIDTH, OPEN_FILE_HEIGHT),
                lambda model: _master_data_support_MasterOpenFilesDialog(
                    _master_data_support_FakeIconProvider(),
                    None,
                    [],
                    object(),
                    workspace_state_model=model,
                ),
            ),
            (
                "payroll_classes",
                QtCore.QSize(PAYROLL_CLASS_WINDOW_WIDTH, PAYROLL_CLASS_WINDOW_HEIGHT),
                lambda model: _master_data_support_MasterPayrollClassListDialog(
                    _master_data_support_FakeIconProvider(),
                    workspace_state_model=model,
                    pay_classes=[PayClass(uid="pay-1", name="Regular")],
                ),
            ),
        )
        for key, default_size, factory in cases:
            with self.subTest(dialog=key):
                model = make_workspace_state_model()
                source = factory(model)
                try:
                    self.assertEqual(
                        source.size(),
                        source._window_state._bounded_size(default_size),
                    )
                    self.assertGreater(source.maximumWidth(), source.minimumWidth())
                    self.assertGreater(source.maximumHeight(), source.minimumHeight())
                    flags = source.windowFlags()
                    self.assertFalse(
                        bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
                    )
                    self.assertTrue(
                        bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
                    )
                    self.assertTrue(
                        bool(flags & QtCore.Qt.WindowType.WindowCloseButtonHint)
                    )
                    resized = QtCore.QSize(
                        min(
                            source.width() + 20, source.screen().availableSize().width()
                        ),
                        min(
                            source.height() + 20,
                            source.screen().availableSize().height(),
                        ),
                    )
                    source.resize(resized)
                    resized = source.size()
                    source.show()
                    self.app.processEvents()
                    source.showMaximized()
                    self.app.processEvents()
                    self.assertTrue(source.isMaximized())
                    source.reject()
                finally:
                    source.cleanup()
                    source.deleteLater()
                self.assertEqual(model.state.dialog_sizes[key], list(resized.toTuple()))
                self.assertTrue(model.state.dialog_maximized[key])
                restored = factory(model)
                try:
                    restored.show()
                    self.app.processEvents()
                    self.assertTrue(restored.isMaximized())
                    restored.showNormal()
                    self.app.processEvents()
                    # The windowed size saved with the maximized state returns.
                    self.assertEqual(restored.size(), resized)
                    restored.reject()
                finally:
                    restored.cleanup()
                    restored.deleteLater()
                self.assertFalse(model.state.dialog_maximized[key])

    def test_master_picker_rename_reapplies_active_filter(self):
        for factory, query in (
            (self._payroll_class_dialog_with_save, "Regular"),
            (self._job_status_dialog_with_save, "Bidding"),
        ):
            with self.subTest(dialog=factory.__name__):
                dialog = factory(lambda _changes: {})
                try:
                    dialog.show()
                    self.app.processEvents()
                    dialog.edit_find.setText(query)
                    item = dialog.tree.topLevelItem(0)
                    uid = item.data(dialog._uid_col, dialog._UID_ROLE)
                    dialog.tree.setCurrentItem(item)
                    dialog.tree.editItem(item, dialog._edit_col)
                    editor = dialog.tree.viewport().focusWidget()
                    self.assertIsInstance(editor, QtWidgets.QLineEdit)
                    editor.selectAll()
                    QTest.keyClicks(editor, "Different name")
                    QTest.keyClick(editor, QtCore.Qt.Key.Key_Return)
                    self.app.processEvents()
                    self.assertEqual(item.text(dialog._name_col), "Different name")
                    self.assertTrue(item.isHidden())
                    self.assertFalse(dialog.btn_delete.isEnabled())
                    dialog.edit_find.clear()
                    self.assertFalse(item.isHidden())
                    self.assertEqual(item.data(dialog._uid_col, dialog._UID_ROLE), uid)
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_master_picker_rejected_save_keeps_blank_draft_editable_for_retry(self):
        for factory in (
            self._payroll_class_dialog_with_save,
            self._job_status_dialog_with_save,
        ):
            for asynchronous in (False, True):
                with self.subTest(dialog=factory.__name__, asynchronous=asynchronous):
                    submissions = []
                    completions = []

                    def save(changes):
                        submissions.append(
                            {
                                key: [dict(row) for row in changes[key]]
                                for key in ("new", "updated")
                            }
                        )
                        return (
                            False if len(submissions) == 1 else {"new_0": "created-1"}
                        )

                    def queue(changes, completed):
                        save(changes)
                        completions.append(completed)
                        return True

                    dialog = factory(save)
                    if asynchronous:
                        dialog._save_async_fn = queue
                    try:
                        dialog.show()
                        self.app.processEvents()
                        dialog.btn_new.click()
                        editor = dialog.tree.findChild(QtWidgets.QLineEdit)
                        self.assertIsNotNone(editor)
                        QTest.keyClick(editor, QtCore.Qt.Key.Key_Escape)
                        self.app.processEvents()
                        draft = dialog.tree.currentItem()
                        self.assertEqual(draft.text(dialog._name_col), "")
                        dialog.btn_select.click()
                        if asynchronous:
                            completions.pop()(False, None)
                        # The select attempt submitted once (a blank draft is not
                        # a row to create), was rejected, and the dialog stays
                        # open with the draft still in the tree for a retry.
                        self.assertEqual(len(submissions), 1)
                        self.assertEqual(submissions[0]["new"], [])
                        self.assertGreaterEqual(
                            dialog.tree.indexOfTopLevelItem(draft), 0
                        )
                        self.assertTrue(dialog.isVisible())
                        self.assertTrue(dialog.btn_new.isEnabled())
                        dialog.tree.editItem(draft, dialog._edit_col)
                        editor = dialog.tree.viewport().focusWidget()
                        self.assertIsNotNone(editor)
                        self.assertIsInstance(editor, QtWidgets.QLineEdit)
                        QTest.keyClicks(editor, "New record")
                        QTest.keyClick(editor, QtCore.Qt.Key.Key_Return)
                        self.app.processEvents()
                        self.assertEqual(draft.text(dialog._name_col), "New record")
                        dialog.btn_select.click()
                        if asynchronous:
                            completions.pop()(True, {"new_0": "created-1"})
                        self.assertEqual(len(submissions), 2)
                        self.assertEqual(
                            [row["name"] for row in submissions[-1]["new"]],
                            ["New record"],
                        )
                        self.assertEqual(
                            dialog.result(), QtWidgets.QDialog.DialogCode.Accepted
                        )
                        self.assertIn(
                            "New record",
                            [item.name for item in dialog.get_result().items],
                        )
                    finally:
                        dialog.close()
                        dialog.cleanup()
                        dialog.deleteLater()

    def test_master_data_x_close_cancel_and_escape_do_not_save_pending_edits(self):
        cases = (
            (
                self._payroll_class_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(0, "Overtime"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 0),
                ),
            ),
            (
                self._job_status_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(1, "Awarded"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 1),
                ),
            ),
            (
                self._employee_dialog_with_save,
                lambda dialog: self._rename_first_employee(dialog, "Mia"),
            ),
        )
        for make_dialog, mutate in cases:
            for action in ("close", "cancel", "escape"):
                save_calls = []
                dialog = make_dialog(lambda changes: save_calls.append(changes) or True)
                try:
                    mutate(dialog)
                    if action == "close":
                        dialog.close()
                    elif action == "cancel":
                        dialog.reject()
                    else:
                        dialog.show()
                        QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
                    self.app.processEvents()
                    self.assertEqual(save_calls, [], action)
                    self.assertFalse(dialog._save_done, action)
                finally:
                    dialog.close()
                    dialog.cleanup()
                    dialog.deleteLater()

    def test_master_data_accept_still_saves_pending_edits(self):
        cases = (
            (
                self._payroll_class_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(0, "Overtime"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 0),
                ),
            ),
            (
                self._job_status_dialog_with_save,
                lambda dialog: (
                    dialog.tree.topLevelItem(0).setText(1, "Awarded"),
                    dialog._on_item_changed(dialog.tree.topLevelItem(0), 1),
                ),
            ),
            (
                self._employee_dialog_with_save,
                lambda dialog: self._rename_first_employee(dialog, "Mia"),
            ),
        )
        for make_dialog, mutate in cases:
            save_calls = []
            dialog = make_dialog(lambda changes: save_calls.append(changes) or True)
            try:
                mutate(dialog)
                dialog.accept()
                self.assertEqual(len(save_calls), 1)
                self.assertTrue(dialog._save_done)
            finally:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()

    @staticmethod
    def _rename_first_employee(dialog, first_name: str) -> None:
        dialog._employees[0].first_name = first_name

    def test_async_master_data_completion_preserves_external_interactivity_block(self):
        for external_block in (True, False):
            with self.subTest(external_block=external_block):
                self._run_async_completion(external_block)

    def _run_async_completion(self, external_block):
        condition_callbacks = []
        condition_dialog = _master_data_support_MasterConditionTypesDialog(
            _master_data_support_FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: self.fail("sync save must not run"),
            save_async_fn=lambda _changes, completed: (
                condition_callbacks.append(completed) or True
            ),
            reload_fn=lambda: [CdnType(uid="type-1", name="Asphalt")],
            menu_mode=True,
        )
        layer_callbacks = []
        layer_dialog = _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
            update_name_fn=lambda _uid, _name: self.fail("sync save must not run"),
            update_name_async_fn=lambda _uid, _name, completed: (
                layer_callbacks.append(completed) or True
            ),
            reload_fn=lambda: [self._layer("layer-1", "Renamed", 1)],
        )
        try:
            condition_item = condition_dialog.tree.topLevelItem(0)
            condition_dialog._set_item_text(condition_item, "Asphalt")
            condition_dialog._on_item_changed(condition_item, 0)
            layer_item = layer_dialog.tree.topLevelItem(0)
            layer_dialog._set_item_text(layer_item, "Renamed")
            layer_dialog._on_item_changed(layer_item, 2)
            self.assertEqual(len(condition_callbacks), 1)
            self.assertEqual(len(layer_callbacks), 1)
            if external_block:
                condition_dialog.set_interactive(False)
                layer_dialog.set_interactive(False)
            condition_callbacks[0](True, {})
            layer_callbacks[0](True, None)
            # Without an external block the completed save returns the dialog to
            # an interactive state; with one, completion must not lift it.
            self.assertEqual(condition_dialog._is_interactive, not external_block)
            self.assertEqual(layer_dialog._is_interactive, not external_block)
            self.assertEqual(condition_dialog.btn_new.isEnabled(), not external_block)
            self.assertEqual(layer_dialog.btn_new.isEnabled(), not external_block)
        finally:
            condition_dialog.close()
            condition_dialog.cleanup()
            condition_dialog.deleteLater()
            layer_dialog.close()
            layer_dialog.cleanup()
            layer_dialog.deleteLater()
