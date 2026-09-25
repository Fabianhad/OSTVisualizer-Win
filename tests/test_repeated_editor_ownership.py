import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionResultDto,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.areas_dialog import BidAreasDialog
from ost_visualizer.presentation.dialogs.layers_dialog import LayersDialog
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from PySide6 import QtWidgets
from tests.workspace_state_test_support import make_workspace_state_model


class FakeReadService:
    def display_to_inches(self, text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    def inches_to_display(self, value, _metric):
        return "" if not value else str(value)

    def get_quantity_options_for_type(self, _condition_type):
        return []

    def get_valid_uoms_for_calc_type(self, _calc_type, _metric):
        return []


class RepeatedEditorOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_condition_handler_rebinds_same_dialog_after_each_mdb_or_sql_save(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                original = Condition(uid="1", name="Original", ref_no=1)
                conditions = {"1": original}
                saves = []
                handles = []
                sidebar = QtWidgets.QWidget()
                sidebar.collect_ordered_condition_uids = lambda: ["1"]
                bid_ref = BidRef("sql-id" if sql else "test.mdb", "7")
                data = SimpleNamespace(
                    is_current_bid_locked=lambda: False,
                    get_bid_conditions=lambda: conditions,
                    get_all_takeoffs=lambda: [],
                    get_current_bid=lambda: SimpleNamespace(measure_base=0),
                    get_cdn_types=lambda: {},
                    get_bid_layer_snapshot=lambda: [],
                    get_layer_uids_in_use=lambda: set(),
                )
                read = FakeReadService()
                read.get_cdn_types = lambda _db: {}
                read.get_merged_bid_layers = lambda _db, _bid: []

                def update(_database, _bid, uid, dto):
                    conditions[uid] = replace(conditions[uid], **dto.get_changes())
                    saves.append(conditions[uid])
                    return UpdateConditionResultDto(success=True)

                def queue(
                    database, _bid, uids, changes, completed, *, edit_lease_handle
                ):
                    conditions[uids[0]] = replace(conditions[uids[0]], **changes)
                    saves.append(conditions[uids[0]])
                    handles.append(edit_lease_handle)
                    completed(
                        QueuedMutationResult(
                            database_id=database,
                            runtime_generation=1,
                            operation_id="00000000-0000-0000-0000-000000000001",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )
                    return len(saves)

                def grant(database, resources, completed, **options):
                    completed(
                        EditLeaseResult(
                            True,
                            handle=EditLeaseHandle(
                                database,
                                f"draft-{len(saves)}",
                                1,
                                options["operation_id"],
                                options["owning_surface"],
                                resources,
                            ),
                        )
                    )

                coordinator = SimpleNamespace(
                    ui_access_manager=Mock(),
                    conditions_sidebar=sidebar,
                    main_window=SimpleNamespace(icon_provider=None),
                    event_bus=EventBus(),
                    highlight_sidebar=Mock(),
                    placement=SimpleNamespace(is_active=False),
                    flush_deferred_for_file=lambda _database: True,
                    request_collaboration_edit=grant,
                    end_collaboration_edit=Mock(),
                )
                coordinator.ui_access_manager.is_allowed.return_value = True
                service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _db: sql,
                    update_condition=update,
                    queue_conditions_update=queue,
                )
                handler = ConditionActionHandler(
                    coordinator,
                    service,
                    read,
                    data,
                    SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
                    make_workspace_state_model(),
                )

                def interact(dialog, _events):
                    dialog.show()
                    try:
                        self.assertIs(dialog._current_condition(), original)
                        for name in ("Second", "Third"):
                            previous = dialog._current_condition()
                            dialog._name_edit.setText(name)
                            dialog._on_apply()
                            self.assertIsNot(conditions["1"], previous)
                            self.assertIs(dialog._current_condition(), conditions["1"])
                            self.assertEqual(dialog._current_condition().name, name)
                            self.assertFalse(dialog._dirty)
                            self.assertTrue(dialog.isVisible())
                        return QtWidgets.QDialog.DialogCode.Rejected
                    finally:
                        dialog.reject()

                try:
                    with patch(
                        "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
                        side_effect=interact,
                    ):
                        handler.on_edit_requested(["1"])
                    self.assertEqual(len(saves), 2)
                    if sql:
                        self.assertIsNot(handles[0], handles[1])
                finally:
                    sidebar.close()
                    sidebar.deleteLater()

    def test_layers_repeated_rename_reloads_exact_replacement(self):
        original = BidLayer(
            uid="1", bid_uid="7", name="Original", sequence=1, show=True
        )
        layers = [original]
        saved = []

        def rename(uid, name):
            self.assertEqual(uid, "1")
            layers[0] = replace(layers[0], name=name)
            saved.append(layers[0])
            return True

        dialog = LayersDialog(
            Mock(),
            make_workspace_state_model(),
            layers=layers,
            reload_fn=lambda: layers,
            update_name_fn=rename,
        )
        try:
            dialog.show()
            self.assertIs(dialog._layers[0], original)
            for name in ("Second", "Third"):
                previous = dialog._layers[0]
                dialog.tree.topLevelItem(0).setText(2, name)
                self.assertIsNot(dialog._layers[0], previous)
                self.assertIs(dialog._layers[0], layers[0])
                self.assertEqual(dialog._layers[0].name, name)
            self.assertEqual(len(saved), 2)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_area_draft_uid_mapping_survives_second_save(self):
        changes = []

        def save(change):
            changes.append(change)
            return {"new_0": "42"} if change.new else {}

        dialog = BidAreasDialog(
            Mock(),
            make_workspace_state_model(),
            bid_areas=[],
            save_fn=save,
            bid_ref=BidRef("test.mdb", "7"),
        )
        try:
            dialog._on_new()
            item = dialog.tree.currentItem()
            dialog.tree.blockSignals(True)
            item.setText(0, "Second")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(item.data(0, dialog._UID_ROLE), "42")
            dialog.tree.blockSignals(True)
            item.setText(0, "Third")
            dialog.tree.blockSignals(False)
            self.assertTrue(dialog._live_save())
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[1].new, [])
            self.assertEqual(changes[1].updated[0].uid, "42")
            self.assertEqual(changes[1].updated[0].name, "Third")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
