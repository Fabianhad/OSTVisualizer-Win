from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from types import SimpleNamespace
import unittest
import threading
import random
import queue
from unittest.mock import Mock
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import (
    CollectedTakeoffsResult,
    ProjectDataService,
)
from ost_visualizer.application.interfaces.i_event_bus import IEventBus
from ost_visualizer.application.interfaces.i_mesh_generator import IMeshGenerator
from ost_visualizer.application.interfaces.i_visualization_provider import (
    IVisualizationProvider,
)


class _TransactionMonitor:
    def __init__(self, *, monitoring: bool = False) -> None:
        self.monitoring = monitoring
        self.start_calls = 0
        self.stop_calls = 0
        self.callback = None
        self.cleanup_calls = 0
        self.dialog_states = []
        self.message_parents = []

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

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        self.stop_monitoring()

    def set_update_dialog_active(self, active):
        self.dialog_states.append(active)

    def set_message_parent(self, parent):
        self.message_parents.append(parent)


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
        if backend == DatabaseBackend.ACCESS:
            return DatabaseDescriptor.for_access(locator)
        return DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="test-server", database=locator),
            database_id=locator,
            schema_version=1,
        )


class _ProjectOperations:
    def __init__(self) -> None:
        self.reloads: list[str] = []

    def reload_database(self, locator: str) -> bool:
        self.reloads.append(locator)
        return True


class _SceneNotifier:
    def __init__(self) -> None:
        self.refreshes: list[str] = []
        self.scenes = queue.Queue()
        self.cleanup_calls = 0

    def set_handlers(self, on_scene_ready, on_full_refresh):
        self.on_scene_ready = on_scene_ready
        self.on_full_refresh = on_full_refresh

    def notify_scene_ready(self, geometries, generation, failed):
        self.scenes.put((geometries, generation, failed))

    def deliver_scene(self):
        self.on_scene_ready(*self.scenes.get(timeout=2))

    def cleanup(self):
        self.cleanup_calls += 1

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


def _page(page_uid: str) -> Page:
    return Page(
        uid=page_uid,
        name=page_uid,
        width_pts=720.0,
        height_pts=360.0,
        scale_factor1=1.0,
        scale_factor2=1.0,
    )


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


class FakeCleanupObject:
    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


