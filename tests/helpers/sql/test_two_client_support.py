import os
import queue
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
import tests.helpers.sql.two_client_support as two_client_support
from tests.helpers.sql.two_client_support import (
    ClientProcessConfiguration,
    ClientProcessResult,
    ClientScenario,
    TwoClientProcessHarness,
    TwoClientRunResult,
)


class SqlTwoClientSupportTests(unittest.TestCase):
    def test_harness_uses_windows_spawn_and_independent_processes(self):
        harness = TwoClientProcessHarness(timeout_seconds=10)
        self.assertEqual(harness.start_method, "spawn")
        result = harness.run(
            ClientProcessConfiguration("first", ClientScenario.FOUNDATION_PROBE),
            ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
        )
        result.assert_clean()
        first, second = result.clients
        self.assertEqual((first.client_id, second.client_id), ("first", "second"))
        self.assertNotEqual(first.process_id, second.process_id)
        self.assertNotIn(os.getpid(), (first.process_id, second.process_id))
        self.assertNotEqual(first.stack_identity, second.stack_identity)

    def test_child_exception_is_returned_to_parent(self):
        result = TwoClientProcessHarness(timeout_seconds=10).run(
            ClientProcessConfiguration("first", ClientScenario.FAIL),
            ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
        )
        self.assertEqual(
            result.clients[0].error, "RuntimeError: deliberate child failure"
        )
        self.assertEqual(result.clients[1].error, "")
        with self.assertRaisesRegex(RuntimeError, "deliberate child failure"):
            result.assert_clean()

    def test_barrier_timeout_is_reported_without_hanging(self):
        result = TwoClientProcessHarness(timeout_seconds=2).run(
            ClientProcessConfiguration("first", ClientScenario.FAIL_BEFORE_BARRIER),
            ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
        )
        first, second = result.clients
        self.assertEqual(first.error, "RuntimeError: deliberate pre-barrier failure")
        self.assertTrue(second.error.startswith("BrokenBarrierError"))
        with self.assertRaisesRegex(
            RuntimeError,
            "SQL client first failed: RuntimeError: deliberate pre-barrier",
        ):
            result.assert_clean()

    def test_result_payload_is_exact_and_bounded(self):
        original = ClientProcessResult("client", 10, "stack")
        self.assertEqual(
            ClientProcessResult.from_payload(original.to_payload()), original
        )
        payload = original.to_payload()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            ClientProcessResult.from_payload(payload)
        with self.assertRaisesRegex(ValueError, "bounded result size"):
            ClientProcessResult("x" * 513, 10, "stack").validate()

    def test_cleanup_failure_is_a_hard_failure(self):
        first = ClientProcessResult(
            "first", 10, "stack-1", cleanup_errors=("session remained",)
        )
        second = ClientProcessResult("second", 11, "stack-2")
        with self.assertRaisesRegex(RuntimeError, "clean up completely"):
            TwoClientRunResult((first, second)).assert_clean()

    def test_second_process_start_failure_cleans_the_first_process_and_queue(self):
        class _Process:
            def __init__(self, fail_start=False):
                self.fail_start = fail_start
                self.started = False
                self.alive = False
                self.join_count = 0
                self.terminated = False

            def start(self):
                if self.fail_start:
                    raise RuntimeError("second process could not start")
                self.started = True
                self.alive = True

            def join(self, _timeout):
                self.join_count += 1

            def is_alive(self):
                return self.alive

            def terminate(self):
                self.terminated = True
                self.alive = False

        class _Queue:
            def __init__(self):
                self.closed = False
                self.joined = False

            def close(self):
                self.closed = True

            def join_thread(self):
                self.joined = True

        first_process = _Process()
        second_process = _Process(fail_start=True)
        result_queue = _Queue()
        harness = TwoClientProcessHarness(timeout_seconds=1)
        harness._context = type(
            "Context",
            (),
            {
                "Barrier": lambda _self, *_args, **_kwargs: object(),
                "Queue": lambda _self, **_kwargs: result_queue,
            },
        )()
        processes = iter((first_process, second_process))
        harness._process = lambda *_args: next(processes)
        with self.assertRaisesRegex(RuntimeError, "second process could not start"):
            harness.run(
                ClientProcessConfiguration("first", ClientScenario.FOUNDATION_PROBE),
                ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
            )
        self.assertTrue(first_process.terminated)
        self.assertEqual(first_process.join_count, 1)
        self.assertTrue(result_queue.closed)
        self.assertTrue(result_queue.joined)


class FakeBarrier:
    def __init__(self):
        self.waited = 0
        self.aborted = False

    def wait(self):
        self.waited += 1

    def abort(self):
        self.aborted = True


class FakeQueue:
    def __init__(self, payloads=(), empty=False):
        self.payloads = list(payloads)
        self.empty = empty
        self.put_payloads = []
        self.closed = False
        self.joined = False
        self.get_timeouts = []

    def put(self, payload):
        self.put_payloads.append(payload)

    def get(self, timeout):
        self.get_timeouts.append(timeout)
        if self.empty or not self.payloads:
            raise queue.Empty()
        return self.payloads.pop(0)

    def close(self):
        self.closed = True

    def join_thread(self):
        self.joined = True


