import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.interfaces.i_shutdown_aware import IShutdownAware
from ost_visualizer.application.orchestrators.lifecycle_orchestrator import (
    LifecycleOrchestrator,
)
from ost_visualizer.application.service_container import ServiceContainer


class FakeShutdownParticipant(IShutdownAware):
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class LifecycleOrchestratorTests(unittest.TestCase):
    def test_lifecycle_shutdown_releases_controller_and_container_references(self):
        participant = FakeShutdownParticipant()
        app_controller = SimpleNamespace(cleanup_calls=0)

        def cleanup():
            app_controller.cleanup_calls += 1

        app_controller.cleanup = cleanup
        container = ServiceContainer()
        container.register_instance("participant", participant)
        lifecycle = LifecycleOrchestrator(
            container=container,
            visualization_orchestrator=object(),
            event_bus=object(),
            logger=logging.getLogger("test"),
        )
        lifecycle.set_app_controller(app_controller)
        lifecycle.shutdown()
        lifecycle.shutdown()
        self.assertEqual(participant.shutdown_calls, 1)
        self.assertEqual(app_controller.cleanup_calls, 1)
        self.assertIsNone(lifecycle._app_controller)
        self.assertIsNone(lifecycle._container)
        self.assertIsNone(lifecycle._viz_orchestrator)
        self.assertIsNone(lifecycle.event_bus)

    def test_lifecycle_shutdown_releases_references_when_controller_cleanup_fails(self):
        participant = FakeShutdownParticipant()
        app_controller = SimpleNamespace(
            cleanup=lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed"))
        )
        container = ServiceContainer()
        container.register_instance("participant", participant)
        lifecycle = LifecycleOrchestrator(
            container=container,
            visualization_orchestrator=object(),
            event_bus=object(),
            logger=logging.getLogger("test"),
        )
        lifecycle.set_app_controller(app_controller)
        with self.assertLogs("test", level="ERROR"):
            lifecycle.shutdown()
        lifecycle.shutdown()
        self.assertEqual(participant.shutdown_calls, 1)
        self.assertIsNone(lifecycle._app_controller)
        self.assertIsNone(lifecycle._container)
        self.assertIsNone(lifecycle._viz_orchestrator)
        self.assertIsNone(lifecycle.event_bus)

    def test_participant_failure_does_not_skip_other_participants_or_controller(self):
        calls = []

        class Participant(IShutdownAware):
            def __init__(self, name, error=None):
                self.name = name
                self.error = error

            def shutdown(self):
                calls.append(self.name)
                if self.error is not None:
                    raise self.error

        container = ServiceContainer()
        container.register_instance("broken", Participant("broken", OSError("busy")))
        container.register_instance("healthy", Participant("healthy"))
        container.register_instance("unrelated", object())
        lifecycle = LifecycleOrchestrator(
            container, object(), object(), logging.getLogger("test")
        )
        lifecycle.set_app_controller(
            SimpleNamespace(cleanup=lambda: calls.append("controller"))
        )
        with self.assertLogs("test", level="ERROR"):
            lifecycle.shutdown()
        lifecycle.shutdown()
        self.assertEqual(calls, ["broken", "healthy", "controller"])

    def test_discovery_failure_still_cleans_controller_and_releases_owners(self):
        class BrokenContainer:
            def get_by_interface(self, interface):
                self.interface = interface
                raise RuntimeError("discovery failed")

        calls = []
        container = BrokenContainer()
        lifecycle = LifecycleOrchestrator(
            container, object(), object(), logging.getLogger("test")
        )
        lifecycle.set_app_controller(
            SimpleNamespace(cleanup=lambda: calls.append("controller"))
        )
        with self.assertLogs("test", level="ERROR"):
            lifecycle.shutdown()
        lifecycle.shutdown()
        self.assertIs(container.interface, IShutdownAware)
        self.assertEqual(calls, ["controller"])
        self.assertIsNone(lifecycle._container)
        self.assertIsNone(lifecycle._app_controller)
        self.assertIsNone(lifecycle._viz_orchestrator)
        self.assertIsNone(lifecycle.event_bus)

    def test_license_expiry_closes_visualization_without_shutting_down_application(
        self,
    ):
        calls = []
        visualization = SimpleNamespace(
            close_realtime_visualization=lambda: calls.append("close")
        )
        lifecycle = LifecycleOrchestrator(
            ServiceContainer(), visualization, object(), logging.getLogger("test")
        )
        lifecycle.set_app_controller(
            SimpleNamespace(cleanup=lambda: calls.append("cleanup"))
        )
        lifecycle.handle_license_expired("expired")
        self.assertEqual(calls, ["close"])
        lifecycle.shutdown()
        self.assertEqual(calls, ["close", "cleanup"])


class LifecycleShutdownDetailTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.messages = []

        def exception(self, message, *args):
            self.messages.append(message % args)

    def orchestrator(self, container, controller=None):
        logger = self._Logger()
        orchestrator = LifecycleOrchestrator(container, object(), object(), logger)
        if controller is not None:
            orchestrator.set_app_controller(controller)
        return orchestrator, logger

    def test_each_shutdown_failure_is_logged_with_its_message_and_does_not_stop_the_rest(
        self,
    ):
        class Participant:
            def __init__(self, name, error=None):
                self.name, self.error, self.stopped = name, error, False

            def shutdown(self):
                self.stopped = True
                if self.error:
                    raise self.error

            def __repr__(self):
                return self.name

        class Container:
            def __init__(self, participants):
                self.participants = participants

            def get_by_interface(self, interface):
                return self.participants

        class Controller:
            cleaned = False

            def cleanup(self):
                Controller.cleaned = True
                raise RuntimeError("cleanup boom")

        bad = Participant("bad", RuntimeError("boom"))
        good = Participant("good")
        orchestrator, logger = self.orchestrator(Container([bad, good]), Controller())
        orchestrator.shutdown()
        self.assertTrue(bad.stopped and good.stopped and Controller.cleaned)
        self.assertEqual(
            logger.messages,
            [
                "Error shutting down bad: boom",
                "Error cleaning up application controller: cleanup boom",
            ],
        )

    def test_a_failed_participant_discovery_is_logged_and_shutdown_still_completes_once(
        self,
    ):
        class Container:
            calls = 0

            def get_by_interface(self, interface):
                Container.calls += 1
                raise RuntimeError("discovery boom")

        orchestrator, logger = self.orchestrator(Container())
        orchestrator.shutdown()
        orchestrator.shutdown()
        self.assertEqual(Container.calls, 1)
        self.assertEqual(
            logger.messages, ["Error discovering shutdown participants: discovery boom"]
        )
        self.assertIs(orchestrator._shutdown_performed, True)

    def test_shutdown_releases_every_reference_and_the_event_bus_is_exposed_until_then(
        self,
    ):
        class Container:
            def get_by_interface(self, interface):
                return []

        bus = object()
        orchestrator = LifecycleOrchestrator(Container(), object(), bus, self._Logger())
        self.assertIs(orchestrator.event_bus, bus)
        self.assertIsNone(orchestrator._app_controller)
        orchestrator.set_app_controller(object())
        orchestrator.shutdown()
        self.assertIsNone(orchestrator.event_bus)
        self.assertIsNone(orchestrator._container)
        self.assertIsNone(orchestrator._viz_orchestrator)
        self.assertIsNone(orchestrator._app_controller)


