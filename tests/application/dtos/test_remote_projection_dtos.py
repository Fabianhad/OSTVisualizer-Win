import unittest
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)


class RemoteProjectionBarrierTests(unittest.TestCase):
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
        barrier = RemoteProjectionBarrier(
            database_id="sql-db",
            runtime_generation=4,
            is_runtime_current=lambda _database_id, _generation: False,
            on_complete=lambda success: results.append(success),
        )
        main = barrier.register("main")
        barrier.seal()
        main.complete(True)
        self.assertEqual(results, [False])

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
