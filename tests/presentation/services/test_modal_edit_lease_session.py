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


def _handle(draft_id, runtime_generation=3, database_id="database"):
    return EditLeaseHandle(
        database_id=database_id,
        draft_id=draft_id,
        runtime_generation=runtime_generation,
        operation_id="SetScaleDialog",
        owning_surface="main-window-dialog",
        resources=(ResourceRef("page", "42", 7),),
    )


def _loss(handle, **overrides):
    values = dict(
        database_id=handle.database_id,
        draft_id=handle.draft_id,
        runtime_generation=handle.runtime_generation,
        operation_id=handle.operation_id,
        owning_surface=handle.owning_surface,
        resources=handle.resources,
        reason="trust-lost",
    )
    values.update(overrides)
    return EditLeaseLoss(**values)


class _ScriptedOwner:
    def __init__(self, *results):
        self._results = list(results)
        self.requests = 0
        self.released = []

    def request_collaboration_edit(
        self, _database_id, _resources, callback, **_options
    ):
        self.requests += 1
        callback(self._results.pop(0))

    def end_collaboration_edit(self, handle):
        self.released.append(handle)


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

    def test_lease_loss_for_another_draft_generation_or_database_keeps_modal_open(
        self,
    ):
        for overrides in (
            {"draft_id": "other-draft"},
            {"runtime_generation": 4},
            {"database_id": "other-database"},
        ):
            with self.subTest(overrides=overrides):
                events = EventBus()
                handle = _handle("draft-1")
                owner = _ScriptedOwner(EditLeaseResult(True, handle=handle))
                dialog = QtWidgets.QDialog()
                rejected = []
                dialog.rejected.connect(lambda: rejected.append(True))
                session = ModalEditLeaseSession(
                    owner,
                    "database",
                    handle.resources,
                    "SetScaleDialog",
                    event_bus=events,
                )
                session.bind_dialog(dialog)
                session.request_initial(lambda result: None)
                events.publish(
                    AppEvents.EDIT_LEASE_LOST, loss=_loss(handle, **overrides)
                )
                self.assertEqual(rejected, [])
                self.assertEqual(owner.released, [])
                session.close()
                self.assertEqual(owner.released, [handle])
                dialog.deleteLater()

    def test_close_releases_current_lease_once_and_ignores_later_loss_events(self):
        events = EventBus()
        handle = _handle("draft-1")
        owner = _ScriptedOwner(EditLeaseResult(True, handle=handle))
        dialog = QtWidgets.QDialog()
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        session = ModalEditLeaseSession(
            owner, "database", handle.resources, "SetScaleDialog", event_bus=events
        )
        session.bind_dialog(dialog)
        session.request_initial(lambda result: None)
        session.close()
        session.close()
        events.publish(AppEvents.EDIT_LEASE_LOST, loss=_loss(handle))
        self.assertEqual(owner.released, [handle])
        self.assertEqual(rejected, [])
        dialog.deleteLater()


class ModalEditLeaseSessionMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _session(self, owner):
        session = ModalEditLeaseSession(
            owner,
            "database",
            (ResourceRef("page", "42", 7),),
            "SetScaleDialog",
            event_bus=EventBus(),
        )
        self.addCleanup(session.close)
        return session

    def test_submit_without_a_granted_lease_is_refused_without_submitting(self):
        session = self._session(_ScriptedOwner())
        completed = []
        submitted = []
        started = session.submit_mutation(
            lambda handle, done: submitted.append(handle) or True,
            lambda success, value=None: completed.append((success, value)),
        )
        self.assertFalse(started)
        self.assertEqual(submitted, [])
        self.assertEqual(completed, [(False, None)])

    def test_successful_mutation_reacquires_lease_before_reporting_completion(self):
        first = _handle("draft-1")
        second = _handle("draft-2")
        owner = _ScriptedOwner(
            EditLeaseResult(True, handle=first), EditLeaseResult(True, handle=second)
        )
        session = self._session(owner)
        session.request_initial(lambda result: None)
        completed = []
        submitted = []

        def submit(handle, done):
            submitted.append(handle)
            done(True, "saved")
            return True

        self.assertTrue(
            session.submit_mutation(
                submit, lambda success, value=None: completed.append((success, value))
            )
        )
        self.assertEqual(submitted, [first])
        self.assertEqual(owner.requests, 2)
        self.assertEqual(completed, [(True, "saved")])
        session.close()
        self.assertEqual(owner.released, [second])

    def test_failed_reacquire_after_mutation_reports_failure_and_rejects_dialog(self):
        first = _handle("draft-1")
        owner = _ScriptedOwner(
            EditLeaseResult(True, handle=first),
            EditLeaseResult(False, "lease lost"),
        )
        session = self._session(owner)
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        session.bind_dialog(dialog)
        session.request_initial(lambda result: None)
        completed = []
        session.submit_mutation(
            lambda handle, done: done(True, "saved") or True,
            lambda success, value=None: completed.append((success, value)),
        )
        self.assertEqual(completed, [(False, None)])
        self.assertEqual(rejected, [True])

    def test_mutation_that_does_not_start_keeps_the_original_lease(self):
        first = _handle("draft-1")
        owner = _ScriptedOwner(EditLeaseResult(True, handle=first))
        session = self._session(owner)
        session.request_initial(lambda result: None)
        completed = []
        self.assertFalse(
            session.submit_mutation(
                lambda handle, done: False,
                lambda success, value=None: completed.append((success, value)),
            )
        )
        self.assertEqual(completed, [])
        self.assertEqual(owner.requests, 1)
        session.close()
        self.assertEqual(owner.released, [first])

    def test_mutation_that_raises_restores_the_lease_for_release(self):
        first = _handle("draft-1")
        owner = _ScriptedOwner(EditLeaseResult(True, handle=first))
        session = self._session(owner)
        session.request_initial(lambda result: None)

        def exploding_submit(handle, done):
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            session.submit_mutation(exploding_submit, lambda *args: None)
        session.close()
        self.assertEqual(owner.released, [first])

    def test_denied_initial_request_is_forwarded_and_holds_no_lease(self):
        denied = EditLeaseResult(False, "locked by another user")
        owner = _ScriptedOwner(denied)
        session = self._session(owner)
        results = []
        session.request_initial(results.append)
        self.assertEqual(results, [denied])
        session.close()
        self.assertEqual(owner.released, [])
