import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.services.modal_edit_lease_session import (
    ModalEditLeaseSession,
)
from PySide6 import QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class ModalEditLeaseSessionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

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