class LifecycleInterruptPropagationTests(unittest.TestCase):
    """Shutdown contains ordinary failures (logged, the rest still runs) and an interrupt (KeyboardInterrupt or
    SystemExit, a BaseException that is not an Exception) from any stage is never swallowed as a handled error: the
    original interrupt is re-raised after the remaining stages ran (see LifecycleInterruptPolicyTests).
    """

    class _Logger:
        def __init__(self):
            self.messages = []

        def exception(self, message, *args):
            self.messages.append(message % args)

    class _Container:
        def __init__(self, participants=(), discovery_error=None):
            self.participants = list(participants)
            self.discovery_error = discovery_error

        def get_by_interface(self, interface):
            if self.discovery_error is not None:
                raise self.discovery_error
            return self.participants

    class _InterruptedParticipant:
        def shutdown(self):
            raise KeyboardInterrupt("participant interrupted")

    def test_an_interrupt_in_any_shutdown_stage_is_not_swallowed(self):
        def interrupted_controller():
            raise KeyboardInterrupt("controller interrupted")

        scenarios = (
            (
                "discovery",
                self._Container(discovery_error=KeyboardInterrupt("discovery")),
                None,
                "discovery",
            ),
            (
                "participant",
                self._Container([self._InterruptedParticipant()]),
                None,
                "participant interrupted",
            ),
            (
                "controller",
                self._Container(),
                SimpleNamespace(cleanup=interrupted_controller),
                "controller interrupted",
            ),
        )
        for stage, container, controller, text in scenarios:
            with self.subTest(stage=stage):
                logger = self._Logger()
                orchestrator = LifecycleOrchestrator(
                    container, object(), object(), logger
                )
                if controller is not None:
                    orchestrator.set_app_controller(controller)
                with self.assertRaisesRegex(KeyboardInterrupt, f"^{text}$"):
                    orchestrator.shutdown()
                self.assertEqual(logger.messages, [])


