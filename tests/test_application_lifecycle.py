import logging
import inspect
import threading
import unittest
from unittest.mock import patch
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
from ost_visualizer import main as application_main
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
            on_scene_ready=lambda geometries, generation, scene_failed: scene_calls.append(
                (geometries, generation, scene_failed)
            ),
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


class ApplicationStartupFailureTests(unittest.TestCase):
    def test_main_window_construction_failure_shuts_down_configured_application(self):
        shutdown_calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: shutdown_calls.append(True))
        controller = SimpleNamespace(
            get_service=lambda name: (
                lifecycle if name == "lifecycle_orchestrator" else None
            )
        )
        container = SimpleNamespace(get=lambda name: controller)
        app = SimpleNamespace(processEvents=lambda: None)
        socket = SimpleNamespace(
            connectToServer=lambda _name: None,
            waitForConnected=lambda _timeout: False,
        )
        server = SimpleNamespace(
            removeServer=lambda _name: None,
            listen=lambda _name: True,
        )
        splash = SimpleNamespace(show=lambda: None)
        logger = SimpleNamespace(
            info=lambda *_args: None, exception=lambda *_args: None
        )
        with patch.object(
            application_main, "_install_runtime_logging", return_value=logger
        ), patch.object(
            application_main,
            "parse_project_file_args",
            return_value=SimpleNamespace(has_file_args=False),
        ), patch.object(
            application_main.QtWidgets, "QApplication", return_value=app
        ), patch.object(
            application_main, "QLocalSocket", return_value=socket
        ), patch.object(
            application_main, "QLocalServer", return_value=server
        ), patch.object(
            application_main, "SplashScreen", return_value=splash
        ), patch.object(
            application_main, "configure_application", return_value=container
        ), patch.object(
            application_main.MainWindow,
            "__new__",
            side_effect=RuntimeError("window construction failed"),
        ), self.assertRaisesRegex(
            RuntimeError, "window construction failed"
        ):
            application_main.main()
        self.assertEqual(shutdown_calls, [True])

    def test_event_loop_exit_shuts_down_application_without_window_close(self):
        shutdown_calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: shutdown_calls.append(True))
        controller = SimpleNamespace(
            get_service=lambda name: (
                lifecycle if name == "lifecycle_orchestrator" else None
            )
        )
        container = SimpleNamespace(get=lambda _name: controller)
        app = SimpleNamespace(processEvents=lambda: None, exec=lambda: 7)
        socket = SimpleNamespace(
            connectToServer=lambda _name: None,
            waitForConnected=lambda _timeout: False,
        )
        server = SimpleNamespace(
            removeServer=lambda _name: None,
            listen=lambda _name: True,
        )
        splash = SimpleNamespace(show=lambda: None)
        logger = SimpleNamespace(
            info=lambda *_args: None, exception=lambda *_args: None
        )
        with patch.object(
            application_main, "_install_runtime_logging", return_value=logger
        ), patch.object(
            application_main,
            "parse_project_file_args",
            return_value=SimpleNamespace(has_file_args=False),
        ), patch.object(
            application_main.QtWidgets, "QApplication", return_value=app
        ), patch.object(
            application_main, "QLocalSocket", return_value=socket
        ), patch.object(
            application_main, "QLocalServer", return_value=server
        ), patch.object(
            application_main, "SplashScreen", return_value=splash
        ), patch.object(
            application_main, "configure_application", return_value=container
        ), patch.object(
            application_main, "MainWindow", return_value=object()
        ), patch.object(
            application_main, "_install_single_instance_handler"
        ), self.assertRaisesRegex(
            SystemExit, "7"
        ):
            application_main.main()
        self.assertEqual(shutdown_calls, [True])


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

    def get_pdf_exporter(
        self,
        _coord_system,
        _color_service,
        _takeoff_service,
        _uom_service,
        _annotation_caption_resolver,
    ):
        return object()

    def get_ost_exporter(self, _uom_service):
        return object()

    def get_osp_exporter(self, _uom_service, _version):
        return object()

    def get_ost_importer(self, conn_manager=None):
        _ = conn_manager
        return object()

    def get_osp_importer(self, conn_manager=None):
        _ = conn_manager
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
                create_database=lambda name=None, progress_callback=None: created_path
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
        container.register_instance("project_write_service", SimpleNamespace())
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

    def test_ost_status_blocks_falsey_connection_manager(self):
        class _FalseyConnectionManager:
            def __init__(self):
                self.write_blocks = []

            def __bool__(self):
                return False

            def set_write_blocked(self, active):
                self.write_blocks.append(active)

        class _Signal:
            def connect(self, callback):
                self.callback = callback

        class _Signaler:
            def __init__(self):
                self.ost_changed = _Signal()

            def emit_status(self, active):
                self.ost_changed.callback(active)

        class _Monitor:
            def set_ost_status_callback(self, callback):
                self.callback = callback

        class _Provider(FakeInfrastructureProvider):
            def __init__(self, monitor):
                self.monitor = monitor

            def get_transaction_monitor(self):
                return self.monitor

        class _EventBus(FakeEventBus):
            def __init__(self):
                super().__init__()
                self.publications = []

            def publish(self, event_type, **payload):
                self.publications.append((event_type, payload))

        container = ServiceContainer()
        container.register_instance("project_read_service", SimpleNamespace())
        container.register_instance("project_write_service", SimpleNamespace())
        container.register_instance(
            "reload_database_use_case",
            SimpleNamespace(execute=lambda: None),
        )
        connection_manager = _FalseyConnectionManager()
        monitor = _Monitor()
        event_bus = _EventBus()
        ServiceBuilder(
            container=container,
            logger=logging.getLogger("test"),
            infrastructure_provider=_Provider(monitor),
            scene_notifier=object(),
            ost_signaler=_Signaler(),
        ).build(
            config_model=SimpleNamespace(),
            project_data_service=SimpleNamespace(),
            project_operations_service=SimpleNamespace(),
            event_bus=event_bus,
            connection_manager=connection_manager,
            license_api_client=object(),
        )
        monitor.callback(True)
        self.assertEqual(connection_manager.write_blocks, [True])
        self.assertEqual(
            event_bus.publications,
            [(AppEvents.OST_STATUS_CHANGED, {"active": True})],
        )

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

    def test_lifecycle_shutdown_releases_references_when_controller_cleanup_fails(self):
        participant = FakeShutdownParticipant()
        app_controller = SimpleNamespace(
            cleanup=lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed"))
        )
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
                on_main_thread=lambda _success, _message, _extra_data: None,
            )
            thread.join(timeout=2)
        self.assertEqual(manager._active_threads, [])

    def test_license_thread_manager_normal_completion_reaches_main_callback(self):
        queued = []
        completed = []

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        thread = manager.spawn_with_bridge(
            operation=lambda: (True, "ok", "license-result"),
            callback_bridge=QueuedBridge(),
            on_main_thread=lambda *args: completed.append(args),
        )
        thread.join(timeout=1.0)
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(completed, [(True, "ok", "license-result")])
        self.assertEqual(manager._active_threads, [])
        manager.cleanup()
        manager.cleanup()

    def test_license_thread_manager_cleanup_suppresses_late_worker_callback(self):
        started = threading.Event()
        release = threading.Event()
        callbacks = []

        class RecordingBridge:
            def request_callback(self, callback, success, message):
                callbacks.append((callback, success, message))

        def operation():
            started.set()
            release.wait()
            return True, "ok", "license-result"

        manager = LicenseThreadManager(logging.getLogger("test"))
        thread = manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=RecordingBridge(),
            on_main_thread=lambda *args: callbacks.append(args),
        )
        self.assertTrue(started.wait(1.0))
        with self.assertLogs("test", level="WARNING"):
            manager.cleanup(timeout=0.0)
        release.set()
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(callbacks, [])

    def test_license_thread_manager_cleanup_invalidates_queued_callback(self):
        queued = []
        completed = []

        class QueuedBridge:
            def request_callback(self, callback, success, message):
                queued.append((callback, success, message))

        manager = LicenseThreadManager(logging.getLogger("test"))
        thread = manager.spawn_with_bridge(
            operation=lambda: (True, "ok", "license-result"),
            callback_bridge=QueuedBridge(),
            on_main_thread=lambda *args: completed.append(args),
        )
        thread.join(timeout=1.0)
        self.assertEqual(len(queued), 1)
        manager.cleanup()
        callback, success, message = queued.pop()
        callback(success, message)
        self.assertEqual(completed, [])

    def test_license_thread_manager_cleanup_continues_after_join_failure(self):
        class FailingThread:
            name = "failing"

            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise RuntimeError("join failed")

        class RecordingThread:
            name = "recording"

            def __init__(self):
                self.join_calls = []
                self.alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                self.join_calls.append(timeout)
                self.alive = False

        manager = LicenseThreadManager(logging.getLogger("test"))
        recording = RecordingThread()
        manager._active_threads = [FailingThread(), recording]
        with self.assertRaisesRegex(RuntimeError, "join failed"):
            manager.cleanup(timeout=0.25)
        self.assertEqual(recording.join_calls, [0.25])
        self.assertEqual(manager._active_threads, [])
        manager.cleanup(timeout=0.25)

    def test_license_thread_cleanup_waits_for_an_accepted_worker_to_start(self):
        real_thread = threading.Thread
        start_entered = threading.Event()
        allow_start = threading.Event()
        cleanup_started = threading.Event()
        order = []
        order_lock = threading.Lock()

        class DelayedStartThread(real_thread):
            def start(self):
                start_entered.set()
                allow_start.wait(1.0)
                super().start()

        class RecordingBridge:
            def request_callback(self, _callback, _success, _message):
                pass

        def operation():
            with order_lock:
                order.append("operation")
            return True, "ok", None

        manager = LicenseThreadManager(logging.getLogger("test"))
        with patch(
            "ost_visualizer.application.orchestrators.license_thread_manager.threading.Thread",
            DelayedStartThread,
        ):
            spawn_call = real_thread(
                target=lambda: manager.spawn_with_bridge(
                    operation=operation,
                    callback_bridge=RecordingBridge(),
                    on_main_thread=lambda *_args: None,
                )
            )
            spawn_call.start()
            self.assertTrue(start_entered.wait(1.0))

            def cleanup():
                cleanup_started.set()
                manager.cleanup(timeout=1.0)
                with order_lock:
                    order.append("cleanup")

            cleanup_call = real_thread(target=cleanup)
            cleanup_call.start()
            self.assertTrue(cleanup_started.wait(1.0))
            allow_start.set()
            spawn_call.join(1.0)
            cleanup_call.join(1.0)
        self.assertFalse(spawn_call.is_alive())
        self.assertFalse(cleanup_call.is_alive())
        self.assertEqual(order, ["operation", "cleanup"])


if __name__ == "__main__":
    unittest.main()
