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
        self.assertIs(
            session.submit_mutation(
                lambda handle, done: False,
                lambda success, value=None: completed.append((success, value)),
            ),
            False,
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


class _DeferredOwner:
    def __init__(self):
        self.requests = []
        self.callbacks = []
        self.released = []

    def request_collaboration_edit(self, database_id, resources, callback, **options):
        self.requests.append((database_id, resources, options))
        self.callbacks.append(callback)

    def end_collaboration_edit(self, handle):
        self.released.append(handle)


class _RecordingBus(EventBus):
    def __init__(self):
        super().__init__()
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))
        super().subscribe(event_type, callback)

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))
        super().unsubscribe(event_type, callback)


class ModalEditLeaseSessionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _session(self, owner, bus=None, **options):
        session = ModalEditLeaseSession(
            owner,
            "database",
            (ResourceRef("page", "42", 7),),
            "SetScaleDialog",
            event_bus=bus or EventBus(),
            **options,
        )
        self.addCleanup(session.close)
        return session

    def test_lease_requests_carry_the_exact_scope_and_operation_identity(self):
        owner = _DeferredOwner()
        dependency = (ResourceRef("layer", "5", 7),)
        session = self._session(
            owner, dependency_resources=dependency, owning_surface="detached-dialog"
        )
        session.request_initial(lambda result: None)
        first = _handle("draft-1")
        owner.callbacks[0](EditLeaseResult(True, handle=first))
        session.submit_mutation(lambda handle, done: True, lambda *args: None)
        expected = (
            "database",
            (ResourceRef("page", "42", 7),),
            {
                "dependency_resources": dependency,
                "operation_id": "SetScaleDialog",
                "owning_surface": "detached-dialog",
            },
        )
        self.assertEqual(owner.requests, [expected])
        default = _DeferredOwner()
        self._session(default).request_initial(lambda result: None)
        self.assertEqual(
            default.requests[0][2],
            {
                "dependency_resources": (),
                "operation_id": "SetScaleDialog",
                "owning_surface": "main-window-dialog",
            },
        )

    def test_session_subscribes_once_and_unsubscribes_the_same_handler_on_close(self):
        bus = _RecordingBus()
        session = self._session(_DeferredOwner(), bus)
        self.assertEqual(len(bus.subscriptions), 1)
        event_type, handler = bus.subscriptions[0]
        self.assertIs(event_type, AppEvents.EDIT_LEASE_LOST)
        session.close()
        session.close()
        self.assertEqual(bus.unsubscriptions, [(AppEvents.EDIT_LEASE_LOST, handler)])
        self.assertEqual(bus._subscribers.get(AppEvents.EDIT_LEASE_LOST, []), [])

    def test_accepted_initial_lease_is_used_for_mutations_and_released_on_close(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        denied = EditLeaseResult(False, "locked")
        session.accept_initial_lease(denied)
        submitted = []
        completed = []
        self.assertFalse(
            session.submit_mutation(
                lambda handle, done: submitted.append(handle) or True,
                lambda *args: completed.append(args),
            )
        )
        self.assertEqual((submitted, completed), ([], [(False, None)]))
        handle = _handle("draft-1")
        session.accept_initial_lease(EditLeaseResult(True, handle=handle))
        self.assertTrue(
            session.submit_mutation(
                lambda held, done: submitted.append(held) or True, lambda *args: None
            )
        )
        self.assertEqual(submitted, [handle])
        self.assertEqual(owner.released, [])

    def test_accepted_initial_lease_is_released_on_close(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        handle = _handle("draft-1")
        session.accept_initial_lease(EditLeaseResult(True, handle=handle))
        session.close()
        self.assertEqual(owner.released, [handle])

    def test_asynchronous_mutation_reacquires_the_lease_when_it_completes(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        first = _handle("draft-1")
        second = _handle("draft-2")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        done_callbacks = []
        completed = []
        self.assertTrue(
            session.submit_mutation(
                lambda handle, done: done_callbacks.append(done) or True,
                lambda success, value=None: completed.append((success, value)),
            )
        )
        self.assertEqual((owner.requests, completed), ([], []))
        done_callbacks[0](False, "rejected")
        self.assertEqual(len(owner.requests), 1)
        self.assertEqual(completed, [])
        owner.callbacks[0](EditLeaseResult(True, handle=second))
        self.assertEqual(completed, [(False, "rejected")])
        session.close()
        self.assertEqual(owner.released, [second])

    def test_synchronous_completion_of_a_mutation_that_did_not_start_is_reported(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        first = _handle("draft-1")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        completed = []

        def refuse(handle, done):
            done(False, "preflight failed")
            return False

        self.assertFalse(
            session.submit_mutation(
                refuse, lambda success, value=None: completed.append((success, value))
            )
        )
        self.assertEqual(completed, [(False, "preflight failed")])
        self.assertEqual(owner.requests, [])
        session.close()
        self.assertEqual(owner.released, [first])

    def test_mutation_finishing_after_close_neither_reacquires_nor_reports(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        session.accept_initial_lease(EditLeaseResult(True, handle=_handle("draft-1")))
        done_callbacks = []
        completed = []
        session.submit_mutation(
            lambda handle, done: done_callbacks.append(done) or True,
            lambda *args: completed.append(args),
        )
        session.close()
        done_callbacks[0](True, "saved")
        self.assertEqual((owner.requests, completed, owner.released), ([], [], []))

    def test_reacquired_lease_resolving_after_close_is_released_not_reported(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        session.accept_initial_lease(EditLeaseResult(True, handle=_handle("draft-1")))
        completed = []
        session.submit_mutation(
            lambda handle, done: done(True, "saved") or True,
            lambda *args: completed.append(args),
        )
        late = _handle("draft-2")
        session.close()
        owner.callbacks[0](EditLeaseResult(True, handle=late))
        self.assertEqual(owner.released, [late])
        self.assertEqual(completed, [])
        owner.callbacks[0](EditLeaseResult(False, "late denial"))
        self.assertEqual(owner.released, [late])

    def test_late_denied_initial_request_after_close_reports_cancellation_only(self):
        owner = _DeferredOwner()
        session = self._session(owner)
        results = []
        session.request_initial(results.append)
        session.close()
        owner.callbacks[0](EditLeaseResult(False, "locked"))
        self.assertEqual(owner.released, [])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].granted)
        self.assertEqual(
            results[0].message, "The edit was cancelled while the dialog was closing."
        )

    def test_loss_is_matched_against_the_reacquired_lease_not_the_original(self):
        events = EventBus()
        owner = _DeferredOwner()
        session = self._session(owner, events)
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        session.bind_dialog(dialog)
        first = _handle("draft-1")
        second = _handle("draft-2")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        session.submit_mutation(
            lambda handle, done: done(True, "saved") or True, lambda *args: None
        )
        owner.callbacks[0](EditLeaseResult(True, handle=second))
        events.publish(AppEvents.EDIT_LEASE_LOST, loss=_loss(first))
        self.assertEqual(rejected, [])
        events.publish(AppEvents.EDIT_LEASE_LOST, loss=_loss(second))
        self.assertEqual(rejected, [True])
        session.close()
        self.assertEqual(owner.released, [])

    def test_loss_while_a_mutation_is_in_flight_is_ignored(self):
        events = EventBus()
        owner = _DeferredOwner()
        session = self._session(owner, events)
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        rejected = []
        dialog.rejected.connect(lambda: rejected.append(True))
        session.bind_dialog(dialog)
        first = _handle("draft-1")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        session.submit_mutation(lambda handle, done: True, lambda *args: None)
        events.publish(AppEvents.EDIT_LEASE_LOST, loss=_loss(first))
        self.assertEqual(rejected, [])

    def test_loss_without_a_bound_dialog_only_drops_the_lease(self):
        events = EventBus()
        owner = _DeferredOwner()
        session = self._session(owner, events)
        first = _handle("draft-1")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        events.publish(AppEvents.EDIT_LEASE_LOST, loss=_loss(first))
        session.close()
        self.assertEqual(owner.released, [])
        completed = []
        self.assertFalse(
            session.submit_mutation(
                lambda h, d: True, lambda *args: completed.append(args)
            )
        )
        self.assertEqual(completed, [(False, None)])


class ModalEditLeaseSessionClosedAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_closed_session_releases_a_lease_accepted_after_close(self):
        owner = _DeferredOwner()
        session = ModalEditLeaseSession(
            owner,
            "database",
            (ResourceRef("page", "42", 7),),
            "SetScaleDialog",
            event_bus=EventBus(),
        )
        session.close()
        late = _handle("late-draft")
        session.accept_initial_lease(EditLeaseResult(True, handle=late))
        self.assertEqual(owner.released, [late])
        completed = []
        self.assertIs(
            session.submit_mutation(
                lambda held, done: self.fail("closed session must not submit"),
                lambda *args: completed.append(args),
            ),
            False,
        )
        self.assertEqual(completed, [(False, None)])
        session.close()
        self.assertEqual(owner.released, [late])

    def test_closed_session_ignores_a_denied_late_acceptance(self):
        owner = _DeferredOwner()
        session = ModalEditLeaseSession(
            owner,
            "database",
            (ResourceRef("page", "42", 7),),
            "SetScaleDialog",
            event_bus=EventBus(),
        )
        session.close()
        session.accept_initial_lease(EditLeaseResult(False, "locked"))
        self.assertEqual(owner.released, [])

    def test_session_closed_while_submitting_releases_the_lease_it_gets_back(self):
        for outcome in ("not started", "raises"):
            with self.subTest(outcome=outcome):
                owner = _DeferredOwner()
                session = ModalEditLeaseSession(
                    owner,
                    "database",
                    (ResourceRef("page", "42", 7),),
                    "SetScaleDialog",
                    event_bus=EventBus(),
                )
                handle = _handle("draft-1")
                session.accept_initial_lease(EditLeaseResult(True, handle=handle))

                def submit(held, done):
                    session.close()
                    if outcome == "raises":
                        raise RuntimeError("boom")
                    return False

                if outcome == "raises":
                    with self.assertRaisesRegex(RuntimeError, "boom"):
                        session.submit_mutation(submit, lambda *args: None)
                else:
                    self.assertIs(
                        session.submit_mutation(submit, lambda *args: None), False
                    )
                self.assertEqual(owner.released, [handle])
                session.close()
                self.assertEqual(owner.released, [handle])


class ModalEditLeaseSessionStaleCompletionTests(unittest.TestCase):
    """A duplicate terminal delivery of one mutation must not act on the next."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_duplicate_mutation_completion_does_not_reacquire_or_report_again(self):
        owner = _DeferredOwner()
        session = ModalEditLeaseSession(
            owner,
            "database",
            (ResourceRef("page", "42", 7),),
            "SetScaleDialog",
            event_bus=EventBus(),
        )
        self.addCleanup(session.close)
        first, second, third = _handle("d1"), _handle("d2"), _handle("d3")
        session.accept_initial_lease(EditLeaseResult(True, handle=first))
        done_a = []
        completed_a = []
        completed_b = []
        session.submit_mutation(
            lambda held, done: done_a.append(done) or True,
            lambda success, value=None: completed_a.append((success, value)),
        )
        done_a[0](True, "a")
        owner.callbacks[0](EditLeaseResult(True, handle=second))
        self.assertEqual(completed_a, [(True, "a")])
        # The dialog starts the NEXT mutation on the re-acquired lease.
        done_b = []
        session.submit_mutation(
            lambda held, done: done_b.append((held, done)) or True,
            lambda success, value=None: completed_b.append((success, value)),
        )
        self.assertIs(done_b[0][0], second)
        # A duplicate terminal delivery of mutation A arrives while B is in flight.
        done_a[0](False, "stale")
        self.assertEqual(len(owner.requests), 1)
        self.assertEqual(completed_a, [(True, "a")])
        self.assertEqual(completed_b, [])
        # B still completes normally: one re-acquisition, one report.
        done_b[0][1](True, "b")
        self.assertEqual(len(owner.requests), 2)
        owner.callbacks[1](EditLeaseResult(True, handle=third))
        self.assertEqual(completed_b, [(True, "b")])
        session.close()
        self.assertEqual(owner.released, [third])
