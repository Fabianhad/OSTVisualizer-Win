import unittest
from types import SimpleNamespace
from ost_visualizer.application.orchestrators.visualization_orchestrator import (
    VisualizationOrchestrator,
)


class FakeCleanupObject:
    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


class VisualizationOrchestratorLifecycleTests(unittest.TestCase):
    def test_visualization_orchestrator_cleanup_releases_service_reference(self):
        service = FakeCleanupObject()
        orchestrator = VisualizationOrchestrator()
        orchestrator.set_visualization_service(service)
        orchestrator.cleanup()
        orchestrator.cleanup()
        self.assertEqual(service.cleanup_calls, 1)
        self.assertIsNone(orchestrator._visualization_service)

    def test_close_routes_to_current_service_and_empty_state_is_safe(self):
        orchestrator = VisualizationOrchestrator()
        calls = []
        orchestrator.close_realtime_visualization()
        orchestrator.cleanup()
        service = SimpleNamespace(
            close_realtime_visualization=lambda: calls.append("close"),
            cleanup=lambda: calls.append("cleanup"),
        )
        orchestrator.set_visualization_service(service)
        orchestrator.close_realtime_visualization()
        self.assertEqual(calls, ["close"])
        orchestrator.cleanup()
        orchestrator.close_realtime_visualization()
        self.assertEqual(calls, ["close", "cleanup"])

    def test_failed_cleanup_retains_owner_for_retry(self):
        calls = []

        def cleanup():
            calls.append("cleanup")
            if len(calls) == 1:
                raise RuntimeError("renderer busy")

        service = SimpleNamespace(cleanup=cleanup)
        orchestrator = VisualizationOrchestrator()
        orchestrator.set_visualization_service(service)
        with self.assertRaisesRegex(RuntimeError, "renderer busy"):
            orchestrator.cleanup()
        self.assertIs(orchestrator._visualization_service, service)
        orchestrator.cleanup()
        orchestrator.cleanup()
        self.assertEqual(calls, ["cleanup", "cleanup"])
        self.assertIsNone(orchestrator._visualization_service)
