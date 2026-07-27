import logging
import inspect
import threading
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.builders.orchestrator_builder import AppOrchestrators
from ost_visualizer.application.builders.service_builder import ServiceBuilder
from ost_visualizer.application.events.app_events import (
    AppEvents,
    NativeSceneUpdatedEvent,
)
from ost_visualizer.application.interfaces.i_thread_scene_notifier import (
    IThreadSceneNotifier,
)
from ost_visualizer.application.interfaces.i_shutdown_aware import IShutdownAware
from ost_visualizer.application.orchestrators.license_thread_manager import (
    LicenseThreadManager,
)
from ost_visualizer.application.orchestrators.lifecycle_orchestrator import (
    LifecycleOrchestrator,
)
from ost_visualizer.application.orchestrators.visualization_orchestrator import (
    VisualizationOrchestrator,
)
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.application.services.annotation_view_event_handler import (
    AnnotationViewEventHandler,
)
from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.presentation.services.qt_scene_notifier import QtSceneNotifier


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class QtSceneNotifierLifecycleTests(unittest.TestCase):
    def test_scene_outcome_crosses_qt_bridge_and_cleanup_blocks_late_callbacks(self):
        notifier = QtSceneNotifier()
        scene_calls = []
        notifier.set_handlers(
            on_scene_ready=lambda *args: scene_calls.append(args),
            on_full_refresh=lambda _file_path: None,
        )
        notifier.notify_scene_ready([], 7, True)
        notifier.cleanup()
        notifier.notify_scene_ready([], 8, False)
        self.assertEqual(scene_calls, [([], 7, True)])

    def test_native_scene_contract_has_no_legacy_bounds_payload(self):
        self.assertNotIn(
            "bounds",
            {field.name for field in fields(NativeSceneUpdatedEvent)},
        )
        self.assertNotIn(
            "bounds",
            inspect.signature(IThreadSceneNotifier.notify_scene_ready).parameters,
        )
        self.assertNotIn(
            "bounds",
            inspect.signature(QtSceneNotifier.notify_scene_ready).parameters,
        )


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


class FakeInfrastructureProvider:
    def get_icon_provider(self):
        return None

    def get_transaction_monitor(self):
        return SimpleNamespace(set_ost_status_callback=lambda _callback: None)

    def get_takeoff_domain_service(self):
        return object()

    def get_uom_service(self):
        return object()

    def get_visualization_provider(self, _takeoff_service):
        return object()

    def get_coordinate_transformer_factory(self):
        return SimpleNamespace(create=lambda: object())

    def get_color_service(self):
        return object()

    def get_pdf_exporter(self, *_args):
        return object()

    def get_ost_exporter(self, _uom_service):
        return object()

    def get_osp_exporter(self, *_args):
        return object()

    def get_ost_importer(self, **_call_options):
        return object()

    def get_osp_importer(self, **_call_options):
        return object()

    def get_database_creator(self):
        return object()

    def get_default_working_dir(self):
        return ""


