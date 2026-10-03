import inspect
import re
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, Mock, create_autospec
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ConcurrencyToken,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.interfaces.i_database_mutation_executor import (
    IDatabaseMutationExecutor,
    IMutationRecorder,
)
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.use_cases.project.update_condition_use_case import (
    UpdateConditionUseCase,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
import tests.integration.navigation.test_token_overlap as test_navigation_token_overlap
from tests.helpers.sql.collaboration import _batch, _change


def strict_project_reader_double():
    """Stand-in for the SqlProjectReader that SqlRemoteChangeReader wraps.
    A bare Mock() accepts any attribute, so a renamed or invented reader method would
    silently return a Mock. spec_set limits the double to the attribute names the real
    reader has. It is deliberately NOT spec'd with the class itself: Mock(spec=
    SqlProjectReader) passes isinstance(), which would switch hydrate_connection onto
    its takeoff-only replay path (covered by tests/infrastructure/sql/
    test_remote_change_reader.py) instead of the general path these tests exercise.
    """
    names = [name for name in dir(SqlProjectReader) if not name.startswith("__")]
    return Mock(spec_set=names)


class GlobalConditionScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_navigation_token_overlap.NavigationTokenOverlapTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.context = self.fixture.context
        self.connection = MagicMock()
        self.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            (8,),
            (9,),
        ]
        self.reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        self.reader._reader = strict_project_reader_double()
        self.rows = {
            8: {"42": Condition("42", name="A New")},
            9: {"44": Condition("44", name="B New")},
        }
        self.folders = {8: {"80": object()}, 9: {"90": object()}}
        self.reader._reader._parse_bid_conditions_for_bid.side_effect = (
            lambda _connection, bid_uid, *_args: self.rows[int(bid_uid)]
        )
        self.reader._reader._parse_bid_condition_folders_for_bid.side_effect = (
            lambda _connection, bid_uid, *_args: self.folders[int(bid_uid)]
        )

    def deliver(self, records):
        coalesced = SqlProjectWriter._coalesce_records(records)
        batch = _batch(
            "database",
            "epoch",
            0,
            4,
            tuple(
                _change("database", record.resource, 4, operation=record.operation)
                for record in coalesced
            ),
        )
        hydrated = self.reader.hydrate_connection(batch, self.connection)
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
        return coalesced, hydrated

    def test_two_bid_coalescing_retains_scope(self):
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(uid), bid), ChangeOperation.UPDATE
            )
            for bid, start in ((8, 1), (9, 301))
            for uid in range(start, start + 300)
        ]
        coalesced, hydrated = self.deliver(records)
        self.assertEqual(
            [r.resource for r in coalesced],
            [
                ResourceRef("conditions_collection", "8", 8),
                ResourceRef("conditions_collection", "9", 9),
            ],
        )
        self.assertEqual(
            [r.operation for r in coalesced],
            [ChangeOperation.BULK_REFRESH] * 2,
        )
        self.assertEqual(set(hydrated.conditions_by_bid), {8, 9})
        self.assertIs(hydrated.conditions_by_bid[9]["44"], self.rows[9]["44"])
        self.assertIs(self.context.data.get_bid_conditions()["42"], self.rows[8]["42"])
        self.assertNotIn("44", self.context.data.get_bid_conditions())
        self.assertEqual(self.context.runtime.acknowledged_version, 4)
        self.connection.cursor.assert_not_called()

    def test_database_wide_collection_hydrates_current_bids_before_acknowledging(self):
        # Only Bids 8 and 9 remain at the hydration snapshot. Coalescing retains
        # no historical Bid list, so current SQL owners define the reload scope.
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(bid + 1000), bid), ChangeOperation.UPDATE
            )
            for bid in range(8, 459)
        ]
        coalesced, hydrated = self.deliver(records)
        self.assertEqual(
            [r.resource for r in coalesced],
            [
                ResourceRef("conditions_collection", "database"),
            ],
        )
        self.assertEqual(
            [r.operation for r in coalesced], [ChangeOperation.BULK_REFRESH]
        )
        self.assertEqual(set(hydrated.conditions_by_bid), {8, 9})
        self.assertEqual(hydrated.condition_folders_by_bid, self.folders)
        self.assertIs(self.context.data.get_bid_conditions()["42"], self.rows[8]["42"])
        self.assertNotIn("44", self.context.data.get_bid_conditions())
        self.assertEqual(self.context.runtime.acknowledged_version, 4)
        self.assertFalse(self.context.runtime.recovery_requested)
        self.assertTrue(self.context.runtime.healthy)
        self.connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SELECT [UID] FROM [Bids] ORDER BY [UID]"
        )
        # Inactive content is not cached: later navigation reads SQL content and
        # Bid-scoped versions afresh, independently of the acknowledged feed.
        self.context.data.replace_database_hierarchy(
            HierarchyFileEntry(
                file_path="database",
                orphan_bids=[
                    self.context.fixture.info,
                    HierarchyBidInfo(uid="9", name="B"),
                ],
            ),
            {},
        )
        resource = ResourceRef("condition", "44", 9)
        token = ConcurrencyToken((5).to_bytes(8, "big"))
        self.context.tokens._reader.resources[resource] = token
        data = self.context.fixture.read()
        data.pages = []
        data.bid_conditions = deepcopy(self.rows[9])
        self.fixture.files.prepare_bid_load.side_effect = None
        self.fixture.files.prepare_bid_load.return_value = data
        ref = BidRef("database", "9")
        prepared = self.fixture.loader.prepare(ref)
        self.assertTrue(self.fixture.loader.apply_prepared(ref, prepared))
        self.assertEqual(self.context.data.get_bid_conditions()["44"].name, "B New")
        self.assertNotIn("42", self.context.data.get_bid_conditions())
        self.assertEqual(
            self.context.tokens.expected_versions("database", (resource,))[0].expected,
            token,
        )
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = create_autospec(
            DatabaseCapabilityService, instance=True
        )
        service._database_capability_service.is_editable.return_value = True
        service._event_bus = self.context.events
        service._session_registry = DatabaseSessionRegistry()
        service._session_registry.register("database", "session")
        service._concurrency_tokens = self.context.tokens
        service._project_data = self.context.data
        service._bid_write_guard = create_autospec(ActiveBidWriteGuard, instance=True)
        service._bid_write_guard.blocks_active_locked_bid_write.return_value = False
        writer = create_autospec(IMdbWriter, instance=True)
        server = deepcopy(self.rows[9]["44"])

        def update(database_id, bid_uid, condition_uid, updates):
            self.assertEqual(
                (database_id, bid_uid, condition_uid), ("database", "9", "44")
            )
            server.name = updates.get("name")
            return True

        writer.update_condition.side_effect = update
        service._update_condition = UpdateConditionUseCase(writer)
        service._mutation_executor = create_autospec(
            IDatabaseMutationExecutor, instance=True
        )

        def execute(request, operation):
            self.assertEqual(len(request.expected_versions), 1)
            self.assertEqual(request.expected_versions[0].resource, resource)
            self.assertEqual(request.expected_versions[0].expected, token)
            return DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(create_autospec(IMutationRecorder, instance=True)),
                resulting_versions={resource: ConcurrencyToken((6).to_bytes(8, "big"))},
            )

        service._mutation_executor.execute.side_effect = execute
        updates = UpdateConditionDto()
        updates.set("name", "B User Edit")
        self.assertTrue(
            service.update_condition("database", "9", "44", updates, False).success
        )
        self.assertEqual(server.name, "B User Edit")


class StrictProjectReaderDoubleTests(unittest.TestCase):
    def test_the_double_takes_the_general_path_and_only_has_real_reader_methods(self):
        double = strict_project_reader_double()
        self.assertNotIsInstance(double, SqlProjectReader)
        with self.assertRaises(AttributeError):
            double._parse_bid_conditions_for_bid_renamed
        with self.assertRaises(AttributeError):
            double.invented_method = lambda: None
        self.assertTrue(callable(double._parse_bid_conditions_for_bid))

    def test_every_reader_method_the_remote_reader_calls_exists_on_the_real_reader(
        self,
    ):
        called = set(
            re.findall(
                r"self\._reader\.(\w+)", inspect.getsource(SqlRemoteChangeReader)
            )
        )
        self.assertGreaterEqual(len(called), 15)
        self.assertEqual(
            {name for name in called if not hasattr(SqlProjectReader, name)}, set()
        )
        double = strict_project_reader_double()
        for name in called:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(double, name)))


if __name__ == "__main__":
    unittest.main()
