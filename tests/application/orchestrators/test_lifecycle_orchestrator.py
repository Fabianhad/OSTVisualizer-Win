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
