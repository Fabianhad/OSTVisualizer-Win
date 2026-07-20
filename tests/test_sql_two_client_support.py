import unittest
from tests.sql_two_client_support import (
    ClientProcessConfiguration,
    ClientProcessResult,
    ClientScenario,
    TwoClientProcessHarness,
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
        self.assertNotEqual(first.process_id, second.process_id)
        self.assertNotEqual(first.stack_identity, second.stack_identity)

    def test_child_exception_is_returned_to_parent(self):
        result = TwoClientProcessHarness(timeout_seconds=10).run(
            ClientProcessConfiguration("first", ClientScenario.FAIL),
            ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
        )
        with self.assertRaisesRegex(RuntimeError, "deliberate child failure"):
            result.assert_clean()

    def test_barrier_timeout_is_reported_without_hanging(self):
        result = TwoClientProcessHarness(timeout_seconds=2).run(
            ClientProcessConfiguration("first", ClientScenario.FAIL_BEFORE_BARRIER),
            ClientProcessConfiguration("second", ClientScenario.FOUNDATION_PROBE),
        )
        with self.assertRaisesRegex(
            RuntimeError, "deliberate pre-barrier failure|BrokenBarrierError"
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
        from tests.sql_two_client_support import TwoClientRunResult

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


if __name__ == "__main__":
    unittest.main()
