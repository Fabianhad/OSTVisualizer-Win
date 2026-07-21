import unittest
from types import SimpleNamespace
from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from ost_visualizer.domain.entities.database_descriptor import DatabaseBackend
from ost_visualizer.infrastructure.monitoring.transaction_monitor import (
    MonitorState,
    TransactionMonitor,
)


class _TransactionMonitor:
    def __init__(self, *, monitoring: bool = False) -> None:
        self.monitoring = monitoring
        self.start_calls = 0
        self.stop_calls = 0
        self.callback = None

    def is_monitoring(self) -> bool:
        return self.monitoring

    def start_monitoring(self, callback) -> bool:
        self.start_calls += 1
        self.callback = callback
        self.monitoring = True
        return True

    def stop_monitoring(self) -> None:
        self.stop_calls += 1
        self.monitoring = False


class _ProjectData:
    def __init__(self, locator: str) -> None:
        self.locator = locator

    def has_loaded_files(self) -> bool:
        return bool(self.locator)

    def get_current_file_path(self) -> str:
        return self.locator


class _DescriptorRegistry:
    def __init__(self, backends: dict[str, DatabaseBackend]) -> None:
        self._backends = backends

    def resolve(self, locator: str):
        backend = self._backends.get(locator)
        if backend is None:
            return None
        return SimpleNamespace(backend=backend)


class _ProjectOperations:
    def __init__(self) -> None:
        self.reloads: list[str] = []

    def reload_database(self, locator: str) -> bool:
        self.reloads.append(locator)
        return True


class _SceneNotifier:
    def __init__(self) -> None:
        self.refreshes: list[str] = []

    def notify_full_refresh(self, locator: str) -> None:
        self.refreshes.append(locator)


class _CallbackBridge:
    def __init__(self) -> None:
        self.pending = []

    def dispatch(self, callback, payload) -> None:
        self.pending.append((callback, payload))

    def run_pending(self) -> None:
        pending, self.pending = self.pending, []
        for callback, payload in pending:
            callback(payload)


def _service(
    locator: str,
    backend: DatabaseBackend,
    *,
    monitoring: bool = False,
) -> tuple[
    VisualizationService,
    _TransactionMonitor,
    _ProjectData,
    _ProjectOperations,
    _SceneNotifier,
]:
    service = VisualizationService.__new__(VisualizationService)
    monitor = _TransactionMonitor(monitoring=monitoring)
    project_data = _ProjectData(locator)
    operations = _ProjectOperations()
    notifier = _SceneNotifier()
    service._transaction_monitor = monitor
    service._database_descriptor_registry = _DescriptorRegistry({locator: backend})
    service.project_data = project_data
    service.project_operations = operations
    service._scene_notifier = notifier
    service._callback_bridge = _CallbackBridge()
    service._database_monitor_generation = 0
    service._monitored_access_locator = None
    return service, monitor, project_data, operations, notifier


class VisualizationServiceDatabaseMonitoringTests(unittest.TestCase):
    def test_access_database_starts_and_processes_companion_commit_monitor(self):
        locator = "C:/projects/local.mdb"
        service, monitor, _data, operations, notifier = _service(
            locator, DatabaseBackend.ACCESS
        )
        service.start_database_monitoring()
        self.assertEqual(monitor.start_calls, 1)
        monitor.callback()
        self.assertEqual(operations.reloads, [])
        service._callback_bridge.run_pending()
        self.assertEqual(operations.reloads, [locator])
        self.assertEqual(notifier.refreshes, [locator])

    def test_sql_database_never_starts_access_companion_monitor(self):
        locator = "sql-database-id"
        service, monitor, _data, operations, notifier = _service(
            locator, DatabaseBackend.SQL_SERVER
        )
        service.start_database_monitoring()
        self.assertEqual(monitor.start_calls, 0)
        self.assertEqual(operations.reloads, [])
        self.assertEqual(notifier.refreshes, [])

    def test_stale_access_commit_callback_cannot_reload_sql_after_switch(self):
        access_locator = "C:/projects/local.mdb"
        sql_locator = "sql-database-id"
        service, monitor, project_data, operations, notifier = _service(
            access_locator, DatabaseBackend.ACCESS
        )
        service._database_descriptor_registry = _DescriptorRegistry(
            {
                access_locator: DatabaseBackend.ACCESS,
                sql_locator: DatabaseBackend.SQL_SERVER,
            }
        )
        service.start_database_monitoring()
        callback = monitor.callback
        callback()
        project_data.locator = sql_locator
        service._callback_bridge.run_pending()
        self.assertEqual(operations.reloads, [])
        self.assertEqual(notifier.refreshes, [])

    def test_stale_access_commit_callback_cannot_reload_another_access_database(self):
        first_locator = "C:/projects/first.mdb"
        second_locator = "C:/projects/second.mdb"
        service, monitor, project_data, operations, notifier = _service(
            first_locator, DatabaseBackend.ACCESS
        )
        service._database_descriptor_registry = _DescriptorRegistry(
            {
                first_locator: DatabaseBackend.ACCESS,
                second_locator: DatabaseBackend.ACCESS,
            }
        )
        service.start_database_monitoring()
        monitor.callback()
        project_data.locator = second_locator
        service.start_database_monitoring()
        service._callback_bridge.run_pending()
        self.assertEqual(operations.reloads, [])
        self.assertEqual(notifier.refreshes, [])
        self.assertEqual(monitor.start_calls, 2)
        self.assertEqual(monitor.stop_calls, 1)

    def test_switch_to_sql_stops_running_access_companion_monitor(self):
        locator = "sql-database-id"
        service, monitor, _data, _operations, _notifier = _service(
            locator, DatabaseBackend.SQL_SERVER, monitoring=True
        )
        service.start_database_monitoring()
        self.assertEqual(monitor.stop_calls, 1)
        self.assertFalse(monitor.monitoring)

    def test_monitor_stop_clears_pending_debounced_commit(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertIsNone(monitor._callback)

    def test_monitor_stop_cleans_stale_state_after_worker_already_exited(self):
        monitor = TransactionMonitor()
        monitor._pending_callback = True
        monitor._last_signal_time = 123.0
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertFalse(monitor._pending_callback)
        self.assertEqual(monitor._last_signal_time, 0.0)
        self.assertIsNone(monitor._callback)

    def test_monitor_stop_resets_connection_state_for_later_access_restart(self):
        monitor = TransactionMonitor()
        monitor._is_monitoring = True
        monitor._state = MonitorState.CONNECTED
        monitor._status_online = True
        monitor.stop_monitoring()
        self.assertEqual(monitor._state, MonitorState.INITIAL)
        self.assertFalse(monitor._status_online)

    def test_monitor_stop_retains_worker_reference_until_worker_really_exits(self):
        class _StillRunningThread:
            def __init__(self) -> None:
                self.join_calls = []

            def is_alive(self) -> bool:
                return True

            def join(self, timeout=None) -> None:
                self.join_calls.append(timeout)

        monitor = TransactionMonitor()
        thread = _StillRunningThread()
        monitor._monitor_thread = thread
        monitor._is_monitoring = True
        monitor._callback = lambda: None
        monitor.stop_monitoring()
        self.assertIs(monitor._monitor_thread, thread)
        self.assertTrue(monitor._is_monitoring)
        self.assertIsNone(monitor._callback)
        self.assertEqual(thread.join_calls, [1.5])


if __name__ == "__main__":
    unittest.main()