class FakeProcess:
    def __init__(self, stays_alive=False):
        self.stays_alive = stays_alive
        self.alive = False
        self.joins = []
        self.terminated = False

    def start(self):
        self.alive = True

    def join(self, timeout):
        self.joins.append(timeout)
        if not self.stays_alive:
            self.alive = False

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False


def _harness_with(processes, result_queue, timeout=3):
    harness = TwoClientProcessHarness(timeout_seconds=timeout)
    harness._context = type(
        "Context",
        (),
        {
            "Barrier": lambda _self, *_args, **_kwargs: FakeBarrier(),
            "Queue": lambda _self, **_kwargs: result_queue,
        },
    )()
    iterator = iter(processes)
    harness._process = lambda *_args: next(iterator)
    return harness


def _payload(client_id, **changes):
    result = ClientProcessResult(client_id, 100, f"stack-{client_id}", **changes)
    return result.to_payload()


class SqlTwoClientHarnessContractTests(unittest.TestCase):
    """Harness bookkeeping verified with fake processes (no spawn, no SQL)."""

    def configurations(self, first="first", second="second"):
        return (
            ClientProcessConfiguration(first, ClientScenario.FOUNDATION_PROBE),
            ClientProcessConfiguration(second, ClientScenario.FOUNDATION_PROBE),
        )

    def test_timeout_must_be_positive_and_at_most_two_minutes(self):
        for timeout in (0, -1, 120.5, 1000):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "between 0 and 120"):
                    TwoClientProcessHarness(timeout_seconds=timeout)
        self.assertEqual(
            TwoClientProcessHarness(timeout_seconds=120).start_method, "spawn"
        )
        TwoClientProcessHarness(timeout_seconds=0.5)

    def test_invalid_configurations_are_rejected_before_any_process_exists(self):
        harness = TwoClientProcessHarness(timeout_seconds=1)
        harness._process = lambda *_args: self.fail("no process may be created")
        with self.assertRaisesRegex(ValueError, "distinct client identities"):
            harness.run(*self.configurations("same", "same"))
        with self.assertRaisesRegex(ValueError, "bounded result size"):
            harness.run(*self.configurations("x" * 513, "second"))
        with self.assertRaisesRegex(ValueError, "bounded result size"):
            harness.run(*self.configurations("first", "y" * 513))

    def test_results_are_returned_in_the_order_of_the_requested_clients(self):
        result_queue = FakeQueue([_payload("second"), _payload("first")])
        processes = [FakeProcess(), FakeProcess()]
        harness = _harness_with(processes, result_queue)
        result = harness.run(*self.configurations())
        self.assertEqual([c.client_id for c in result.clients], ["first", "second"])
        self.assertEqual(result_queue.get_timeouts, [3, 3])
        self.assertEqual([p.joins for p in processes], [[3], [3]])
        self.assertFalse(any(p.terminated for p in processes))
        self.assertTrue(result_queue.closed and result_queue.joined)

    def test_results_with_unexpected_identities_are_refused(self):
        for payloads in (
            [_payload("first"), _payload("intruder")],
            [_payload("first"), _payload("first")],
        ):
            with self.subTest(ids=[p["client_id"] for p in payloads]):
                harness = _harness_with(
                    [FakeProcess(), FakeProcess()], FakeQueue(payloads)
                )
                with self.assertRaisesRegex(RuntimeError, "invalid identities"):
                    harness.run(*self.configurations())

    def test_malformed_child_payloads_fail_the_run(self):
        bad = _payload("second")
        bad["extra"] = 1
        harness = _harness_with(
            [FakeProcess(), FakeProcess()], FakeQueue([_payload("first"), bad])
        )
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            harness.run(*self.configurations())

    def test_a_silent_child_times_out_and_resources_are_released(self):
        result_queue = FakeQueue(empty=True)
        processes = [FakeProcess(), FakeProcess()]
        harness = _harness_with(processes, result_queue)
        with self.assertRaisesRegex(
            RuntimeError, "Timed out waiting for a spawned SQL client"
        ):
            harness.run(*self.configurations())
        self.assertTrue(result_queue.closed and result_queue.joined)
        self.assertEqual([p.joins for p in processes], [[3], [3]])

    def test_a_child_that_ignores_the_timeout_is_terminated(self):
        result_queue = FakeQueue([_payload("first"), _payload("second")])
        stubborn = FakeProcess(stays_alive=True)
        processes = [FakeProcess(), stubborn]
        harness = _harness_with(processes, result_queue)
        with self.assertRaisesRegex(RuntimeError, "did not exit within the timeout"):
            harness.run(*self.configurations())
        self.assertTrue(stubborn.terminated)
        self.assertFalse(processes[0].terminated)
        self.assertTrue(result_queue.closed and result_queue.joined)

    def test_run_result_reports_child_errors_before_cleanup_problems(self):
        failed = ClientProcessResult(
            "first", 1, "s1", cleanup_errors=("leaked",), error="ValueError: boom"
        )
        clean = ClientProcessResult("second", 2, "s2")
        with self.assertRaisesRegex(
            RuntimeError, "SQL client first failed: ValueError: boom"
        ):
            TwoClientRunResult((failed, clean)).assert_clean()
        leaked = ClientProcessResult(
            "second", 2, "s2", remaining_resources=("session 51",)
        )
        with self.assertRaisesRegex(RuntimeError, "second did not clean up completely"):
            TwoClientRunResult(
                (ClientProcessResult("first", 1, "s1"), leaked)
            ).assert_clean()
        TwoClientRunResult(
            (ClientProcessResult("first", 1, "s1"), clean)
        ).assert_clean()


