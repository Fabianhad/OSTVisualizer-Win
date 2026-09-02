import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.config import (
    BID_AREAS_WINDOW_HEIGHT,
    BID_AREAS_WINDOW_WIDTH,
    CDNTYPE_WINDOW_HEIGHT,
    CDNTYPE_WINDOW_WIDTH,
    EMPLOYEES_WINDOW_HEIGHT,
    EMPLOYEES_WINDOW_WIDTH,
    LAYERS_WINDOW_HEIGHT,
    LAYERS_WINDOW_WIDTH,
    JOB_STATUSES_WINDOW_HEIGHT,
    JOB_STATUSES_WINDOW_WIDTH,
    OPEN_FILE_HEIGHT,
    OPEN_FILE_WIDTH,
    PAYROLL_CLASS_WINDOW_HEIGHT,
    PAYROLL_CLASS_WINDOW_WIDTH,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.areas_dialog import (
    BidAreaPickerDialog,
    BidAreasDialog,
)
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.layers_dialog import (
    LayersDialog,
    LayersDialogMode,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.deferred_dialog_save import (
    DeferredDialogSaveController,
)
from ost_visualizer.presentation.utils.tree_widget import DEFAULT_TREE_ROW_HEIGHT
from tests.workspace_state_test_support import (
    make_workspace_state_model,
    with_workspace_state,
)

BidAreaPickerDialog = with_workspace_state(BidAreaPickerDialog)
BidAreasDialog = with_workspace_state(BidAreasDialog)
ConditionTypesDialog = with_workspace_state(ConditionTypesDialog)
EmployeesDialog = with_workspace_state(EmployeesDialog)
JobStatusesDialog = with_workspace_state(JobStatusesDialog)
LayersDialog = with_workspace_state(LayersDialog)
OpenFilesDialog = with_workspace_state(OpenFilesDialog)
PageSettingsBar = with_workspace_state(PageSettingsBar)
PayrollClassListDialog = with_workspace_state(PayrollClassListDialog)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class ProjectTreeMasterDataReadTests(unittest.TestCase):
    def test_sql_job_status_menu_uses_authoritative_model_snapshot(self):
        expected = [JobStatus(uid="status-1", name="Open")]

        class ReadService:
            def get_job_statuses(self, _file_path):
                raise AssertionError(
                    "SQL job statuses must not be read on the Qt thread"
                )

        owner = SimpleNamespace(
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: True
            ),
            _project_data_service=SimpleNamespace(
                get_job_status_snapshot=lambda _file_path: expected
            ),
            _project_read_service=ReadService(),
        )
        self.assertEqual(
            MainWindow._get_project_tree_job_statuses(owner, "sql-database"),
            expected,
        )


class FakeIconProvider:
    def set_window_icon(self, _window):
        pass


class PageSettingsScaleDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )

    def tearDown(self):
        self.bar.deleteLater()
        self.app.processEvents()

    def test_custom_scale_display_tracks_page_refresh_without_emitting_requests(self):
        scale_requests = []
        custom_requests = []
        self.bar.scale_change_requested.connect(
            lambda *args: scale_requests.append(args)
        )
        self.bar.custom_scale_requested.connect(
            lambda *args: custom_requests.append(args)
        )
        initial_count = self.bar.scale_combo.count()
        for _ in range(12):
            self.bar.load_page("custom-1", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)
        self.assertEqual(scale_requests, [])
        self.assertEqual(custom_requests, [])
        self.bar.load_page("custom-2", 0.3751, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.3751" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)
        self.bar.load_page("custom-1", 0.26000000000000001, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)

    def test_switching_between_custom_and_predefined_resets_one_custom_item(self):
        custom_index = self.bar.scale_combo.count() - 1
        initial_count = self.bar.scale_combo.count()
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentIndex(), custom_index)
        self.assertEqual(self.bar.scale_combo.itemText(custom_index), '0.26" = 1\' 0"')
        self.bar.load_page("predefined", 0.125, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '1/8" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.itemText(custom_index), "Custom scale")
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentIndex(), custom_index)
        self.assertEqual(self.bar.scale_combo.count(), initial_count)

    def test_predefined_and_reloaded_scale_labels_remain_readable(self):
        for sf1, sf2, expected in (
            (1.0, 240.0, '1" = 20\' 0"'),
            (0.125, 12.0, '1/8" = 1\' 0"'),
            (0.1875, 12.0, '3/16" = 1\' 0"'),
        ):
            self.bar.load_page("page", sf1, sf2, "")
            self.assertEqual(self.bar.scale_combo.currentText(), expected)
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.bar.scale_combo.blockSignals(True)
        self.bar.clear_bid()
        self.assertTrue(self.bar.scale_combo.signalsBlocked())
        self.bar.scale_combo.blockSignals(False)
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')

    def test_programmatic_area_updates_preserve_existing_qt_signal_block(self):
        self.bar.area_combo.blockSignals(True)
        try:
            self.bar.load_bid_areas(
                BidRef("db.mdb", "bid-1"),
                areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
            )
            self.assertTrue(self.bar.area_combo.signalsBlocked())
            self.bar.load_page("page-1", 1.0, 1.0, "area-1")
            self.assertTrue(self.bar.area_combo.signalsBlocked())
            self.bar.clear_bid()
            self.assertTrue(self.bar.area_combo.signalsBlocked())
        finally:
            self.bar.area_combo.blockSignals(False)

    def test_area_usage_is_owned_and_cleared_with_bid_state(self):
        bid_usage = {"area-1"}
        page_usage = {"area-1"}
        self.bar.load_bid_areas(
            BidRef("db.mdb", "bid-1"),
            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
            areas_with_takeoff=bid_usage,
        )
        self.bar.load_page(
            "page-1",
            1.0,
            1.0,
            "area-1",
            areas_with_takeoff=page_usage,
        )
        bid_usage.clear()
        page_usage.clear()
        self.assertEqual(self.bar._bid_areas_in_use, {"area-1"})
        self.assertEqual(self.bar._page_areas_in_use, {"area-1"})
        self.bar.clear_bid()
        self.assertIsNone(self.bar._bid_areas_in_use)
        self.assertIsNone(self.bar._page_areas_in_use)
        self.assertEqual(self.bar._current_scale_index, -1)

    def test_non_architectural_custom_and_invalid_scales_use_safe_display(self):
        self.bar.load_page("metric-custom", 2.5, 1000.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), "2.5 : 1000")
        for sf1, sf2 in (
            (None, 12.0),
            (0.0, 12.0),
            (0.26, 0.0),
            (float("nan"), 12.0),
        ):
            self.bar.load_page("invalid", sf1, sf2, "")
            self.assertEqual(self.bar.scale_combo.currentIndex(), -1)
            self.assertEqual(self.bar.scale_combo.currentText(), "")


