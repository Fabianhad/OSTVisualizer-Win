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

    def test_each_shutdown_failure_is_logged_with_its_message_and_does_not_stop_the_rest(self):
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
            ["Error shutting down bad: boom", "Error cleaning up application controller: cleanup boom"],
        )

    def test_a_failed_participant_discovery_is_logged_and_shutdown_still_completes_once(self):
        class Container:
            calls = 0

            def get_by_interface(self, interface):
                Container.calls += 1
                raise RuntimeError("discovery boom")

        orchestrator, logger = self.orchestrator(Container())
        orchestrator.shutdown()
        orchestrator.shutdown()
        self.assertEqual(Container.calls, 1)
        self.assertEqual(logger.messages, ["Error discovering shutdown participants: discovery boom"])
        self.assertIs(orchestrator._shutdown_performed, True)

    def test_shutdown_releases_every_reference_and_the_event_bus_is_exposed_until_then(self):
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
