import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.adjust_images_dialog import (
    AdjustImagesDialog,
)
from ost_visualizer.presentation.dialogs.set_scale_dialog import SetScaleDialog
from ost_visualizer.presentation.dialogs.rename_page_dialog import (
    PageRenameTarget,
    RenamePageDialog,
)
from ost_visualizer.presentation.services.modal_edit_lease_session import (
    ModalEditLeaseSession,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class PageSettingsModalLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_adjust_images_waits_for_authoritative_async_save(self):
        callbacks = []
        dialog = AdjustImagesDialog(
            None,
            None,
            0,
            False,
            False,
            False,
            False,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        try:
            dialog._flip_x_check.setChecked(True)
            dialog._on_ok()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertFalse(dialog._ok_btn.isEnabled())
            dialog.reject()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            callbacks[0](True)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_access_page_setting_modals_tolerate_parent_destruction(self):
        class DestroyedWithParentDialog(QtWidgets.QDialog):
            def __init__(self, *args, **_kwargs):
                super().__init__(args[1])

            def cleanup(self):
                pass

        cases = (
            ("AdjustImagesDialog", "open_adjust_images_dialog"),
            ("SetScaleDialog", "open_set_scale_dialog"),
            ("RenamePageDialog", "open_rename_page_dialog"),
        )
        for dialog_name, method_name in cases:
            with self.subTest(dialog=dialog_name):
                window = QtWidgets.QWidget()
                page = Page(uid="page-1", name="Page 1")
                bid_ref = BidRef("database.mdb", "8")
                coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
                coordinator.main_window = window
                coordinator.event_bus = EventBus()
                coordinator._icon_provider = None
                coordinator.ui_state_manager = SimpleNamespace(
                    active_page_uid=page.uid,
                    get_selected_bid_ref=lambda: bid_ref,
                )
                coordinator.ui_access_manager = SimpleNamespace(
                    is_allowed=lambda _feature: True
                )
                coordinator.project_data = SimpleNamespace(
                    get_page=lambda uid: page if uid == page.uid else None
                )
                coordinator.takeoff_sidebar = SimpleNamespace(
                    get_page_order=lambda: [page.uid]
                )
                coordinator._project_write_service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _database_id: False
                )

                def destroy_parent(_dialog, _event_bus):
                    delete(window)
                    return QtWidgets.QDialog.DialogCode.Rejected

                with patch(
                    "ost_visualizer.presentation.coordinators."
                    f"ui_event_coordinator.{dialog_name}",
                    DestroyedWithParentDialog,
                ), patch(
                    "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                    "exec_with_ost_blocking",
                    side_effect=destroy_parent,
                ):
                    getattr(coordinator, method_name)()

    def test_set_scale_failure_restores_interactive_retry(self):
        callbacks = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        try:
            dialog._custom_radio.setChecked(True)
            dialog._custom_factor2_edit.setText("96")
            dialog._on_apply()
            self.assertFalse(dialog._ok_btn.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
            ):
                callbacks[0](False)
            self.assertTrue(dialog._ok_btn.isEnabled())
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_rename_page_focus_timer_is_dropped_after_dialog_destruction(self):
        dialog = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: True,
        )
        calls = []
        dialog._select_new_name = lambda: calls.append(True)
        dialog.show()
        delete(dialog)
        self.app.processEvents()
        self.assertEqual(calls, [])

    def test_adjust_images_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = AdjustImagesDialog(
            None,
            None,
            0,
            False,
            False,
            False,
            False,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        dialog._flip_x_check.setChecked(True)
        dialog._on_apply()
        delete(dialog)
        callbacks[0](True)

    def test_set_scale_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        dialog._custom_radio.setChecked(True)
        dialog._custom_factor2_edit.setText("96")
        dialog._on_apply()
        delete(dialog)
        callbacks[0](True)

    def test_rename_page_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = RenamePageDialog(
            None,
            None,
            [PageRenameTarget("page-1", "Page 1")],
            "page-1",
            lambda _uid, _name: self.fail("SQL must not use synchronous save"),
            save_async_fn=lambda _uid, _name, completed: callbacks.append(completed)
            or True,
        )
        dialog._new_name_edit.setText("Renamed")
        dialog._on_ok()
        delete(dialog)
        callbacks[0](True)

    def test_modal_closes_when_its_exact_sql_edit_lease_is_lost(self):
        events = EventBus()
        resource = ResourceRef("page", "42", 7)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft-before-reconnect",
            runtime_generation=3,
            operation_id="SetScaleDialog",
            owning_surface="main-window-dialog",
            resources=(resource,),
        )

        class Owner:
            @staticmethod
            def request_collaboration_edit(
                _database_id,
                _resources,
                callback,
                **_options,
            ):
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(_handle):
                self.fail("A lost lease must not be released as if it were current")

        dialog = QtWidgets.QDialog()
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        session = ModalEditLeaseSession(
            Owner(),
            "database",
            (resource,),
            "SetScaleDialog",
            event_bus=events,
        )
        session.bind_dialog(dialog)
        try:
            session.request_initial(lambda result: self.assertTrue(result.granted))
            events.publish(
                AppEvents.EDIT_LEASE_LOST,
                loss=EditLeaseLoss(
                    database_id=handle.database_id,
                    draft_id=handle.draft_id,
                    runtime_generation=handle.runtime_generation,
                    operation_id=handle.operation_id,
                    owning_surface=handle.owning_surface,
                    resources=handle.resources,
                    reason="trust-lost",
                ),
            )
            self.assertEqual(rejected, [True])
        finally:
            session.close()
            dialog.deleteLater()

    def test_closed_modal_releases_a_late_initial_lease_grant(self):
        events = EventBus()
        resource = ResourceRef("page", "42", 7)
        pending = []
        released = []
        completed = []

        class Owner:
            @staticmethod
            def request_collaboration_edit(
                _database_id,
                _resources,
                callback,
                **_options,
            ):
                pending.append(callback)

            @staticmethod
            def end_collaboration_edit(handle):
                released.append(handle)

        session = ModalEditLeaseSession(
            Owner(),
            "database",
            (resource,),
            "SetScaleDialog",
            event_bus=events,
        )
        session.request_initial(completed.append)
        session.close()
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="late-draft",
            runtime_generation=3,
            operation_id="SetScaleDialog",
            owning_surface="main-window-dialog",
            resources=(resource,),
        )
        pending[0](EditLeaseResult(True, handle=handle))
        self.assertEqual(released, [handle])
        self.assertEqual(len(completed), 1)
        self.assertFalse(completed[0].granted)


if __name__ == "__main__":
    unittest.main()
