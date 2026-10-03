import dataclasses
import gc
import threading
import unittest
import weakref
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
    RemoteProjectionToken,
)
from tests.helpers.lock_guard import guard_mapping


class RemoteProjectionBarrierTests(unittest.TestCase):
    def test_reused_surface_id_does_not_let_old_token_complete_new_work(self):
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database, _generation: True,
            on_complete=results.append,
        )
        first = barrier.register("main")
        first.complete(True)
        self.assertEqual(results, [])
        replacement = barrier.register("main")
        barrier.seal()
        first.complete(False)
        self.assertEqual(results, [])
        replacement.complete(True)
        self.assertEqual(results, [True])
        first.complete(False)
        replacement.complete(False)
        self.assertEqual(results, [True])

    def test_completion_waits_for_every_registered_surface(self) -> None:
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda database_id, generation: (
                database_id == "sql-db" and generation == 4
            ),
            on_complete=lambda success: results.append(success),
        )
        main = barrier.register("main")
        detached = barrier.register("detached:page-1")
        barrier.seal()
        main.complete(True)
        self.assertEqual(results, [])
        detached.complete(True)
        self.assertEqual(results, [True])
        detached.complete(True)
        self.assertEqual(results, [True])

    def test_stale_runtime_cannot_complete_successfully(self) -> None:
        results = []
        current_generation = 4
        checked = []

        def is_current(database, generation):
            checked.append((database, generation))
            return database == "sql-db" and generation == current_generation

        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=is_current,
            on_complete=lambda success: results.append(success),
        )
        main = barrier.register("main")
        self.assertTrue(barrier.is_current())
        current_generation = 5
        barrier.seal()
        main.complete(True)
        self.assertEqual(results, [False])
        self.assertEqual(checked, [("sql-db", 4), ("sql-db", 4)])

    def test_failed_reconciliation_cannot_complete_without_surfaces(self) -> None:
        results = []
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=results.append,
        )
        barrier.fail()
        barrier.seal()
        self.assertEqual(results, [False])

    def test_synchronous_completion_waits_for_seal_and_publishes_once(self):
        for with_surface in (False, True):
            with self.subTest(with_surface=with_surface):
                results = []
                barrier = RemoteProjectionBarrier(
                    database_id="db",
                    runtime_generation=1,
                    is_runtime_current=lambda _db, _generation: True,
                    on_complete=results.append,
                )
                if with_surface:
                    barrier.register("main").complete(True)
                self.assertEqual(results, [])
                barrier.seal()
                self.assertEqual(results, [True])
                barrier.fail()
                barrier.seal()
                self.assertEqual(results, [True])
                with self.assertRaisesRegex(RuntimeError, "sealed"):
                    barrier.register("late")

    def test_one_surface_failure_waits_for_other_surface_in_either_order(self):
        for failure_first in (True, False):
            with self.subTest(failure_first=failure_first):
                results = []
                barrier = RemoteProjectionBarrier(
                    database_id="db",
                    runtime_generation=1,
                    is_runtime_current=lambda _db, _generation: True,
                    on_complete=results.append,
                )
                main = barrier.register("main")
                detached = barrier.register("detached")
                barrier.seal()
                main.complete(not failure_first)
                self.assertEqual(results, [])
                detached.complete(failure_first)
                self.assertEqual(results, [False])

    def test_invalid_registration_and_foreign_token_preserve_pending_work(self):
        results = []
        other_results = []
        barrier = RemoteProjectionBarrier(
            database_id="db",
            runtime_generation=1,
            is_runtime_current=lambda _db, _generation: True,
            on_complete=results.append,
        )
        other = RemoteProjectionBarrier(
            database_id="other",
            runtime_generation=1,
            is_runtime_current=lambda _db, _generation: True,
            on_complete=other_results.append,
        )
        with self.assertRaisesRegex(ValueError, "required"):
            barrier.register("")
        main = barrier.register("main")
        foreign = other.register("main")
        with self.assertRaisesRegex(ValueError, "already registered"):
            barrier.register("main")
        barrier.seal()
        with self.assertRaisesRegex(ValueError, "another barrier"):
            barrier.complete(foreign, False)
        self.assertEqual(results, [])
        self.assertEqual(other_results, [])
        main.complete(True)
        foreign.complete(True)
        other.seal()
        self.assertEqual(results, [True])
        self.assertEqual(other_results, [True])

    def test_raising_completion_is_consumed_once(self):
        results = []

        def complete(success):
            results.append(success)
            raise RuntimeError("observer failed")

        barrier = RemoteProjectionBarrier(
            database_id="db",
            runtime_generation=1,
            is_runtime_current=lambda _db, _generation: True,
            on_complete=complete,
        )
        main = barrier.register("main")
        barrier.seal()
        with self.assertRaisesRegex(RuntimeError, "observer failed"):
            main.complete(True)
        main.complete(False)
        barrier.seal()
        self.assertEqual(results, [True])


