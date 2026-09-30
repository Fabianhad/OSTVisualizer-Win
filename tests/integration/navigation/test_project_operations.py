import threading
import unittest
from types import SimpleNamespace
from ost_visualizer.application.services.navigation_load_service import (
    NavigationLoadService,
    NavigationLoadState,
)
from ost_visualizer.application.services.project_operations_service import (
    ProjectOperationsService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1


class _Registry:
    def __init__(self, descriptors):
        self._descriptors = {item.database_id: item for item in descriptors}

    def resolve(self, locator):
        return self._descriptors.get(locator)


class _QueuedDispatcher:
    def __init__(self):
        self.calls = []
        self.ready = threading.Event()

    def dispatch(self, callback, payload):
        self.calls.append((callback, payload))
        self.ready.set()

    def drain(self):
        calls = list(self.calls)
        self.calls.clear()
        self.ready.clear()
        for callback, payload in calls:
            callback(payload)


def _sql_descriptor(database="OSTV_IT_NAVIGATION"):
    return DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database=database),
        schema_version=SQL_SCHEMA_V1.version,
    )


class ProjectOperationsNavigationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.descriptor = _sql_descriptor()
        self.dispatcher = _QueuedDispatcher()
        self.service = NavigationLoadService(
            _Registry([self.descriptor]), self.dispatcher
        )

    def tearDown(self):
        self.service.cleanup()

    def test_mdb_bid_load_uses_same_projection_contract_without_fake_async(self):
        mdb_descriptor = DatabaseDescriptor.for_access("C:/temporary/navigation.mdb")
        service = NavigationLoadService(_Registry([mdb_descriptor]), self.dispatcher)
        try:
            calls = []

            class _UseCase:
                def execute(self, requested):
                    calls.append(("execute", threading.get_ident(), requested))
                    return True

                def prepare(self, _requested):
                    raise AssertionError("MDB navigation must remain immediate")

                def apply_prepared(self, _requested, _result):
                    raise AssertionError("MDB navigation must remain immediate")

            operations = ProjectOperationsService(SimpleNamespace(), service)
            operations.configure_use_cases(
                SimpleNamespace(),
                lambda _path=None: True,
                _UseCase(),
                lambda _path=None: True,
            )
            completed = []
            bid_ref = BidRef(mdb_descriptor.database_id, "17")
            self.assertFalse(
                operations.request_load_bid(
                    bid_ref, lambda *args: completed.append(args)
                )
            )
            self.assertEqual(calls, [("execute", threading.get_ident(), bid_ref)])
            self.assertEqual(completed, [(True, "")])
            self.assertEqual(self.dispatcher.calls, [])
        finally:
            service.cleanup()

    def test_project_operations_applies_prepared_bid_only_on_dispatch_thread(self):
        calling_thread = threading.get_ident()
        thread_ids = []
        bid_ref = BidRef(self.descriptor.database_id, "17")

        class _UseCase:
            def prepare(self, requested):
                thread_ids.append(("prepare", threading.get_ident(), requested))
                return BidLoadResult()

            def apply_prepared(self, requested, result):
                thread_ids.append(("apply", threading.get_ident(), requested, result))
                return True

            def execute(self, _requested):
                raise AssertionError("SQL navigation must not execute synchronously")

        operations = ProjectOperationsService(SimpleNamespace(), self.service)
        operations.configure_use_cases(
            SimpleNamespace(),
            lambda _path=None: True,
            _UseCase(),
            lambda _path=None: True,
        )
        completed = []
        self.assertTrue(
            operations.request_load_bid(bid_ref, lambda *args: completed.append(args))
        )
        self.assertTrue(self.dispatcher.ready.wait(1.0))
        self.dispatcher.drain()
        self.assertEqual(thread_ids[0][0], "prepare")
        self.assertNotEqual(thread_ids[0][1], calling_thread)
        self.assertEqual(thread_ids[1][0:2], ("apply", calling_thread))
        self.assertEqual(completed, [(True, "")])