class ApplicationLifecycleTests(unittest.TestCase):
    def test_new_access_database_is_registered_before_first_open(self):
        created_path = Path("C:/jobs/new-project.mdb")

        class _FileState:
            def __init__(self):
                self.file_entries = []

            def contains_path(self, _path):
                return False

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _FileState()
        registry = DatabaseDescriptorRegistry()
        controller = AppController(
            container=SimpleNamespace(),
            event_bus=FakeEventBus(),
            logger=logging.getLogger("test"),
            orchestrators=None,
            project_data_service=None,
            file_loading_service=None,
            load_files_from_config_use_case=None,
            working_directory_service=SimpleNamespace(
                create_database=lambda *_args, **_kwargs: created_path
            ),
            file_state_model=state,
            database_descriptor_registry=registry,
        )
        self.assertEqual(controller.create_new_database(), str(created_path))
        self.assertEqual(len(state.file_entries), 1)
        self.assertIsNotNone(registry.resolve(str(created_path)))

    def test_main_window_handler_factory_uses_owned_app_controller(self):
        source = Path("ost_visualizer/presentation/main_window.py").read_text(
            encoding="utf-8"
        )
        handler_factory = source.split("    def _create_handlers", maxsplit=1)[1].split(
            "\n    def ", maxsplit=1
        )[0]
        self.assertNotIn("=app_controller.get_service", handler_factory)
        self.assertIn("=self.app_controller.get_service", handler_factory)

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
        callback = lambda **_call_options: None
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

    def test_app_controller_cleanup_continues_after_stage_failures(self):
        cleanup_calls = []

        class FailingEventBus(FakeEventBus):
            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                raise RuntimeError("unsubscribe failed")

        class FailingCleanup:
            def __init__(self, name, *, fails=False):
                self.name = name
                self.fails = fails

            def cleanup(self):
                cleanup_calls.append(self.name)
                if self.fails:
                    raise RuntimeError(f"{self.name} failed")

        class FailingContainer(ServiceContainer):
            def clear(self):
                cleanup_calls.append("container")
                super().clear()
                raise RuntimeError("container failed")

        def failing_hook():
            cleanup_calls.append("failing-hook")
            raise RuntimeError("hook failed")

        event_bus = FailingEventBus()
        container = FailingContainer()
        container.register_instance("retained", object())
        controller = AppController(
            container=container,
            event_bus=event_bus,
            logger=logging.getLogger("test.cleanup.failures"),
            orchestrators=AppOrchestrators(
                visualization=FailingCleanup("visualization", fails=True),
                lifecycle=object(),
                license=FailingCleanup("license"),
            ),
            project_data_service=object(),
            file_loading_service=object(),
            load_files_from_config_use_case=object(),
            working_directory_service=object(),
            file_state_model=object(),
            cleanup_hooks=[
                failing_hook,
                lambda: cleanup_calls.append("successful-hook"),
            ],
        )
        callback = lambda **_call_options: None
        controller.subscribe_to_event(AppEvents.LICENSE_EXPIRED, callback)

        with self.assertLogs(controller.logger, level="ERROR") as logs:
            controller.cleanup()

        self.assertEqual(
            cleanup_calls,
            [
                "visualization",
                "license",
                "failing-hook",
                "successful-hook",
                "container",
            ],
        )
        self.assertEqual(
            event_bus.unsubscriptions,
            [(AppEvents.LICENSE_EXPIRED, callback)],
        )
        self.assertGreaterEqual(len(logs.output), 4)
        self.assertIsNone(controller.container)
        self.assertIsNone(controller.event_bus)
        self.assertIsNone(controller.orchestrators)
        self.assertEqual(controller._subscriptions, [])
        self.assertEqual(controller._cleanup_hooks, [])
        self.assertEqual(container._services, {})

    def test_summary_csv_export_service_resolves_project_read_service_from_container(
        self,
    ):
        container = ServiceContainer()
        container.register_instance("project_read_service", SimpleNamespace())
        container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(execute=lambda: None),
        )
        ServiceBuilder(
            container=container,
            logger=logging.getLogger("test"),
            infrastructure_provider=FakeInfrastructureProvider(),
            scene_notifier=object(),
        ).build(
            config_model=SimpleNamespace(),
            project_data_service=SimpleNamespace(),
            project_operations_service=SimpleNamespace(),
            event_bus=FakeEventBus(),
            connection_manager=None,
            license_api_client=object(),
        )
        service = container.get("summary_csv_export_service")
        self.assertIsNotNone(service)

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
        service._mesh_worker = SimpleNamespace(
            join=join_mesh_worker,
            is_alive=lambda: False,
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 4
        service._mesh_generation_identity = object()
        service._mesh_generation_delivered = False
        service.close_realtime_visualization = lambda: None
        service._transaction_monitor = monitor
        service._database_descriptor_registry = object()
        service._callback_bridge = object()
        service._monitored_access_locator = "C:/projects/local.mdb"
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
        self.assertIsNone(service._database_descriptor_registry)
        self.assertIsNone(service._callback_bridge)
        self.assertIsNone(service._monitored_access_locator)
        self.assertIsNone(service._scene_notifier)
        self.assertIsNone(service._mesh_pending_task)
        self.assertIsNone(service._mesh_generation_identity)
        self.assertIsNone(service.config_model)
        self.assertIsNone(service._mesh_generator)
        self.assertIsNone(service._visualization_provider)
        self.assertIsNone(service.project_data)
        self.assertIsNone(service.project_operations)
        self.assertIsNone(service.event_bus)

    def test_visualization_cleanup_retains_dependencies_when_mesh_worker_is_alive(
        self,
    ):
        monitor = FakeCleanupObject()
        notifier = FakeCleanupObject()
        service = VisualizationService.__new__(VisualizationService)
        retained = object()
        service._mesh_shutdown = SimpleNamespace(set=lambda: None)
        service._mesh_task_event = SimpleNamespace(set=lambda: None)
        service._mesh_worker = SimpleNamespace(
            join=lambda *, timeout=None: None,
            is_alive=lambda: True,
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 4
        service._mesh_generation_identity = retained
        service._mesh_generation_delivered = False
        service.close_realtime_visualization = lambda: None
        service._transaction_monitor = monitor
        service._database_descriptor_registry = retained
        service._callback_bridge = retained
        service._monitored_access_locator = "C:/projects/local.mdb"
        service._scene_notifier = notifier
        service._mesh_pending_task = ("large", "task")
        service.config_model = retained
        service._mesh_generator = retained
        service._visualization_provider = retained
        service.project_data = retained
        service.project_operations = retained
        service.event_bus = retained

        with self.assertRaisesRegex(RuntimeError, "worker did not stop"):
            VisualizationService.cleanup(service)

        self.assertEqual(monitor.cleanup_calls, 1)
        self.assertEqual(notifier.cleanup_calls, 0)
        self.assertIs(service._transaction_monitor, monitor)
        self.assertIs(service._scene_notifier, notifier)
        self.assertIs(service._visualization_provider, retained)
        self.assertIs(service.event_bus, retained)

    def test_visualization_orchestrator_cleanup_releases_service_reference(self):
        service = FakeCleanupObject()
        orchestrator = VisualizationOrchestrator()
        orchestrator.set_visualization_service(service)
        orchestrator.cleanup()
        orchestrator.cleanup()
        self.assertEqual(service.cleanup_calls, 1)
        self.assertIsNone(orchestrator._visualization_service)

    def test_license_thread_manager_removes_thread_when_callback_dispatch_fails(self):
        class RaisingBridge:
            def request_callback(self, _callback, _success, _message):
                raise RuntimeError("dispatch failed")

        manager = LicenseThreadManager(logging.getLogger("test"))
        with self.assertLogs("test", level="ERROR"):
            thread = manager.spawn_with_bridge(
                operation=lambda: (True, "ok", None),
                callback_bridge=RaisingBridge(),
                on_main_thread=lambda *_args: None,
            )
            thread.join(timeout=2)
        self.assertEqual(manager._active_threads, [])


if __name__ == "__main__":
    unittest.main()
