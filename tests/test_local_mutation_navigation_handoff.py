from copy import deepcopy
import unittest
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    ConcurrencyToken,
    HydratedDatabaseChangeBatch,
    MutationOutcomeStatus,
)
from ost_visualizer.domain.entities.condition import Condition
from tests import test_navigation_token_overlap
from tests.test_sql_collaboration_phase4 import (
    _batch,
    _change,
    _queue_test_mutation,
    _committed_execution,
)


class LocalMutationNavigationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_navigation_token_overlap.NavigationTokenOverlapTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.context = self.fixture.context
        self.coordinator = self.context.coordinator
        self.runtime = self.context.runtime
        self.runtime.established = True
        self.runtime.healthy = True
        self.context.store.acquire_locks.return_value = ()
        self.context.tokens.load_bid("database", "8")
        self.context.fixture.model.bid_conditions = {"42": Condition("42", name="Old")}
        self.results = []
        self.order = []

    def run_mutation(self, *, navigate=False, delete=False):
        def commit():
            self.order.append("commit V2")
            self.fixture.server.name = "Local Two"
            self.fixture.version = ConcurrencyToken((2).to_bytes(8, "big"))
            self.context.tokens.apply_result(
                "database", {self.fixture.resource: self.fixture.version}
            )
            return _committed_execution()

        def hydrate(*_args):
            self.order.append("hydrate V2")
            return HydratedDatabaseChangeBatch(
                _batch(
                    "database",
                    "epoch",
                    0,
                    2,
                    (_change("database", self.fixture.resource, 2),),
                ),
                conditions_by_bid={8: {"42": deepcopy(self.fixture.server)}},
                condition_folders_by_bid={8: {}},
            )

        self.context.store.hydrate_operation.side_effect = hydrate
        original_release = self.coordinator._release_queued_mutation_resources

        def release(*args):
            result = original_release(*args)
            if navigate:
                # Hydration has finished; resource cleanup precedes Qt dispatch.
                self.order.append("navigation V3")
                self.fixture.server.name = "Navigation Three"
                self.fixture.version = ConcurrencyToken((3).to_bytes(8, "big"))
                self.context.tokens._reader.resources[self.fixture.resource] = (
                    self.fixture.version
                )
                prepared = self.fixture.loader.prepare(self.context.fixture.bid_ref)
                if delete:
                    prepared.bid_data.bid_conditions = {}
                self.assertTrue(
                    self.fixture.loader.apply_prepared(
                        self.context.fixture.bid_ref, prepared
                    )
                )
                self.new_bid = self.context.fixture.model.current_bid
                self.new_condition = self.context.data.get_bid_conditions().get("42")
                self.pages = list(self.context.data.get_all_pages())
                self.context.fixture.model.select_pages(["1"])
            return result

        _queue_test_mutation(
            self.coordinator,
            "database",
            (self.fixture.resource,),
            commit,
            self.results.append,
            expected_id_count=0,
            mutation_type=CollaborationMutationType.PROJECT_WRITE,
        )
        with patch.object(
            self.coordinator, "_release_queued_mutation_resources", side_effect=release
        ):
            self.coordinator._process_mutation_requests(self.runtime)

    def assert_superseded(self):
        self.assertEqual(self.order, ["commit V2", "hydrate V2", "navigation V3"])
        self.assertIs(self.context.fixture.model.current_bid, self.new_bid)
        self.assertIs(
            self.context.data.get_bid_conditions().get("42"), self.new_condition
        )
        self.assertEqual(self.context.fixture.model.get_selected_pages(), ["1"])
        self.assertTrue(
            all(a is b for a, b in zip(self.pages, self.context.data.get_all_pages()))
        )
        self.assertEqual(
            self.context.tokens.expected_versions("database", (self.fixture.resource,))[
                0
            ].expected,
            ConcurrencyToken((3).to_bytes(8, "big")),
        )
        self.assertEqual(
            self.results[0].outcome_status,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        self.assertTrue(self.results[0].commit_attempted)
        self.assertTrue(self.runtime.recovery_requested)

    def test_newer_same_bid_navigation_survives_local_hydration(self):
        self.run_mutation(navigate=True)
        self.assert_superseded()
        self.assertEqual(self.new_condition.name, "Navigation Three")

    def test_navigation_deleted_condition_is_not_resurrected(self):
        self.run_mutation(navigate=True, delete=True)
        self.assert_superseded()
        self.assertNotIn("42", self.context.data.get_bid_conditions())

    def test_clean_local_completion_projects_and_next_write_commits(self):
        self.run_mutation()
        self.assertEqual(
            self.results[0].outcome_status, MutationOutcomeStatus.COMMITTED
        )
        self.assertEqual(self.context.data.get_bid_conditions()["42"].name, "Local Two")
        self.assertTrue(self.fixture.edit().success)
        self.assertEqual(
            self.fixture.presented, ConcurrencyToken((2).to_bytes(8, "big"))
        )
