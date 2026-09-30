import unittest
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
