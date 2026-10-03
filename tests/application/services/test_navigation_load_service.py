import logging
import queue
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch
from ost_visualizer.application.services.navigation_load_service import (
    NavigationLoadResult,
    NavigationLoadService,
    NavigationLoadState,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)


class _Registry:
    def __init__(self, descriptors):
        self.descriptors = {item.database_id: item for item in descriptors}

    def resolve(self, locator):
        return self.descriptors.get(locator)


class _QueuedDispatcher:
    def __init__(self):
        self.calls = queue.Queue()

    def dispatch(self, callback, payload):
        self.calls.put((callback, payload))

    def take(self):
        return self.calls.get(timeout=1.0)

    def complete_one(self):
        callback, payload = self.take()
        callback(payload)


def _sql_descriptor(database="OSTV_IT_NAVIGATION"):
    return DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database=database),
        schema_version=1,
    )


class _NavigationFixture(unittest.TestCase):
    def setUp(self):
        self.descriptor = _sql_descriptor()
        self.dispatcher = _QueuedDispatcher()
        self.registry = _Registry([self.descriptor])
        self.releases = []
        self.service = NavigationLoadService(self.registry, self.dispatcher)
        self.addCleanup(self._close)

    def _close(self):
        self.service.cleanup()
        for release in self.releases:
            release.set()
        self.service._thread.join(1.0)
        self.assertFalse(self.service._thread.is_alive(), "navigation worker leaked")

    def _blocked_work(self, value, executed=None):
        started = threading.Event()
        release = threading.Event()
        self.releases.append(release)

        def work():
            if executed is not None:
                executed.append(value)
            started.set()
            if not release.wait(2.0):
                raise TimeoutError("test did not release navigation work")
            return value

        return work, started, release


