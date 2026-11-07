import os
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.aggregates.file_state_aggregate import FileStateAggregate
from ost_visualizer.domain.entities.file_state import FileEntry, FileState


class FileStateOwnershipTests(unittest.TestCase):
    def test_failed_file_state_save_preserves_authoritative_in_memory_entries(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)

        class _FailingRepository:
            def load(self):
                return FileState(file_entries=[original])

            def save(self, _state):
                raise OSError("disk unavailable")

        aggregate = FileStateAggregate(_FailingRepository())
        with self.assertRaises(OSError):
            aggregate.update_entries([original.with_checked(False)])
        self.assertEqual(aggregate.file_entries, [original])

    def test_file_state_entries_are_defensive_copies(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)
        repository = SimpleNamespace(
            load=lambda: FileState(file_entries=[original]),
            save=lambda _state: None,
        )
        aggregate = FileStateAggregate(repository)
        returned_entry = aggregate.file_entries[0]
        returned_entry.is_checked = False
        self.assertTrue(aggregate.file_entries[0].is_checked)

    def test_file_state_update_does_not_retain_caller_owned_entries(self):
        persisted = []
        repository = SimpleNamespace(
            load=lambda: FileState(),
            save=lambda state: persisted.append(FileState.from_dict(state.to_dict())),
        )
        aggregate = FileStateAggregate(repository)
        caller_entry = FileEntry("C:/projects/active.mdb", is_checked=True)
        aggregate.update_entries([caller_entry])
        caller_entry.is_checked = False
        self.assertTrue(aggregate.file_entries[0].is_checked)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].file_entries, aggregate.file_entries)
        self.assertEqual(aggregate.file_entries[0].file_path, "C:/projects/active.mdb")

    def test_file_state_reload_failure_preserves_last_known_entries(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)

        class _Repository:
            load_count = 0

            def load(self):
                self.load_count += 1
                if self.load_count == 1:
                    return FileState(file_entries=[original])
                raise OSError("temporary read failure")

            def save(self, _state):
                pass

        aggregate = FileStateAggregate(_Repository())
        aggregate.reload()
        self.assertEqual(aggregate.file_entries, [original])


class _RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message, *args):
        self.errors.append(message % args)


class _ScriptedRepository:
    def __init__(self, *loads, save_error=None):
        self._loads = list(loads)
        self.saved = []
        self.save_error = save_error

    def load(self):
        outcome = self._loads.pop(0) if len(self._loads) > 1 else self._loads[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def save(self, state):
        if self.save_error:
            raise self.save_error
        self.saved.append(state)


class FileStateLoadAndReloadTests(unittest.TestCase):
    def test_missing_state_file_starts_empty_without_logging_an_error(self):
        logger = _RecordingLogger()
        aggregate = FileStateAggregate(
            _ScriptedRepository(FileNotFoundError("none")), logger
        )
        self.assertEqual(aggregate.file_entries, [])
        self.assertEqual(logger.errors, [])

    def test_unsupported_saved_state_is_logged_with_its_reason_and_keeps_empty_state(
        self,
    ):
        logger = _RecordingLogger()
        aggregate = FileStateAggregate(
            _ScriptedRepository(ValueError("unsupported saved version")), logger
        )
        self.assertEqual(aggregate.file_entries, [])
        self.assertEqual(
            logger.errors, ["unsupported saved version; keeping current file state"]
        )

    def test_unreadable_state_file_is_logged_and_keeps_empty_state(self):
        logger = _RecordingLogger()
        aggregate = FileStateAggregate(_ScriptedRepository(OSError("locked")), logger)
        self.assertEqual(aggregate.file_entries, [])
        self.assertEqual(logger.errors, ["Error reading file state: locked"])

    def test_reload_replaces_state_with_what_the_repository_now_holds(self):
        first = FileEntry("C:/projects/a.mdb", is_checked=True)
        second = FileEntry("C:/projects/b.mdb", is_checked=False)
        repository = _ScriptedRepository(
            FileState(file_entries=[first]), FileState(file_entries=[second])
        )
        aggregate = FileStateAggregate(repository)
        self.assertEqual(aggregate.file_entries, [first])
        aggregate.reload()
        self.assertEqual(aggregate.file_entries, [second])
        self.assertFalse(aggregate.contains_path("C:/projects/a.mdb"))

    def test_reload_after_a_value_error_keeps_the_previous_entries_and_logs(self):
        original = FileEntry("C:/projects/a.mdb")
        logger = _RecordingLogger()
        aggregate = FileStateAggregate(
            _ScriptedRepository(
                FileState(file_entries=[original]), ValueError("corrupt")
            ),
            logger,
        )
        aggregate.reload()
        self.assertEqual(aggregate.file_entries, [original])
        self.assertEqual(logger.errors, ["corrupt; keeping current file state"])

    def test_without_an_injected_logger_the_module_logger_reports_failures(self):
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.file_state_aggregate", level="ERROR"
        ) as captured:
            FileStateAggregate(_ScriptedRepository(OSError("locked")))
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Error reading file state: locked"],
        )


class FileStateContainsPathAndSaveTests(unittest.TestCase):
    def test_contains_path_is_true_only_for_the_known_path(self):
        entry = FileEntry("C:/projects/Active.mdb")
        aggregate = FileStateAggregate(
            _ScriptedRepository(FileState(file_entries=[entry]))
        )
        self.assertIs(aggregate.contains_path("C:/projects/Active.mdb"), True)
        self.assertIs(aggregate.contains_path("C:/projects/other.mdb"), False)

    @unittest.skipUnless(
        os.name == "nt", "path case and separators are normalised by the Windows rules"
    )
    def test_contains_path_ignores_case_separators_and_dot_segments_on_windows(self):
        entry = FileEntry("C:/projects/Active.mdb")
        aggregate = FileStateAggregate(
            _ScriptedRepository(FileState(file_entries=[entry]))
        )
        self.assertIs(aggregate.contains_path(r"c:\projects\.\ACTIVE.MDB"), True)

    def test_update_deduplicates_before_saving_and_retains_the_saved_state(self):
        repository = _ScriptedRepository(FileState())
        aggregate = FileStateAggregate(repository)
        aggregate.update_entries(
            [
                FileEntry("C:/projects/a.mdb", is_checked=False),
                FileEntry("c:/PROJECTS/a.mdb", is_checked=True),
                FileEntry("C:/projects/b.mdb", is_checked=False),
            ]
        )
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(
            [(e.file_path, e.is_checked) for e in repository.saved[0].file_entries],
            [("C:/projects/a.mdb", True), ("C:/projects/b.mdb", False)],
        )
        self.assertEqual(aggregate.file_entries, repository.saved[0].file_entries)

    def test_failed_save_is_logged_and_reraised_the_same_error(self):
        logger = _RecordingLogger()
        error = OSError("disk full")
        aggregate = FileStateAggregate(
            _ScriptedRepository(FileState(), save_error=error), logger
        )
        with self.assertRaises(OSError) as raised:
            aggregate.update_entries([FileEntry("C:/projects/a.mdb")])
        self.assertIs(raised.exception, error)
        self.assertEqual(logger.errors, ["Error saving file state: disk full"])