class MasterDataDialogButtonModeTests(unittest.TestCase):
    def test_page_settings_scale_activation_emits_one_request_per_commit(self):
        bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"), areas=[])
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        scale_requests = []
        custom_requests = []
        bar.scale_change_requested.connect(
            lambda *args: scale_requests.append(tuple(args))
        )
        bar.custom_scale_requested.connect(
            lambda *args: custom_requests.append(tuple(args))
        )
        try:
            predefined_index = next(
                index
                for index in range(bar.scale_combo.count())
                if isinstance(bar.scale_combo.itemData(index), tuple)
                and bar.scale_combo.itemData(index) != (1.0, 1.0)
            )
            expected_scale = bar.scale_combo.itemData(predefined_index)
            bar.scale_combo.activated.emit(predefined_index)
            bar.scale_combo.activated.emit(predefined_index)
            custom_index = bar.scale_combo.count() - 1
            bar.scale_combo.activated.emit(custom_index)
            self.assertEqual(
                scale_requests,
                [
                    ("db.mdb", "page-1", *expected_scale),
                    ("db.mdb", "page-1", *expected_scale),
                ],
            )
            self.assertEqual(custom_requests, [("db.mdb", "page-1")])
        finally:
            bar.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def _employee_dialog(self, *, menu_mode=False):
        return EmployeesDialog(
            FakeIconProvider(),
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
        return EmployeesDialog(
            FakeIconProvider(),
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
        return ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
            menu_mode=menu_mode,
        )

    def _payroll_class_dialog(self, *, menu_mode=False):
        return PayrollClassListDialog(
            FakeIconProvider(),
            pay_classes=[],
            menu_mode=menu_mode,
        )

    def _payroll_class_dialog_with_save(self, save_fn):
        return PayrollClassListDialog(
            FakeIconProvider(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
            save_fn=save_fn,
            menu_mode=True,
        )

    def _job_status_dialog_with_save(self, save_fn):
        return JobStatusesDialog(
            FakeIconProvider(),
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

    def _default_layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="",
            name=name,
            show=show,
            sequence=sequence,
            is_template=True,
            is_locked=True,
        )

    def _click_checkbox(self, checkbox: QtWidgets.QCheckBox) -> None:
        QTest.mouseClick(checkbox, QtCore.Qt.MouseButton.LeftButton)
        self.app.processEvents()

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
            areas = BidAreasDialog(FakeIconProvider(), bid_areas=[self._area()])
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
            layers = LayersDialog(
                FakeIconProvider(),
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
            payroll = PayrollClassListDialog(
                FakeIconProvider(),
                pay_classes=[PayClass(uid="pay-1", name="Regular")],
            )
            dialogs.append(payroll)
            self._assert_row_height(
                payroll.tree.topLevelItem(0), payroll.tree.columnCount()
            )
            open_files = OpenFilesDialog(
                FakeIconProvider(),
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
                lambda model: BidAreasDialog(
                    FakeIconProvider(),
                    workspace_state_model=model,
                    bid_areas=[self._area()],
                ),
            ),
            (
                "condition_types",
                QtCore.QSize(CDNTYPE_WINDOW_WIDTH, CDNTYPE_WINDOW_HEIGHT),
                lambda model: ConditionTypesDialog(
                    FakeIconProvider(),
                    workspace_state_model=model,
                    condition_types=[CdnType(uid="type-1", name="Concrete")],
                    save_fn=lambda _changes: {},
                    reload_fn=lambda: [CdnType(uid="type-1", name="Concrete")],
                ),
            ),
            (
                "employees",
                QtCore.QSize(EMPLOYEES_WINDOW_WIDTH, EMPLOYEES_WINDOW_HEIGHT),
                lambda model: EmployeesDialog(
                    FakeIconProvider(),
                    workspace_state_model=model,
                    employees=[],
                ),
            ),
            (
                "job_statuses",
                QtCore.QSize(JOB_STATUSES_WINDOW_WIDTH, JOB_STATUSES_WINDOW_HEIGHT),
                lambda model: JobStatusesDialog(
                    FakeIconProvider(),
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
                lambda model: LayersDialog(
                    FakeIconProvider(),
                    workspace_state_model=model,
                    layers=[self._layer("layer-1", "Layer 1", 1)],
                ),
            ),
            (
                "open_files",
                QtCore.QSize(OPEN_FILE_WIDTH, OPEN_FILE_HEIGHT),
                lambda model: OpenFilesDialog(
                    FakeIconProvider(),
                    None,
                    [],
                    object(),
                    workspace_state_model=model,
                ),
            ),
            (
                "payroll_classes",
                QtCore.QSize(PAYROLL_CLASS_WINDOW_WIDTH, PAYROLL_CLASS_WINDOW_HEIGHT),
                lambda model: PayrollClassListDialog(
                    FakeIconProvider(),
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
                    restored.reject()
                finally:
                    restored.cleanup()
                    restored.deleteLater()
                self.assertFalse(model.state.dialog_maximized[key])

    def test_employees_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._employee_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._employee_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_change.text(), "Change")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_menu_dialog_shows_ok_only(self):
        dialog = BidAreasDialog(FakeIconProvider(), bid_areas=[self._area()])
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_ok.text(), "OK")
            self.assertNotIn("Select", button_texts)
            self.assertNotIn("Cancel", button_texts)
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_interactivity_revocation_blocks_inline_writes(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._update_button_states()
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertFalse(dialog.btn_move_down.isEnabled())
            dialog._set_item_name(item, "Renamed")
            dialog._on_item_changed(item, 0)
            dialog._on_new()
            dialog._on_delete()
            self.assertEqual(item.text(0), "Main")
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(save_calls, [])
            dialog.set_interactive(True)
            self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_selection_cannot_reenable_when_noninteractive(self):
        dialog = BidAreaPickerDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
        )
        try:
            dialog.set_interactive(False)
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            dialog._update_button_states()
            self.assertFalse(dialog.btn_select.isEnabled())
            dialog._on_select()
            self.assertIsNone(dialog.get_selected_uid())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_types_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._condition_types_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_types_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._condition_types_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_payroll_class_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._payroll_class_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_payroll_class_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._payroll_class_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_keeps_select_and_cancel_buttons(self):
        dialog = BidAreaPickerDialog(FakeIconProvider(), bid_areas=[self._area()])
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_area_picker_forwards_async_and_existing_constructor_arguments(self):
        async_save = lambda _changes, _completed: True
        saved = []
        used_uids = {"area-1"}
        dialog = BidAreaPickerDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_async_fn=async_save,
            used_uids=used_uids,
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            self.assertIs(dialog._save_async_fn, async_save)
            self.assertEqual(dialog._used_uids, used_uids)
            self.assertIsNotNone(dialog._on_saved_fn)
            dialog._on_saved_fn()
            self.assertEqual(saved, ["saved"])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_deferred_dialog_save_controller_flushes_scheduled_save(self):
        calls = []
        controller = DeferredDialogSaveController(lambda: calls.append("save") or True)
        try:
            controller.schedule()
            self.assertEqual(calls, [])
            self.assertTrue(controller.pending)
            self.assertTrue(controller.flush())
            self.assertEqual(calls, ["save"])
            self.assertFalse(controller.pending)
        finally:
            controller.cleanup()

    def test_bid_area_picker_select_new_area_flushes_and_returns_mapped_uid(self):
        save_calls = []
        dialog = BidAreaPickerDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(save_calls, [])
            dialog._on_select()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.get_selected_uid(), "area-2")
            self.assertEqual(len(save_calls), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_keeps_new_uid_pending_when_uid_map_missing(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: {},
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertFalse(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "new_0")
            self.assertIn("new_0", dialog._new_uids)
            self.assertEqual(saved, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_new_uid_map_on_save(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: {"new_0": "area-2"},
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "area-2")
            self.assertNotIn("new_0", dialog._new_uids)
            self.assertEqual(saved, ["saved"])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_applies_uid_map_when_refresh_fails(self):
        saved = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda _changes: WriteReloadResult(
                {"new_0": "area-2"},
                write_success=True,
                reload_success=False,
            ),
            on_saved_fn=lambda: saved.append("saved"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "area-2")
            self.assertNotIn("new_0", dialog._new_uids)
            self.assertEqual(saved, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_new_area_save_does_not_rewrite_existing_areas(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual([area.uid for area in save_calls[0].new], ["new_0"])
            self.assertEqual(save_calls[0].updated, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_move_schedules_save_and_flushes_changed_rows(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[
                self._area(),
                BidArea("area-2", "bid-1", "", "Area 2", 2),
                BidArea("area-3", "bid-1", "", "Area 3", 3),
            ],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            dialog._on_move_down()
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(
                [(area.uid, area.sequence) for area in save_calls[0].updated],
                [("area-2", 0), ("area-1", 1)],
            )
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_new_area_name(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, " main ")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_called_once_with(
                dialog, "Duplicate Area", "Area main already exists."
            )
            self.assertEqual(item.text(0), "")
            self.assertEqual(save_calls, [])
            self.assertIn("new_0", dialog._new_uids)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_duplicate_existing_area_rename(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[
                self._area(),
                BidArea(
                    uid="area-2",
                    bid_uid="bid-1",
                    parent_uid="",
                    name="Secondary",
                    sequence=2,
                ),
            ],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(1)
            dialog.tree.blockSignals(True)
            item.setText(0, "Main")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_called_once_with(
                dialog, "Duplicate Area", "Area Main already exists."
            )
            self.assertEqual(item.text(0), "Secondary")
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_current_name_is_noop(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(save_calls, [])
            self.assertEqual(item.text(0), "Main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_duplicate_check_excludes_current_uid(self):
        save_calls = []

        def save_fn(changes):
            save_calls.append(changes)
            return {}

        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=save_fn,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "main")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(save_calls, [])
            self.assertTrue(dialog.flush_pending_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0].updated[0].uid, "area-1")
            self.assertEqual(save_calls[0].updated[0].name, "main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_rejects_empty_existing_area_name(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=lambda changes: save_calls.append(changes) or {},
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "   ")
            dialog.tree.blockSignals(False)
            with patch(
                "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
            ) as warning:
                dialog._on_item_changed(item, 0)
            warning.assert_not_called()
            self.assertEqual(item.text(0), "Main")
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_valid_unique_rename_saves_and_updates_valid_name(self):
        save_calls = []

        def save_fn(changes):
            save_calls.append(changes)
            return {}

        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[self._area()],
            save_fn=save_fn,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.blockSignals(True)
            item.setText(0, "Level 1")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0].updated[0].name, "Level 1")
            dialog.tree.blockSignals(True)
            item.setText(0, "Main")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(save_calls), 2)
            self.assertEqual(save_calls[1].updated[0].name, "Main")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_bid_areas_dialog_cleanup_flushes_pending_save(self):
        save_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: save_calls.append(changes) or {"new_0": "area-2"},
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(save_calls, [])
            dialog.cleanup()
            self.assertEqual(len(save_calls), 1)
            self.assertTrue(dialog.has_saved_changes())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_bid_areas_async_rejection_never_falls_back_to_sync_save(self):
        sync_calls = []
        async_calls = []
        dialog = BidAreasDialog(
            FakeIconProvider(),
            bid_areas=[],
            save_fn=lambda changes: sync_calls.append(changes),
            save_async_fn=lambda changes, _completed: (
                async_calls.append(changes) or False
            ),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Area 2")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertFalse(dialog.flush_pending_save())
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(sync_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_page_settings_area_picker_saves_without_database_refresh(self):
        load_calls = []
        save_calls = []
        refresh_calls = []
        workspace_models = []

        def load_areas(file_path, bid_uid):
            load_calls.append((file_path, bid_uid))
            if not refresh_calls:
                return []
            return [BidArea("area-2", "bid-1", "", "Area 2", 1)]

        def save_areas(
            file_path,
            bid_uid,
            changes,
            publish_database_refreshed_after_write=True,
        ):
            save_calls.append(
                (
                    file_path,
                    bid_uid,
                    changes,
                    {
                        "publish_database_refreshed_after_write": (
                            publish_database_refreshed_after_write
                        )
                    },
                )
            )
            return {"new_0": "area-2"}

        def refresh_areas(file_path):
            refresh_calls.append(file_path)

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_fn = save_fn
                self._on_saved_fn = on_saved_fn
                workspace_models.append(workspace_state_model)

            def set_interactive(self, _enabled):
                pass

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def exec_picker(picker, _event_bus):
            picker._save_fn(object())
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=load_areas,
            save_areas_fn=save_areas,
            refresh_areas_fn=refresh_areas,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )
        area_changes = []
        bar.area_change_requested.connect(
            lambda file_path, page_uid, area_uid: area_changes.append(
                (file_path, page_uid, area_uid)
            )
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(
                save_calls[0][3]["publish_database_refreshed_after_write"], False
            )
            self.assertEqual(refresh_calls, ["db.mdb"])
            self.assertIn(("db.mdb", "bid-1"), load_calls)
            self.assertEqual(workspace_models, [bar._workspace_state_model])
            self.assertEqual(bar.area_combo.get_current_area_uid(), "area-2")
            self.assertEqual(area_changes, [("db.mdb", "page-1", "area-2")])
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_ignores_callbacks_after_bid_is_cleared(self):
        save_calls = []
        refresh_calls = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_fn = save_fn
                self._on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return False

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [],
            save_areas_fn=lambda *args, **kwargs: save_calls.append((args, kwargs)),
            refresh_areas_fn=refresh_calls.append,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)

        def exec_picker(picker, _event_bus):
            bar.clear_bid()
            self.assertIsNone(picker._save_fn(object()))
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(save_calls, [])
            self.assertEqual(refresh_calls, [])
            self.assertIsNone(bar._bid_ref)
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_uses_async_save_without_sync_refresh(self):
        async_calls = []
        sync_calls = []
        refresh_calls = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_async_fn = save_async_fn
                self._on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def save_async(bid_ref, changes, completed):
            async_calls.append((bid_ref, changes))
            completed(True, {"new-0": "area-2"})
            return True

        def exec_picker(picker, _event_bus):
            self.assertTrue(
                picker._save_async_fn(
                    {"new": [{"uid": "new-0", "name": "Area 2"}]},
                    lambda _success, _uid_map: None,
                )
            )
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        area = BidArea("area-2", "bid-1", "", "Area 2", 1)
        bar = PageSettingsBar(
            FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [area],
            save_areas_fn=lambda *args, **kwargs: sync_calls.append((args, kwargs)),
            save_areas_async_fn=save_async,
            refresh_areas_fn=refresh_calls.append,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
        )
        bar.load_bid_areas(BidRef("sql-database", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(async_calls[0][0], BidRef("sql-database", "bid-1"))
            self.assertEqual(sync_calls, [])
            self.assertEqual(refresh_calls, [])
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_selects_backend_with_real_dialog(self):
        observed = []

        def inspect_dialog(dialog, _event_bus):
            observed.append(
                (
                    dialog._bid_ref.file_path,
                    dialog._save_async_fn,
                    set(dialog._used_uids),
                    callable(dialog._on_saved_fn),
                )
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        from ost_visualizer.presentation.components import page_settings_bar

        old_exec = page_settings_bar.exec_with_ost_blocking
        page_settings_bar.exec_with_ost_blocking = inspect_dialog
        try:
            for database_id, uses_async in (
                ("access.mdb", False),
                ("sql-database", True),
            ):
                bar = PageSettingsBar(
                    FakeIconProvider(),
                    event_bus=EventBus(),
                    load_areas_fn=lambda _file_path, bid_uid: [
                        BidArea("area-1", bid_uid, "", "Area 1", 1)
                    ],
                    save_areas_fn=lambda *_args, **_kwargs: {},
                    save_areas_async_fn=lambda *_args: True,
                    uses_async_areas_fn=lambda _file_path, value=uses_async: value,
                    refresh_areas_fn=lambda _file_path: None,
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                )
                bar.load_bid_areas(
                    BidRef(database_id, "bid-1"),
                    areas_with_takeoff={"area-1"},
                )
                bar.load_page("page-1", 1.0, 1.0, "area-1")
                bar.set_interactive(True)
                try:
                    bar._on_area_browse()
                finally:
                    bar.deleteLater()
        finally:
            page_settings_bar.exec_with_ost_blocking = old_exec
        self.assertEqual(
            [
                (database_id, callback is not None, used, has_saved_callback)
                for database_id, callback, used, has_saved_callback in observed
            ],
            [
                ("access.mdb", False, {"area-1"}, True),
                ("sql-database", True, {"area-1"}, True),
            ],
        )

    def test_open_areas_dialog_refreshes_once_after_saved_changes(self):
        reload_calls = []
        bid_ref = BidRef("db.mdb", "bid-1")

        class Access:
            def is_allowed(self, _feature):
                return True

        class UiState:
            selected_area_uid = None
            selected_file_path = bid_ref.file_path

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def get_area_uids_with_takeoff(self):
                return set()

        class ReadService:
            def get_bid_areas(self, file_path, bid_uid):
                return [BidArea("area-1", bid_uid, "", "Area 1", 1)]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return False

            def reload_and_notify(self, file_path):
                reload_calls.append(file_path)
                return True

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
                pass

            def cleanup(self):
                pass

            def has_saved_changes(self):
                return True

            def deleteLater(self):
                pass

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = UiState()
        coordinator.ui_access_manager = Access()
        coordinator.project_data = ProjectData()
        coordinator._project_read_service = ReadService()
        coordinator._project_write_service = WriteService()
        coordinator._icon_provider = FakeIconProvider()

        def request_local_edit(
            database_id,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            callback(
                EditLeaseResult(
                    True,
                    handle=EditLeaseHandle(
                        database_id=database_id,
                        draft_id="areas-test-draft",
                        runtime_generation=0,
                        operation_id=operation_id,
                        owning_surface=owning_surface,
                        resources=resources,
                        dependency_resources=dependency_resources,
                    ),
                )
            )

        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=request_local_edit,
            end_edit_lease=lambda _handle: None,
        )
        coordinator.main_window = None
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator.event_bus = EventBus()
        from ost_visualizer.presentation.coordinators import ui_event_coordinator

        old_dialog = ui_event_coordinator.BidAreasDialog
        old_exec = ui_event_coordinator.exec_with_ost_blocking
        ui_event_coordinator.BidAreasDialog = CapturingAreasDialog
        ui_event_coordinator.exec_with_ost_blocking = (
            lambda _dialog, _event_bus: QtWidgets.QDialog.DialogCode.Rejected
        )
        try:
            UIEventCoordinator.open_areas_dialog(coordinator)
        finally:
            ui_event_coordinator.BidAreasDialog = old_dialog
            ui_event_coordinator.exec_with_ost_blocking = old_exec
        self.assertEqual(reload_calls, ["db.mdb"])

    def test_sql_master_data_save_transfers_and_reacquires_modal_lease(self):
        database_id = "sql-database"
        lease_requests = []
        queued_handles = []
        queued_callbacks = []
        released_handles = []
        completions = []
        access_allowed = [True]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return True

            @staticmethod
            def queue_job_statuses_save(
                file_path,
                changes,
                callback,
                *,
                edit_lease_handle,
            ):
                self.assertEqual(file_path, database_id)
                self.assertTrue(changes["updated"])
                queued_handles.append(edit_lease_handle)
                queued_callbacks.append(callback)
                return 1

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = QtWidgets.QWidget()
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator._icon_provider = FakeIconProvider()
        coordinator._editable_master_data_file_path = lambda: database_id
        coordinator._project_write_service = WriteService()
        coordinator._project_read_service = SimpleNamespace()
        coordinator.project_data = SimpleNamespace(
            get_job_status_snapshot=lambda _file_path: [
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
            get_used_job_status_uids=lambda _file_path: set(),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path=database_id,
            get_selected_bid_ref=lambda: None,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: access_allowed[0]
        )
        coordinator.event_bus = EventBus()

        def request_local_edit(
            file_path,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            handle = EditLeaseHandle(
                database_id=file_path,
                draft_id=f"draft-{len(lease_requests) + 1}",
                runtime_generation=1,
                operation_id=operation_id,
                owning_surface=owning_surface,
                resources=resources,
                dependency_resources=dependency_resources,
            )
            lease_requests.append(handle)
            callback(EditLeaseResult(True, handle=handle))

        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=request_local_edit,
            end_edit_lease=released_handles.append,
        )

        def exercise_save(dialog, _event_bus):
            started = dialog._save_async_fn(
                {
                    "new": [],
                    "updated": [
                        JobStatus(
                            uid="status-1",
                            name="Awarded",
                            locked=False,
                            sequence=1,
                        )
                    ],
                    "deleted_uids": [],
                },
                lambda success, mapping: completions.append((success, mapping)),
            )
            self.assertTrue(started)
            operation_id = str(uuid.uuid4())
            queued_callbacks[0](
                QueuedMutationResult(
                    database_id=database_id,
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(
                        MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED
                    ),
                )
            )
            self.assertEqual(completions, [])
            self.assertEqual(len(lease_requests), 1)
            queued_callbacks[0](
                QueuedMutationResult(
                    database_id=database_id,
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    authoritative_result=AuthoritativeMutationResult(
                        affected_families=("job_statuses",)
                    ),
                )
            )
            access_allowed[0] = False
            self.assertFalse(
                dialog._save_async_fn(
                    {
                        "new": [],
                        "updated": [
                            JobStatus(
                                uid="status-1",
                                name="Closed",
                                locked=False,
                                sequence=1,
                            )
                        ],
                        "deleted_uids": [],
                    },
                    lambda success, mapping: completions.append((success, mapping)),
                )
            )

        try:
            with patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=exercise_save,
            ):
                coordinator.open_job_statuses_dialog()
        finally:
            coordinator.main_window.close()
            coordinator.main_window.deleteLater()
        self.assertEqual(len(lease_requests), 2)
        self.assertEqual(queued_handles, [lease_requests[0]])
        self.assertEqual(released_handles, [lease_requests[1]])
        self.assertEqual(completions, [(True, {}), (False, None)])
        self.assertEqual(
            {resource.resource_type for resource in lease_requests[0].resources},
            {"job_status", "job_statuses_collection"},
        )

    def test_base_picker_does_not_accept_when_save_returns_false(self):
        dialog = self._payroll_class_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_dialog_does_not_accept_when_save_returns_false(self):
        dialog = self._employee_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_cannot_navigate_past_invalid_required_fields(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
            ),
            EmployeeRecord(
                uid="emp-2",
                employee_no="2",
                first_name="Mia",
                last_name="Ray",
            ),
        ]
        dialog = EmployeeDetailDialog(
            FakeIconProvider(), employees, 0, make_workspace_state_model()
        )
        try:
            dialog.edit_first_name.clear()
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                dialog._on_next()
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].first_name, "Ava")
            warning.assert_called_once_with(
                dialog, "Employee Detail", "First Name is required."
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_cannot_navigate_past_unknown_pay_class(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
                pay_class_uid="pay-1",
            ),
            EmployeeRecord(
                uid="emp-2",
                employee_no="2",
                first_name="Mia",
                last_name="Ray",
            ),
        ]
        dialog = EmployeeDetailDialog(
            FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
        )
        try:
            dialog.combo_pay_class.setEditText("Unknown")
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "confirm_not_found",
                return_value=False,
            ) as confirm:
                dialog._on_next()
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].pay_class_uid, "pay-1")
            confirm.assert_called_once_with(dialog, "Unknown")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_new_employee_saves_immediately_and_selects_real_uid(self):
        save_calls = []

        def save_fn(changes):
            employee = changes["new"][0]
            save_calls.append(
                {
                    "new_uid": employee.uid,
                    "new_is_new": employee.is_new,
                    "updated": list(changes["updated"]),
                }
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0]["new_uid"], "new_0")
            self.assertTrue(save_calls[0]["new_is_new"])
            self.assertEqual(save_calls[0]["updated"], [])
            current_item = dialog.tree.currentItem()
            self.assertIsNotNone(current_item)
            self.assertEqual(current_item.data(0, dialog._UID_ROLE), "emp-2")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog._employees[-1].uid, "emp-2")
            self.assertFalse(dialog._employees[-1].is_new)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_new_employee_remains_after_reopen_from_saved_source(self):
        saved_employees = []

        def save_fn(changes):
            employee = changes["new"][0]
            saved_employees.append(
                Employee(
                    uid="emp-2",
                    employee_no=employee.employee_no,
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                )
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
        reopened = EmployeesDialog(
            FakeIconProvider(),
            employees=saved_employees,
            selected_uid="emp-2",
        )
        try:
            self.assertEqual(reopened.tree.topLevelItemCount(), 1)
            self.assertEqual(
                reopened.tree.topLevelItem(0).data(0, reopened._UID_ROLE), "emp-2"
            )
            self.assertEqual(reopened.tree.currentItem().text(1), "Mia Ray")
        finally:
            reopened.close()
            reopened.cleanup()
            reopened.deleteLater()

    def test_employee_detail_cancel_does_not_save_new_employee(self):
        save_calls = []
        dialog = self._employee_dialog_with_save(
            lambda changes: save_calls.append(changes) or {"new_0": "emp-2"}
        )
        try:
            detail_dialog = self._employee_detail_dialog_stub(
                QtWidgets.QDialog.DialogCode.Rejected
            )
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(save_calls, [])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_cancel_does_not_modify_existing_employee(self):
        dialog = self._employee_dialog()
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            detail_dialog = self._employee_detail_dialog_stub(
                QtWidgets.QDialog.DialogCode.Rejected
            )
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_change()
            self.assertEqual(dialog._employees[0].first_name, "Ava")
            self.assertEqual(dialog._employees[0].last_name, "Lee")
            self.assertEqual(dialog.tree.topLevelItem(0).text(1), "Ava Lee")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_async_create_requires_authoritative_uid_mapping(self):
        callbacks = []
        dialog = EmployeesDialog(
            FakeIconProvider(),
            employees=[],
            save_async_fn=lambda _changes, completed: (
                callbacks.append(completed) or True
            ),
            menu_mode=True,
        )
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                self._employee_detail_dialog_stub(),
            ):
                dialog._on_new_with_first_name("Mia")
            dialog.accept()
            self.assertTrue(dialog._operation_pending)
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog.show_warning"
            ) as warning:
                callbacks[0](True, {})
            self.assertFalse(dialog._operation_pending)
            self.assertFalse(dialog._save_done)
            self.assertTrue(dialog._employees[0].is_new)
            self.assertEqual(dialog._employees[0].uid, "new_0")
            warning.assert_called_once_with(
                dialog, "Employees", "Failed to create employee."
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_async_failure_preserves_external_interactivity_block(self):
        callbacks = []
        dialog = EmployeesDialog(
            FakeIconProvider(),
            employees=[Employee(uid="emp-1", first_name="Ava")],
            save_async_fn=lambda _changes, completed: (
                callbacks.append(completed) or True
            ),
            menu_mode=True,
        )
        try:
            dialog._employees[0].first_name = "Mia"
            dialog.accept()
            dialog.set_interactive(False)
            callbacks[0](False, None)
            self.assertFalse(dialog._interactive)
            self.assertFalse(dialog.btn_new.isEnabled())
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    @staticmethod
    def _employee_detail_dialog_stub(
        result=QtWidgets.QDialog.DialogCode.Accepted,
    ):
        class DetailDialog:
            def __init__(
                self,
                _icon_provider,
                employees,
                current_index,
                parent=None,
                pay_classes=None,
                pay_classes_save_fn=None,
                pay_classes_save_async_fn=None,
                workspace_state_model=make_workspace_state_model(),
            ):
                self._employees = list(employees)
                self._current_index = current_index
                employee = self._employees[current_index]
                employee.employee_no = "2"
                employee.first_name = "Mia"
                employee.last_name = "Ray"

            def exec(self):
                return result

            def get_results(self):
                return self._employees

            def get_current_uid(self):
                return self._employees[self._current_index].uid

            def get_pay_classes(self):
                return []

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        return DetailDialog

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

    def test_condition_type_rename_rolls_back_when_save_fails(self):
        reload_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            reload_fn=lambda: reload_calls.append("reload") or [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog._set_item_text(item, "Asphalt")
            with patch(
                "ost_visualizer.presentation.dialogs.condition_types_dialog.show_warning"
            ):
                dialog._on_item_changed(item, 0)
            self.assertEqual(item.text(0), "Concrete")
            self.assertEqual(reload_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_async_create_rejection_removes_provisional_row(self):
        async_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[],
            save_fn=lambda _changes: self.fail("sync save must not run"),
            save_async_fn=lambda changes, _completed: (
                async_calls.append(changes) or False
            ),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Concrete")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 0)
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layer_async_create_rejection_removes_provisional_row(self):
        async_calls = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[],
            insert_fn=lambda _name, _sequence: self.fail("sync insert must not run"),
            insert_async_fn=lambda name, sequence, _completed: (
                async_calls.append((name, sequence)) or False
            ),
            reload_fn=lambda: [],
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(2, "Layer 1")
            dialog.tree.blockSignals(False)
            dialog._on_item_changed(item, 2)
            self.assertEqual(async_calls, [("Layer 1", 0)])
            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
            self.assertIsNone(dialog._pending_new_item)
            self.assertTrue(dialog._is_interactive)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_async_master_data_completion_preserves_external_interactivity_block(self):
        condition_callbacks = []
        condition_dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: self.fail("sync save must not run"),
            save_async_fn=lambda _changes, completed: (
                condition_callbacks.append(completed) or True
            ),
            reload_fn=lambda: [CdnType(uid="type-1", name="Asphalt")],
            menu_mode=True,
        )
        layer_callbacks = []
        layer_dialog = LayersDialog(
            FakeIconProvider(),
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
            condition_dialog.set_interactive(False)
            layer_dialog.set_interactive(False)
            condition_callbacks[0](True, {})
            layer_callbacks[0](True, None)
            self.assertFalse(condition_dialog._is_interactive)
            self.assertFalse(layer_dialog._is_interactive)
            self.assertFalse(condition_dialog.btn_new.isEnabled())
            self.assertFalse(layer_dialog.btn_new.isEnabled())
        finally:
            condition_dialog.close()
            condition_dialog.cleanup()
            condition_dialog.deleteLater()
            layer_dialog.close()
            layer_dialog.cleanup()
            layer_dialog.deleteLater()

    def test_condition_type_delete_keeps_row_when_save_fails(self):
        reload_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            reload_fn=lambda: reload_calls.append("reload") or [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs."
                    "condition_types_dialog.confirm_multi_delete",
                    return_value=[("Concrete", "type-1")],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.condition_types_dialog.show_warning"
                ),
            ):
                dialog._on_delete()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.tree.topLevelItem(0).text(0), "Concrete")
            self.assertEqual(reload_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_uses_shared_validation_for_blocked_uids(self):
        validate_calls = []
        delete_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: False,
            blocked_delete_uids_fn=lambda uids: validate_calls.append(list(uids))
            or set(),
            delete_fn=lambda uids: delete_calls.append(list(uids))
            or WriteReloadResult({}, True, True),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            with patch(
                "ost_visualizer.presentation.dialogs."
                "condition_types_dialog.confirm_multi_delete",
                return_value=[("Concrete", "type-1")],
            ) as confirm_delete:
                dialog._on_delete()
            self.assertEqual(validate_calls, [["type-1"]])
            self.assertEqual(delete_calls, [["type-1"]])
            self.assertEqual(confirm_delete.call_args.args[3], set())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_interactivity_revocation_blocks_inline_writes(self):
        save_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda changes: save_calls.append(changes) or {},
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._set_item_text(item, "Asphalt")
            dialog._on_item_changed(item, 0)
            self.assertEqual(item.text(0), "Concrete")
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_delete_validation_failure_is_contained(self):
        delete_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda _changes: {},
            blocked_delete_uids_fn=lambda _uids: (_ for _ in ()).throw(
                RuntimeError("validation unavailable")
            ),
            delete_fn=lambda uids: delete_calls.append(list(uids)),
            reload_fn=lambda: [],
            menu_mode=True,
        )
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            with (
                patch(
                    "ost_visualizer.presentation.dialogs."
                    "condition_types_dialog.confirm_multi_delete"
                ) as confirm_delete,
                patch(
                    "ost_visualizer.presentation.dialogs.condition_types_dialog."
                    "show_warning"
                ) as warning,
            ):
                dialog._on_delete()
            confirm_delete.assert_not_called()
            warning.assert_called_once_with(
                dialog,
                "Condition Types",
                "Failed to validate condition type deletion.",
            )
            self.assertEqual(delete_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_condition_type_stale_selected_item_does_not_crash_button_update(self):
        save_calls = []
        dialog = ConditionTypesDialog(
            FakeIconProvider(),
            condition_types=[CdnType(uid="type-1", name="Concrete")],
            save_fn=lambda changes: save_calls.append(changes) or {},
            reload_fn=lambda: [],
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog._items = []
            dialog._update_button_states()
            item.setText(0, "Asphalt")
            dialog._on_item_changed(item, 0)
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertEqual(save_calls, [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_select_mode_shows_select_and_cancel(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
        )
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertIn("Select", button_texts)
            self.assertIn("Cancel", button_texts)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_interactivity_revocation_blocks_inline_writes(self):
        rename_calls = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
            reload_fn=lambda: [],
            update_name_fn=lambda uid, name: rename_calls.append((uid, name)) or True,
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.set_interactive(False)
            self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers,
            )
            dialog._set_item_text(item, "Renamed")
            dialog._on_item_changed(item, 2)
            self.assertEqual(item.text(2), "Layer 1")
            self.assertEqual(rename_calls, [])
            dialog.set_interactive(True)
            self.assertTrue(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            self.assertEqual(
                dialog.tree.editTriggers(),
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked,
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_shows_ok_only_for_close_action(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._default_layer("layer-1", "Layer 1", 1)],
            mode=LayersDialogMode.DEFAULT_LAYERS,
        )
        try:
            button_texts = [
                button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
            ]
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertIsNone(dialog.btn_cancel)
            self.assertIn("OK", button_texts)
            self.assertNotIn("Select", button_texts)
            self.assertNotIn("Cancel", button_texts)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_dialog_allows_template_layer_management(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._default_layer("default-1", "Default 1", 1),
                self._default_layer("default-2", "Default 2", 2),
                self._layer("bid-layer-1", "Bid Layer", 3),
            ],
            mode=LayersDialogMode.DEFAULT_LAYERS,
        )
        try:
            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
            default_item = dialog.tree.topLevelItem(0)
            self.assertTrue(default_item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
            dialog.tree.setCurrentItem(default_item)
            dialog._update_button_states()
            self.assertTrue(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertTrue(dialog.btn_move_down.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_default_layers_menu_opens_layers_dialog_with_default_source(self):
        default_layers = [self._default_layer("default-1", "Default 1", 1)]
        observed = {}

        class ReadService:
            def __init__(self):
                self.default_calls = []

            def get_default_layers(self, file_path):
                self.default_calls.append(file_path)
                return list(default_layers)

            def get_merged_bid_layers(self, _file_path, _bid_uid):
                raise AssertionError("Default Layers should not load bid layers")

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return False

            def insert_default_layer_result(self, db_path, name, after_sequence):
                observed["insert"] = (db_path, name, after_sequence)
                return WriteReloadResult("default-new", True, True)

            def delete_default_layers(self, db_path, layer_uids):
                observed["delete"] = (db_path, list(layer_uids))
                return BatchWriteResult(
                    requested_uids=list(layer_uids),
                    succeeded_uids=list(layer_uids),
                    reload_success=True,
                )

            def update_default_layer_show(self, db_path, layer_uid, show):
                observed["show"] = (db_path, layer_uid, show)
                return True

            def update_all_default_layers_show(self, db_path, show):
                observed["show_all"] = (db_path, show)
                return True

            def update_default_layer_name(self, db_path, layer_uid, name):
                observed["name"] = (db_path, layer_uid, name)
                return True

            def swap_default_layer_sequence(self, db_path, layer_uid, neighbor_uid):
                observed["move"] = (db_path, layer_uid, neighbor_uid)
                return True

        class ProjectData:
            def __init__(self):
                self.current_file = None

            def set_current_file(self, file_path):
                self.current_file = file_path

        class AccessManager:
            allowed = True

            def is_allowed(self, _feature):
                return self.allowed

        class MainWindow(QtWidgets.QWidget):
            def get_selected_database_context_file_path(self):
                return "defaults.mdb"

        read_service = ReadService()
        project_data = ProjectData()
        main_window = MainWindow()
        access_manager = AccessManager()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = main_window
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="defaults.mdb",
            get_selected_bid_ref=lambda: None,
        )
        coordinator.ui_access_manager = access_manager
        coordinator.project_data = project_data
        coordinator._icon_provider = FakeIconProvider()
        coordinator._project_read_service = read_service
        coordinator._project_write_service = WriteService()
        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=lambda database_id, resources, callback, **_kwargs: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id=database_id,
                            draft_id="layers-test-draft",
                            runtime_generation=0,
                            operation_id="layers-test-edit",
                            owning_surface="test",
                            resources=resources,
                        ),
                    )
                )
            ),
            end_edit_lease=lambda _handle: None,
        )
        coordinator.event_bus = EventBus()

        def capture_dialog(dialog, _event_bus):
            observed["button_text"] = dialog.btn_select.text()
            observed["cancel_button"] = dialog.btn_cancel
            observed["layer_names"] = [layer.name for layer in dialog._layers]
            observed["async_callbacks"] = (
                dialog._insert_async_fn,
                dialog._delete_many_async_fn,
                dialog._update_name_async_fn,
                dialog._move_async_fn,
                dialog._update_show_async_fn,
                dialog._update_all_show_async_fn,
            )
            observed["new_uid"] = dialog._insert_fn("Added", 1)
            access_manager.allowed = False
            dialog._delete_many_fn(["default-1"])
            dialog._update_show_fn("default-1", False)
            dialog._update_all_show_fn(False)
            dialog._update_name_fn("default-1", "Renamed")
            dialog._move_fn("default-1", "default-2")

        try:
            with patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=capture_dialog,
            ):
                UIEventCoordinator.open_default_layers_dialog(coordinator)
        finally:
            main_window.close()
            main_window.deleteLater()
        self.assertEqual(read_service.default_calls, ["defaults.mdb"])
        self.assertEqual(project_data.current_file, "defaults.mdb")
        self.assertEqual(observed["button_text"], "OK")
        self.assertIsNone(observed["cancel_button"])
        self.assertEqual(observed["layer_names"], ["Default 1"])
        self.assertEqual(observed["async_callbacks"], (None,) * 6)
        self.assertEqual(observed["insert"], ("defaults.mdb", "Added", 1))
        self.assertEqual(observed["new_uid"], "default-new")
        self.assertNotIn("delete", observed)
        self.assertNotIn("show", observed)
        self.assertNotIn("show_all", observed)
        self.assertNotIn("name", observed)
        self.assertNotIn("move", observed)

    def test_access_master_data_menus_do_not_install_sql_save_callbacks(self):
        dialogs = []
        main_window = QtWidgets.QWidget()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = main_window
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator._icon_provider = FakeIconProvider()
        coordinator._editable_master_data_file_path = lambda: "master-data.mdb"
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator._project_read_service = SimpleNamespace(
            get_employees_and_pay_classes=lambda _file_path: (
                [
                    Employee(
                        uid="emp-1",
                        employee_no="1",
                        first_name="Ava",
                        last_name="Lee",
                    )
                ],
                [PayClass(uid="pay-1", name="Regular")],
            ),
            get_estimator_uids_in_use=lambda _file_path: set(),
            get_job_statuses=lambda _file_path: [
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: None
        )
        coordinator._exec_with_collaboration_lease = (
            lambda dialog, *_args, **_kwargs: dialogs.append(dialog)
        )
        try:
            coordinator.open_employees_dialog()
            coordinator.open_job_statuses_dialog()
            coordinator.open_payroll_classes_dialog()
            self.assertEqual(len(dialogs), 3)
            employees, job_statuses, pay_classes = dialogs
            self.assertIsNone(employees._save_async_fn)
            self.assertIsNone(employees._pay_classes_save_async_fn)
            self.assertIsNone(job_statuses._save_async_fn)
            self.assertIsNone(pay_classes._save_async_fn)
        finally:
            for dialog in dialogs:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()
            main_window.close()
            main_window.deleteLater()

    def test_layers_dialog_multi_delete_uses_batch_callback_once(self):
        delete_many_calls = []
        reload_calls = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload") or [],
            delete_many_fn=lambda uids: delete_many_calls.append(list(uids))
            or BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1", "layer-2"],
                failed_uids=[],
                reload_success=True,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch("ost_visualizer.presentation.dialogs.layers_dialog.show_warning"),
            ):
                dialog._on_delete()
            self.assertEqual(delete_many_calls, [["layer-1", "layer-2"]])
            self.assertEqual(reload_calls, ["reload"])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_checkbox_click_updates_state_and_visual_immediately(self):
        actual_show = {"layer-1": True}

        def update_show(layer_uid, show):
            actual_show[layer_uid] = bool(show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            self.app.processEvents()
            checkbox = dialog._checkboxes[0]
            self._click_checkbox(checkbox)
            self.assertFalse(actual_show["layer-1"])
            self.assertFalse(checkbox.isChecked())
            self.assertFalse(dialog._layers[0].show)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_checkbox_repeated_clicks_alternate_cleanly(self):
        actual_show = {"layer-1": True}
        calls = []

        def update_show(layer_uid, show):
            calls.append((layer_uid, bool(show)))
            actual_show[layer_uid] = bool(show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            self.app.processEvents()
            checkbox = dialog._checkboxes[0]
            observed = []
            for _ in range(3):
                self._click_checkbox(checkbox)
                observed.append((actual_show["layer-1"], checkbox.isChecked()))
            self.assertEqual(
                observed,
                [(False, False), (True, True), (False, False)],
            )
            self.assertEqual(
                calls,
                [
                    ("layer-1", False),
                    ("layer-1", True),
                    ("layer-1", False),
                ],
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_and_sidebar_checkbox_state_stay_synchronized(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])

        def update_show(layer_uid, show):
            sidebar.set_layer_visible(layer_uid, show)
            return True

        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1, show=True)],
            reload_fn=lambda: [self._layer("layer-1", "Layer 1", 1, show=True)],
            update_show_fn=update_show,
        )
        try:
            dialog.show()
            sidebar.show()
            self.app.processEvents()
            self._click_checkbox(dialog._checkboxes[0])
            self.assertFalse(dialog._checkboxes[0].isChecked())
            self.assertFalse(dialog._layers[0].show)
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            layer = next(
                layer for layer in sidebar.get_layers() if layer.uid == "layer-1"
            )
            self.assertFalse(layer.show)
            self._click_checkbox(dialog._checkboxes[0])
            self.assertTrue(dialog._checkboxes[0].isChecked())
            self.assertTrue(dialog._layers[0].show)
            self.assertTrue(sidebar._checkboxes[0].isChecked())
            layer = next(
                layer for layer in sidebar.get_layers() if layer.uid == "layer-1"
            )
            self.assertTrue(layer.show)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_checkbox_click_updates_visual_state_and_emits_once(self):
        sidebar = BidLayersSidebar(None)
        calls = []
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1, show=True)])
        sidebar.set_toggle_callback(lambda uid, show: calls.append((uid, show)))
        try:
            self._click_checkbox(sidebar._checkboxes[0])
            self.assertFalse(sidebar._checkboxes[0].isChecked())
            self.assertEqual(calls, [("layer-1", False)])
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_reload_cancels_pending_new_layer_editor(self):
        sidebar = BidLayersSidebar(None)
        layer = self._layer("layer-1", "Layer 1", 1)
        sidebar.load_layers([layer])
        sidebar.set_pending_selection(layer.uid)
        try:
            sidebar._on_add_clicked()
            self.assertIsNotNone(sidebar._pending_new_item)
            self.assertTrue(sidebar._pending_new_editor_connected)
            sidebar.load_layers([layer])
            self.assertIsNone(sidebar._pending_new_item)
            self.assertFalse(sidebar._pending_new_editor_connected)
            self.assertEqual(sidebar._selected_uid, layer.uid)
            self.assertEqual(sidebar._table.topLevelItemCount(), 1)
            sidebar._on_add_clicked()
            self.assertIsNotNone(sidebar._pending_new_item)
            self.assertEqual(sidebar._table.topLevelItemCount(), 2)
        finally:
            sidebar.clear()
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_sidebar_inline_rename_rejects_blank_and_trims_name(self):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers([self._layer("layer-1", "Layer 1", 1)])
        renamed = []
        sidebar.layer_renamed.connect(
            lambda layer_uid, name: renamed.append((layer_uid, name))
        )
        item = sidebar._table.topLevelItem(0)
        try:
            item.setText(1, "   ")
            self.assertEqual(item.text(1), "Layer 1")
            self.assertEqual(renamed, [])
            item.setText(1, "  Renamed Layer  ")
            self.assertEqual(renamed, [("layer-1", "Renamed Layer")])
        finally:
            sidebar.close()
            sidebar.deleteLater()

    def test_layers_dialog_partial_batch_delete_reloads_and_warns(self):
        reload_calls = []
        warnings = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload")
            or [self._layer("layer-2", "Layer 2", 2)],
            delete_many_fn=lambda _uids: BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1"],
                failed_uids=["layer-2"],
                reload_success=True,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning",
                    side_effect=lambda *_args: warnings.append(_args),
                ),
            ):
                dialog._on_delete()
            self.assertEqual(reload_calls, ["reload"])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.tree.topLevelItem(0).text(2), "Layer 2")
            self.assertEqual(len(warnings), 1)
            self.assertIn("Some layers were deleted", warnings[0][2])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_refresh_failure_warning_is_not_partial_delete(self):
        reload_calls = []
        warnings = []
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[
                self._layer("layer-1", "Layer 1", 1),
                self._layer("layer-2", "Layer 2", 2),
            ],
            reload_fn=lambda: reload_calls.append("reload") or [],
            delete_many_fn=lambda _uids: BatchWriteResult(
                requested_uids=["layer-1", "layer-2"],
                succeeded_uids=["layer-1", "layer-2"],
                failed_uids=[],
                reload_success=False,
            ),
        )
        try:
            for i in range(dialog.tree.topLevelItemCount()):
                dialog.tree.topLevelItem(i).setSelected(True)
            with (
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.confirm_multi_delete",
                    return_value=[
                        ("Layer 1", "layer-1"),
                        ("Layer 2", "layer-2"),
                    ],
                ),
                patch(
                    "ost_visualizer.presentation.dialogs.layers_dialog.show_warning",
                    side_effect=lambda *_args: warnings.append(_args),
                ),
            ):
                dialog._on_delete()
            self.assertEqual(reload_calls, ["reload"])
            self.assertEqual(len(warnings), 1)
            self.assertIn("refresh failed", warnings[0][2])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_layers_dialog_stale_selected_item_does_not_crash_button_update(self):
        dialog = LayersDialog(
            FakeIconProvider(),
            layers=[self._layer("layer-1", "Layer 1", 1)],
        )
        try:
            item = dialog.tree.topLevelItem(0)
            dialog.tree.setCurrentItem(item)
            dialog._layers = []
            dialog._update_button_states()
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.btn_delete.isEnabled())
            self.assertFalse(dialog.btn_move_up.isEnabled())
            self.assertFalse(dialog.btn_move_down.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