class NavigationLoadServiceTests(_NavigationFixture):
    def test_sql_read_returns_promptly_and_runs_off_calling_thread(self):
        calling_thread = threading.get_ident()
        work, started, release = self._blocked_work(7)
        worker_threads = []
        completed = []
        completion_threads = []

        def read():
            worker_threads.append(threading.get_ident())
            return work()

        def complete(result):
            completion_threads.append(threading.get_ident())
            completed.append(result)

        self.assertEqual(
            self.service.state(),
            NavigationLoadResult("", 0, "", "", NavigationLoadState.EMPTY),
        )
        state = self.service.submit(
            self.descriptor.database_id, "bid-1", read, complete
        )
        self.assertTrue(started.wait(1.0))
        self.assertFalse(
            release.is_set()
        )  # Submission returned while read is still blocked.
        self.assertEqual(self.service.state(), state)
        self.assertEqual(state.state, NavigationLoadState.LOADING)
        self.assertEqual(
            (state.database_id, state.bid_uid), (self.descriptor.database_id, "bid-1")
        )
        self.assertTrue(state.request_id)
        self.assertEqual(state.generation, 1)
        self.assertEqual(completed, [])
        release.set()
        callback, payload = self.dispatcher.take()
        self.assertEqual(completed, [])
        self.assertEqual(self.service.state(), state)
        callback(payload)
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], calling_thread)
        self.assertEqual(completion_threads, [calling_thread])
        self.assertEqual(
            completed, [replace(state, state=NavigationLoadState.READY, value=7)]
        )
        self.assertEqual(
            self.service.state(), replace(state, state=NavigationLoadState.READY)
        )
        self.assertTrue(self.dispatcher.calls.empty())

    def test_stale_completion_cannot_replace_newer_request(self):
        first, started, release = self._blocked_work("a")
        completed = []
        first_state = self.service.submit(
            self.descriptor.database_id, "bid-a", first, completed.append
        )
        self.assertTrue(started.wait(1.0))
        second = self.service.submit(
            self.descriptor.database_id, "bid-b", lambda: "b", completed.append
        )
        self.assertNotEqual(first_state.request_id, second.request_id)
        self.assertGreater(second.generation, first_state.generation)
        release.set()
        self.dispatcher.complete_one()
        self.assertEqual(
            completed, [replace(second, state=NavigationLoadState.READY, value="b")]
        )
        self.assertTrue(self.dispatcher.calls.empty())

    def test_rapid_a_b_a_discards_the_superseded_queued_read(self):
        executed = []
        completed = []
        first, started, release = self._blocked_work("a1", executed)
        self.service.submit(self.descriptor.database_id, "a", first, completed.append)
        self.assertTrue(started.wait(1.0))
        self.service.submit(
            self.descriptor.database_id,
            "b",
            lambda: executed.append("b"),
            completed.append,
        )

        def latest():
            executed.append("a2")
            return "a2"

        state = self.service.submit(
            self.descriptor.database_id, "a", latest, completed.append
        )
        release.set()
        self.dispatcher.complete_one()
        self.assertEqual(executed, ["a1", "a2"])
        self.assertEqual(
            completed, [replace(state, state=NavigationLoadState.READY, value="a2")]
        )
        self.assertTrue(self.dispatcher.calls.empty())

    def test_cancelled_read_allows_retry_without_old_completion(self):
        completed = []
        work, started, release = self._blocked_work("done")
        state = self.service.submit(
            self.descriptor.database_id, "bid-1", work, completed.append
        )
        self.assertTrue(started.wait(1.0))
        self.service.cancel(self.descriptor.database_id)
        self.assertEqual(
            self.service.state(),
            NavigationLoadResult(
                "", state.generation + 1, "", "", NavigationLoadState.CANCELLED
            ),
        )
        release.set()
        # A later worker request proves the cancelled one passed its dispatch check.
        latest = self.service.submit(
            self.descriptor.database_id, "bid-2", lambda: "next", completed.append
        )
        self.dispatcher.complete_one()
        self.assertEqual(
            completed, [replace(latest, state=NavigationLoadState.READY, value="next")]
        )
        self.assertTrue(self.dispatcher.calls.empty())

    def test_cancel_after_cleanup_cannot_consume_worker_stop_signal(self):
        completed = []
        work, started, release = self._blocked_work("done")
        self.service.submit(
            self.descriptor.database_id, "bid-1", work, completed.append
        )
        self.assertTrue(started.wait(1.0))
        self.service.cleanup()
        stopped = self.service.state()
        self.service.cancel()
        self.assertEqual(self.service.state(), stopped)
        release.set()
        self.service._thread.join(1.0)
        self.assertFalse(self.service._thread.is_alive())
        self.assertEqual(completed, [])
        self.assertTrue(self.dispatcher.calls.empty())

    def test_repeated_cleanup_stops_idle_worker_once(self):
        self.service.cleanup()
        stopped = self.service.state()
        self.service.cleanup()
        self.service._thread.join(1.0)
        self.assertFalse(self.service._thread.is_alive())
        self.assertEqual(self.service.state(), stopped)
        self.assertEqual(stopped.state, NavigationLoadState.CANCELLED)
        with self.assertRaisesRegex(RuntimeError, "loading has stopped"):
            self.service.submit(
                self.descriptor.database_id,
                "new",
                lambda: self.fail("closed worker ran"),
                self.fail,
            )
        self.assertTrue(self.dispatcher.calls.empty())

    def test_failure_is_terminal_and_user_safe(self):
        completed = []

        def fail():
            raise OSError("connection unavailable")

        with self.assertLogs(
            "ost_visualizer.application.services.navigation_load_service",
            level="WARNING",
        ):
            state = self.service.submit(
                self.descriptor.database_id, "bid-1", fail, completed.append
            )
            self.dispatcher.complete_one()
        self.assertEqual(
            completed,
            [
                replace(
                    state,
                    state=NavigationLoadState.FAILED,
                    message="connection unavailable",
                )
            ],
        )
        self.assertEqual(
            self.service.state(), replace(state, state=NavigationLoadState.FAILED)
        )
        retry = self.service.submit(
            self.descriptor.database_id, "bid-1", lambda: 8, completed.append
        )
        self.dispatcher.complete_one()
        self.assertEqual(
            completed[-1], replace(retry, state=NavigationLoadState.READY, value=8)
        )
        self.assertEqual(len(completed), 2)
        self.assertTrue(self.dispatcher.calls.empty())

    def test_bridged_stale_result_cannot_project_same_uid_in_new_database(self):
        completed = []
        self.service.submit(
            self.descriptor.database_id, "same-bid", lambda: "old", completed.append
        )
        old_callback, old_payload = self.dispatcher.take()
        new_database = _sql_descriptor("other").database_id
        new = self.service.submit(
            new_database, "same-bid", lambda: "new", completed.append
        )
        new_callback, new_payload = self.dispatcher.take()
        old_callback(old_payload)
        self.assertEqual(completed, [])
        self.assertEqual(self.service.state(), new)
        new_callback(new_payload)
        old_callback(old_payload)
        self.assertEqual(
            completed, [replace(new, state=NavigationLoadState.READY, value="new")]
        )
        self.assertEqual(
            self.service.state(), replace(new, state=NavigationLoadState.READY)
        )

    def test_cancel_and_cleanup_reject_already_bridged_result(self):
        for terminal in (self.service.cancel, self.service.cleanup):
            with self.subTest(terminal=terminal.__name__):
                completed = []
                self.service.submit(
                    self.descriptor.database_id, "bid", lambda: 1, completed.append
                )
                callback, payload = self.dispatcher.take()
                terminal()
                stopped = self.service.state()
                callback(payload)
                self.assertEqual(completed, [])
                self.assertEqual(self.service.state(), stopped)

    def test_other_database_cancel_preserves_pending_request(self):
        completed = []
        state = self.service.submit(
            self.descriptor.database_id, "bid", lambda: 1, completed.append
        )
        callback, payload = self.dispatcher.take()
        self.service.cancel("other-database")
        self.assertEqual(self.service.state(), state)
        callback(payload)
        self.assertEqual(
            completed, [replace(state, state=NavigationLoadState.READY, value=1)]
        )

    def test_backend_and_invalid_submission_contracts(self):
        access = DatabaseDescriptor.for_access("test.mdb")
        self.registry.descriptors[access.database_id] = access
        self.assertTrue(self.service.uses_background_reads(self.descriptor.database_id))
        self.assertFalse(self.service.uses_background_reads(access.database_id))
        self.assertFalse(self.service.uses_background_reads("missing"))
        original = self.service.state()
        with self.assertRaisesRegex(ValueError, "requires a database ID"):
            self.service.submit(
                "", "bid", lambda: self.fail("invalid request ran"), self.fail
            )
        self.assertEqual(self.service.state(), original)
        self.assertTrue(self.dispatcher.calls.empty())


