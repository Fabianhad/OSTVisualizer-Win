from tests.helpers.sql.strict_sql_fakes import StrictLeaseProxy, strict_manager
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
        self.assertEqual(hydrated.condition_folders_by_bid, {8: {}})
        self.assertEqual(calls, [("condition-layers", "8")])
        bid_data = hydrated.bid_data_by_bid[8]
        self.assertEqual([t.uid for t in bid_data.bid_takeoffs], ["30"])
        self.assertEqual(set(bid_data.bid_pages), {"20"})
        self.assertEqual(set(bid_data.pages), {"20"})
        # A Takeoff change never hydrates areas, hierarchy or master data.
        self.assertEqual(hydrated.areas_by_bid, {})
        self.assertIsNone(hydrated.hierarchy_file)
        self.assertIsNone(hydrated.job_statuses)
        self.assertEqual(hydrated.cover_sheet_by_bid, {})
        self.assertIs(hydrated.batch, batch)

    def test_batch_without_changes_hydrates_nothing_and_never_touches_connection(
        self,
    ):
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = SimpleNamespace()
        batch = _batch("database", "epoch", 1, 2)
        hydrated = reader.hydrate_connection(batch, object())
        self.assertIs(hydrated.batch, batch)
        self.assertEqual(hydrated.conditions_by_bid, {})
        self.assertEqual(hydrated.bid_data_by_bid, {})
        self.assertIsNone(hydrated.hierarchy_file)

    def test_global_collection_change_expands_to_every_bid_in_uid_order(self):
        seen_conditions = []
        queries = []

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_parameters):
                queries.append(sql)

            @staticmethod
            def fetchall():
                return [(3,), (7,)]

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = SimpleNamespace(
            _schema=lambda _connection: object(),
            _parse_cdn_types=lambda _connection: {},
            _parse_bid_layers_for_bid=lambda _connection, bid_uid: {},
            _parse_bid_conditions_for_bid=lambda _connection, bid_uid, *_args: (
                seen_conditions.append(bid_uid) or {bid_uid: Condition(uid=bid_uid)}
            ),
            _parse_bid_condition_folders_for_bid=lambda *_args: {},
        )
        batch = _batch(
            "database",
            "epoch",
            1,
            1,
            (_change("database", ResourceRef("conditions_collection", "database")),),
        )
        hydrated = reader.hydrate_connection(batch, _Connection())
        self.assertEqual(queries, ["SELECT [UID] FROM [Bids] ORDER BY [UID]"])
        self.assertEqual(seen_conditions, ["3", "7"])
        self.assertEqual(set(hydrated.conditions_by_bid), {3, 7})
        self.assertEqual(set(hydrated.conditions_by_bid[7]), {"7"})

    def test_takeoff_hydration_batches_bound_parameters_and_query_count(self):
        parameter_queries = tuple(
            (f"SELECT {index}", tuple(range(10))) for index in range(201)
        )
        parameter_batches = tuple(_recorded_query_batches(parameter_queries))
        self.assertEqual(
            tuple(item for batch in parameter_batches for item in batch),
            parameter_queries,
        )
        self.assertEqual(len(parameter_batches), 2)
        self.assertEqual(
            tuple(
                sum(len(parameters) for _query, parameters in batch)
                for batch in parameter_batches
            ),
            (_MAX_HYDRATION_BATCH_PARAMETERS, 10),
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
        exact_fit = tuple(
            (f"SELECT {index}", tuple(range(10)))
            for index in range(_MAX_HYDRATION_BATCH_PARAMETERS // 10)
        )
        self.assertEqual(
            tuple(len(batch) for batch in _recorded_query_batches(exact_fit)),
            (len(exact_fit),),
        )
        self.assertEqual(
            tuple(len(batch) for batch in _recorded_query_batches(exact_fit[:1])),
            (1,),
        )
        self.assertEqual(tuple(_recorded_query_batches(())), ())
        half = _MAX_HYDRATION_BATCH_PARAMETERS // 2
        self.assertEqual(
            tuple(
                len(batch)
                for batch in _recorded_query_batches(
                    (("SELECT 1", (0,) * half), ("SELECT 2", (0,) * half))
                )
            ),
            (2,),
        )
        self.assertEqual(
            tuple(
                len(batch)
                for batch in _recorded_query_batches(
                    (("SELECT 1", (0,) * half), ("SELECT 2", (0,) * (half + 1)))
                )
            ),
            (1, 1),
        )
        with self.assertRaises(ValueError):
            tuple(
                _recorded_query_batches(
                    (("SELECT ?", tuple(range(_MAX_HYDRATION_BATCH_PARAMETERS + 1))),)
                )
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

    def test_replay_rejects_changed_query_order_and_unused_results(self):
        class _Cursor:
            description = (("Value",),)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_parameters):
                return self

            @staticmethod
            def fetchall():
                return ((1,),)

            @staticmethod
            def nextset():
                return True

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

        queries = (("SELECT  A", (1,)), ("SELECT B", ()))
        replay = _execute_recorded_queries(_Connection(), queries)
        with self.assertRaisesRegex(RuntimeError, "unused result sets"):
            replay.assert_consumed()
        with replay.cursor() as cursor:
            # Whitespace differences are not an order change.
            cursor.execute("SELECT A", 1)
        with replay.cursor() as cursor:
            with self.assertRaisesRegex(RuntimeError, "order changed"):
                cursor.execute("SELECT B", 99)
        replay = _execute_recorded_queries(_Connection(), queries)
        with replay.cursor() as cursor:
            with self.assertRaisesRegex(RuntimeError, "order changed"):
                cursor.execute("SELECT B")
        empty = _execute_recorded_queries(_Connection(), ())
        empty.assert_consumed()
        with empty.cursor() as cursor:
            with self.assertRaisesRegex(RuntimeError, "no result set remaining"):
                cursor.execute("SELECT A")

    def test_replay_rejects_batches_with_too_few_result_sets(self):
        class _Cursor:
            description = (("Value",),)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_parameters):
                return self

            @staticmethod
            def fetchall():
                return ()

            @staticmethod
            def nextset():
                return False

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

        with self.assertRaisesRegex(RuntimeError, "too few result sets"):
            _execute_recorded_queries(
                _Connection(), (("SELECT 1", ()), ("SELECT 2", ()))
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
        remote_reader._connections = strict_manager(connections)
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
        self.assertEqual(
            [connection._inner for connection in hydration_connections],
            [connections.lease],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)
        self.assertEqual(
            [
                (change.resource.resource_type, change.resource.resource_id)
                for change in hydrated.batch.changes
            ],
            [
                ("database", "database"),
                ("default_layers_collection", "database"),
                ("job_statuses_collection", "database"),
                ("employees_collection", "database"),
                ("pay_classes_collection", "database"),
                ("conditions_collection", "8"),
                ("areas_collection", "8"),
                ("takeoffs_collection", "8"),
                ("annotations_collection", "8"),
                ("pages_collection", "8"),
                ("layers_collection", "8"),
                ("cover_sheet", "8"),
            ],
        )
        self.assertTrue(
            all(
                change.operation == ChangeOperation.BULK_REFRESH
                and change.commit_version == 19
                for change in hydrated.batch.changes
            )
        )

    def test_initial_reconciliation_without_bid_only_refreshes_database_scope(self):
        class _Cursor:
            def __init__(self):
                self.statements = []

            def execute(self, sql, *_parameters):
                self.statements.append(sql)
                return self

            @staticmethod
            def fetchone():
                return (19,)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()

            def cursor(self):
                return self.cursor_value

            @staticmethod
            def commit():
                pass

            @staticmethod
            def rollback():
                pass

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                yield _Lease()

        remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        remote_reader._requests = _ReadRequestFactory()
        remote_reader._connections = strict_manager(_Connections())
        remote_reader.hydrate_connection = lambda batch, _connection: (
            HydratedDatabaseChangeBatch(batch)
        )
        hydrated = remote_reader.initial_reconciliation("database", None, 19)
        self.assertEqual(
            [change.resource.resource_type for change in hydrated.batch.changes],
            [
                "database",
                "default_layers_collection",
                "job_statuses_collection",
                "employees_collection",
                "pay_classes_collection",
            ],
        )
        self.assertTrue(
            all(change.resource.bid_uid is None for change in hydrated.batch.changes)
        )

    def test_initial_reconciliation_failures_roll_back_and_never_hydrate(self):
        for label, version_row, message in (
            ("checkpoint ahead", (5,), "ahead of the database"),
            ("no row", None, "Change Tracking metadata is unavailable"),
            ("null version", (None,), "Change Tracking metadata is unavailable"),
        ):
            with self.subTest(label=label):

                class _Cursor:
                    def __init__(self):
                        self.statements = []

                    def execute(self, sql, *_parameters):
                        self.statements.append(sql)
                        return self

                    @staticmethod
                    def fetchone():
                        return version_row

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

                    @contextmanager
                    def connection(self, _request, *, autocommit=False):
                        yield self.lease

                connections = _Connections()
                remote_reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
                remote_reader._requests = _ReadRequestFactory()
                remote_reader._connections = strict_manager(connections)

                def hydrate(_batch, _connection):
                    raise AssertionError("must not hydrate after a failed probe")

                remote_reader.hydrate_connection = hydrate
                with self.assertRaisesRegex(ValueError, message):
                    remote_reader.initial_reconciliation("database", 8, 11)
                self.assertEqual(connections.lease.rollbacks, 1)
                # Only the snapshot preamble commit; nothing was committed after.
                self.assertEqual(connections.lease.commits, 1)

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

        schema_value = object()
        cdn_types_value = {"4": object()}
        layers_value = {"3": object()}
        condition_arguments = []

        class _Reader:
            logger = None

            @staticmethod
            def _schema(connection):
                reader_connections.append(connection)
                return schema_value

            def _parse_cdn_types(self, _connection):
                return cdn_types_value

            def _parse_bid_layers_for_bid(self, _connection, bid_uid):
                return layers_value

            def _parse_bid_conditions_for_bid(
                self, _connection, bid_uid, layers, cdn_types, schema
            ):
                condition_arguments.append((bid_uid, layers, cdn_types, schema))
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
        self.assertEqual(len(condition_arguments), 1)
        bid_key, layers_arg, cdn_arg, schema_arg = condition_arguments[0]
        self.assertEqual(bid_key, "8")
        self.assertIs(layers_arg, layers_value)
        self.assertIs(cdn_arg, cdn_types_value)
        self.assertIs(schema_arg, schema_value)
        self.assertEqual(set(hydrated.bid_data_by_bid), {8})
        self.assertEqual(hydrated.bid_data_by_bid[8].bid_takeoffs, [])
        self.assertEqual(hydrated.bid_data_by_bid[8].bid_pages, {})
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
        self.assertEqual(hydrated.job_statuses, (JobStatus("status-1", "Renamed"),))
        self.assertEqual(hydrated.used_job_status_uids, frozenset({"status-1"}))
        self.assertEqual(
            hydrated.employees, (Employee("employee-1", first_name="Renamed"),)
        )
        self.assertEqual(hydrated.used_employee_uids, frozenset({"employee-1"}))
        # Pay classes were not part of the change, so they are not hydrated.
        self.assertIsNone(hydrated.pay_classes)
        self.assertEqual(hydrated.settings_defaults, {})

    def test_pay_class_change_hydrates_pay_classes_without_employees(self):
        pay_class = PayClass("pay-1", "Foreman")

        class _Reader:
            @staticmethod
            def _parse_employees_and_pay_classes(_connection):
                return ([Employee("employee-1")], [pay_class])

        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._reader = _Reader()
        batch = _batch(
            "database",
            "epoch",
            1,
            1,
            (_change("database", ResourceRef("pay_class", "pay-1")),),
        )
        hydrated = reader.hydrate_connection(batch, object())
        self.assertEqual(hydrated.pay_classes, (pay_class,))
        self.assertIsNone(hydrated.employees)
        self.assertIsNone(hydrated.used_employee_uids)
        self.assertIsNone(hydrated.job_statuses)


import logging  # noqa: E402
import re  # noqa: E402
from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    MAX_PARAMETERS,
    Reply,
    StrictSqlServer,
    snapshot_transaction_rules,
)
from ost_visualizer.domain.entities.database_descriptor import (  # noqa: E402
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (  # noqa: E402
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader  # noqa: E402
from ost_visualizer.infrastructure.sql.schema_definition import (  # noqa: E402
    SQL_SCHEMA_V1,
)
from ost_visualizer.infrastructure.sql.write_schema import (  # noqa: E402
    CurrentSqlWriteSchema,
)


def _takeoff_columns():
    return tuple(
        sorted(
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema).get_columns("BidTakeoffs")
        )
    )


class RemoteChangeReaderStrictReplayTests(unittest.TestCase):
    """Takeoff-only hydration through a real SqlProjectReader over the strict model."""

    def _reader(self, server, *, measure_base=0):
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._connections = server.manager()
        project_reader = SqlProjectReader.__new__(SqlProjectReader)
        project_reader.logger = logging.getLogger("tests.sql_remote_replay")
        project_reader._schema_contract = CurrentSqlWriteSchema(
            SQL_SCHEMA_V1.core_schema
        )
        reader._reader = project_reader

        def select(call):
            # one result set per statement of the batch, in statement order
            statements = re.split(r";\s*", call.sql.strip().rstrip(";"))
            sets = [
                (
                    ((measure_base,),)
                    if "SELECT [MeasureBase] FROM [Bids]" in statement
                    else ()
                )
                for statement in statements
            ]
            return Reply.sets(*sets, columns=_takeoff_columns())

        server.on("SELECT", select)
        return reader

    def _hydrate(self, reader, server, bids):
        batch = _batch(
            "database",
            "epoch",
            1,
            2,
            tuple(
                _change("database", ResourceRef("takeoff", "30", bid), sequence=2)
                for bid in bids
            ),
        )
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
        )
        with server.patched():
            with reader._connections.connection(request) as lease:
                return reader.hydrate_connection(batch, lease)

    def test_takeoff_only_batch_replays_every_recorded_query_through_the_driver(self):
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        reader = self._reader(server)
        hydrated = self._hydrate(reader, server, (8, 9))
        self.assertEqual(set(hydrated.conditions_by_bid), {8, 9})
        self.assertEqual(set(hydrated.bid_data_by_bid), {8, 9})
        self.assertEqual(hydrated.bid_data_by_bid[8].bid_takeoffs, [])
        server.assert_everything_closed()
        executed = [
            (sql, params)
            for connection in server.connections
            for cursor in connection.cursors
            for sql, params in cursor.executed
        ]
        # the recorded reads travel as ONE batched statement, not one per query
        self.assertEqual(len(executed), 1)
        self.assertGreater(executed[0][0].count(";"), 4)
        self.assertLessEqual(len(executed[0][1]), MAX_PARAMETERS)

    def test_a_large_takeoff_only_batch_is_split_below_the_query_and_parameter_limits(
        self,
    ):
        server = StrictSqlServer()
        reader = self._reader(server)
        bids = tuple(range(1, 121))
        hydrated = self._hydrate(reader, server, bids)
        self.assertEqual(set(hydrated.bid_data_by_bid), set(bids))
        executed = [
            (sql, params)
            for connection in server.connections
            for cursor in connection.cursors
            for sql, params in cursor.executed
        ]
        self.assertGreater(len(executed), 1)
        sizes = []
        for sql, params in executed:
            sizes.append(len(re.split(r";\s*", sql.strip())))
            self.assertLessEqual(len(params), _MAX_HYDRATION_BATCH_PARAMETERS)
        # one shared CdnTypes read plus six reads per Bid; batches fill to the cap
        self.assertEqual(sum(sizes), 1 + 6 * len(bids))
        self.assertEqual(sizes[0], _MAX_HYDRATION_BATCH_QUERIES)
        self.assertTrue(all(size <= _MAX_HYDRATION_BATCH_QUERIES for size in sizes))
        server.assert_everything_closed()

    def test_replay_cursor_serves_rows_in_order_like_a_driver_cursor(self):
        from ost_visualizer.infrastructure.sql.remote_change_reader import (
            _QueryRecordingCursor,
            _QueryReplayConnection,
        )

        description = (("Value",),)
        replay = _QueryReplayConnection(
            [
                ("SELECT 1", (), description, ((1,), (2,), (3,))),
                ("SELECT 2", (), description, ((9,),)),
                ("SELECT 3", (), description, ()),
            ]
        )
        with replay.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone(), (1,))
            # fetchall continues after the rows already fetched
            self.assertEqual(cursor.fetchall(), ((2,), (3,)))
            self.assertIsNone(cursor.fetchone())
        with replay.cursor() as cursor:
            cursor.execute("SELECT 2")
            self.assertEqual(cursor.fetchall(), ((9,),))
            self.assertEqual(cursor.fetchall(), ())
        with replay.cursor() as cursor:
            cursor.execute("SELECT 3")
            self.assertIsNone(cursor.fetchone())
        replay.assert_consumed()
        # while recording nothing has been read yet
        recording = _QueryRecordingCursor(object(), frozenset())
        self.assertIsNone(recording.fetchone())
        self.assertEqual(recording.fetchall(), ())

    def _initial_reconciliation(self, server, checkpoint, hydrate=None):
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._requests = SimpleNamespace(
            request=lambda _database_id, *, read_only: SqlConnectionRequest(
                SqlServerDatabaseLocation(server="localhost", database="TEST")
            )
        )
        reader._connections = server.manager()
        seen = []

        def hydrate_connection(batch, connection):
            seen.append(connection._connection.commits)
            if hydrate is not None:
                hydrate()
            return HydratedDatabaseChangeBatch(batch)

        reader.hydrate_connection = hydrate_connection
        with server.patched():
            result = reader.initial_reconciliation("database", 8, checkpoint)
        return result, seen

    def test_initial_reconciliation_hydrates_inside_the_snapshot_then_commits_once(
        self,
    ):
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT CHANGE_TRACKING_CURRENT_VERSION()", Reply.rows((19,)))
        result, seen = self._initial_reconciliation(server, 11)
        self.assertEqual(seen, [1])  # only the snapshot preamble committed so far
        self.assertEqual(result.batch.high_water_version, 19)
        self.assertEqual(result.batch.delivered_through_version, 11)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (2, 0))
        self.assertEqual(
            server.event_kinds(1),
            [
                "cursor_open",
                "execute",
                "commit",
                "execute",
                "cursor_close",
                "cursor_open",
                "execute",
                "cursor_close",
                "commit",
                "close",
            ],
        )
        server.assert_everything_closed()

    def test_initial_reconciliation_checkpoint_boundary_and_failed_hydration_roll_back(
        self,
    ):
        # a checkpoint equal to the high-water version is valid; one above is not
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT CHANGE_TRACKING_CURRENT_VERSION()", Reply.rows((19,)))
        result, _seen = self._initial_reconciliation(server, 19)
        self.assertEqual(result.batch.delivered_through_version, 19)
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT CHANGE_TRACKING_CURRENT_VERSION()", Reply.rows((19,)))
        with self.assertRaisesRegex(ValueError, "ahead of the database"):
            self._initial_reconciliation(server, 20)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
        server.assert_everything_closed()
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT CHANGE_TRACKING_CURRENT_VERSION()", Reply.rows((19,)))

        def explode():
            raise RuntimeError("hydration exploded")

        with self.assertRaisesRegex(RuntimeError, "hydration exploded"):
            self._initial_reconciliation(server, 11, hydrate=explode)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
        server.assert_everything_closed()