class VisualizationServiceLifecycleTests(unittest.TestCase):
    def _live_service(self):
        data = Mock(spec=ProjectDataService)
        data.get_current_bid_ref.return_value = BidRef("db.mdb", "bid-1")
        data.collect_takeoffs_for_pages.return_value = CollectedTakeoffsResult(
            takeoffs=[Takeoff("t1", "c1", page_uid="p1")], valid_page_uids=["p1"]
        )
        data.get_bid_conditions.return_value = {"c1": Condition("c1", "Wall", 1)}
        data.get_page_area_selections.return_value = {"p1": "a1"}
        data.get_page.side_effect = lambda uid: _page(uid)
        provider = Mock(spec=IVisualizationProvider)
        generator = Mock(spec=IMeshGenerator)
        generator.generate_meshes.return_value = ([], {}, None)
        provider.get_mesh_generator.return_value = generator
        provider.convert_meshes_to_geometries.return_value = []
        notifier = _SceneNotifier()
        monitor = _TransactionMonitor()
        bus = Mock(spec=IEventBus)
        service = VisualizationService(
            Config(),
            data,
            _ProjectOperations(),
            bus,
            monitor,
            _DescriptorRegistry({"db.mdb": DatabaseBackend.ACCESS}),
            _CallbackBridge(),
            provider,
            notifier,
        )
        self.addCleanup(
            lambda: service.cleanup() if service.event_bus is not None else None
        )
        return service, data, provider, generator, notifier, monitor, bus

    def test_constructor_worker_delivers_once_then_cleanup_invalidates_late_result(
        self,
    ):
        service, data, provider, generator, notifier, monitor, bus = (
            self._live_service()
        )
        geometries = [
            MeshGeometry(
                vertices=[0, 0, 0, 1, 0, 0, 0, 1, 0],
                normals=[0, 0, 1] * 3,
                indices=[0, 1, 2],
                color="#123456",
                opacity=1.0,
                page_uid="p1",
                condition_uid="c1",
                takeoff_uid="t1",
            )
        ]
        provider.convert_meshes_to_geometries.return_value = geometries
        service.refresh_mesh_view(["p1", "p1"])
        identity = service.get_pending_mesh_scene_identity()
        result = notifier.scenes.get(timeout=2)
        bus.publish.assert_not_called()
        data.collect_takeoffs_for_pages.assert_called_once_with(["p1"])
        generator.generate_meshes.assert_called_once_with(
            data.get_bid_conditions.return_value,
            data.collect_takeoffs_for_pages.return_value.takeoffs,
            page_area_selections={"p1": "a1"},
            display_mode=service.config_model.display_mode_3d,
            grayscale_enabled=service.config_model.grayscale_enabled,
            inactive_object_color=service.config_model.inactive_object_color,
            page_infos={
                "p1": {
                    "scale_factor1": 1.0,
                    "scale_factor2": 1.0,
                    "rotation": 0,
                    "flip_x": False,
                    "flip_y": False,
                    "width": 720.0,
                    "height": 360.0,
                    "view_scale": 1.0,
                }
            },
        )
        provider.convert_meshes_to_geometries.assert_called_once_with([], {})
        notifier.on_scene_ready(*result)
        notifier.on_scene_ready(*result)
        bus.publish.assert_called_once_with(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=geometries,
            scene_identity=identity,
            scene_failed=False,
        )
        self.assertIsNone(service.get_pending_mesh_scene_identity())
        service.cleanup()
        self.assertFalse(service._mesh_worker.is_alive())
        self.assertEqual((monitor.cleanup_calls, notifier.cleanup_calls), (1, 1))
        notifier.on_scene_ready(*result)
        self.assertEqual(bus.publish.call_count, 1)

    def test_cancellation_during_worker_generation_discards_result_before_conversion(
        self,
    ):
        service, _data, provider, generator, notifier, _monitor, bus = (
            self._live_service()
        )
        entered = threading.Event()
        release = threading.Event()

        def generate(*_args, **_kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("Test did not release mesh generation")
            return [], {}, None

        generator.generate_meshes.side_effect = generate
        self.addCleanup(release.set)
        service.refresh_mesh_view(["old-page"])
        self.assertTrue(entered.wait(2))
        service.cancel_mesh_view_refresh()
        self.assertIsNone(service.get_pending_mesh_scene_identity())
        service.refresh_mesh_view(["new-page"])
        identity = service.get_pending_mesh_scene_identity()
        release.set()
        notifier.deliver_scene()
        self.assertEqual(generator.generate_meshes.call_count, 2)
        provider.convert_meshes_to_geometries.assert_called_once_with([], {})
        bus.publish.assert_called_once_with(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=[],
            scene_identity=identity,
            scene_failed=False,
        )
        self.assertEqual(identity.page_uids, ("new-page",))
        self.assertTrue(notifier.scenes.empty())

    def test_no_active_bid_cancels_queued_result_without_publishing_empty_scene(self):
        service, data, _provider, _generator, notifier, _monitor, bus = (
            self._live_service()
        )
        service.refresh_mesh_view(["p1"])
        result = notifier.scenes.get(timeout=2)
        data.get_current_bid_ref.return_value = None
        service.refresh_mesh_view(["p1"])
        notifier.on_scene_ready(*result)
        bus.publish.assert_not_called()
        self.assertIsNone(service.get_pending_mesh_scene_identity())

    def test_worker_conversion_failure_is_terminal_and_retry_uses_new_identity(self):
        service, _data, provider, generator, notifier, _monitor, bus = (
            self._live_service()
        )
        provider.convert_meshes_to_geometries.side_effect = [
            RuntimeError("conversion failed"),
            [],
        ]
        with self.assertLogs(
            "ost_visualizer.application.services.visualization_service", level="ERROR"
        ):
            service.refresh_mesh_view(["p1"])
            first = service.get_pending_mesh_scene_identity()
            notifier.deliver_scene()
        bus.publish.assert_called_once_with(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=[],
            scene_identity=first,
            scene_failed=True,
        )
        self.assertIsNone(service.get_pending_mesh_scene_identity())
        service.refresh_mesh_view(["p1"])
        second = service.get_pending_mesh_scene_identity()
        notifier.deliver_scene()
        self.assertGreater(second.generation, first.generation)
        self.assertEqual(second.bid_ref, first.bid_ref)
        self.assertEqual(second.page_uids, first.page_uids)
        self.assertEqual(bus.publish.call_count, 2)
        self.assertEqual(generator.generate_meshes.call_count, 2)
        bus.publish.assert_called_with(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=[],
            scene_identity=second,
            scene_failed=False,
        )

    def test_visualization_service_cleanup_releases_monitor_and_project_references(
        self,
    ):
        monitor = FakeCleanupObject()
        notifier = FakeCleanupObject()
        service = VisualizationService.__new__(VisualizationService)

        def join_mesh_worker(*, timeout=None):
            _ = timeout

        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = threading.Event()
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
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = threading.Event()
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


class VisualizationServiceDatabaseMonitoringTests(unittest.TestCase):
    def test_mesh_refresh_snapshots_persisted_page_transform_for_worker(self):
        page = _page("page-flipped")
        page.rotation = 90
        page.flip_x = True
        page.flip_y = False
        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(
                takeoffs=[object()]
            ),
            get_bid_conditions=lambda: {},
            get_page_area_selections=lambda: {},
            get_page=lambda uid: page if uid == page.uid else None,
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition",
            grayscale_enabled=False,
            inactive_object_color="#2468ac",
        )
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = threading.Event()
        service.refresh_mesh_view([page.uid])
        page_info = service._mesh_pending_task[-2][page.uid]
        page.flip_x = False
        page.flip_y = True
        self.assertEqual(page_info["rotation"], 90)
        self.assertTrue(page_info["flip_x"])
        self.assertFalse(page_info["flip_y"])
        self.assertEqual(page_info["width"], 720.0)
        self.assertEqual(page_info["height"], 360.0)

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
            convert_meshes_to_geometries=lambda _meshes, _colors: []
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

    def test_meshless_conversion_failure_is_identified_and_retryable(self):
        published = []
        bid_ref = BidRef("db.mdb", "bid-empty")
        conversion_attempts = [RuntimeError("conversion failed"), []]
        service = VisualizationService.__new__(VisualizationService)
        service.project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            collect_takeoffs_for_pages=lambda _pages: SimpleNamespace(takeoffs=[]),
        )

        def convert(_meshes, _colors):
            outcome = conversion_attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        service._visualization_provider = SimpleNamespace(
            convert_meshes_to_geometries=convert
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
        service.refresh_mesh_view(["page-1"])
        service.refresh_mesh_view(["page-1"])
        self.assertEqual(len(published), 2)
        self.assertTrue(published[0][1]["scene_failed"])
        self.assertEqual(published[0][1]["scene_identity"].generation, 1)
        self.assertFalse(published[1][1]["scene_failed"])
        self.assertEqual(published[1][1]["scene_identity"].generation, 2)

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
        service._on_scene_ready([], 41, False)
        self.assertEqual(published, [])
        service._on_scene_ready([], 42, False)
        self.assertEqual(len(published), 1)
        event, payload = published[0]
        self.assertIs(event, AppEvents.NATIVE_SCENE_UPDATED)
        self.assertEqual(payload["scene_identity"].bid_ref.file_path, "db.mdb")
        self.assertEqual(payload["scene_identity"].bid_ref.bid_uid, "bid-42")
        self.assertEqual(payload["scene_identity"].page_uids, ("page-42",))
        self.assertEqual(payload["scene_identity"].generation, 42)
        service._on_scene_ready([], 42, False)
        self.assertEqual(len(published), 1)

    def test_pending_mesh_identity_is_exposed_only_until_delivery_or_cancellation(self):
        service = VisualizationService.__new__(VisualizationService)
        identity = MeshSceneIdentity(BidRef("db.mdb", "bid-42"), ("page-42",), 42)
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = identity.generation
        service._mesh_generation_identity = identity
        service._mesh_generation_delivered = False
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service.event_bus = SimpleNamespace(publish=lambda _event, **_payload: None)
        self.assertEqual(service.get_pending_mesh_scene_identity(), identity)
        service._on_scene_ready([], identity.generation, False)
        self.assertIsNone(service.get_pending_mesh_scene_identity())
        next_identity = MeshSceneIdentity(BidRef("db.mdb", "bid-43"), ("page-43",), 43)
        service._mesh_generation_id = next_identity.generation
        service._mesh_generation_identity = next_identity
        service._mesh_generation_delivered = False
        self.assertEqual(service.get_pending_mesh_scene_identity(), next_identity)
        service.cancel_mesh_view_refresh()
        self.assertIsNone(service.get_pending_mesh_scene_identity())

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
            get_page=lambda uid: _page(uid),
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition",
            grayscale_enabled=False,
            inactive_object_color="#2468ac",
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
        service._mesh_task_event = threading.Event()
        service.refresh_mesh_view(["page-a"])
        page_a_generation = service._mesh_generation_id
        service.refresh_mesh_view(["page-b"])
        page_b_generation = service._mesh_generation_id
        service._on_scene_ready([], page_a_generation, False)
        self.assertEqual(published, [])
        service._on_scene_ready([], page_b_generation, False)
        self.assertEqual(published[0][1]["scene_identity"].page_uids, ("page-b",))
        current_bid[0] = BidRef("db.mdb", "bid-2")
        service.refresh_mesh_view(["page-b"])
        bid_two_generation = service._mesh_generation_id
        service._on_scene_ready([], page_b_generation, False)
        self.assertEqual(len(published), 1)
        service._on_scene_ready([], bid_two_generation, False)
        self.assertEqual(published[1][1]["scene_identity"].bid_ref, current_bid[0])

    def test_superseded_generation_is_rejected_for_the_same_page_selection(self):
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
            get_page=lambda uid: _page(uid),
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition",
            grayscale_enabled=False,
            inactive_object_color="#2468ac",
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
        service._mesh_task_event = threading.Event()
        service.refresh_mesh_view(["page-a"])
        failed_generation = service._mesh_generation_id
        service.refresh_mesh_view(["page-a"])
        retry_generation = service._mesh_generation_id
        service._on_scene_ready([], failed_generation, False)
        self.assertEqual(published, [])
        service._on_scene_ready([], retry_generation, False)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0][1]["scene_identity"].page_uids, ("page-a",))

    def test_worker_failure_publishes_terminal_failure_and_retry_succeeds(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        published = []
        notifier = _SceneNotifier()
        publication_threads = []

        class FlakyGenerator:
            def __init__(self):
                self.calls = 0

            def generate_meshes(
                self,
                bid_conditions,
                bid_takeoffs,
                page_area_selections=None,
                display_mode="solid",
                grayscale_enabled=True,
                *,
                inactive_object_color,
                page_infos=None,
            ):
                del (
                    bid_conditions,
                    bid_takeoffs,
                    page_area_selections,
                    display_mode,
                    grayscale_enabled,
                    inactive_object_color,
                    page_infos,
                )
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
            get_page=lambda uid: _page(uid),
        )
        service.config_model = SimpleNamespace(
            display_mode_3d="condition",
            grayscale_enabled=False,
            inactive_object_color="#2468ac",
        )
        service._visualization_provider = SimpleNamespace(
            convert_meshes_to_geometries=lambda _meshes, _colors: []
        )
        service._mesh_generator = FlakyGenerator()

        def publish(event, **payload):
            published.append((event, payload))
            publication_threads.append(threading.get_ident())

        service.event_bus = SimpleNamespace(publish=publish)
        service._mesh_generation_lock = threading.Lock()
        service._mesh_generation_id = 0
        service._mesh_generation_identity = None
        service._mesh_generation_delivered = True
        service._mesh_pending_task = None
        service._mesh_shutdown = threading.Event()
        service._mesh_task_event = threading.Event()
        service._scene_notifier = notifier
        notifier.set_handlers(service._on_scene_ready, service._on_full_refresh_ready)
        worker = threading.Thread(target=service._mesh_worker_loop, daemon=True)
        worker.start()
        try:
            service.refresh_mesh_view(["page-a"])
            notifier.deliver_scene()
            self.assertEqual(len(published), 1)
            first_identity = published[0][1]["scene_identity"]
            self.assertEqual(first_identity.page_uids, ("page-a",))
            self.assertEqual(published[0][1]["geometries"], [])
            self.assertTrue(published[0][1]["scene_failed"])
            service.refresh_mesh_view(["page-a"])
            notifier.deliver_scene()
            self.assertEqual(len(published), 2)
            second_identity = published[1][1]["scene_identity"]
            self.assertGreater(second_identity.generation, first_identity.generation)
            self.assertFalse(published[1][1]["scene_failed"])
            self.assertEqual(publication_threads, [threading.get_ident()] * 2)
            self.assertEqual(service._mesh_generator.calls, 2)
            self.assertTrue(notifier.scenes.empty())
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
                get_page=lambda uid: _page(uid),
            )
            service.config_model = SimpleNamespace(
                display_mode_3d="condition",
                grayscale_enabled=False,
                inactive_object_color="#2468ac",
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
            service._mesh_task_event = threading.Event()
            generations = []
            expected_generation = 0
            expected_identity = None
            delivered = True
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
                    expected_generation += 1
                    expected_identity = MeshSceneIdentity(
                        current_bid[0], tuple(sorted(set(pages))), expected_generation
                    )
                    delivered = False
                    generations.append(expected_generation)
                    identity = service._mesh_generation_identity
                    self.assertEqual(identity, expected_identity)
                elif action == 2:
                    service.cancel_mesh_view_refresh()
                    expected_generation += 1
                    expected_identity = None
                    delivered = True
                    generations.append(expected_generation)
                else:
                    generation = rng.choice(generations)
                    before = len(published)
                    should_publish = bool(
                        expected_identity is not None
                        and generation == expected_generation
                        and not delivered
                    )
                    service._on_scene_ready([], generation, False)
                    self.assertEqual(len(published) - before, int(should_publish))
                    if should_publish:
                        delivered = True
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

    def test_monitor_dialog_controls_forward_exact_values_without_starting_monitor(
        self,
    ):
        service, monitor, _data, operations, notifier = _service(
            "local.mdb", DatabaseBackend.ACCESS
        )
        parent = object()
        service.set_message_parent(parent)
        service.set_update_dialog_active(True)
        service.set_update_dialog_active(False)
        service.set_message_parent(None)
        self.assertEqual(monitor.message_parents, [parent, None])
        self.assertEqual(monitor.dialog_states, [True, False])
        self.assertEqual((monitor.start_calls, monitor.stop_calls), (0, 0))
        self.assertEqual(operations.reloads, [])
        self.assertEqual(notifier.refreshes, [])

    def test_repeated_monitor_start_keeps_current_subscription(self):
        service, monitor, _data, operations, notifier = _service(
            "local.mdb", DatabaseBackend.ACCESS
        )
        service.start_database_monitoring()
        callback = monitor.callback
        service.start_database_monitoring()
        self.assertIs(monitor.callback, callback)
        self.assertEqual((monitor.start_calls, monitor.stop_calls), (1, 0))
        callback()
        service._callback_bridge.run_pending()
        self.assertEqual(operations.reloads, ["local.mdb"])
        self.assertEqual(notifier.refreshes, ["local.mdb"])

    def test_failed_monitored_reload_does_not_publish_refresh_and_next_change_retries(
        self,
    ):
        service, monitor, _data, operations, notifier = _service(
            "local.mdb", DatabaseBackend.ACCESS
        )
        operations.reload_database = Mock(side_effect=[False, True])
        service.start_database_monitoring()
        monitor.callback()
        service._callback_bridge.run_pending()
        self.assertEqual(notifier.refreshes, [])
        monitor.callback()
        service._callback_bridge.run_pending()
        self.assertEqual(notifier.refreshes, ["local.mdb"])
        self.assertEqual(
            operations.reload_database.call_args_list,
            [unittest.mock.call("local.mdb")] * 2,
        )

    def test_missing_database_or_descriptor_stops_monitor_without_reload(self):
        for locator in ("", "unknown.mdb"):
            with self.subTest(locator=locator):
                service, monitor, _data, operations, notifier = _service(
                    locator, DatabaseBackend.ACCESS, monitoring=True
                )
                service._database_descriptor_registry = _DescriptorRegistry({})
                service.start_database_monitoring()
                self.assertFalse(monitor.monitoring)
                self.assertEqual((monitor.start_calls, monitor.stop_calls), (0, 1))
                self.assertEqual(operations.reloads, [])
                self.assertEqual(notifier.refreshes, [])

    def test_access_monitor_marks_completed_refresh_as_external(self):
        published = []
        service = VisualizationService.__new__(VisualizationService)
        service.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        service._on_full_refresh_ready("same-path.mdb")
        self.assertEqual(
            published,
            [
                (
                    AppEvents.DATABASE_REFRESHED,
                    {"file_path": "same-path.mdb", "external_change": True},
                )
            ],
        )

    def test_queued_access_callback_cannot_reach_same_path_reopen(self):
        locator = "C:/projects/same-path.mdb"
        service, monitor, _data, operations, notifier = _service(
            locator, DatabaseBackend.ACCESS
        )
        service.start_database_monitoring()
        monitor.callback()
        service.stop_database_monitoring()
        service.start_database_monitoring()
        service._callback_bridge.run_pending()
        self.assertEqual(operations.reloads, [])
        self.assertEqual(notifier.refreshes, [])

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
