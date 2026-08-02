import threading
import time
import unittest
from types import SimpleNamespace
from ost_visualizer.application.services.navigation_load_service import (
    NavigationLoadService,
    NavigationLoadState,
)
from ost_visualizer.application.services.project_operations_service import (
    ProjectOperationsService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1


class _Registry:
    def __init__(self, descriptors):
        self._descriptors = {item.database_id: item for item in descriptors}

    def resolve(self, locator):
        return self._descriptors.get(locator)


class _QueuedDispatcher:
    def __init__(self):
        self.calls = []
        self.ready = threading.Event()

    def dispatch(self, callback, payload):
        self.calls.append((callback, payload))
        self.ready.set()

    def drain(self):
        calls = list(self.calls)
        self.calls.clear()
        self.ready.clear()
        for callback, payload in calls:
            callback(payload)


def _sql_descriptor(database="OSTV_IT_NAVIGATION"):
    return DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database=database),
        schema_version=SQL_SCHEMA_V1.version,
    )


class NavigationLoadServiceTests(unittest.TestCase):
    def setUp(self):
        self.descriptor = _sql_descriptor()
        self.dispatcher = _QueuedDispatcher()
        self.service = NavigationLoadService(
            _Registry([self.descriptor]), self.dispatcher
        )

    def tearDown(self):
        self.service.cleanup()

    def test_project_operations_has_no_synchronous_bid_navigation_entry_point(self):
        self.assertFalse(hasattr(ProjectOperationsService, "load_bid"))

    def test_sql_read_returns_promptly_and_runs_off_calling_thread(self):
        calling_thread = threading.get_ident()
        release = threading.Event()
        worker_threads = []
        completed = []
        started = time.perf_counter()
        state = self.service.submit(
            self.descriptor.database_id,
            "bid-1",
            lambda: (worker_threads.append(threading.get_ident()), release.wait(), 7)[
                2
            ],
            completed.append,
        )
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.05)
        self.assertEqual(state.state, NavigationLoadState.LOADING)
        release.set()
        self.assertTrue(self.dispatcher.ready.wait(1.0))
        self.assertEqual(completed, [])
        self.dispatcher.drain()
        self.assertEqual(worker_threads and worker_threads[0] != calling_thread, True)
        self.assertEqual(completed[0].value, 7)
        self.assertEqual(completed[0].state, NavigationLoadState.READY)

    def test_stale_completion_cannot_replace_newer_request(self):
        first_release = threading.Event()
        completed = []
        self.service.submit(
            self.descriptor.database_id,
            "bid-a",
            lambda: (first_release.wait(), "a")[1],
            completed.append,
        )
        self.service.submit(
            self.descriptor.database_id,
            "bid-b",
            lambda: "b",
            completed.append,
        )
        first_release.set()
        self.assertTrue(self.dispatcher.ready.wait(1.0))
        self.dispatcher.drain()
        deadline = time.monotonic() + 1.0
        while not self.dispatcher.calls and time.monotonic() < deadline:
            time.sleep(0.005)
        self.dispatcher.drain()
        self.assertEqual([result.value for result in completed], ["b"])

    def test_rapid_a_b_a_discards_the_superseded_queued_read(self):
        release = threading.Event()
        first_started = threading.Event()
        executed = []
        completed = []
        self.service.submit(
            self.descriptor.database_id,
            "a",
            lambda: (
                executed.append("a1"),
                first_started.set(),
                release.wait(),
                "a1",
            )[3],
            completed.append,
        )
        self.assertTrue(first_started.wait(1.0))
        self.service.submit(
            self.descriptor.database_id,
            "b",
            lambda: (executed.append("b"), "b")[1],
            completed.append,
        )
        self.service.submit(
            self.descriptor.database_id,
            "a",
            lambda: (executed.append("a2"), "a2")[1],
            completed.append,
        )
        release.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self.dispatcher.calls:
                self.dispatcher.drain()
            if completed:
                break
            time.sleep(0.005)
        self.assertEqual(executed, ["a1", "a2"])
        self.assertEqual([result.value for result in completed], ["a2"])

    def test_cancelled_read_does_not_touch_destroyed_projection(self):
        release = threading.Event()
        started = threading.Event()
        completed = []
        self.service.submit(
            self.descriptor.database_id,
            "bid-1",
            lambda: (started.set(), release.wait(), "done")[2],
            completed.append,
        )
        self.assertTrue(started.wait(1.0))
        self.service.cancel(self.descriptor.database_id)
        release.set()
        time.sleep(0.05)
        self.assertEqual(completed, [])
        self.assertEqual(self.dispatcher.calls, [])
        self.assertEqual(self.service.state().state, NavigationLoadState.CANCELLED)

    def test_failure_is_terminal_and_user_safe(self):
        completed = []

        def fail():
            raise OSError("connection unavailable")

        self.service.submit(
            self.descriptor.database_id,
            "bid-1",
            fail,
            completed.append,
        )
        self.assertTrue(self.dispatcher.ready.wait(1.0))
        self.dispatcher.drain()
        self.assertEqual(completed[0].state, NavigationLoadState.FAILED)
        self.assertEqual(completed[0].message, "connection unavailable")
        terminal = self.service.state()
        self.assertEqual(terminal.state, NavigationLoadState.FAILED)
        self.assertEqual(terminal.database_id, self.descriptor.database_id)
        self.assertEqual(terminal.bid_uid, "bid-1")

    def test_mdb_bid_load_uses_same_projection_contract_without_fake_async(self):
        mdb_descriptor = DatabaseDescriptor.for_access("C:/temporary/navigation.mdb")
        service = NavigationLoadService(_Registry([mdb_descriptor]), self.dispatcher)
        try:
            calls = []

            class _UseCase:
                def execute(self, requested):
                    calls.append(("execute", threading.get_ident(), requested))
                    return True

                def prepare(self, _requested):
                    raise AssertionError("MDB navigation must remain immediate")

                def apply_prepared(self, _requested, _result):
                    raise AssertionError("MDB navigation must remain immediate")

            operations = ProjectOperationsService(SimpleNamespace(), service)
            operations.configure_use_cases(
                SimpleNamespace(),
                lambda _path=None: True,
                _UseCase(),
                lambda _path=None: True,
            )
            completed = []
            bid_ref = BidRef(mdb_descriptor.database_id, "17")
            self.assertFalse(
                operations.request_load_bid(
                    bid_ref, lambda *args: completed.append(args)
                )
            )
            self.assertEqual(calls, [("execute", threading.get_ident(), bid_ref)])
            self.assertEqual(completed, [(True, "")])
            self.assertEqual(self.dispatcher.calls, [])
        finally:
            service.cleanup()

    def test_project_operations_applies_prepared_bid_only_on_dispatch_thread(self):
        calling_thread = threading.get_ident()
        thread_ids = []
        bid_ref = BidRef(self.descriptor.database_id, "17")

        class _UseCase:
            def prepare(self, requested):
                thread_ids.append(("prepare", threading.get_ident(), requested))
                return BidLoadResult()

            def apply_prepared(self, requested, result):
                thread_ids.append(("apply", threading.get_ident(), requested, result))
                return True

            def execute(self, _requested):
                raise AssertionError("SQL navigation must not execute synchronously")

        operations = ProjectOperationsService(SimpleNamespace(), self.service)
        operations.configure_use_cases(
            SimpleNamespace(),
            lambda _path=None: True,
            _UseCase(),
            lambda _path=None: True,
        )
        completed = []
        self.assertTrue(
            operations.request_load_bid(bid_ref, lambda *args: completed.append(args))
        )
        self.assertTrue(self.dispatcher.ready.wait(1.0))
        self.dispatcher.drain()
        self.assertEqual(thread_ids[0][0], "prepare")
        self.assertNotEqual(thread_ids[0][1], calling_thread)
        self.assertEqual(thread_ids[1][0:2], ("apply", calling_thread))
        self.assertEqual(completed, [(True, "")])


if __name__ == "__main__":
    unittest.main()
