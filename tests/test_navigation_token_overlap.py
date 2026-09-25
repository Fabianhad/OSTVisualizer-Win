import threading
import unittest
from copy import deepcopy
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    DatabaseMutationResult,
    HydratedDatabaseChangeBatch,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.services.navigation_load_service import (
    NavigationLoadService,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
)
from ost_visualizer.application.use_cases.project.update_condition_use_case import (
    UpdateConditionUseCase,
)
from ost_visualizer.domain.entities.condition import Condition
from tests import test_remote_batch_navigation_handoff
from tests.test_sql_collaboration_phase4 import _batch, _change


class NavigationTokenOverlapTests(unittest.TestCase):
    def setUp(self):
        self.context = (
            test_remote_batch_navigation_handoff.RemoteBatchNavigationHandoffTests()
        )
        self.context.setUp()
        self.addCleanup(self.context.doCleanups)
        self.resource = ResourceRef("condition", "42", 8)
        self.server = Condition("42", name="Old")
        self.version = ConcurrencyToken((1).to_bytes(8, "big"))
        self.context.tokens._reader.resources = {self.resource: self.version}
        self.files = Mock()
        self.files.prepare_bid_load.side_effect = self.read
        workspace = Mock()
        workspace.uses_sql_workspace.return_value = False
        self.loader = LoadBidUseCase(
            self.context.fixture.model,
            self.context.data,
            self.files,
            self.context.tokens,
            workspace,
        )

    def read(self, *_args):
        data = self.context.fixture.read()
        data.bid_conditions = {"42": deepcopy(self.server)}
        return data

    def remote_update(self):
        self.server.name = "Remote New"
        self.version = ConcurrencyToken((2).to_bytes(8, "big"))
        self.context.tokens._reader.resources[self.resource] = self.version
        batch = _batch(
            "database", "epoch", 0, 2, (_change("database", self.resource, 2),)
        )
        hydrated = HydratedDatabaseChangeBatch(
            batch,
            conditions_by_bid={8: {"42": deepcopy(self.server)}},
            condition_folders_by_bid={8: {}},
        )
        runtime = self.context.runtime
        self.context.coordinator._on_remote_batch(
            (
                "database",
                runtime.generation,
                runtime.session_generation,
                hydrated,
                self.context.fixture.model.current_bid,
            )
        )
        self.assertEqual(runtime.acknowledged_version, 2)
        self.assertTrue(runtime.healthy)

    def edit(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = Mock()
        service._database_capability_service.is_editable.return_value = True
        service._event_bus = self.context.events
        service._session_registry = DatabaseSessionRegistry()
        service._session_registry.register("database", "session")
        service._concurrency_tokens = self.context.tokens
        service._project_data = self.context.data
        service._bid_write_guard = Mock()
        service._bid_write_guard.blocks_active_locked_bid_write.return_value = False
        writer = Mock()

        def update(_db, _bid, _uid, updates):
            self.server.name = updates.get("name")
            return True

        writer.update_condition.side_effect = update
        service._update_condition = UpdateConditionUseCase(writer)
        executor = Mock()

        def execute(request, operation):
            self.presented = request.expected_versions[0].expected
            if self.presented != self.version:
                return DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                )
            value = operation(Mock())
            self.version = ConcurrencyToken(
                (int.from_bytes(self.version.value, "big") + 1).to_bytes(8, "big")
            )
            return DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
                resulting_versions={self.resource: self.version},
            )

        executor.execute.side_effect = execute
        service._mutation_executor = executor
        updates = UpdateConditionDto()
        updates.set("name", "User Edit")
        return service.update_condition("database", "8", "42", updates, False)

    def test_pending_navigation_rejects_accepted_remote_token_advance(self):
        self.files.prepare_bid_load.side_effect = None
        self.files.prepare_bid_load.return_value = self.read()
        queued = threading.Event()
        callbacks = []
        dispatcher = Mock()

        def dispatch(callback, payload):
            callbacks.append((callback, payload))
            queued.set()

        dispatcher.dispatch.side_effect = dispatch
        navigation = NavigationLoadService(Mock(), dispatcher)
        self.addCleanup(navigation.cleanup)
        applied = []
        navigation.submit(
            "database",
            "8",
            lambda: self.loader.prepare(self.context.fixture.bid_ref),
            lambda result: applied.append(
                self.loader.apply_prepared(self.context.fixture.bid_ref, result.value)
            ),
        )
        self.assertTrue(queued.wait(2))
        self.remote_update()
        bid = self.context.fixture.model.current_bid
        condition = self.context.data.get_bid_conditions()["42"]
        pages = list(self.context.data.get_all_pages())
        callback, payload = callbacks.pop()
        callback(payload)
        self.assertEqual(applied, [False])
        self.assertIs(self.context.fixture.model.current_bid, bid)
        self.assertIs(self.context.data.get_bid_conditions()["42"], condition)
        self.assertEqual(condition.name, "Remote New")
        self.assertTrue(
            all(a is b for a, b in zip(pages, self.context.data.get_all_pages()))
        )
        self.files.apply_bid_load.assert_not_called()
        self.assertTrue(self.edit().success)
        self.assertEqual(self.presented, ConcurrencyToken((2).to_bytes(8, "big")))

    def test_clean_navigation_write_commits(self):
        pending = self.loader.prepare(self.context.fixture.bid_ref)
        self.assertTrue(
            self.loader.apply_prepared(self.context.fixture.bid_ref, pending)
        )
        self.assertTrue(self.edit().success)
        self.assertEqual(self.presented, ConcurrencyToken((1).to_bytes(8, "big")))
        self.assertEqual(self.server.name, "User Edit")

    def test_remote_change_without_projection_conflicts_with_loaded_baseline(self):
        pending = self.loader.prepare(self.context.fixture.bid_ref)
        self.assertTrue(
            self.loader.apply_prepared(self.context.fixture.bid_ref, pending)
        )
        self.server.name = "Remote New"
        self.version = ConcurrencyToken((2).to_bytes(8, "big"))
        self.assertFalse(self.edit().success)
        self.assertEqual(self.presented, ConcurrencyToken((1).to_bytes(8, "big")))
        self.assertEqual(self.server.name, "Remote New")
