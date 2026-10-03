import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
)
from types import SimpleNamespace
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
from ost_visualizer.presentation.components.progress_dialog import ProgressDialog
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete


class DatabaseMaintenanceFailureWorkflowTests(unittest.TestCase):
    def test_compaction_and_validation_failure_leave_original_intact(self):
        expected_messages = {
            "compact": "engine failure",
            "validation": "Compacted database validation failed; "
            "the original was not replaced.",
            "replace": "replacement failed",
        }
        for failure in ("compact", "validation", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "test.mdb"
                source.write_bytes(b"original database contents")
                engine = Mock()

                def compact(_source, destination):
                    Path(destination).write_bytes(b"compacted")
                    if failure == "compact":
                        raise RuntimeError("engine failure")

                engine.CompactDatabase.side_effect = compact
                counts = [{"Data": 2}, {"Data": 1 if failure == "validation" else 2}]
                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    side_effect=counts,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    side_effect=OSError("replacement failed"),
                ):
                    # compact() touches neither the file-loading service nor the
                    # event bus; plain namespaces fail loudly if that changes.
                    service = DatabaseMaintenanceService(
                        MdbDatabaseMaintenance(MdbConnectionManager()),
                        SimpleNamespace(),
                        SimpleNamespace(),
                    )
                    result = service.compact(str(source))
                self.assertFalse(result.success)
                self.assertEqual(result.message, expected_messages[failure])
                self.assertEqual(source.read_bytes(), b"original database contents")
                self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_replacement_failing_after_the_original_moved_restores_or_preserves_it(
        self,
    ):
        for scenario in ("original_moved_away", "original_still_present"):
            with self.subTest(
                scenario=scenario
            ), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "test.mdb"
                source.write_bytes(b"original database contents")
                engine = Mock()
                engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                    dst
                ).write_bytes(b"compacted")

                def partial_replace(src, _dst, backup):
                    # The file system moved (or copied) the original to the
                    # backup name and then failed before installing the result.
                    if scenario == "original_moved_away":
                        os.rename(src, backup)
                    else:
                        Path(backup).write_bytes(Path(src).read_bytes())
                    raise OSError("replacement interrupted")

                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    return_value={"Data": 1},
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    partial_replace,
                ):
                    result = DatabaseMaintenanceService(
                        MdbDatabaseMaintenance(MdbConnectionManager()),
                        SimpleNamespace(),
                        SimpleNamespace(),
                    ).compact(str(source))
                self.assertFalse(result.success)
                self.assertEqual(result.message, "replacement interrupted")
                # Either way the original database is back under its own name.
                self.assertEqual(source.read_bytes(), b"original database contents")
                leftovers = [
                    entry for entry in Path(folder).iterdir() if entry != source
                ]
                if scenario == "original_moved_away":
                    # Restored by renaming the backup; the work folder is removed.
                    self.assertEqual(leftovers, [])
                else:
                    # Source and backup both exist: recovery files are kept.
                    self.assertEqual(len(leftovers), 1)
                    self.assertTrue(leftovers[0].name.startswith(".ost-compact-"))
                    self.assertEqual(
                        (leftovers[0] / "original.backup").read_bytes(),
                        b"original database contents",
                    )

    def test_source_change_during_compaction_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "test.mdb"
            source.write_bytes(b"original")
            engine = Mock()

            def compact(_source, destination):
                Path(destination).write_bytes(b"compacted")
                source.write_bytes(b"newer external contents")

            engine.CompactDatabase.side_effect = compact
            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ):
                result = DatabaseMaintenanceService(
                    MdbDatabaseMaintenance(MdbConnectionManager()),
                    SimpleNamespace(),
                    SimpleNamespace(),
                ).compact(str(source))
            self.assertFalse(result.success)
            self.assertEqual(
                result.message,
                "The source database changed during maintenance; "
                "it was not replaced.",
            )
            self.assertEqual(source.read_bytes(), b"newer external contents")
            self.assertEqual(list(Path(folder).iterdir()), [source])


