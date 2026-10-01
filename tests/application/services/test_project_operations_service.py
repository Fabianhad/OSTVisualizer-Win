import unittest
from unittest.mock import Mock, call
from ost_visualizer.application.services.navigation_load_service import (
    NavigationLoadResult,
    NavigationLoadService,
    NavigationLoadState,
)
from ost_visualizer.application.services.project_operations_service import (
    ILoadBidUseCase,
    ILoadFileUseCase,
    ProjectOperationsService,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    PreparedBidLoad,
)
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.project_data_service import ProjectDataService


class ProjectOperationsNavigationContractTests(unittest.TestCase):
    def setUp(self):
        self.navigation = Mock(spec=NavigationLoadService)
        self.navigation.uses_background_reads.return_value = False
        self.navigation.state.return_value = NavigationLoadResult(
            "", 0, "", "", NavigationLoadState.EMPTY
        )
        self.service = ProjectOperationsService(
            Mock(spec=ProjectDataService), self.navigation
        )
        self.files = Mock(spec=ILoadFileUseCase, last_error="")
        self.files.execute.return_value = True
        self.bids = Mock(spec=ILoadBidUseCase)
        self.bids.execute.return_value = True
        self.bids.prepare.return_value = PreparedBidLoad(BidLoadResult(), None)
        self.bids.apply_prepared.return_value = True
        self.unload = Mock(return_value=True)
        self.reload = Mock(return_value=True)
        self.service.configure_use_cases(
            self.files, self.unload, self.bids, self.reload
        )

    def test_project_operations_has_no_synchronous_bid_navigation_entry_point(self):
        self.assertFalse(hasattr(ProjectOperationsService, "load_bid"))

    def test_unconfigured_operations_reject_before_dispatch(self):
        service = ProjectOperationsService(
            Mock(spec=ProjectDataService), self.navigation
        )
        for operation, message in (
            (lambda: service.load_file("db"), "LoadFileUseCase"),
            (lambda: service.unload_file(), "UnloadFileUseCase"),
            (lambda: service.reload_database(), "ReloadDatabaseUseCase"),
            (
                lambda: service.request_load_bid(BidRef("db", "1"), self.fail),
                "LoadBidUseCase",
            ),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                RuntimeError, message + " is not configured"
            ):
                operation()
        self.assertEqual(self.navigation.mock_calls, [])

    def test_file_load_reports_latest_error_and_success_clears_old_error(self):
        self.files.execute.return_value = False
        self.files.last_error = "denied"
        self.assertIs(self.service.load_file("first"), False)
        self.assertEqual(self.service.last_error, "denied")
        self.files.execute.return_value = True
        self.files.last_error = None
        self.assertIs(self.service.load_file("second"), True)
        self.assertEqual(self.service.last_error, "")
        self.files.execute.side_effect = OSError("unavailable")
        self.service.last_error = "old"
        with self.assertRaisesRegex(OSError, "unavailable"):
            self.service.load_file("third")
        self.assertEqual(self.service.last_error, "")
        self.assertEqual(
            self.files.execute.call_args_list,
            [call("first"), call("second"), call("third")],
        )

    def test_reload_and_unload_forward_exact_target_and_result(self):
        for handler, operation in (
            (self.reload, self.service.reload_database),
            (self.unload, self.service.unload_file),
        ):
            for target, success in ((None, True), ("other-db", False)):
                with self.subTest(target=target, operation=operation.__name__):
                    handler.return_value = success
                    self.assertIs(operation(target), success)
            self.assertEqual(handler.call_args_list, [call(None), call("other-db")])
        self.assertEqual(self.navigation.mock_calls, [])

    def test_mdb_navigation_reports_success_failure_and_exception_once(self):
        ref = BidRef("db.mdb", "1")
        for result in (True, False, OSError("read failed"), RuntimeError()):
            with self.subTest(result=result):
                self.bids.execute.side_effect = (
                    result if isinstance(result, Exception) else None
                )
                self.bids.execute.return_value = result
                completed = []
                self.assertIs(
                    self.service.request_load_bid(
                        ref, lambda *args: completed.append(args)
                    ),
                    False,
                )
                expected = (
                    (False, str(result) or type(result).__name__)
                    if isinstance(result, Exception)
                    else (result, "")
                )
                self.assertEqual(completed, [expected])
        self.assertEqual(self.bids.execute.call_args_list, [call(ref)] * 4)
        self.bids.prepare.assert_not_called()
        self.bids.apply_prepared.assert_not_called()
        self.navigation.submit.assert_not_called()

    def test_sql_navigation_queues_captured_read_then_applies_prepared_value(self):
        self.navigation.uses_background_reads.return_value = True
        ref = BidRef("sql-db", "1")
        completed = []
        self.assertIs(
            self.service.request_load_bid(ref, lambda *args: completed.append(args)),
            True,
        )
        self.navigation.uses_background_reads.assert_called_once_with("sql-db")
        self.assertEqual(self.navigation.submit.call_count, 1)
        database, bid, work, callback = self.navigation.submit.call_args.args
        self.assertEqual((database, bid), ("sql-db", "1"))
        self.assertEqual(completed, [])
        self.assertEqual(self.bids.mock_calls, [])
        prepared = work()
        self.assertIs(prepared, self.bids.prepare.return_value)
        callback(
            NavigationLoadResult(
                "request", 1, database, bid, NavigationLoadState.READY, prepared
            )
        )
        self.assertEqual(
            self.bids.mock_calls,
            [call.prepare(ref), call.apply_prepared(ref, prepared)],
        )
        self.assertEqual(completed, [(True, "")])

    def test_sql_read_failure_and_missing_value_never_apply_prepared_state(self):
        self.navigation.uses_background_reads.return_value = True
        ref = BidRef("sql-db", "1")
        for state, message in (
            (NavigationLoadState.FAILED, "server unavailable"),
            (NavigationLoadState.CANCELLED, ""),
            (NavigationLoadState.READY, ""),
        ):
            with self.subTest(state=state):
                completed = []
                self.service.request_load_bid(ref, lambda *args: completed.append(args))
                callback = self.navigation.submit.call_args.args[3]
                callback(
                    NavigationLoadResult(
                        "request", 1, ref.file_path, ref.bid_uid, state, message=message
                    )
                )
                self.assertEqual(
                    completed, [(False, message or "The SQL bid could not be loaded.")]
                )
        self.assertEqual(self.bids.mock_calls, [])

    def test_sql_projection_rejection_and_exception_report_one_failure(self):
        self.navigation.uses_background_reads.return_value = True
        ref = BidRef("sql-db", "1")
        prepared = self.bids.prepare.return_value
        for outcome in (False, RuntimeError("projection failed")):
            with self.subTest(outcome=outcome):
                self.bids.apply_prepared.reset_mock()
                self.bids.apply_prepared.return_value = outcome
                self.bids.apply_prepared.side_effect = (
                    outcome if isinstance(outcome, Exception) else None
                )
                completed = []
                self.service.request_load_bid(ref, lambda *args: completed.append(args))
                callback = self.navigation.submit.call_args.args[3]
                result = NavigationLoadResult(
                    "request",
                    1,
                    ref.file_path,
                    ref.bid_uid,
                    NavigationLoadState.READY,
                    prepared,
                )
                if isinstance(outcome, Exception):
                    with self.assertLogs(
                        "ost_visualizer.application.services.project_operations_service",
                        level="ERROR",
                    ):
                        callback(result)
                else:
                    callback(result)
                self.bids.apply_prepared.assert_called_once_with(ref, prepared)
                self.assertEqual(
                    completed,
                    [
                        (
                            False,
                            (
                                str(outcome)
                                if isinstance(outcome, Exception)
                                else "The SQL bid could not be loaded."
                            ),
                        )
                    ],
                )

    def test_completion_exception_is_not_reinterpreted_as_second_load_result(self):
        for background in (False, True):
            with self.subTest(background=background):
                self.navigation.uses_background_reads.return_value = background
                completed = []
                ref = BidRef("db", "1")

                def completion(success, message):
                    completed.append((success, message))
                    raise RuntimeError("editor closed during projection")

                with self.assertRaisesRegex(
                    RuntimeError, "editor closed during projection"
                ):
                    self.service.request_load_bid(ref, completion)
                    if background:
                        callback = self.navigation.submit.call_args.args[3]
                        callback(
                            NavigationLoadResult(
                                "request",
                                1,
                                ref.file_path,
                                ref.bid_uid,
                                NavigationLoadState.READY,
                                self.bids.prepare.return_value,
                            )
                        )
                self.assertEqual(completed, [(True, "")])

    def test_cancel_and_loading_state_use_current_navigation_service(self):
        for state in NavigationLoadState:
            with self.subTest(state=state):
                self.navigation.state.return_value = NavigationLoadResult(
                    "request", 1, "db", "1", state
                )
                self.assertIs(
                    self.service.navigation_load_in_progress(),
                    state == NavigationLoadState.LOADING,
                )
        self.service.cancel_navigation_load("db")
        self.service.cancel_navigation_load()
        self.assertEqual(self.navigation.cancel.call_args_list, [call("db"), call("")])