class SqlTwoClientChildEntryTests(unittest.TestCase):
    """The spawned-process entry point, called in-process with fakes."""

    def run_entry(self, scenario, probe=None):
        barrier, results = FakeBarrier(), FakeQueue()
        configuration = ClientProcessConfiguration("child", scenario)
        with patch.object(
            two_client_support,
            "_construct_independent_application_stack",
            probe or (lambda: None),
        ):
            two_client_support._client_process_entry(configuration, barrier, results)
        (payload,) = results.put_payloads
        return barrier, ClientProcessResult.from_payload(payload)

    def test_probe_runs_after_the_barrier_and_reports_this_process(self):
        calls = []
        barrier, result = self.run_entry(
            ClientScenario.FOUNDATION_PROBE, probe=lambda: calls.append("probe")
        )
        self.assertEqual(calls, ["probe"])
        self.assertEqual(barrier.waited, 1)
        self.assertFalse(barrier.aborted)
        self.assertEqual((result.client_id, result.process_id), ("child", os.getpid()))
        self.assertEqual(result.error, "")
        self.assertEqual(result.cleanup_errors, ())
        self.assertEqual(str(uuid.UUID(result.stack_identity)), result.stack_identity)

    def test_failure_scenarios_become_error_results_not_exceptions(self):
        barrier, result = self.run_entry(ClientScenario.FAIL)
        self.assertEqual(result.error, "RuntimeError: deliberate child failure")
        self.assertEqual(barrier.waited, 1)
        barrier, result = self.run_entry(ClientScenario.FAIL_BEFORE_BARRIER)
        self.assertEqual(result.error, "RuntimeError: deliberate pre-barrier failure")
        self.assertTrue(barrier.aborted)
        self.assertEqual(barrier.waited, 0)

    def test_stack_construction_errors_are_reported_and_truncated(self):
        def explode():
            raise ValueError("x" * 2000)

        _, result = self.run_entry(ClientScenario.FOUNDATION_PROBE, probe=explode)
        self.assertTrue(result.error.startswith("ValueError: xxx"))
        self.assertEqual(len(result.error), 512)

    def test_payloads_must_have_exactly_the_known_fields_and_bounded_values(self):
        payload = ClientProcessResult("client", 10, "stack").to_payload()
        for field in list(payload):
            with self.subTest(missing=field):
                trimmed = {k: v for k, v in payload.items() if k != field}
                with self.assertRaisesRegex(ValueError, "unexpected fields"):
                    ClientProcessResult.from_payload(trimmed)
        invalid = (
            ClientProcessResult("client", -1, "stack"),
            ClientProcessResult("client", 1, "s" * 513),
            ClientProcessResult("client", 1, "stack", error="e" * 513),
            ClientProcessResult("client", 1, "stack", cleanup_errors=("c",) * 65),
            ClientProcessResult("client", 1, "stack", remaining_resources=("r" * 513,)),
        )
        for result in invalid:
            with self.subTest(result=result):
                with self.assertRaises(ValueError):
                    result.to_payload()
        ClientProcessResult(
            "c" * 512, 0, "s" * 512, ("c",) * 64, ("r",) * 64, "e" * 512
        ).validate()
        with self.assertRaisesRegex(ValueError, "bounded result size"):
            ClientProcessResult.from_payload({**payload, "client_id": "x" * 513})
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            ClientProcessResult.from_payload({**payload, "process_id": -1})

    def test_in_memory_credential_adapter_never_touches_the_credential_manager(self):
        adapter = two_client_support._InMemoryCredentialAdapter()
        self.assertIsNone(adapter.read_password("target"))
        adapter.write_password("target", "user", "secret-value")
        self.assertEqual(adapter.read_password("target"), "secret-value")
        adapter.delete_password("target")
        adapter.delete_password("target")
        self.assertIsNone(adapter.read_password("target"))

    def test_pending_operation_journal_keeps_records_by_operation_id(self):
        journal = two_client_support._PendingOperationJournal()
        record = SimpleNamespace(operation_id="op-1")
        journal.save(record)
        self.assertEqual(journal.list_all(), (record,))
        journal.remove("op-1")
        journal.remove("op-1")
        self.assertEqual(journal.list_all(), ())


if __name__ == "__main__":
    unittest.main()
