import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.dtos.file_dto import FileLoadResultDto
from ost_visualizer.application.builders.orchestrator_builder import AppOrchestrators
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.service_container import ServiceContainer
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
import tempfile
import threading
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry


def _make_controller(**overrides):
    dependencies = dict(
        container=ServiceContainer(),
        event_bus=EventBus(),
        logger=logging.getLogger(__name__),
        orchestrators=None,
        project_data_service=None,
        file_loading_service=None,
        load_files_from_config_use_case=None,
        working_directory_service=None,
        file_state_model=None,
    )
    dependencies.update(overrides)
    return AppController(**dependencies)


class FakeEventBus(EventBus):
    def __init__(self):
        super().__init__()
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, event_type, callback):
        super().subscribe(event_type, callback)
        self.subscriptions.append((event_type, callback))

    def unsubscribe(self, event_type, callback):
        super().unsubscribe(event_type, callback)
        self.unsubscriptions.append((event_type, callback))


class FakeCleanupObject:
    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


class AppControllerLifecycleTests(unittest.TestCase):
    def test_failed_unsubscribe_retries_without_repeating_other_cleanup(self):
        class FailsOnceEventBus(EventBus):
            attempts = 0

            def unsubscribe(self, event_type, callback):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("transient unsubscribe failure")
                super().unsubscribe(event_type, callback)

        bus = FailsOnceEventBus()
        delivered = []
        visualization, license_orchestrator = FakeCleanupObject(), FakeCleanupObject()
        hooks = []
        controller = AppController(
            container=ServiceContainer(),
            event_bus=bus,
            logger=logging.getLogger("test.cleanup.retry"),
            orchestrators=AppOrchestrators(
                visualization=visualization,
                lifecycle=object(),
                license=license_orchestrator,
            ),
            project_data_service=None,
            file_loading_service=None,
            load_files_from_config_use_case=None,
            working_directory_service=None,
            file_state_model=None,
            cleanup_hooks=[lambda: hooks.append("done")],
        )
        controller.subscribe_to_event(
            AppEvents.LICENSE_EXPIRED, lambda message="": delivered.append(message)
        )
        controller.subscribe_to_event(
            AppEvents.LICENSE_EXPIRED,
            lambda message="": delivered.append("second:" + message),
        )
        with self.assertLogs(controller.logger, level="ERROR"):
            controller.cleanup()
        controller.cleanup()
        bus.publish(AppEvents.LICENSE_EXPIRED, message="stale")
        self.assertEqual(delivered, [])
        self.assertEqual(bus.attempts, 3)
        self.assertEqual(
            (visualization.cleanup_calls, license_orchestrator.cleanup_calls), (1, 1)
        )
        self.assertEqual(hooks, ["done"])
        self.assertIsNone(controller.event_bus)
        controller.cleanup()
        self.assertEqual(bus.attempts, 3)

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
            container=ServiceContainer(),
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

    def test_create_database_forwards_request_without_duplicating_existing_entry(self):
        entry = FileEntry(str(Path("C:/jobs/existing.mdb")), is_checked=True)
        state = SimpleNamespace(
            file_entries=[entry],
            contains_path=Mock(return_value=True),
            update_entries=Mock(),
        )
        creator = SimpleNamespace(
            create_database=Mock(return_value=Path(entry.file_path))
        )
        registry = DatabaseDescriptorRegistry()
        controller = _make_controller(
            working_directory_service=creator,
            file_state_model=state,
            database_descriptor_registry=registry,
        )
        progress = Mock()
        self.assertEqual(
            controller.create_new_database("Existing", progress),
            str(Path(entry.file_path)),
        )
        creator.create_database.assert_called_once_with(
            "Existing", progress_callback=progress
        )
        state.update_entries.assert_not_called()
        self.assertEqual(state.file_entries, [entry])
        self.assertEqual(registry.resolve(entry.database_id), entry.descriptor)

    def test_failed_database_creation_does_not_register_or_update_file_state(self):
        for failure in (None, RuntimeError("creation failed")):
            with self.subTest(failure=failure):
                state = SimpleNamespace(
                    file_entries=[], contains_path=Mock(), update_entries=Mock()
                )
                create = Mock(return_value=None, side_effect=failure)
                registry = Mock(spec=DatabaseDescriptorRegistry)
                controller = _make_controller(
                    working_directory_service=SimpleNamespace(create_database=create),
                    file_state_model=state,
                    database_descriptor_registry=registry,
                )
                if failure is None:
                    self.assertIsNone(controller.create_new_database())
                else:
                    with self.assertLogs(controller.logger, level="ERROR"):
                        self.assertIsNone(controller.create_new_database())
                state.contains_path.assert_not_called()
                state.update_entries.assert_not_called()
                registry.register.assert_not_called()

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
        for service_name in ("retained", "lazy_retained"):
            with self.assertRaises(KeyError):
                container.get(service_name)

    def test_app_controller_cleanup_continues_after_stage_failures(self):
        cleanup_calls = []

        class FailingEventBus(FakeEventBus):
            def unsubscribe(self, event_type, callback):
                self.unsubscriptions.append((event_type, callback))
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
        self.assertIs(controller.event_bus, event_bus)
        self.assertIsNone(controller.orchestrators)
        self.assertEqual(
            controller._subscriptions, [(AppEvents.LICENSE_EXPIRED, callback)]
        )
        self.assertEqual(controller._cleanup_hooks, [])
        self.assertEqual(container._services, {})