class _PlanSpy:
    """Reader double that records which parse operations a change set triggers."""

    def __init__(self, cover_sheet=None):
        self.calls = []
        self.cover_sheet = cover_sheet

    def _record(self, name, *args):
        self.calls.append((name, args))

    def _schema(self, connection):
        self.calls.append(("_schema", ()))
        return CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

    def _parse_cdn_types(self, connection):
        self._record("cdn_types")
        return {}

    def _parse_bid_layers_for_bid(self, connection, bid_uid):
        self._record("bid_layers", bid_uid)
        return {}

    def _parse_bid_conditions_for_bid(
        self, connection, bid_uid, layers, cdn_types, schema
    ):
        self._record("conditions", bid_uid)
        return {}

    def _parse_bid_condition_folders_for_bid(self, connection, bid_uid, schema):
        self._record("folders", bid_uid)
        return {}

    def _parse_bid_areas_for_bid(self, connection, bid_uid, schema):
        self._record("areas", bid_uid)
        return {}

    def _parse_bid_takeoffs_for_bid(self, connection, bid_uid, schema):
        self._record("takeoffs", bid_uid)
        return [], {}

    def _parse_bid_pages_for_bid(self, connection, bid_uid, layers, schema):
        self._record("pages", bid_uid)
        return {}

    def _parse_bid_annotations_for_bid(self, connection, bid_uid, layers, schema):
        self._record("annotations", bid_uid)
        return []

    def _parse_page_area_selections_for_bid(self, connection, bid_uid, pages, schema):
        self._record("page_area_selections", bid_uid)
        return {}

    def _parse_bid_layers_for_sidebar(self, connection, bid_uid):
        self._record("sidebar_layers", bid_uid)
        return []

    def parse_file_connection(self, database_id, connection):
        self._record("hierarchy", database_id)
        return HierarchyFileEntry(file_path=database_id), {}

    def _parse_settings_defaults(self, connection):
        self._record("settings_defaults")
        return {}

    def _parse_default_layers(self, connection):
        self._record("default_layers")
        return []

    def _parse_job_statuses(self, connection):
        self._record("job_statuses")
        return []

    def _parse_used_job_status_uids(self, connection):
        self._record("used_job_statuses")
        return set()

    def _parse_employees_and_pay_classes(self, connection):
        self._record("employees_and_pay_classes")
        return [], []

    def _parse_used_employee_uids(self, connection):
        self._record("used_employees")
        return set()

    def _parse_cover_sheet_data(self, connection, bid_uid):
        self._record("cover_sheet", bid_uid)
        return self.cover_sheet

    def _parse_pages_with_delete_content(self, connection, bid_uid):
        self._record("delete_content", bid_uid)
        return set()

    def names(self):
        return sorted((name, args) for name, args in self.calls if name != "_schema")