def _barrier(on_complete, *, current=lambda _database, _generation: True, **options):
    return RemoteProjectionBarrier(
        database_id="db",
        runtime_generation=1,
        is_runtime_current=current,
        on_complete=on_complete,
        **options,
    )


class RemoteProjectionBarrierContractTests(unittest.TestCase):
    def test_resource_uid_aliases_are_normalized_per_family(self):
        barrier = _barrier(
            lambda success: None,
            resource_uid_aliases_by_family={
                "takeoffs": ("10", 11, "10", "", None, "12"),
                7: [3, 3, "x"],
                "empty": (),
            },
        )
        self.assertEqual(
            barrier.resource_uid_aliases_by_family,
            {"takeoffs": ("10", "11", "12"), "7": ("3", "x"), "empty": ()},
        )
        self.assertEqual(
            _barrier(lambda success: None).resource_uid_aliases_by_family, {}
        )
        self.assertEqual(
            _barrier(
                lambda success: None, resource_uid_aliases_by_family=None
            ).resource_uid_aliases_by_family,
            {},
        )

    def test_tokens_are_immutable_and_only_the_issued_token_can_complete_a_surface(
        self,
    ):
        results = []
        barrier = _barrier(results.append)
        issued = barrier.register("main")
        self.assertEqual((issued.surface_id, issued._barrier), ("main", barrier))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issued.surface_id = "other"
        forged = RemoteProjectionToken("main", barrier)
        self.assertEqual(forged, issued)
        barrier.seal()
        forged.complete(True)
        barrier.complete(forged, False)
        self.assertEqual(results, [])
        issued.complete(True)
        self.assertEqual(results, [True])

    def test_sealing_a_stale_barrier_without_surfaces_reports_failure(self):
        for current, expected in ((True, True), (False, False)):
            with self.subTest(current=current):
                results = []
                barrier = _barrier(
                    results.append, current=lambda _database, _generation: current
                )
                barrier.seal()
                self.assertEqual(results, [expected])

    def test_surface_failure_cannot_be_undone_by_a_repeated_completion(self):
        results = []
        barrier = _barrier(results.append)
        main = barrier.register("main")
        detached = barrier.register("detached")
        barrier.seal()
        main.complete(False)
        main.complete(True)
        self.assertEqual(results, [])
        detached.complete(True)
        self.assertEqual(results, [False])

    def test_completion_callback_is_released_once_it_has_run(self):
        class Observer:
            def __init__(self):
                self.results = []

            def __call__(self, success):
                self.results.append(success)

        observer = Observer()
        reference = weakref.ref(observer)
        barrier = _barrier(observer)
        surface = barrier.register("main")
        barrier.seal()
        surface.complete(True)
        self.assertEqual(observer.results, [True])
        del observer
        gc.collect()
        self.assertIsNone(reference())

    def test_completion_callback_may_reenter_the_barrier_without_deadlock(self):
        results = []
        reentry = []

        def observer(success):
            results.append(success)
            barrier.seal()
            barrier.fail()
            with self.assertRaisesRegex(RuntimeError, "sealed"):
                barrier.register("late")
            reentry.append(True)

        barrier = _barrier(observer)
        surface = barrier.register("main")
        worker = threading.Thread(
            target=lambda: (barrier.seal(), surface.complete(True)), daemon=True
        )
        worker.start()
        worker.join(10.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual((results, reentry), ([True], [True]))

    def test_every_state_access_happens_under_the_barrier_lock(self):
        results = []
        barrier = _barrier(results.append)
        barrier._pending = guard_mapping(barrier._lock, barrier._pending)
        main = barrier.register("main")
        detached = barrier.register("detached")
        with self.assertRaises(ValueError):
            barrier.register("main")
        barrier.fail()
        barrier.seal()
        barrier.seal()
        main.complete(True)
        detached.complete(True)
        main.complete(True)
        self.assertEqual(results, [False])
        with self.assertRaisesRegex(AssertionError, "without the lock"):
            barrier._pending.get("main")

    def test_racing_completions_deliver_exactly_one_result(self):
        for success in (True, False):
            with self.subTest(success=success):
                results = []
                barrier = _barrier(results.append)
                surfaces = [barrier.register(f"surface-{index}") for index in range(8)]
                barrier.seal()
                start = threading.Barrier(len(surfaces))

                def finish(surface, outcome):
                    start.wait(10.0)
                    surface.complete(outcome)
                    surface.complete(not outcome)

                threads = [
                    threading.Thread(
                        target=finish, args=(surface, success or index != 3)
                    )
                    for index, surface in enumerate(surfaces)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10.0)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(results, [success])