class AppControllerDatabaseRestoreTests(unittest.TestCase):
    def test_database_availability_requires_checked_existing_access_or_checked_sql(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exists.mdb"
            path.touch()
            available = FileEntry(str(path), is_checked=True)
            unchecked = FileEntry(str(path), is_checked=False)
            missing = FileEntry(str(path.with_name("missing.mdb")), is_checked=True)
            sql = FileEntry.for_descriptor(
                DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(server="unreachable", database="fixture"),
                    schema_version=1,
                ),
                is_checked=True,
            )
            for entries, expected in (
                ([], False),
                ([unchecked, missing], False),
                ([missing, available], True),
                ([sql], True),
            ):
                with self.subTest(entries=entries):
                    controller = _make_controller(
                        file_state_model=SimpleNamespace(file_entries=entries)
                    )
                    self.assertIs(controller.has_any_databases(), expected)

    def test_discovery_is_applied_before_registration_and_load(self):
        original = FileEntry("C:/jobs/original.mdb", is_checked=True)
        discovered = FileEntry("C:/jobs/discovered.mdb", is_checked=True)
        state = SimpleNamespace(file_entries=[original], reload=Mock())

        def update_entries(entries):
            state.file_entries = list(entries)

        state.update_entries = Mock(side_effect=update_entries)
        registry = DatabaseDescriptorRegistry()
        merge = Mock(return_value=[original, discovered])
        connected = []
        controller = _make_controller(
            file_state_model=state,
            database_descriptor_registry=registry,
            working_directory_service=SimpleNamespace(
                merge_discovered_into_file_state=merge
            ),
        )

        def load(backends):
            self.assertEqual(backends, {DatabaseBackend.ACCESS})
            self.assertEqual(state.file_entries, [original, discovered])
            self.assertEqual(
                registry.resolve(discovered.database_id), discovered.descriptor
            )
            return [discovered.runtime_locator]

        controller._load_files_from_config_use_case = SimpleNamespace(execute=load)
        controller.container.register_instance(
            "database_capability_service",
            SimpleNamespace(mark_connected=connected.append),
        )
        sql = SimpleNamespace(start_database=Mock())
        controller.container.register_instance("sql_collaboration_coordinator", sql)
        self.assertEqual(
            controller.load_files_from_config(), [discovered.runtime_locator]
        )
        state.reload.assert_called_once_with()
        merge.assert_called_once_with([original])
        state.update_entries.assert_called_once_with([original, discovered])
        self.assertEqual(connected, [discovered.database_id])
        sql.start_database.assert_not_called()

    def test_discovery_failure_and_unchecked_sql_do_not_prevent_access_restore(self):
        entry = FileEntry("C:/jobs/current.mdb", is_checked=True)
        sql_entry = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(server="localhost", database="unchecked"),
                schema_version=1,
            ),
            is_checked=False,
        )
        state = SimpleNamespace(
            file_entries=[entry, sql_entry], reload=Mock(), update_entries=Mock()
        )
        loader = SimpleNamespace(execute=Mock(return_value=[entry.runtime_locator]))
        connected = []
        sql = SimpleNamespace(start_database=Mock())
        controller = _make_controller(
            file_state_model=state,
            working_directory_service=SimpleNamespace(
                merge_discovered_into_file_state=Mock(
                    side_effect=OSError("discovery unavailable")
                )
            ),
            load_files_from_config_use_case=loader,
        )
        controller.container.register_instance(
            "database_capability_service",
            SimpleNamespace(mark_connected=connected.append),
        )
        controller.container.register_instance("sql_collaboration_coordinator", sql)
        with self.assertLogs(controller.logger, level="WARNING"):
            self.assertEqual(
                controller.load_files_from_config(), [entry.runtime_locator]
            )
        loader.execute.assert_called_once_with({DatabaseBackend.ACCESS})
        self.assertEqual(connected, [entry.database_id])
        state.update_entries.assert_not_called()
        sql.start_database.assert_not_called()

    def test_active_unload_captures_context_before_service_clears_it(self):
        for current_path, target in (
            ("C:/jobs/active.mdb", None),
            ("C:/jobs/other.mdb", "c:\\JOBS\\ACTIVE.mdb"),
        ):
            with self.subTest(target=target):
                paths = {"current": current_path, "bid": "C:/jobs/active.mdb"}
                order = []
                bus = EventBus()
                bus.subscribe(
                    AppEvents.FILE_UNLOADED,
                    lambda **payload: order.append(("event", payload)),
                )

                def unload(file_path):
                    order.append(("unload", file_path))
                    paths.clear()
                    return FileLoadResultDto(success=True)

                controller = _make_controller(
                    event_bus=bus,
                    project_data_service=SimpleNamespace(
                        get_current_file_path=lambda: paths.get("current"),
                        get_current_bid_file_path=lambda: paths.get("bid"),
                    ),
                    file_loading_service=SimpleNamespace(unload_file=unload),
                    orchestrators=SimpleNamespace(
                        visualization=SimpleNamespace(
                            close_realtime_visualization=lambda: order.append("close")
                        )
                    ),
                )
                self.assertTrue(controller.unload_file(target))
                self.assertEqual(
                    order,
                    [
                        ("unload", target),
                        "close",
                        (
                            "event",
                            {
                                "file_path": target or current_path,
                                "active_context_removed": True,
                            },
                        ),
                    ],
                )

    def test_unload_exception_or_absent_context_never_closes_or_publishes(self):
        for current_path in (None, "active.mdb"):
            with self.subTest(current_path=current_path):
                loader = SimpleNamespace(
                    unload_file=Mock(side_effect=OSError("read failed"))
                )
                visualization = SimpleNamespace(close_realtime_visualization=Mock())
                bus = SimpleNamespace(publish=Mock())
                controller = _make_controller(
                    event_bus=bus,
                    project_data_service=SimpleNamespace(
                        get_current_file_path=lambda: current_path,
                        get_current_bid_file_path=lambda: current_path,
                    ),
                    file_loading_service=loader,
                    orchestrators=SimpleNamespace(visualization=visualization),
                )
                if current_path:
                    with self.assertLogs(controller.logger, level="ERROR"):
                        self.assertFalse(controller.unload_file())
                    loader.unload_file.assert_called_once_with(None)
                else:
                    self.assertFalse(controller.unload_file())
                    loader.unload_file.assert_not_called()
                visualization.close_realtime_visualization.assert_not_called()
                bus.publish.assert_not_called()

    def test_startup_loads_access_and_requests_sql_start_on_caller_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / "available.mdb"
            access_path.touch()
            access_entry = FileEntry(str(access_path), is_checked=True)
            sql_descriptor = DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="localhost", database="UNAVAILABLE_SQL"
                ),
                schema_version=1,
            )
            sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
            execute_calls = []
            starts = []
            connected = []

            class _LoadConfigured:
                def execute(self, backends):
                    execute_calls.append((set(backends), threading.get_ident()))
                    return [access_entry.runtime_locator]

            controller = _make_controller()
            controller.logger = logging.getLogger("test.startup.controller")
            controller._auto_discover_databases = lambda: None
            controller._database_descriptor_registry = DatabaseDescriptorRegistry()
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
            for name, service in services.items():
                controller.container.register_instance(name, service)
            main_thread = threading.get_ident()
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])
        self.assertEqual(
            controller._database_descriptor_registry.resolve(sql_entry.database_id),
            sql_descriptor,
        )
        self.assertEqual(
            controller._database_descriptor_registry.resolve(access_entry.database_id),
            access_entry.descriptor,
        )
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

    def test_sql_only_startup_schedules_connection_without_loading_access(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=1,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        starts = []
        load_configured = SimpleNamespace(execute=Mock(return_value=[]))
        controller = _make_controller()
        controller.logger = logging.getLogger("test.startup.sql_only")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = DatabaseDescriptorRegistry()
        controller._file_state_model = SimpleNamespace(file_entries=[entry])
        controller._load_files_from_config_use_case = load_configured
        capability = SimpleNamespace(mark_connected=Mock(), mark_disconnected=Mock())
        controller.container.register_instance(
            "database_capability_service", capability
        )
        controller.container.register_instance(
            "sql_collaboration_coordinator",
            SimpleNamespace(
                start_database=lambda database_id, **kwargs: starts.append(
                    (database_id, kwargs)
                )
            ),
        )
        self.assertEqual(AppController.load_files_from_config(controller), [])
        load_configured.execute.assert_called_once_with({DatabaseBackend.ACCESS})
        capability.mark_connected.assert_not_called()
        capability.mark_disconnected.assert_not_called()
        self.assertEqual(
            starts,
            [(descriptor.database_id, {"retry_initial_failure": False})],
        )
        self.assertTrue(AppController.has_any_databases(controller))

    def test_sql_start_scheduling_failure_still_returns_loaded_access(self):
        access_entry = FileEntry("C:/projects/active.mdb", is_checked=True)
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=1,
        )
        sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
        controller = _make_controller()
        controller.logger = logging.getLogger("test.startup.schedule_failure")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = DatabaseDescriptorRegistry()
        controller._file_state_model = SimpleNamespace(
            file_entries=[access_entry, sql_entry]
        )
        controller._load_files_from_config_use_case = SimpleNamespace(
            execute=lambda _backends: [access_entry.runtime_locator]
        )

        def fail_start(_database_id, **_kwargs):
            raise RuntimeError("worker could not be scheduled")

        connected, disconnected = [], []
        services = {
            "database_capability_service": SimpleNamespace(
                mark_connected=connected.append,
                mark_disconnected=disconnected.append,
            ),
            "sql_collaboration_coordinator": SimpleNamespace(start_database=fail_start),
        }
        for name, service in services.items():
            controller.container.register_instance(name, service)
        with self.assertLogs(controller.logger, level="ERROR"):
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])
        self.assertEqual(connected, [access_entry.database_id])
        self.assertEqual(disconnected, [sql_entry.database_id])

    def test_unloading_inactive_database_preserves_active_visualization(self):
        closed_visualizations = []
        published = []
        active_access = "C:/projects/active.mdb"
        inactive_sql = "sql-database-id"
        controller = _make_controller()
        controller.logger = logging.getLogger("test.startup.inactive_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda file_path: FileLoadResultDto(
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
        self.assertEqual(
            published,
            [
                (
                    AppEvents.FILE_UNLOADED,
                    {
                        "file_path": inactive_sql,
                        "active_context_removed": False,
                    },
                )
            ],
        )

    def test_failed_active_database_unload_preserves_active_visualization(self):
        closed_visualizations = []
        active_access = "C:/projects/active.mdb"
        controller = _make_controller()
        controller.logger = logging.getLogger("test.startup.failed_active_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda _file_path: FileLoadResultDto(
                success=False,
                error_message="database is busy",
            )
        )
        controller.orchestrators = SimpleNamespace(
            visualization=SimpleNamespace(
                close_realtime_visualization=lambda: closed_visualizations.append(True)
            )
        )
        controller.event_bus = SimpleNamespace(publish=Mock())
        with self.assertLogs(controller.logger, level="ERROR"):
            self.assertFalse(AppController.unload_file(controller, active_access))
        self.assertEqual(closed_visualizations, [])
        controller.event_bus.publish.assert_not_called()
