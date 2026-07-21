import unittest
import random
import threading
from types import SimpleNamespace
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from ost_visualizer.domain.entities.database_descriptor import DatabaseBackend
from ost_visualizer.domain.entities.identity_refs import BidRef
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
    def test_empty_and_meshless_page_selections_publish_authoritative_scenes(
        self,
    ):
        published = []
        bid_ref = BidRef("db.mdb", "bid-empty")
        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(takeoffs=[]),
        )
        service._visualization_provider = SimpleNamespace(
            convert_meshes_to_geometries=lambda _meshes, _colors: (
                [],
                (0, 0, 0, 0, 0, 0),
            )
        )
        service.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service.refresh_mesh_view([])
        self.assertEqual(len(published), 1)
        empty_identity = published[0][1]["scene_identity"]
        self.assertEqual(empty_identity.bid_ref, bid_ref)
        self.assertEqual(empty_identity.page_uids, ())
        self.assertEqual(empty_identity.generation, 1)
        service.refresh_mesh_view(["page-1"])
        self.assertEqual(len(published), 2)
        event, payload = published[1]
        self.assertIs(event, AppEvents.NATIVE_SCENE_UPDATED)
        self.assertEqual(payload["scene_identity"].bid_ref, bid_ref)
        self.assertEqual(payload["scene_identity"].page_uids, ("page-1",))
        self.assertEqual(payload["scene_identity"].generation, 2)

    def test_scene_ready_publishes_only_current_generation_with_bid_identity(self):
        published = []
        service = VisualizationService.__new__(VisualizationService)
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 42
        service._mesh_generation_identity = MeshSceneIdentity(
            BidRef("db.mdb", "bid-42"), ("page-42",), 42
        )
        service._mesh_generation_delivered = False
        service._mesh_shutdown = threading.Event()
        service.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        service._on_scene_ready([], (0, 1, 0, 1, 0, 1), 41)
        self.assertEqual(published, [])
        service._on_scene_ready([], (0, 1, 0, 1, 0, 1), 42)
        self.assertEqual(len(published), 1)
        event, payload = published[0]
        self.assertIs(event, AppEvents.NATIVE_SCENE_UPDATED)
        self.assertEqual(payload["scene_identity"].bid_ref.file_path, "db.mdb")
        self.assertEqual(payload["scene_identity"].bid_ref.bid_uid, "bid-42")
        self.assertEqual(payload["scene_identity"].page_uids, ("page-42",))
        self.assertEqual(payload["scene_identity"].generation, 42)
        service._on_scene_ready([], (0, 1, 0, 1, 0, 1), 42)
        self.assertEqual(len(published), 1)

    def test_rapid_page_and_bid_switches_reject_obsolete_mesh_results(self):
        published = []
        current_bid = [BidRef("db.mdb", "bid-1")]
        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: current_bid[0],
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(
                takeoffs=[object()]
            ),
            get_bid_conditions=lambda: {},
            get_page_area_selections=lambda: {},
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition", grayscale_enabled=False
        )
        service.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = SimpleNamespace(set=lambda: None)
        service.refresh_mesh_view(["page-a"])
        page_a_generation = service._mesh_generation_id
        service.refresh_mesh_view(["page-b"])
        page_b_generation = service._mesh_generation_id
        service._on_scene_ready([], None, page_a_generation)
        self.assertEqual(published, [])
        service._on_scene_ready([], None, page_b_generation)
        self.assertEqual(published[0][1]["scene_identity"].page_uids, ("page-b",))
        current_bid[0] = BidRef("db.mdb", "bid-2")
        service.refresh_mesh_view(["page-b"])
        bid_two_generation = service._mesh_generation_id
        service._on_scene_ready([], None, page_b_generation)
        self.assertEqual(len(published), 1)
        service._on_scene_ready([], None, bid_two_generation)
        self.assertEqual(published[1][1]["scene_identity"].bid_ref, current_bid[0])

    def test_failed_generation_can_be_retried_for_the_same_page_selection(self):
        published = []
        bid_ref = BidRef("db.mdb", "bid-1")
        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(
                takeoffs=[object()]
            ),
            get_bid_conditions=lambda: {},
            get_page_area_selections=lambda: {},
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition", grayscale_enabled=False
        )
        service.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = SimpleNamespace(set=lambda: None)
        service.refresh_mesh_view(["page-a"])
        failed_generation = service._mesh_generation_id
        service.refresh_mesh_view(["page-a"])
        retry_generation = service._mesh_generation_id
        service._on_scene_ready([], None, failed_generation)
        self.assertEqual(published, [])
        service._on_scene_ready([], None, retry_generation)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0][1]["scene_identity"].page_uids, ("page-a",))

    def test_worker_failure_publishes_current_empty_scene_and_retry_succeeds(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        published = []
        scene_ready = threading.Event()

        class FlakyGenerator:
            def __init__(self):
                self.calls = 0

            def generate_meshes(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("generation failed")
                return [], {}, None

        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(
                takeoffs=[object()]
            ),
            get_bid_conditions=lambda: {},
            get_page_area_selections=lambda: {},
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition", grayscale_enabled=False
        )
        service._visualization_provider = SimpleNamespace(
            convert_meshes_to_geometries=lambda _meshes, _colors: ([], None)
        )
        service._mesh_generator = FlakyGenerator()

        def publish(event, **payload):
            published.append((event, payload))
            scene_ready.set()

        service.event_bus = SimpleNamespace(publish=publish)
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = threading.Event()
        service._scene_notifier = SimpleNamespace(
            notify_scene_ready=lambda geometries, bounds, generation: (
                service._on_scene_ready(geometries, bounds, generation)
            )
        )
        worker = threading.Thread(target=service._mesh_worker_loop, daemon=True)
        worker.start()
        try:
            service.refresh_mesh_view(["page-a"])
            self.assertTrue(scene_ready.wait(2.0))
            self.assertEqual(len(published), 1)
            first_identity = published[0][1]["scene_identity"]
            self.assertEqual(first_identity.page_uids, ("page-a",))
            self.assertEqual(published[0][1]["geometries"], [])
            scene_ready.clear()
            service.refresh_mesh_view(["page-a"])
            self.assertTrue(scene_ready.wait(2.0))
            self.assertEqual(len(published), 2)
            second_identity = published[1][1]["scene_identity"]
            self.assertGreater(second_identity.generation, first_identity.generation)
        finally:
            service._mesh_shutdown.set()
            service._mesh_task_event.set()
            worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())

    def test_randomized_scene_identity_ordering_is_deterministic(self):
        for seed in range(20):
            rng = random.Random(9300 + seed)
            published = []
            current_bid = [BidRef("db.mdb", "bid-a")]
            service = VisualizationService.__new__(VisualizationService)
            service.project_data = SimpleNamespace(
                get_current_bid_ref=lambda: current_bid[0],
                collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(
                    takeoffs=[object()]
                ),
                get_bid_conditions=lambda: {},
                get_page_area_selections=lambda: {},
            )
            service.config_model = SimpleNamespace(
                display_mode_3d="condition", grayscale_enabled=False
            )
            service.event_bus = SimpleNamespace(
                publish=lambda event, **payload: published.append((event, payload))
            )
            service._mesh_generation_lock = threading.Lock()
            service._mesh_generation_id = 0
            service._mesh_generation_identity = None
            service._mesh_generation_delivered = True
            service._mesh_pending_task = None
            service._mesh_shutdown = threading.Event()
            service._mesh_task_event = SimpleNamespace(set=lambda: None)
            generations = []
            for _step in range(300):
                action = rng.randrange(4)
                if action <= 1 or not generations:
                    current_bid[0] = BidRef(
                        "db.mdb", rng.choice(("bid-a", "bid-b", "bid-c"))
                    )
                    page_count = rng.randint(1, 55)
                    pages = [f"page-{rng.randrange(55):02d}" for _ in range(page_count)]
                    rng.shuffle(pages)
                    service.refresh_mesh_view(pages)
                    generations.append(service._mesh_generation_id)
                    identity = service._mesh_generation_identity
                    self.assertEqual(
                        identity.page_uids,
                        tuple(sorted(set(pages))),
                    )
                elif action == 2:
                    service.cancel_mesh_view_refresh()
                    generations.append(service._mesh_generation_id)
                else:
                    generation = rng.choice(generations)
                    before = len(published)
                    expected_identity = service._mesh_generation_identity
                    should_publish = bool(
                        expected_identity is not None
                        and generation == service._mesh_generation_id
                        and not service._mesh_generation_delivered
                    )
                    service._on_scene_ready([], None, generation)
                    self.assertEqual(len(published) - before, int(should_publish))
                    if should_publish:
                        self.assertEqual(
                            published[-1][1]["scene_identity"], expected_identity
                        )
            published_generations = [
                payload["scene_identity"].generation for _event, payload in published
            ]
            self.assertEqual(
                len(published_generations), len(set(published_generations))
            )

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
