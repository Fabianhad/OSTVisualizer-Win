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