class _PlanSqlSpy(_PlanSpy, SqlProjectReader):
    """Same spy, but a SqlProjectReader instance (enables the takeoff-only path)."""

    def __init__(self, cover_sheet=None):
        _PlanSpy.__init__(self, cover_sheet)


def _hydrate_plan(spy, changes, *, bids=(8, 9)):
    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        description = (("UID",),)

        def execute(self, sql, *_parameters):
            self.sql = sql

        def fetchall(self):
            return [(bid,) for bid in bids]

    class _Connection:
        @staticmethod
        def cursor():
            return _Cursor()

    reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
    reader._reader = spy
    batch = _batch(
        "database",
        "epoch",
        1,
        2,
        tuple(_change("database", resource) for resource in changes),
    )
    return reader.hydrate_connection(batch, _Connection()), batch


class RemoteChangeReaderHydrationPlanTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep: which changes hydrate what."""

    def _plan(self, *changes, spy=None, bids=(8, 9)):
        spy = spy or _PlanSpy()
        hydrated, _batch_value = _hydrate_plan(spy, changes, bids=bids)
        return spy.names(), hydrated

    def test_each_resource_family_hydrates_exactly_its_own_reads(self):
        bid = lambda kind, uid="1", bid_uid=8: ResourceRef(
            kind, uid, bid_uid
        )  # noqa: E731
        database = lambda kind: ResourceRef(kind, "database")  # noqa: E731
        cases = (
            (
                "condition",
                bid("condition"),
                [
                    ("bid_layers", ("8",)),
                    ("cdn_types", ()),
                    ("conditions", ("8",)),
                    ("folders", ("8",)),
                ],
            ),
            (
                "condition folder",
                bid("condition_folder"),
                [
                    ("bid_layers", ("8",)),
                    ("cdn_types", ()),
                    ("conditions", ("8",)),
                    ("folders", ("8",)),
                ],
            ),
            ("area", bid("area"), [("areas", ("8",))]),
            ("areas collection", bid("areas_collection", "8"), [("areas", ("8",))]),
            (
                "page",
                bid("page"),
                [
                    ("bid_layers", ("8",)),
                    ("delete_content", ("8",)),
                    ("page_area_selections", ("8",)),
                    ("pages", ("8",)),
                    ("takeoffs", ("8",)),
                ],
            ),
            (
                "pages collection",
                bid("pages_collection", "8"),
                [
                    ("bid_layers", ("8",)),
                    ("delete_content", ("8",)),
                    ("page_area_selections", ("8",)),
                    ("pages", ("8",)),
                    ("takeoffs", ("8",)),
                ],
            ),
            (
                "annotation",
                bid("annotation", "rect/1"),
                [("annotations", ("8",)), ("bid_layers", ("8",))],
            ),
            (
                "layers collection",
                bid("layers_collection", "8"),
                [("sidebar_layers", ("8",))],
            ),
            ("layer", bid("layer"), [("sidebar_layers", ("8",))]),
            (
                "takeoff",
                bid("takeoff"),
                [
                    ("bid_layers", ("8",)),
                    ("cdn_types", ()),
                    ("conditions", ("8",)),
                    ("folders", ("8",)),
                    ("pages", ("8",)),
                    ("takeoffs", ("8",)),
                ],
            ),
            (
                "cover sheet",
                bid("cover_sheet", "8"),
                [("cover_sheet", ("8",)), ("delete_content", ("8",))],
            ),
            (
                "default layers",
                database("default_layers_collection"),
                [("default_layers",)],
            ),
            (
                "job status",
                database("job_statuses_collection"),
                [
                    ("hierarchy", ("database",)),
                    ("job_statuses",),
                    ("settings_defaults",),
                    ("used_job_statuses",),
                ],
            ),
            (
                "employee",
                ResourceRef("employee", "5"),
                [
                    ("employees_and_pay_classes",),
                    ("hierarchy", ("database",)),
                    ("settings_defaults",),
                    ("used_employees",),
                ],
            ),
            (
                "pay class",
                ResourceRef("pay_class", "5"),
                [("employees_and_pay_classes",)],
            ),
            (
                "project",
                ResourceRef("project", "5"),
                [("hierarchy", ("database",)), ("settings_defaults",)],
            ),
            (
                "bid row",
                ResourceRef("bid", "8", 8),
                [("hierarchy", ("database",)), ("settings_defaults",)],
            ),
            (
                "condition type",
                ResourceRef("condition_type", "5"),
                [("hierarchy", ("database",)), ("settings_defaults",)],
            ),
        )
        for label, resource, expected in cases:
            with self.subTest(label=label):
                names, _hydrated = self._plan(resource)
                normalised = sorted((name, args) for name, args in names)
                self.assertEqual(
                    normalised,
                    sorted(
                        (item[0], item[1] if len(item) > 1 else ()) for item in expected
                    ),
                )

    def test_bid_scoped_changes_without_a_bid_that_cannot_expand_hydrate_nothing(self):
        # (a bid-less cover_sheet IS a global change and expands to every bid)
        for kind in ("condition", "page", "takeoff", "annotation", "layer", "area"):
            with self.subTest(kind=kind):
                names, hydrated = self._plan(ResourceRef(kind, "1"))
                self.assertEqual(names, [])
                self.assertEqual(hydrated.conditions_by_bid, {})
                self.assertEqual(hydrated.bid_data_by_bid, {})

    def test_database_level_collections_expand_to_every_bid_beside_ordinary_changes(
        self,
    ):
        names, hydrated = self._plan(
            ResourceRef("areas_collection", "database"),
            ResourceRef("annotation", "rect/1", 3),
            bids=(8, 9),
        )
        self.assertEqual(
            names,
            [
                ("annotations", ("3",)),
                ("areas", ("8",)),
                ("areas", ("9",)),
                ("bid_layers", ("3",)),
            ],
        )
        self.assertEqual(set(hydrated.areas_by_bid), {8, 9})
        self.assertEqual(set(hydrated.bid_data_by_bid), {3})

    def test_a_database_with_no_bids_drops_a_global_collection_change(self):
        names, hydrated = self._plan(
            ResourceRef("takeoffs_collection", "database"), bids=()
        )
        self.assertEqual(names, [])
        self.assertEqual(hydrated.bid_data_by_bid, {})

    def test_content_families_are_collected_per_bid_not_shared_between_bids(self):
        names, hydrated = self._plan(
            ResourceRef("page", "1", 8), ResourceRef("annotation", "rect/1", 9)
        )
        self.assertIn(("page_area_selections", ("8",)), names)
        self.assertNotIn(("page_area_selections", ("9",)), names)
        self.assertIn(("annotations", ("9",)), names)
        self.assertNotIn(("annotations", ("8",)), names)
        self.assertNotIn(("pages", ("9",)), names)
        self.assertEqual(set(hydrated.bid_data_by_bid), {8, 9})

    def test_cover_sheets_are_kept_only_when_the_reader_returns_one(self):
        present = _PlanSpy(cover_sheet={"bid": "8"})
        _names, hydrated = self._plan(ResourceRef("cover_sheet", "8", 8), spy=present)
        self.assertEqual(hydrated.cover_sheet_by_bid, {8: {"bid": "8"}})
        self.assertEqual(hydrated.page_delete_content_uids_by_bid, {8: frozenset()})
        _names, hydrated = self._plan(
            ResourceRef("cover_sheet", "8", 8), spy=_PlanSpy()
        )
        self.assertEqual(hydrated.cover_sheet_by_bid, {})

    def test_takeoff_only_replay_is_used_only_when_every_change_is_a_takeoff_of_a_sql_reader(
        self,
    ):
        takeoff = ResourceRef("takeoff", "30", 8)
        replayed = _PlanSqlSpy()
        names, hydrated = self._plan(takeoff, spy=replayed)
        # recorded once, then replayed once: each read appears twice
        self.assertEqual(
            sorted(name for name, _args in names),
            sorted(
                [
                    "cdn_types",
                    "cdn_types",
                    "bid_layers",
                    "bid_layers",
                    "conditions",
                    "conditions",
                    "folders",
                    "folders",
                    "takeoffs",
                    "takeoffs",
                    "pages",
                    "pages",
                ]
            ),
        )
        self.assertEqual(set(hydrated.bid_data_by_bid), {8})
        # a non-takeoff change beside it (same bid) forces the general path
        for other in (
            ResourceRef("page", "20", 8),
            ResourceRef("area", "20", 8),
            ResourceRef("condition", "20", 8),
            ResourceRef("cover_sheet", "8", 8),
            ResourceRef("employee", "20"),
            ResourceRef("default_layers_collection", "database"),
            ResourceRef("pay_class", "20"),
            ResourceRef("condition", "20", 9),
        ):
            with self.subTest(other=other.resource_type):
                spy = _PlanSqlSpy()
                names, _hydrated = self._plan(takeoff, other, spy=spy)
                counts = {}
                for name, args in names:
                    counts[(name, args)] = counts.get((name, args), 0) + 1
                self.assertEqual(counts.get(("takeoffs", ("8",))), 1, other)
        # the same takeoff with a plain (non-SQL) reader never uses the replay path
        names, _hydrated = self._plan(takeoff, spy=_PlanSpy())
        self.assertEqual(sum(1 for name, _a in names if name == "takeoffs"), 1)

    def test_takeoff_only_hydration_demands_that_every_recorded_read_is_replayed(self):
        class _Skipping(_PlanSqlSpy):
            def _parse_cdn_types(self, connection):
                self._record("cdn_types")
                if not getattr(self, "_recorded_once", False):
                    self._recorded_once = True
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                # the replay phase "forgets" to run the recorded read
                return {}

        with self.assertRaisesRegex(RuntimeError, "unused result sets"):
            self._plan(ResourceRef("takeoff", "30", 8), spy=_Skipping())

    def test_reader_construction_wires_the_descriptor_factory_and_one_shared_manager(
        self,
    ):
        from ost_visualizer.domain.entities.database_descriptor import (
            DatabaseDescriptor,
        )
        from ost_visualizer.infrastructure.database.descriptor_registry import (
            DatabaseDescriptorRegistry,
        )
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="DB"),
            schema_version=1,
        )
        registry.register(descriptor)
        reader = SqlRemoteChangeReader(registry, SimpleNamespace())
        request = reader._requests.request(descriptor.database_id, read_only=True)
        self.assertEqual(request.location, descriptor.sql_location)
        self.assertIsInstance(reader._connections, SqlConnectionManager)
        self.assertIsInstance(reader._reader, SqlProjectReader)
        self.assertIs(reader._reader._sql_connections, reader._connections)
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        reader = SqlRemoteChangeReader(
            registry, SimpleNamespace(), connection_manager=manager
        )
        self.assertIs(reader._connections, manager)
        self.assertIs(reader._reader._sql_connections, manager)

    def test_initial_reconciliation_names_the_database_resource_by_its_database_id(
        self,
    ):
        server = StrictSqlServer()
        snapshot_transaction_rules(server)
        server.on("SELECT CHANGE_TRACKING_CURRENT_VERSION()", Reply.rows((5,)))
        reader = SqlRemoteChangeReader.__new__(SqlRemoteChangeReader)
        reader._requests = SimpleNamespace(
            request=lambda _database_id, *, read_only: SqlConnectionRequest(
                SqlServerDatabaseLocation(server="localhost", database="TEST")
            )
        )
        reader._connections = server.manager()
        reader.hydrate_connection = (
            lambda batch, _connection: HydratedDatabaseChangeBatch(batch)
        )
        with server.patched():
            result = reader.initial_reconciliation("db-42", None, 5)
        first = result.batch.changes[0].resource
        self.assertEqual(
            (first.resource_type, first.resource_id), ("database", "db-42")
        )


class RemoteChangeReaderReplayContractTests(unittest.TestCase):
    """Survivors in the recording/replay classes and the batch splitter."""

    def test_batch_limits_are_pinned_below_the_driver_limit(self):
        self.assertEqual(_MAX_HYDRATION_BATCH_QUERIES, 400)
        self.assertEqual(_MAX_HYDRATION_BATCH_PARAMETERS, 2000)
        self.assertLess(_MAX_HYDRATION_BATCH_PARAMETERS, 2100)
        exactly = tuple((f"SELECT {i}", ()) for i in range(400))
        self.assertEqual([len(b) for b in _recorded_query_batches(exactly)], [400])
        over = exactly + (("SELECT 400", ()),)
        self.assertEqual([len(b) for b in _recorded_query_batches(over)], [400, 1])

    def test_a_single_query_at_the_parameter_cap_is_one_batch_and_batches_restart_at_zero(
        self,
    ):
        cap = _MAX_HYDRATION_BATCH_PARAMETERS
        single = (("SELECT ?", (0,) * cap),)
        self.assertEqual([len(b) for b in _recorded_query_batches(single)], [1])
        half = cap // 2
        four = tuple((f"SELECT {i}", (0,) * half) for i in range(4))
        # each batch holds exactly two half-size queries (the count restarts at zero)
        self.assertEqual([len(b) for b in _recorded_query_batches(four)], [2, 2])

    def test_batches_carry_the_cursor_description_and_none_means_no_columns(self):
        class _Cursor:
            def __init__(self, descriptions):
                self._descriptions = list(descriptions)
                self.description = self._descriptions[0]
                self._index = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_parameters):
                return self

            @staticmethod
            def fetchall():
                return ((1,),)

            def nextset(self):
                self._index += 1
                self.description = self._descriptions[self._index]
                return True

        class _Connection:
            def cursor(self_inner):
                return _Cursor([(("A", None),), None])

        replay = _execute_recorded_queries(
            _Connection(), (("SELECT 1", ()), ("SELECT 2", ()))
        )
        with replay.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.description, (("A", None),))
            self.assertEqual(cursor.fetchone(), (1,))
        with replay.cursor() as cursor:
            cursor.execute("SELECT 2")
            self.assertEqual(cursor.description, ())

    def test_replay_rejects_a_different_statement_even_with_identical_parameters(self):
        from ost_visualizer.infrastructure.sql.remote_change_reader import (
            _QueryReplayConnection,
        )

        replay = _QueryReplayConnection([("SELECT A", (1,), (), ())])
        with replay.cursor() as cursor:
            with self.assertRaisesRegex(RuntimeError, "order changed"):
                cursor.execute("SELECT B", 1)

    def test_recording_and_replay_cursors_are_driver_like_context_managers(self):
        from ost_visualizer.infrastructure.sql.remote_change_reader import (
            _QueryRecordingConnection,
            _QueryReplayConnection,
            _normalized_sql,
        )

        self.assertEqual(_normalized_sql("  SELECT\n  a ,\tb  "), "SELECT a , b")
        recording = _QueryRecordingConnection(frozenset({"UID", "Name"}))
        with recording.cursor() as cursor:
            self.assertIs(
                cursor.execute("SELECT [UID] FROM [BidTakeoffs] WHERE 1=1", 8), cursor
            )
            self.assertEqual(cursor.description, (("Name",), ("UID",)))
            self.assertIs(cursor.__exit__(None, None, None), False)
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.description, ())
        self.assertEqual(
            recording.queries,
            [("SELECT [UID] FROM [BidTakeoffs] WHERE 1=1", (8,)), ("SELECT 1", ())],
        )
        with self.assertRaisesRegex(ValueError, "propagates"):
            with recording.cursor():
                raise ValueError("propagates")
        replay = _QueryReplayConnection([("SELECT 1", (), (("V",),), ((1,),))])
        cursor = replay.cursor()
        self.assertEqual(cursor.description, ())
        self.assertIsNone(cursor.fetchone())
        self.assertEqual(cursor.fetchall(), ())
        self.assertIs(cursor.execute("SELECT 1"), cursor)
        self.assertEqual(cursor.description, (("V",),))
        self.assertIs(cursor.__exit__(None, None, None), False)
        with self.assertRaisesRegex(ValueError, "propagates"):
            with replay.cursor():
                raise ValueError("propagates")


class RemoteChangeReaderLastSurvivorTests(unittest.TestCase):
    def test_a_bid_less_page_beside_a_real_change_does_not_hydrate_a_phantom_bid(self):
        spy = _PlanSpy()
        hydrated, _batch_value = _hydrate_plan(
            spy, (ResourceRef("page", "1"), ResourceRef("annotation", "rect/1", 9))
        )
        names = spy.names()
        self.assertNotIn(("delete_content", ("None",)), names)
        self.assertEqual(set(hydrated.bid_data_by_bid), {9})
        self.assertEqual(hydrated.page_delete_content_uids_by_bid, {})

    def test_cursors_reset_their_state_per_statement_and_start_empty(self):
        from ost_visualizer.infrastructure.sql.remote_change_reader import (
            _QueryRecordingCursor,
            _QueryReplayConnection,
        )

        self.assertEqual(_QueryRecordingCursor(object(), frozenset()).description, ())
        replay = _QueryReplayConnection(
            [
                ("SELECT 1", (), (("A",),), ((1,), (2,))),
                ("SELECT 2", (), (("B",),), ((7,), (8,))),
            ]
        )
        cursor = replay.cursor()
        cursor.execute("SELECT 1")
        self.assertEqual(cursor.fetchone(), (1,))
        # the second statement on the SAME cursor starts at its first row
        cursor.execute("SELECT 2")
        self.assertEqual(cursor.description, (("B",),))
        self.assertEqual(cursor.fetchone(), (7,))
        self.assertEqual(cursor.fetchall(), ((8,),))