class _FinalizingWriter:
    """Cached writer handle whose close() flushes the committed file contents."""

    def __init__(self, source, contents):
        self._source = source
        self._contents = contents
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self._source.write_bytes(self._contents)


class MaintenanceCapturedOwnerWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_first_request_captures_source_after_cached_writer_finalizes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"before writer closes")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            owner = SimpleNamespace(file_path=str(source))
            reloaded = []
            published = []
            files = SimpleNamespace(
                data_service=SimpleNamespace(
                    get_hierarchy=lambda: SimpleNamespace(loaded_files=[owner])
                ),
                reload_database=lambda locator: (
                    reloaded.append(locator) or SimpleNamespace(success=True)
                ),
            )
            events = SimpleNamespace(
                publish=lambda event, **payload: published.append((event, payload))
            )
            router = DatabaseMaintenanceRouter(
                DatabaseDescriptorRegistry(), backend, object()
            )
            service = DatabaseMaintenanceService(router, files, events)
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda src, dst: Path(dst).write_bytes(
                Path(src).read_bytes()
            )

            def replace(src, dst, backup):
                os.rename(src, backup)
                os.rename(dst, src)

            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                replace,
            ):
                for operation in range(2):
                    finalized = f"committed writer {operation}".encode()
                    writer = _FinalizingWriter(source, finalized)
                    manager._write_conns[os.path.normcase(str(source))] = writer
                    target = service.capture_target(str(source))
                    progress = ProgressDialog(
                        str(source), lambda: service.prepare(target)
                    )
                    try:
                        progress.exec()
                        if progress.error is not None:
                            raise progress.error
                        prepared = progress.result
                    finally:
                        progress.cleanup()
                        delete(progress)
                    self.assertTrue(
                        service.finish(target, prepared, lambda _locator: True).success
                    )
                    self.assertEqual(source.read_bytes(), finalized)
                    self.assertEqual(writer.close_calls, 1)
                    self.assertFalse(manager._maintenance_paths)
                    self.assertFalse(manager._write_conns)
                    self.assertFalse(service._operation_lock.locked())
            self.assertEqual(reloaded, [str(source)] * 2)
            self.assertEqual(
                published,
                [(AppEvents.DATABASE_REFRESHED, {"file_path": str(source)})] * 2,
            )

    def test_changed_owner_or_source_before_prepare_never_starts_compaction(self):
        for change in ("none", "owner", "unload", "source", "replacement"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                backend = MdbDatabaseMaintenance(manager)
                reloads = []
                hierarchy = SimpleNamespace(
                    loaded_files=[SimpleNamespace(file_path=str(source))]
                )
                files = SimpleNamespace(
                    data_service=SimpleNamespace(get_hierarchy=lambda: hierarchy),
                    reload_database=lambda locator: reloads.append(locator),
                )
                service = DatabaseMaintenanceService(backend, files, SimpleNamespace())
                target = service.capture_target(str(source))
                if change == "none":
                    pass
                elif change == "owner":
                    hierarchy.loaded_files = [SimpleNamespace(file_path=str(source))]
                elif change == "unload":
                    hierarchy.loaded_files = []
                elif change == "source":
                    source.write_bytes(b"new external contents")
                else:
                    replacement = source.with_suffix(".replacement")
                    replacement.write_bytes(source.read_bytes())
                    stamp = source.stat()
                    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    os.replace(replacement, source)
                engine = Mock()
                engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                    dst
                ).write_bytes(b"compacted")
                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ) as dispatch, patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    return_value={"Data": 1},
                ):
                    if change == "none":
                        # Positive control: an unchanged target does start the
                        # compaction.
                        prepared = service.prepare(target)
                        engine.CompactDatabase.assert_called_once()
                        service.discard(prepared)
                        self.assertFalse(manager._maintenance_paths)
                    else:
                        with self.assertRaisesRegex(
                            RuntimeError, "selected database changed"
                        ):
                            service.prepare(target)
                        dispatch.assert_not_called()
                        self.assertFalse(manager._maintenance_paths)
                self.assertFalse(service._operation_lock.locked())
                self.assertEqual(reloads, [])
                self.assertTrue(source.exists())
                if change != "none":
                    service.release_target(target)
