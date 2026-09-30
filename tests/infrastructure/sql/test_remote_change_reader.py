import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.page_info import BidPageInfo
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.sql.remote_change_reader import (
    _MAX_HYDRATION_BATCH_PARAMETERS,
    _MAX_HYDRATION_BATCH_QUERIES,
    SqlRemoteChangeReader,
    _execute_recorded_queries,
    _recorded_query_batches,
)
from tests.helpers.sql.collaboration import (
    _ReadRequestFactory,
    _batch,
    _change,
)


class RemoteChangeReaderCollaborationTests(unittest.TestCase):
    def test_takeoff_hydration_includes_authoritative_condition_dependency(self):
        calls = []
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = SimpleNamespace(
            _schema=lambda _connection: object(),
            _parse_cdn_types=lambda _connection: {},
            _parse_bid_layers_for_bid=lambda _connection, bid_uid: calls.append(
                ("condition-layers", bid_uid)
            )
            or {},
            _parse_bid_conditions_for_bid=lambda _connection, bid_uid, *_args: {
                "10": Condition(uid="10")
            },
            _parse_bid_condition_folders_for_bid=lambda *_args: {},
            _parse_bid_takeoffs_for_bid=lambda *_args: (
                [Takeoff(uid="30", condition_uid="10", page_uid="20")],
                {},
            ),
            _parse_bid_pages_for_bid=lambda *_args: {
                "20": BidPageInfo(
                    name="Sheet",
                    sheet_no="",
                    sequence=0,
                    image_path="",
                    width_pts=0.0,
                    height_pts=0.0,
                    scale_factor1=1.0,
                    scale_factor2=1.0,
                    rotation=0.0,
                    flip_x=False,
                    flip_y=False,
                    page_index=0,
                    layer_visible=True,
                    overlay_image_path="",
                    overlay_offset_x=0.0,
                    overlay_offset_y=0.0,
                    overlay_rotation=0.0,
                    overlay_resized=False,
                    deskew_rotation_overlay=0.0,
                    overlay_rect=(),
                    image_show_mode=0,
                    zoom_fac=1.0,
                    current_x=0.0,
                    current_y=0.0,
                    invert=False,
                    bitonal=False,
                )
            },
        )
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("takeoff", "30", 8),
                    sequence=2,
                ),
            ),
        )
        hydrated = reader.hydrate_connection(batch, object())
        self.assertEqual(set(hydrated.conditions_by_bid[8]), {"10"})
        self.assertEqual(calls, [("condition-layers", "8")])

    def test_takeoff_hydration_batches_bound_parameters_and_query_count(self):
        parameter_queries = tuple(
            (f"SELECT {index}", tuple(range(10))) for index in range(201)
        )
        parameter_batches = tuple(_recorded_query_batches(parameter_queries))
        self.assertEqual(
            tuple(item for batch in parameter_batches for item in batch),
            parameter_queries,
        )
        self.assertGreater(len(parameter_batches), 1)
        self.assertTrue(
            all(
                sum(len(parameters) for _query, parameters in batch)
                <= _MAX_HYDRATION_BATCH_PARAMETERS
                for batch in parameter_batches
            )
        )
        query_count_queries = tuple(
            (f"SELECT {index}", ()) for index in range(_MAX_HYDRATION_BATCH_QUERIES + 1)
        )
        query_count_batches = tuple(_recorded_query_batches(query_count_queries))
        self.assertEqual(
            tuple(item for batch in query_count_batches for item in batch),
            query_count_queries,
        )
        self.assertEqual(
            tuple(len(batch) for batch in query_count_batches),
            (_MAX_HYDRATION_BATCH_QUERIES, 1),
        )

    def test_takeoff_hydration_replay_preserves_order_across_bounded_batches(self):
        class _BatchCursor:
            def __init__(self, owner):
                self._owner = owner
                self._result_index = 0
                self._results = ()
                self.description = (("Value",),)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *parameters):
                query_count = str(sql).count(";") + 1
                start = self._owner.next_result
                self._owner.next_result += query_count
                self._owner.executions.append((query_count, len(parameters)))
                self._results = tuple(
                    ((start + index,),) for index in range(query_count)
                )
                self._result_index = 0
                return self

            def fetchall(self):
                return self._results[self._result_index]

            def nextset(self):
                self._result_index += 1
                return self._result_index < len(self._results)

        class _BatchConnection:
            def __init__(self):
                self.executions = []
                self.next_result = 0

            def cursor(self):
                return _BatchCursor(self)

        queries = tuple(
            ("SELECT ?", (index,)) for index in range(_MAX_HYDRATION_BATCH_QUERIES + 1)
        )
        connection = _BatchConnection()
        replay = _execute_recorded_queries(connection, queries)
        replayed = []
        for query, parameters in queries:
            with replay.cursor() as cursor:
                cursor.execute(query, *parameters)
                replayed.extend(row[0] for row in cursor.fetchall())
        replay.assert_consumed()
        self.assertEqual(replayed, list(range(len(queries))))
        self.assertEqual(
            connection.executions,
            [
                (_MAX_HYDRATION_BATCH_QUERIES, _MAX_HYDRATION_BATCH_QUERIES),
                (1, 1),
            ],
        )

    def test_initial_reconciliation_uses_one_snapshot_without_advancing_checkpoint(
        self,
    ):
        class _Cursor:
            def __init__(self):
                self.statements = []

            def execute(self, sql, *_parameters):
                self.statements.append(sql)
                return self

            def fetchone(self):
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.statements[-1]:
                    return (19,)
                raise AssertionError(self.statements[-1])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        connections = _Connections()
        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._requests = _ReadRequestFactory()
        remote_reader._connections = connections
        hydration_connections = []

        def hydrate(batch, connection):
            hydration_connections.append(connection)
            self.assertEqual(connections.lease.commits, 1)
            return HydratedDatabaseChangeBatch(batch)

        remote_reader.hydrate_connection = hydrate
        hydrated = remote_reader.initial_reconciliation("database", 8, 11)
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.statements[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(hydrated.batch.high_water_version, 19)
        self.assertEqual(hydrated.batch.delivered_through_version, 11)
        self.assertEqual(hydration_connections, [connections.lease])
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)

    def test_remote_condition_and_area_hydration_uses_current_reader_contract(self):
        condition = object()
        folder = object()
        area = object()
        layer = object()
        reader_connections = []

        class _Connections:
            def __init__(self):
                self.calls = 0

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if not autocommit:
                    raise AssertionError("Remote hydration must use autocommit reads.")
                self.calls += 1
                yield object()

        class _Reader:
            logger = None

            @staticmethod
            def _schema(connection):
                reader_connections.append(connection)
                return object()

            def _parse_cdn_types(self, _connection):
                return {"4": object()}

            def _parse_bid_layers_for_bid(self, _connection, bid_uid):
                return {"3": object()}

            def _parse_bid_conditions_for_bid(
                self, _connection, bid_uid, layers, cdn_types, schema
            ):
                return {"42": condition}

            def _parse_bid_condition_folders_for_bid(
                self, _connection, bid_uid, schema
            ):
                return {"5": folder}

            def _parse_bid_areas_for_bid(self, _connection, bid_uid, schema):
                return {"6": area}

            def _parse_bid_layers_for_sidebar(self, connection, bid_uid):
                reader_connections.append(connection)
                return [layer]

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._connections = _Connections()
        remote_reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            3,
            (
                _change(
                    "database",
                    ResourceRef("conditions_collection", "8", 8),
                    1,
                ),
                _change(
                    "database",
                    ResourceRef("areas_collection", "8", 8),
                    2,
                ),
                _change(
                    "database",
                    ResourceRef("layers_collection", "8", 8),
                    3,
                ),
            ),
        )
        connection = object()
        hydrated = remote_reader.hydrate_connection(batch, connection)
        self.assertEqual(hydrated.conditions_by_bid, {8: {"42": condition}})
        self.assertEqual(hydrated.condition_folders_by_bid, {8: {"5": folder}})
        self.assertEqual(hydrated.areas_by_bid, {8: (area,)})
        self.assertEqual(hydrated.bid_data_by_bid[8].bid_layers, [layer])
        self.assertTrue(reader_connections)
        self.assertTrue(all(value is connection for value in reader_connections))
        self.assertEqual(remote_reader._connections.calls, 0)

    def test_job_status_and_employee_hydration_refreshes_hierarchy_displays(self):
        hierarchy = HierarchyFileEntry(file_path="database")
        parse_calls = []

        class _Reader:
            @staticmethod
            def parse_file_connection(database_id, _connection):
                parse_calls.append(database_id)
                return hierarchy, {}

            @staticmethod
            def _parse_settings_defaults(_connection):
                return {}

            @staticmethod
            def _parse_job_statuses(_connection):
                return (JobStatus("status-1", "Renamed"),)

            @staticmethod
            def _parse_used_job_status_uids(_connection):
                return {"status-1"}

            @staticmethod
            def _parse_employees_and_pay_classes(_connection):
                return ([Employee("employee-1", first_name="Renamed")], [])

            @staticmethod
            def _parse_used_employee_uids(_connection):
                return {"employee-1"}

        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            (
                _change(
                    "database",
                    ResourceRef("job_statuses_collection", "database"),
                    1,
                ),
                _change(
                    "database",
                    ResourceRef("employees_collection", "database"),
                    2,
                ),
            ),
        )
        hydrated = reader.hydrate_connection(batch, object())
        self.assertIs(hydrated.hierarchy_file, hierarchy)
        self.assertEqual(parse_calls, ["database"])