class LifecycleInterruptPolicyTests(unittest.TestCase):
    """Interrupt policy: on KeyboardInterrupt or SystemExit every remaining shutdown stage still runs (each guarded,
    a secondary error is logged), every owner reference is released and the ORIGINAL interrupt is re-raised.
    `_shutdown_performed` stays True (the shutdown did run), so a retry is a no-op with nothing left held.
    """

    INTERRUPTS = (KeyboardInterrupt, SystemExit)

    class _Logger:
        def __init__(self):
            self.messages = []

        def exception(self, message, *args):
            self.messages.append(message % args)

    class _Container:
        def __init__(self, participants=(), discovery_error=None):
            self.participants = list(participants)
            self.discovery_error = discovery_error

        def get_by_interface(self, interface):
            if self.discovery_error is not None:
                raise self.discovery_error
            return self.participants

    class _Participant:
        def __init__(self, name, calls, error=None):
            self.name, self.calls, self.error = name, calls, error

        def shutdown(self):
            self.calls.append(self.name)
            if self.error is not None:
                raise self.error

        def __repr__(self):
            return self.name

    def _lifecycle(self, container, calls, controller_error=None):
        logger = self._Logger()
        lifecycle = LifecycleOrchestrator(container, object(), object(), logger)

        def cleanup():
            calls.append("controller")
            if controller_error is not None:
                raise controller_error

        lifecycle.set_app_controller(SimpleNamespace(cleanup=cleanup))
        return lifecycle, logger

    def _assert_released_and_retry_is_a_noop(self, lifecycle, calls):
        self.assertIsNone(lifecycle._app_controller)
        self.assertIsNone(lifecycle._container)
        self.assertIsNone(lifecycle._viz_orchestrator)
        self.assertIsNone(lifecycle.event_bus)
        self.assertIs(lifecycle._shutdown_performed, True)
        before = list(calls)
        lifecycle.shutdown()
        self.assertEqual(calls, before)

    def test_an_interrupt_in_a_participant_still_runs_the_other_participants_and_the_controller(
        self,
    ):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                calls = []
                interrupt = kind("participant interrupted")
                container = self._Container(
                    [
                        self._Participant("first", calls, interrupt),
                        self._Participant("second", calls),
                    ]
                )
                lifecycle, logger = self._lifecycle(container, calls)
                with self.assertRaises(kind) as raised:
                    lifecycle.shutdown()
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(calls, ["first", "second", "controller"])
                self.assertEqual(logger.messages, [])
                self._assert_released_and_retry_is_a_noop(lifecycle, calls)

    def test_an_interrupt_in_participant_discovery_still_cleans_the_controller_and_releases_the_owners(
        self,
    ):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                calls = []
                interrupt = kind("discovery interrupted")
                lifecycle, logger = self._lifecycle(
                    self._Container(discovery_error=interrupt), calls
                )
                with self.assertRaises(kind) as raised:
                    lifecycle.shutdown()
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(calls, ["controller"])
                self.assertEqual(logger.messages, [])
                self._assert_released_and_retry_is_a_noop(lifecycle, calls)

    def test_an_interrupt_in_the_controller_cleanup_still_releases_every_owner(self):
        for kind in self.INTERRUPTS:
            with self.subTest(interrupt=kind.__name__):
                calls = []
                interrupt = kind("controller interrupted")
                lifecycle, logger = self._lifecycle(
                    self._Container([self._Participant("only", calls)]),
                    calls,
                    controller_error=interrupt,
                )
                with self.assertRaises(kind) as raised:
                    lifecycle.shutdown()
                self.assertIs(raised.exception, interrupt)
                self.assertEqual(calls, ["only", "controller"])
                self.assertEqual(logger.messages, [])
                self._assert_released_and_retry_is_a_noop(lifecycle, calls)

    def test_a_secondary_ordinary_error_after_an_interrupt_is_logged_and_never_replaces_it(
        self,
    ):
        calls = []
        interrupt = KeyboardInterrupt("original")
        container = self._Container(
            [
                self._Participant("first", calls, interrupt),
                self._Participant("broken", calls, OSError("busy")),
                self._Participant("last", calls),
            ]
        )
        lifecycle, logger = self._lifecycle(
            container, calls, controller_error=RuntimeError("cleanup boom")
        )
        with self.assertRaises(KeyboardInterrupt) as raised:
            lifecycle.shutdown()
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(calls, ["first", "broken", "last", "controller"])
        self.assertEqual(
            logger.messages,
            [
                "Error shutting down broken: busy",
                "Error cleaning up application controller: cleanup boom",
            ],
        )
        self._assert_released_and_retry_is_a_noop(lifecycle, calls)

    def test_a_second_interrupt_is_logged_with_both_types_and_the_first_one_is_re_raised(
        self,
    ):
        calls = []
        first = KeyboardInterrupt("first")
        container = self._Container(
            [
                self._Participant("one", calls, first),
                self._Participant("two", calls, SystemExit(2)),
            ]
        )
        lifecycle, logger = self._lifecycle(
            container, calls, controller_error=SystemExit(3)
        )
        with self.assertRaises(KeyboardInterrupt) as raised:
            lifecycle.shutdown()
        self.assertIs(raised.exception, first)
        self.assertEqual(calls, ["one", "two", "controller"])
        self.assertEqual(
            logger.messages,
            [
                "SystemExit while shutting down two after KeyboardInterrupt;"
                " the original KeyboardInterrupt is re-raised",
                "SystemExit while cleaning up application controller after"
                " KeyboardInterrupt; the original KeyboardInterrupt is re-raised",
            ],
        )
        self._assert_released_and_retry_is_a_noop(lifecycle, calls)

    def test_an_interrupt_in_the_controller_after_an_interrupt_in_discovery_keeps_the_first(
        self,
    ):
        calls = []
        first = SystemExit(1)
        lifecycle, logger = self._lifecycle(
            self._Container(discovery_error=first),
            calls,
            controller_error=KeyboardInterrupt("second"),
        )
        with self.assertRaises(SystemExit) as raised:
            lifecycle.shutdown()
        self.assertIs(raised.exception, first)
        self.assertEqual(
            logger.messages,
            [
                "KeyboardInterrupt while cleaning up application controller after"
                " SystemExit; the original SystemExit is re-raised"
            ],
        )
        self._assert_released_and_retry_is_a_noop(lifecycle, calls)
