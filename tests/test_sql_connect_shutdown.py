import threading
import unittest
from unittest.mock import Mock, patch
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from tests.test_sql_collaboration_phase4 import (
    SQL_SCHEMA_V1,
    DatabaseCapabilityService,
    DatabaseDescriptor,
    DatabaseDescriptorRegistry,
    DatabaseSessionRegistry,
    SqlServerDatabaseLocation,
    _CollaborationStore,
    _coordinator,
    _Dispatcher,
    _EventBus,
    _PermissionProbe,
    _Reconciliation,
    _RemoteReader,
    _shutdown_coordinator,
    _token_service,
)


class ConnectShutdownTests(unittest.TestCase):
    def test_connection_returning_after_stop_is_closed_without_session_sql(self):
        entered = threading.Event()
        release = threading.Event()
        stop = threading.Event()
        finished = threading.Event()
        raw = Mock()
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
        )
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = Mock()
        store._requests.request.return_value = request
        store._connections = SqlConnectionManager(
            drivers=["ODBC Driver 18 for SQL Server"]
        )
        results = []
        errors = []

        def connect(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Connection probe was not released")
            return raw

        def run():
            try:
                results.append(
                    store.start_session(
                        "database",
                        "session",
                        "client",
                        "user",
                        "machine",
                        "version",
                        stop_requested=stop.is_set,
                    )
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=connect,
        ) as connector:
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                stop.set()
                self.assertFalse(finished.is_set())
                release.set()
                self.assertTrue(finished.wait(2))
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, [None])
            raw.close.assert_called_once_with()
            raw.cursor.assert_not_called()
            raw.commit.assert_not_called()
            self.assertEqual(
                connector.call_args.kwargs, {"autocommit": False, "timeout": 10}
            )

    def test_stop_before_connect_does_not_open_connection(self):
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = Mock()
        store._connections = Mock()
        self.assertIsNone(
            store.start_session(
                "database",
                "session",
                "client",
                "user",
                "machine",
                "version",
                stop_requested=lambda: True,
            )
        )
        store._connections.connection.assert_not_called()

    def test_login_timeout_is_separate_from_command_timeout(self):
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(
                server="localhost",
                database="TEST",
                connection_timeout_seconds=7,
                command_timeout_seconds=43,
            )
        )
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        raw = Mock()
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            return_value=raw,
        ) as connect:
            with manager.connection(request) as lease:
                self.assertIsNotNone(lease)
                self.assertEqual(raw.timeout, 43)
            self.assertEqual(connect.call_args.kwargs["timeout"], 7)
            raw.close.assert_called_once_with()

    def test_late_startup_result_does_not_start_more_work(self):
        for outcome in ("committed", "cancelled", "os_error", "login_timeout"):
            with self.subTest(outcome=outcome):
                entered = threading.Event()
                release = threading.Event()
                finished = threading.Event()

                class Store(_CollaborationStore):
                    def start_session(self, *args, **kwargs):
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("Startup probe was not released")
                        if outcome == "cancelled":
                            return None
                        if outcome == "os_error":
                            raise OSError("connection failed after stop")
                        if outcome == "login_timeout":
                            raise SqlInfrastructureError(
                                SqlErrorDetails(SqlErrorCode.TIMEOUT, "Login timed out")
                            )
                        return super().start_session(*args, **kwargs)

                descriptors = DatabaseDescriptorRegistry()
                descriptor = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(server="localhost", database="TEST"),
                    schema_version=SQL_SCHEMA_V1.version,
                )
                descriptors.register(descriptor)
                store = Store()
                tokens, drafts = _token_service()
                reader = _RemoteReader()
                coordinator = _coordinator(
                    descriptors,
                    store,
                    reader,
                    _Dispatcher(),
                    _Reconciliation(),
                    DatabaseCapabilityService(descriptors, _PermissionProbe()),
                    DatabaseSessionRegistry(),
                    tokens,
                    drafts,
                    _EventBus(),
                    SQL_SCHEMA_V1.version,
                )
                try:
                    with (
                        patch.object(
                            tokens, "load_database", wraps=tokens.load_database
                        ) as load,
                        patch.object(
                            reader,
                            "initial_reconciliation",
                            wraps=reader.initial_reconciliation,
                        ) as hydrate,
                        patch.object(coordinator, "_on_session_started") as started,
                        patch.object(
                            store, "start_session", wraps=store.start_session
                        ) as connect,
                    ):
                        self.assertTrue(
                            coordinator.start_database(descriptor.database_id)
                        )
                        self.assertTrue(entered.wait(2))
                        coordinator.request_shutdown(lambda *_: finished.set())
                        self.assertFalse(finished.is_set())
                        release.set()
                        self.assertTrue(finished.wait(2))
                        self.assertEqual(connect.call_count, 1)
                        load.assert_not_called()
                        hydrate.assert_not_called()
                        started.assert_not_called()
                        self.assertFalse(store.polled.is_set())
                        self.assertEqual(store.closed.is_set(), outcome == "committed")
                finally:
                    release.set()
                    _shutdown_coordinator(coordinator)
