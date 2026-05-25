import logging
import time
import unittest
from types import SimpleNamespace

from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.builders.orchestrator_builder import \
    AppOrchestrators
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_shutdown_aware import \
    IShutdownAware
from ost_visualizer.application.orchestrators.license_thread_manager import \
    LicenseThreadManager
from ost_visualizer.application.orchestrators.lifecycle_orchestrator import \
    LifecycleOrchestrator
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.application.services.annotation_view_event_handler import \
    AnnotationViewEventHandler
from ost_visualizer.application.services.visualization_service import \
    VisualizationService


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class FakeShutdownParticipant(IShutdownAware):
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class FakeContainer:
    def __init__(self, participants=None):
        self.participants = list(participants or [])

    def get_by_interface(self, _iface):
        return list(self.participants)


class FakeCleanupObject:
    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


class ApplicationLifecycleTests(unittest.TestCase):
    def test_annotation_view_event_handler_shutdown_releases_cached_use_case_graph(
        self,
    ):
        event_bus = FakeEventBus()
        retained = object()
        handler = AnnotationViewEventHandler(
            event_bus=event_bus,
            use_case_factory=lambda: retained,
            logger=logging.getLogger("test"),
        )
        handler.start()
        self.assertIs(handler._get_use_case(), retained)
        handler.shutdown()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.HOTLINK_CLICKED, handler._on_hotlink_clicked)],
        )
        self.assertFalse(handler._subscribed)
        self.assertIsNone(handler._use_case)
        self.assertIsNone(handler._use_case_factory)
        self.assertIsNone(handler._event_bus)

    def test_app_controller_cleanup_releases_application_graph_references(self):
        event_bus = FakeEventBus()
        visualization = FakeCleanupObject()
        license_orchestrator = FakeCleanupObject()
        hook_calls = []
        container = ServiceContainer()
        container.register_instance("retained", object())
        container.register_singleton("lazy_retained", lambda: object())
        controller = AppController(
            container=container,
            event_bus=event_bus,
            logger=logging.getLogger("test"),
            orchestrators=AppOrchestrators(
                visualization=visualization,
                lifecycle=object(),
                license=license_orchestrator,
            ),
            project_data_service=object(),
            file_loading_service=object(),
            load_files_from_config_use_case=object(),
            working_directory_service=object(),
            file_state_model=object(),
            cleanup_hooks=[lambda: hook_calls.append("hook")],
        )
        callback = lambda **_kwargs: None
        controller.subscribe_to_event(AppEvents.LICENSE_EXPIRED, callback)
        controller.cleanup()
        controller.cleanup()
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_EXPIRED, callback)],
        )
        self.assertEqual(visualization.cleanup_calls, 1)
        self.assertEqual(license_orchestrator.cleanup_calls, 1)
        self.assertEqual(hook_calls, ["hook"])
        self.assertEqual(controller._cleanup_hooks, [])
        self.assertIsNone(controller._project_data_service)
        self.assertIsNone(controller._file_loading_service)
        self.assertIsNone(controller._load_files_from_config_use_case)
        self.assertIsNone(controller._working_directory_service)
        self.assertIsNone(controller._file_state_model)
        self.assertIsNone(controller.orchestrators)
        self.assertIsNone(controller.event_bus)
        self.assertIsNone(controller.container)
        self.assertEqual(container._services, {})
        self.assertEqual(container._factories, {})
        self.assertEqual(container._singletons, {})

    def test_lifecycle_shutdown_releases_controller_and_container_references(self):
        participant = FakeShutdownParticipant()
        app_controller = SimpleNamespace(cleanup_calls=0)

        def cleanup():
            app_controller.cleanup_calls += 1

        app_controller.cleanup = cleanup
        lifecycle = LifecycleOrchestrator(
            container=FakeContainer([participant]),
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

    def test_visualization_service_cleanup_releases_monitor_and_project_references(
        self,
    ):
        monitor = FakeCleanupObject()
        notifier = FakeCleanupObject()
        service = VisualizationService.__new__(VisualizationService)

        def join_mesh_worker(*, timeout=None):
            _ = timeout

        service._mesh_shutdown = SimpleNamespace(set=lambda: None)
        service._mesh_task_event = SimpleNamespace(set=lambda: None)
        service._mesh_worker = SimpleNamespace(join=join_mesh_worker)
        service.close_realtime_visualization = lambda: None
        service._transaction_monitor = monitor
        service._scene_notifier = notifier
        service._mesh_pending_task = ("large", "task")
        service.config_model = object()
        service._mesh_generator = object()
        service._visualization_provider = object()
        service.project_data = object()
        service.project_operations = object()
        service.event_bus = object()
        VisualizationService.cleanup(service)
        self.assertEqual(monitor.cleanup_calls, 1)
        self.assertEqual(notifier.cleanup_calls, 1)
        self.assertIsNone(service._transaction_monitor)
        self.assertIsNone(service._scene_notifier)
        self.assertIsNone(service._mesh_pending_task)
        self.assertIsNone(service.config_model)
        self.assertIsNone(service._mesh_generator)
        self.assertIsNone(service._visualization_provider)
        self.assertIsNone(service.project_data)
        self.assertIsNone(service.project_operations)
        self.assertIsNone(service.event_bus)

    def test_license_thread_manager_removes_thread_when_callback_dispatch_fails(self):
        class RaisingBridge:
            def request_callback(self, _callback, _success, _message):
                raise RuntimeError("dispatch failed")

        manager = LicenseThreadManager(logging.getLogger("test"))
        with self.assertLogs("test", level="ERROR"):
            manager.spawn_with_bridge(
                operation=lambda: (True, "ok", None),
                callback_bridge=RaisingBridge(),
                on_main_thread=lambda *_args: None,
            )
            deadline = time.time() + 2
            while manager._active_threads and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(manager._active_threads, [])


if __name__ == "__main__":
    unittest.main()
