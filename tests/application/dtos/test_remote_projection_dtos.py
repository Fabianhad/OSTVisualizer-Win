import unittest
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)


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
