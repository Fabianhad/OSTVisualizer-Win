import unittest
from unittest.mock import Mock, patch
from ost_visualizer.application.use_cases.project.load_file_use_case import (
    LoadFileUseCase,
)
from ost_visualizer.application.use_cases.project.load_files_from_config_use_case import (
    LoadFilesFromConfigUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.domain.repositories.i_file_state_repository import (
    IFileStateRepository,
)

EXISTS_TARGET = (
    "ost_visualizer.application.use_cases.project.load_files_from_config_use_case"
    ".os.path.exists"
)


def _sql_entry(database, is_checked=True):
    return FileEntry.for_descriptor(
        DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation("unused", database), schema_version=1
        ),
        is_checked=is_checked,
    )


class LoadFilesFromConfigUseCaseExecuteTests(unittest.TestCase):
    def test_missing_or_corrupt_saved_state_does_not_attempt_any_load(self):
        for error in (
            FileNotFoundError(),
            OSError("unreadable"),
            ValueError("invalid"),
        ):
            with self.subTest(error=type(error).__name__):
                repository = Mock(spec=IFileStateRepository)
                loader = Mock(spec=LoadFileUseCase)
                repository.load.side_effect = error
                self.assertEqual(
                    LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                        {DatabaseBackend.ACCESS}
                    ),
                    [],
                )
                loader.execute.assert_not_called()

    def test_empty_saved_state_or_no_checked_matching_entries_loads_nothing(self):
        states = {
            "no_entries": FileState([]),
            "only_unchecked": FileState(
                [FileEntry("a.mdb", False), _sql_entry("db", False)]
            ),
            "only_other_backend": FileState([_sql_entry("db")]),
        }
        for label, state in states.items():
            with self.subTest(label=label):
                repository = Mock(spec=IFileStateRepository)
                loader = Mock(spec=LoadFileUseCase)
                repository.load.return_value = state
                with patch(EXISTS_TARGET, return_value=True):
                    result = LoadFilesFromConfigUseCase(
                        loader, repository, Mock()
                    ).execute({DatabaseBackend.ACCESS})
                self.assertEqual(result, [])
                loader.execute.assert_not_called()

    def test_backend_and_checked_filters_do_not_filesystem_check_sql_locators(self):
        sql = _sql_entry("checked-db")
        unchecked_sql = _sql_entry("unchecked-db", is_checked=False)
        repository = Mock(spec=IFileStateRepository)
        loader = Mock(spec=LoadFileUseCase)
        loader.execute.return_value = True
        repository.load.return_value = FileState(
            [FileEntry("ignored.mdb"), unchecked_sql, sql]
        )
        with patch(EXISTS_TARGET) as exists:
            result = LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                {DatabaseBackend.SQL_SERVER}
            )
        self.assertEqual(result, [sql.runtime_locator])
        loader.execute.assert_called_once_with(sql.runtime_locator)
        exists.assert_not_called()

    def test_both_backends_load_in_saved_order_and_only_access_is_path_checked(self):
        sql = _sql_entry("checked-db")
        repository = Mock(spec=IFileStateRepository)
        loader = Mock(spec=LoadFileUseCase)
        loader.execute.return_value = True
        repository.load.return_value = FileState(
            [FileEntry("first.mdb"), sql, FileEntry("second.mdb")]
        )
        with patch(EXISTS_TARGET, return_value=True) as exists:
            result = LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                {DatabaseBackend.ACCESS, DatabaseBackend.SQL_SERVER}
            )
        self.assertEqual(result, ["first.mdb", sql.runtime_locator, "second.mdb"])
        self.assertEqual(
            [call.args[0] for call in exists.call_args_list],
            ["first.mdb", "second.mdb"],
        )

    def test_missing_unchecked_failed_and_raising_entries_do_not_stop_later_loads(self):
        repository = Mock(spec=IFileStateRepository)
        loader = Mock(spec=LoadFileUseCase)
        repository.load.return_value = FileState(
            [
                FileEntry("unchecked", False),
                FileEntry("missing"),
                FileEntry("failed"),
                FileEntry("raising"),
                FileEntry("success"),
            ]
        )
        loader.execute.side_effect = [False, RuntimeError("failed"), True]
        with patch(
            EXISTS_TARGET,
            side_effect=lambda path: path != "missing",
        ) as exists:
            result = LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                {DatabaseBackend.ACCESS}
            )
        self.assertEqual(result, ["success"])
        self.assertEqual(
            [call.args[0] for call in loader.execute.call_args_list],
            ["failed", "raising", "success"],
        )
        self.assertEqual(
            [call.args[0] for call in exists.call_args_list],
            ["missing", "failed", "raising", "success"],
        )
