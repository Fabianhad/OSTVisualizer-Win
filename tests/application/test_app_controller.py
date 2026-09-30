import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.builders.orchestrator_builder import AppOrchestrators
from ost_visualizer.application.events.app_events import (
    AppEvents,
    NativeSceneUpdatedEvent,
)
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
import tempfile
import threading
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from PySide6 import QtCore, QtWidgets


class FakeEventBus:
    def __init__(self):
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        self.unsubscriptions.append((event_type, callback))


class FakeCleanupObject:
    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


class AppControllerLifecycleTests(unittest.TestCase):
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


class AppControllerDatabaseRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_startup_loads_access_synchronously_and_starts_sql_asynchronously(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / "available.mdb"
            access_path.touch()
            access_entry = FileEntry(str(access_path), is_checked=True)
            sql_descriptor = DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="localhost", database="UNAVAILABLE_SQL"
                ),
                schema_version=SQL_SCHEMA_V1.version,
            )
            sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
            execute_calls = []
            starts = []
            connected = []

            class _LoadConfigured:
                def execute(self, backends):
                    execute_calls.append((set(backends), threading.get_ident()))
                    return [access_entry.runtime_locator]

            controller = AppController.__new__(AppController)
            controller.logger = logging.getLogger("test.startup.controller")
            controller._auto_discover_databases = lambda: None
            controller._database_descriptor_registry = SimpleNamespace(
                register_all=lambda _descriptors: None
            )
            controller._file_state_model = SimpleNamespace(
                file_entries=[access_entry, sql_entry]
            )
            controller._load_files_from_config_use_case = _LoadConfigured()
            services = {
                "database_capability_service": SimpleNamespace(
                    mark_connected=connected.append
                ),
                "sql_collaboration_coordinator": SimpleNamespace(
                    start_database=lambda database_id, **kwargs: starts.append(
                        (database_id, kwargs, threading.get_ident())
                    )
                ),
            }
            controller.container = SimpleNamespace(get=services.__getitem__)
            main_thread = threading.get_ident()
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])
        self.assertEqual(execute_calls, [({DatabaseBackend.ACCESS}, main_thread)])
        self.assertEqual(connected, [access_entry.database_id])
        self.assertEqual(
            starts,
            [
                (
                    sql_descriptor.database_id,
                    {"retry_initial_failure": False},
                    main_thread,
                )
            ],
        )

    def test_sql_only_startup_starts_in_background_and_reports_no_loaded_file(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        starts = []

        class _LoadConfigured:
            def execute(self, backends):
                self.assertEqual(backends, {DatabaseBackend.ACCESS})
                return []

        load_configured = _LoadConfigured()
        load_configured.assertEqual = self.assertEqual
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.sql_only")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = SimpleNamespace(
            register_all=lambda _descriptors: None
        )
        controller._file_state_model = SimpleNamespace(file_entries=[entry])
        controller._load_files_from_config_use_case = load_configured
        controller.container = SimpleNamespace(
            get=lambda _name: SimpleNamespace(
                start_database=lambda database_id, **kwargs: starts.append(
                    (database_id, kwargs)
                )
            )
        )
        self.assertEqual(AppController.load_files_from_config(controller), [])
        self.assertEqual(
            starts,
            [(descriptor.database_id, {"retry_initial_failure": False})],
        )
        self.assertTrue(AppController.has_any_databases(controller))

    def test_sql_start_scheduling_failure_still_returns_loaded_access(self):
        access_entry = FileEntry("C:/projects/active.mdb", is_checked=True)
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.schedule_failure")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = SimpleNamespace(
            register_all=lambda _descriptors: None
        )
        controller._file_state_model = SimpleNamespace(
            file_entries=[access_entry, sql_entry]
        )
        controller._load_files_from_config_use_case = SimpleNamespace(
            execute=lambda _backends: [access_entry.runtime_locator]
        )

        def fail_start(_database_id, **_kwargs):
            raise RuntimeError("worker could not be scheduled")

        services = {
            "database_capability_service": SimpleNamespace(
                mark_connected=lambda _database_id: None,
                mark_disconnected=lambda _database_id: None,
            ),
            "sql_collaboration_coordinator": SimpleNamespace(start_database=fail_start),
        }
        controller.container = SimpleNamespace(get=services.__getitem__)
        with self.assertLogs(controller.logger, level="ERROR"):
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])

    def test_unloading_inactive_database_preserves_active_visualization(self):
        closed_visualizations = []
        published = []
        active_access = "C:/projects/active.mdb"
        inactive_sql = "sql-database-id"
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.inactive_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda file_path: SimpleNamespace(
                success=file_path == inactive_sql,
                error_message="",
            )
        )
        controller.orchestrators = SimpleNamespace(
            visualization=SimpleNamespace(
                close_realtime_visualization=lambda: closed_visualizations.append(True)
            )
        )
        controller.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        self.assertTrue(AppController.unload_file(controller, inactive_sql))
        self.assertEqual(closed_visualizations, [])
        self.assertEqual(len(published), 1)
        self.assertFalse(published[0][1]["active_context_removed"])

    def test_failed_active_database_unload_preserves_active_visualization(self):
        closed_visualizations = []
        active_access = "C:/projects/active.mdb"
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.failed_active_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda _file_path: SimpleNamespace(
                success=False,
                error_message="database is busy",
            )
        )
        controller.orchestrators = SimpleNamespace(
            visualization=SimpleNamespace(
                close_realtime_visualization=lambda: closed_visualizations.append(True)
            )
        )
        controller.event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        with self.assertLogs(controller.logger, level="ERROR"):
            self.assertFalse(AppController.unload_file(controller, active_access))
        self.assertEqual(closed_visualizations, [])
