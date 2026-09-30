import unittest
from unittest.mock import Mock, patch
from ost_visualizer.application.use_cases.project.load_files_from_config_use_case import (
    LoadFilesFromConfigUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState


class LoadFilesFromConfigUseCaseExecuteTests(unittest.TestCase):
    def test_missing_or_corrupt_saved_state_does_not_attempt_any_load(self):
        for error in (
            FileNotFoundError(),
            OSError("unreadable"),
            ValueError("invalid"),
        ):
            with self.subTest(error=type(error).__name__):
                repository, loader = Mock(), Mock()
                repository.load.side_effect = error
                self.assertEqual(
                    LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                        {DatabaseBackend.ACCESS}
                    ),
                    [],
                )
                loader.execute.assert_not_called()

    def test_backend_and_checked_filters_do_not_filesystem_check_sql_locators(self):
        sql = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation("unused", "unused"), schema_version=1
            )
        )
        repository, loader = Mock(), Mock()
        repository.load.return_value = FileState([FileEntry("ignored.mdb"), sql])
        with patch(
            "ost_visualizer.application.use_cases.project.load_files_from_config_use_case.os.path.exists"
        ) as exists:
            result = LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                {DatabaseBackend.SQL_SERVER}
            )
        self.assertEqual(result, [sql.runtime_locator])
        loader.execute.assert_called_once_with(sql.runtime_locator)
        exists.assert_not_called()

    def test_missing_unchecked_failed_and_raising_entries_do_not_stop_later_loads(self):
        repository, loader = Mock(), Mock()
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
            "ost_visualizer.application.use_cases.project.load_files_from_config_use_case.os.path.exists",
            side_effect=lambda path: path != "missing",
        ):
            result = LoadFilesFromConfigUseCase(loader, repository, Mock()).execute(
                {DatabaseBackend.ACCESS}
            )
        self.assertEqual(result, ["success"])
        self.assertEqual(
            [call.args[0] for call in loader.execute.call_args_list],
            ["failed", "raising", "success"],
        )