class NavigationLoadServiceBoundaryTests(_NavigationFixture):
    def test_published_results_are_immutable_snapshots(self):
        completed = []
        state = self.service.submit(
            self.descriptor.database_id, "bid", lambda: [1], completed.append
        )
        self.dispatcher.complete_one()
        for result in (state, self.service.state(), completed[0]):
            self.assertEqual(result.message, "")
            with self.assertRaises(FrozenInstanceError):
                result.state = NavigationLoadState.FAILED
            with self.assertRaises(FrozenInstanceError):
                result.value = None

    def test_worker_slot_is_a_single_daemon_latest_wins_queue(self):
        work, started, _release = self._blocked_work("a")
        self.service.submit(self.descriptor.database_id, "a", work, lambda _r: None)
        self.assertTrue(started.wait(1.0))
        for index in range(5):
            self.service.submit(
                self.descriptor.database_id, f"b{index}", lambda: 0, lambda _r: None
            )
        self.assertEqual(self.service._requests.maxsize, 1)
        self.assertEqual(self.service._requests.qsize(), 1)
        self.assertTrue(self.service._thread.daemon)
        self.assertEqual(self.service._thread.name, "NavigationRead")

    def test_state_labels_are_stable_diagnostic_values(self):
        self.assertEqual(
            {state.name: state.value for state in NavigationLoadState},
            {
                "EMPTY": "empty",
                "LOADING": "loading",
                "READY": "ready",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            },
        )

    def test_missing_bid_uid_is_normalized_to_empty_text(self):
        completed = []
        state = self.service.submit(
            self.descriptor.database_id, None, lambda: 1, completed.append
        )
        self.assertEqual(state.bid_uid, "")
        self.assertEqual(self.service.state().bid_uid, "")
        self.dispatcher.complete_one()
        self.assertEqual(completed[0].bid_uid, "")

    def test_cancel_discards_the_queued_read_before_it_can_run(self):
        executed = []
        completed = []
        first, started, release = self._blocked_work("first", executed)
        self.service.submit(self.descriptor.database_id, "a", first, completed.append)
        self.assertTrue(started.wait(1.0))
        self.service.submit(
            self.descriptor.database_id,
            "b",
            lambda: executed.append("queued") or "queued",
            completed.append,
        )
        self.assertEqual(self.service._requests.qsize(), 1)
        self.service.cancel(self.descriptor.database_id)
        self.assertEqual(self.service._requests.qsize(), 0)
        release.set()
        latest = self.service.submit(
            self.descriptor.database_id, "c", lambda: "c", completed.append
        )
        self.dispatcher.complete_one()
        self.assertEqual(executed, ["first"])
        self.assertEqual(
            completed, [replace(latest, state=NavigationLoadState.READY, value="c")]
        )

    def test_cleanup_invalidates_state_and_discards_queued_read_so_worker_stops(self):
        executed = []
        first, started, release = self._blocked_work("first", executed)
        before = self.service.submit(
            self.descriptor.database_id, "a", first, lambda _r: None
        )
        self.assertTrue(started.wait(1.0))
        self.service.submit(
            self.descriptor.database_id,
            "b",
            lambda: executed.append("queued"),
            lambda _r: None,
        )
        queued_generation = self.service.state().generation
        with patch.object(threading, "excepthook") as excepthook:
            self.service.cleanup()
            self.assertEqual(
                self.service.state(),
                NavigationLoadResult(
                    "", queued_generation + 1, "", "", NavigationLoadState.CANCELLED
                ),
            )
            self.assertGreater(queued_generation, before.generation)
            release.set()
            self.service._thread.join(2.0)
            self.assertFalse(self.service._thread.is_alive())
        excepthook.assert_not_called()
        self.assertEqual(executed, ["first"])
        self.assertTrue(self.dispatcher.calls.empty())

    def test_failure_without_message_names_the_exception_type_and_logs_traceback(self):
        completed = []

        def fail():
            raise RuntimeError()

        with self.assertLogs(
            "ost_visualizer.application.services.navigation_load_service",
            level="WARNING",
        ) as logged:
            self.service.submit(
                self.descriptor.database_id, "bid", fail, completed.append
            )
            self.dispatcher.complete_one()
        self.assertEqual(completed[0].state, NavigationLoadState.FAILED)
        self.assertEqual(completed[0].message, "RuntimeError")
        self.assertIs(logged.records[0].exc_info[0], RuntimeError)
        self.assertIn(self.descriptor.database_id, logged.output[0])

    def test_injected_logger_receives_read_failures(self):
        logger = logging.getLogger("test.navigation.injected")
        service = NavigationLoadService(self.registry, self.dispatcher, logger)
        self.addCleanup(service.cleanup)

        def fail():
            raise OSError("down")

        with self.assertLogs(logger, level="WARNING"):
            service.submit(self.descriptor.database_id, "bid", fail, lambda _r: None)
            self.dispatcher.complete_one()
