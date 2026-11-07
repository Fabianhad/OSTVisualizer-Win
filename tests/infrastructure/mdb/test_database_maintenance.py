import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
    _MdbMaintenanceTarget,
    _PreparedMdbMaintenance,
    _replace_file,
    _signature,
    _table_counts,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class AccessMaintenanceOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_capture_reserves_closed_handles_until_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            identity = backend.capture_target(str(source))
            try:
                for mode in (True, False):
                    with self.assertRaisesRegex(RuntimeError, "maintenance"):
                        with manager.connection(str(source), autocommit=mode):
                            self.fail("confirmation reopened an MDB connection")
                self.assertTrue(backend.is_target_current(str(source), identity))
                with self.assertRaisesRegex(RuntimeError, "active operations"):
                    backend.capture_target(str(source))
            finally:
                backend.release_target(str(source), identity)
            backend.release_target(str(source), identity)
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(backend.is_target_current(str(source), identity))
            replacement = backend.capture_target(str(source))
            backend.release_target(str(source), replacement)
            self.assertFalse(manager._maintenance_paths)

    def test_replacement_during_handle_release_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            replacement = source.with_suffix(".replacement")
            replacement.write_bytes(b"replacement")
            manager = MdbConnectionManager()
            writer = Mock()
            writer.close.side_effect = lambda: os.replace(replacement, source)
            manager._write_conns[os.path.normcase(str(source))] = writer
            with self.assertRaisesRegex(RuntimeError, "selected database changed"):
                MdbDatabaseMaintenance(manager).capture_target(str(source))
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(manager._write_conns)
            self.assertEqual(source.read_bytes(), b"replacement")

    def test_staging_holds_leases_until_commit_or_discard(self):
        for failure in ("fsync", "replace", "partial_replace", "restore", "none"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                engine = Mock()
                engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                    dst
                ).write_bytes(b"compacted")
                real_rename = os.rename

                def replace(src, dst, backup):
                    if failure in ("partial_replace", "restore"):
                        real_rename(src, backup)
                    if failure != "none":
                        raise OSError("replacement failure")
                    real_rename(src, backup)
                    real_rename(dst, src)

                def rename(src, dst):
                    if failure == "restore":
                        raise OSError("recovery blocked")
                    real_rename(src, dst)

                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    return_value={"Data": 1},
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.fsync",
                    side_effect=OSError("fsync") if failure == "fsync" else None,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    replace,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.rename",
                    rename,
                ):
                    backend = MdbDatabaseMaintenance(manager)
                    if failure == "fsync":
                        with self.assertRaises(OSError):
                            backend.prepare(
                                str(source), backend.capture_target(str(source))
                            )
                    else:
                        staged = backend.prepare(
                            str(source), backend.capture_target(str(source))
                        )
                        try:
                            self.assertEqual(source.read_bytes(), b"original")
                            with self.assertRaisesRegex(RuntimeError, "maintenance"):
                                with manager.connection(str(source)):
                                    self.fail("lease escaped staging exclusion")
                            if failure == "none":
                                self.assertTrue(staged.commit().success)
                            else:
                                expected_error = {
                                    "replace": (OSError, "replacement failure"),
                                    "partial_replace": (OSError, "replacement failure"),
                                    "restore": (
                                        RuntimeError,
                                        "Replacement recovery failed",
                                    ),
                                }[failure]
                                with self.assertRaisesRegex(*expected_error):
                                    staged.commit()
                        finally:
                            staged.close()
                self.assertFalse(manager._maintenance_paths)
                if failure == "restore":
                    backups = list(Path(folder).glob(".ost-compact-*/original.backup"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_bytes(), b"original")
                else:
                    self.assertEqual(
                        source.read_bytes(),
                        b"compacted" if failure == "none" else b"original",
                    )
                    self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_last_moment_external_write_is_not_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")
            calls = []

            def replace(src, dst, backup):
                if not calls:
                    source.write_bytes(b"newer external data")
                calls.append(True)
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
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    MdbDatabaseMaintenance(manager).compact(str(source))
            self.assertEqual(source.read_bytes(), b"newer external data")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_unavailable_reason_reports_blocked_missing_and_non_mdb_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            other = Path(folder) / "db.accdb"
            other.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            self.assertEqual(backend.unavailable_reason(str(source)), "")
            self.assertEqual(
                backend.unavailable_reason(str(Path(folder) / "missing.mdb")),
                "Select an existing Microsoft Access MDB database.",
            )
            self.assertEqual(
                backend.unavailable_reason(str(other)),
                "Select an existing Microsoft Access MDB database.",
            )
            manager.set_write_blocked(True)
            self.assertEqual(
                backend.unavailable_reason(str(source)),
                "Close On-Screen Takeoff before database maintenance.",
            )

    def test_compacted_table_count_mismatch_keeps_original_and_cleans_work(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")
            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                side_effect=[{"Data": 2}, {"Data": 1}],
            ):
                with self.assertRaisesRegex(RuntimeError, "validation failed"):
                    MdbDatabaseMaintenance(manager).compact(str(source))
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_commit_after_write_block_or_after_success_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")

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
                backend = MdbDatabaseMaintenance(manager)
                blocked = backend.prepare(
                    str(source), backend.capture_target(str(source))
                )
                try:
                    manager.set_write_blocked(True)
                    with self.assertRaisesRegex(RuntimeError, "interrupted"):
                        blocked.commit()
                    self.assertEqual(source.read_bytes(), b"original")
                finally:
                    blocked.close()
                manager.set_write_blocked(False)
                prepared = backend.prepare(
                    str(source), backend.capture_target(str(source))
                )
                try:
                    self.assertTrue(prepared.commit().success)
                    with self.assertRaisesRegex(RuntimeError, "no longer pending"):
                        prepared.commit()
                finally:
                    prepared.close()
            self.assertEqual(source.read_bytes(), b"compacted")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_table_counts_opens_read_only_and_closes_every_recordset(self):
        def table(name, attributes=0):
            return Mock(Name=name, Attributes=attributes)

        def engine_for(tables, broken=()):
            recordsets = []
            database = Mock()
            database.TableDefs = tables

            def open_recordset(sql, kind):
                rows = Mock()
                rows.Fields.return_value.Value = (
                    "not a number" if any(name in sql for name in broken) else 7
                )
                recordsets.append((sql, kind, rows))
                return rows

            database.OpenRecordset.side_effect = open_recordset
            engine = Mock()
            engine.OpenDatabase.return_value = database
            return engine, database, recordsets

        tables = [
            table("Data"),
            table("Attached", 0x40000000),
            table("Odbc", 0x20000000),
            table("Flagged", 0x1),
        ]
        engine, database, recordsets = engine_for(tables)
        self.assertEqual(
            _table_counts(engine, Path("db.mdb")),
            {"Data": 7, "Attached": None, "Odbc": None, "Flagged": 7},
        )
        engine.OpenDatabase.assert_called_once_with("db.mdb", True, True)
        self.assertEqual(
            [(sql, kind) for sql, kind, _rows in recordsets],
            [
                ("SELECT COUNT(*) FROM [Data]", 4),
                ("SELECT COUNT(*) FROM [Flagged]", 4),
            ],
        )
        for _sql, _kind, rows in recordsets:
            rows.Fields.assert_called_once_with(0)
            rows.Close.assert_called_once_with()
        database.Close.assert_called_once_with()
        engine, database, recordsets = engine_for(
            tables + [table("Broken")], broken=("Broken",)
        )
        with self.assertRaises(ValueError):
            _table_counts(engine, Path("db.mdb"))
        self.assertEqual(len(recordsets), 3)
        for _sql, _kind, rows in recordsets:
            rows.Close.assert_called_once_with()
        database.Close.assert_called_once_with()

    def test_prepare_pairs_com_initialisation_and_releases_the_lease_on_failure(self):
        module = "ost_visualizer.infrastructure.mdb.database_maintenance"
        for fails in (False, True):
            with self.subTest(
                build_fails=fails
            ), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                backend = MdbDatabaseMaintenance(manager)
                events = []
                com = Mock()
                com.CoInitialize.side_effect = lambda: events.append("init")
                com.CoUninitialize.side_effect = lambda: events.append("uninit")

                def build(_prepared, fails=fails):
                    events.append("build")
                    if fails:
                        raise RuntimeError("build failed")

                target = backend.capture_target(str(source))
                self.assertEqual(len(manager._maintenance_paths), 1)
                with patch(f"{module}.pythoncom", com), patch(
                    f"{module}._PreparedMdbMaintenance.build", build
                ):
                    if fails:
                        with self.assertRaisesRegex(RuntimeError, "build failed"):
                            backend.prepare(str(source), target)
                        self.assertFalse(target.active)
                    else:
                        prepared = backend.prepare(str(source), target)
                        self.assertTrue(target.active)
                        prepared.close()
                self.assertEqual(events, ["init", "build", "uninit"])
                self.assertFalse(target.active)
                self.assertFalse(manager._maintenance_paths)

    def test_capture_releases_its_lease_when_the_file_changes_after_it_is_taken(self):
        module = "ost_visualizer.infrastructure.mdb.database_maintenance"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            readings = iter([(1, 10, 8, 1000), (1, 11, 8, 1000)])
            error = None
            with patch(f"{module}._signature", lambda _path: next(readings)):
                try:
                    MdbDatabaseMaintenance(manager).capture_target(str(source))
                except RuntimeError as exc:
                    error = exc
            self.assertIn("selected database changed", str(error))
            self.assertFalse(manager._maintenance_paths)

    def test_releasing_a_target_exits_its_lease_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            target = backend.capture_target(str(source))
            self.assertTrue(target.active)
            self.assertEqual(len(manager._maintenance_paths), 1)
            backend.release_target(str(source), target)
            self.assertFalse(target.active)
            self.assertFalse(manager._maintenance_paths)

    def test_table_counts_skips_system_tables_and_rejects_compact_errors(self):
        def table(name, attributes=0):
            return Mock(Name=name, Attributes=attributes)

        def engine_for(tables, counts):
            database = Mock()
            database.TableDefs = tables

            def open_recordset(sql, _kind):
                rows = Mock()
                rows.Fields.return_value.Value = counts[sql]
                return rows

            database.OpenRecordset.side_effect = open_recordset
            engine = Mock()
            engine.OpenDatabase.return_value = database
            return engine, database

        engine, database = engine_for(
            [
                table("MSysObjects"),
                table("MSysCompactError"),
                table("Linked", 0x40000000),
                table("Odd]Name"),
                table("Data"),
            ],
            {
                "SELECT COUNT(*) FROM [MSysCompactError]": 0,
                "SELECT COUNT(*) FROM [Odd]]Name]": 3,
                "SELECT COUNT(*) FROM [Data]": 5,
            },
        )
        self.assertEqual(
            _table_counts(engine, Path("db.mdb")),
            {"Linked": None, "Odd]Name": 3, "Data": 5},
        )
        database.Close.assert_called_once_with()
        engine, database = engine_for(
            [table("MSysCompactError")],
            {"SELECT COUNT(*) FROM [MSysCompactError]": 2},
        )
        with self.assertRaisesRegex(RuntimeError, "repair errors"):
            _table_counts(engine, Path("db.mdb"))
        database.Close.assert_called_once_with()


_MODULE = "ost_visualizer.infrastructure.mdb.database_maintenance"


def _plain_replace(source, destination, backup):
    os.rename(source, backup)
    os.rename(destination, source)


class ReplaceFileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_the_real_windows_replace_swaps_the_files_and_keeps_the_original_backup(
        self,
    ):
        source = self.folder / "db.mdb"
        source.write_bytes(b"original")
        compacted = self.folder / "compacted.mdb"
        compacted.write_bytes(b"compacted")
        backup = self.folder / "original.backup"
        _replace_file(source, compacted, backup)
        self.assertEqual(source.read_bytes(), b"compacted")
        self.assertEqual(backup.read_bytes(), b"original")
        self.assertFalse(compacted.exists())
        self.assertEqual(
            sorted(path.name for path in self.folder.iterdir()),
            ["db.mdb", "original.backup"],
        )

    def test_a_failed_windows_replace_raises_the_system_error_and_changes_nothing(
        self,
    ):
        source = self.folder / "db.mdb"
        source.write_bytes(b"original")
        with self.assertRaises(OSError) as raised:
            _replace_file(source, self.folder / "missing.mdb", self.folder / "b")
        self.assertIn(raised.exception.winerror, (2, 3))
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual([path.name for path in self.folder.iterdir()], ["db.mdb"])

    def test_the_replacement_is_requested_without_any_ignore_error_flag(self):
        # dwReplaceFlags 2 (IGNORE_MERGE_ERRORS) and 4 (IGNORE_ACL_ERRORS) would let
        # a partially applied replacement be reported as a success; no real-file
        # scenario produces those errors hermetically, so the call is inspected.
        calls = []

        def replace_file_w(*arguments):
            calls.append(arguments)
            return 1

        library = Mock(ReplaceFileW=Mock(side_effect=replace_file_w))
        with patch(f"{_MODULE}.ctypes.WinDLL", return_value=library) as load:
            _replace_file(Path("source.mdb"), Path("compacted.mdb"), Path("b.bak"))
        load.assert_called_once_with("kernel32", use_last_error=True)
        self.assertEqual(
            calls, [("source.mdb", "compacted.mdb", "b.bak", 0, None, None)]
        )


class AccessMaintenanceFailureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = self.folder / "db.mdb"
        self.source.write_bytes(b"original")
        self.manager = MdbConnectionManager()
        self.backend = MdbDatabaseMaintenance(self.manager)
        self.engine = Mock()
        self.compact_calls = []

        def compact(src, dst):
            self.compact_calls.append((src, dst))
            Path(dst).write_bytes(b"compacted")

        self.engine.CompactDatabase.side_effect = compact
        self.dispatch = self.enterContext(
            patch(f"{_MODULE}.win32com.client.Dispatch", return_value=self.engine)
        )
        self.counts = self.enterContext(
            patch(f"{_MODULE}._table_counts", return_value={"Data": 1})
        )

    def stage(self, replace=_plain_replace):
        self.enterContext(patch(f"{_MODULE}._replace_file", replace))
        return self.backend.prepare(
            str(self.source), self.backend.capture_target(str(self.source))
        )

    def work_dirs(self):
        return sorted(
            path for path in self.folder.iterdir() if path.name.startswith(".ost-")
        )

    def test_build_compacts_into_a_private_work_folder_and_validates_both_files(self):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        self.dispatch.assert_called_once_with("DAO.DBEngine.120")
        work = self.work_dirs()
        self.assertEqual(len(work), 1)
        self.assertRegex(work[0].name, r"^\.ost-compact-[a-z0-9_]{8}$")
        self.assertEqual(
            self.compact_calls,
            [(str(self.source.absolute()), str(work[0] / "db.mdb"))],
        )
        self.assertEqual(
            [call.args for call in self.counts.call_args_list],
            [
                (self.engine, self.source.absolute()),
                (self.engine, work[0] / "db.mdb"),
            ],
        )
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual((work[0] / "db.mdb").read_bytes(), b"compacted")

    def test_validation_failure_message_names_the_unreplaced_original(self):
        self.counts.side_effect = [{"Data": 2}, {"Data": 1}]
        with self.assertRaises(RuntimeError) as raised:
            self.stage()
        self.assertEqual(
            str(raised.exception),
            "Compacted database validation failed; the original was not replaced.",
        )
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual(self.work_dirs(), [])
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_compact_engine_failure_removes_the_work_folder_and_releases_the_lease(
        self,
    ):
        self.engine.CompactDatabase.side_effect = OSError("compact blew up")
        with self.assertRaisesRegex(OSError, "compact blew up"):
            self.stage()
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual(list(self.folder.iterdir()), [self.source])
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_source_changed_between_capture_and_prepare_is_refused_before_compacting(
        self,
    ):
        target = self.backend.capture_target(str(self.source))
        self.source.write_bytes(b"changed after capture")
        with self.assertRaises(RuntimeError) as raised:
            self.backend.prepare(str(self.source), target)
        self.assertEqual(
            str(raised.exception),
            "The selected database changed; start maintenance again.",
        )
        self.dispatch.assert_not_called()
        self.assertFalse(target.active)
        self.assertEqual(self.manager._maintenance_paths, set())
        self.assertEqual(self.source.read_bytes(), b"changed after capture")

    def test_a_file_replaced_during_capture_reports_the_exact_restart_message(self):
        readings = iter([(1, 10, 8, 1000), (1, 11, 8, 1000)])
        with patch(f"{_MODULE}._signature", lambda _path: next(readings)):
            with self.assertRaises(RuntimeError) as raised:
                self.backend.capture_target(str(self.source))
        self.assertEqual(
            str(raised.exception),
            "The selected database changed; start maintenance again.",
        )

    def test_a_missing_database_cannot_be_captured_and_takes_no_lease(self):
        with self.assertRaises(FileNotFoundError):
            self.backend.capture_target(str(self.folder / "gone.mdb"))
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_second_capture_of_a_leased_database_fails_without_releasing_the_first(
        self,
    ):
        first = self.backend.capture_target(str(self.source))
        self.addCleanup(first.close)
        with self.assertRaisesRegex(RuntimeError, "active operations"):
            self.backend.capture_target(str(self.source))
        self.assertTrue(first.active)
        self.assertEqual(len(self.manager._maintenance_paths), 1)

    def test_target_currency_needs_the_same_path_the_same_file_and_an_open_lease(self):
        target = self.backend.capture_target(str(self.source))
        self.addCleanup(target.close)
        self.assertIs(self.backend.is_target_current(str(self.source), target), True)
        self.assertIs(
            self.backend.is_target_current(str(self.folder / "other.mdb"), target),
            False,
        )
        self.assertIs(self.backend.is_target_current(str(self.source), object()), False)
        self.assertIs(self.backend.is_target_current(str(self.source), None), False)
        self.source.write_bytes(b"grown by an external writer")
        self.assertIs(self.backend.is_target_current(str(self.source), target), False)
        self.source.write_bytes(b"original")
        target.close()
        self.assertIs(self.backend.is_target_current(str(self.source), target), False)

    def test_commit_refuses_a_block_and_a_second_run_with_exact_text(self):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        self.manager.set_write_blocked(True)
        with self.assertRaises(RuntimeError) as raised:
            prepared.commit()
        self.assertEqual(
            str(raised.exception),
            "Maintenance was interrupted by On-Screen Takeoff; "
            "the original was not replaced.",
        )
        self.assertEqual(self.source.read_bytes(), b"original")
        self.manager.set_write_blocked(False)
        self.assertTrue(prepared.commit().success)
        with self.assertRaises(RuntimeError) as again:
            prepared.commit()
        self.assertEqual(
            str(again.exception), "This maintenance result is no longer pending."
        )
        self.assertEqual(self.source.read_bytes(), b"compacted")

    def test_commit_after_the_lease_was_released_is_not_pending(self):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        prepared.close()
        with self.assertRaisesRegex(RuntimeError, "no longer pending"):
            prepared.commit()
        self.assertEqual(self.source.read_bytes(), b"original")

    def test_a_source_modified_after_staging_is_never_replaced(self):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        self.source.write_bytes(b"edited after staging, before commit")
        with self.assertRaises(RuntimeError) as raised:
            prepared.commit()
        self.assertEqual(
            str(raised.exception),
            "The source database changed during maintenance; it was not replaced.",
        )
        self.assertEqual(
            self.source.read_bytes(), b"edited after staging, before commit"
        )
        prepared.close()
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_the_source_is_held_open_for_sharing_only_while_it_is_verified(self):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        real_signature = _signature
        probes = []

        def probing_signature(path):
            if Path(path) == self.source.absolute() and not probes:
                with open(self.source, "rb") as reader:
                    probes.append(("read", reader.read()))
                try:
                    with open(self.source, "ab"):
                        probes.append(("write", "allowed"))
                except PermissionError:
                    probes.append(("write", "denied"))
            return real_signature(path)

        with patch(f"{_MODULE}._signature", probing_signature):
            self.assertTrue(prepared.commit().success)
        self.assertEqual(probes, [("read", b"original"), ("write", "denied")])

    def test_a_source_that_changes_during_the_swap_is_restored_and_work_is_cleaned(
        self,
    ):
        calls = []

        def replace(src, dst, backup):
            if not calls:
                self.source.write_bytes(b"written during the swap")
            calls.append((Path(src).name, Path(dst).name, Path(backup).name))
            _plain_replace(src, dst, backup)

        prepared = self.stage(replace)
        with self.assertRaises(RuntimeError) as raised:
            prepared.commit()
        prepared.close()
        self.assertEqual(
            str(raised.exception),
            "The source changed during replacement; its newer contents were restored.",
        )
        self.assertEqual(
            calls,
            [
                ("db.mdb", "db.mdb", "original.backup"),
                ("db.mdb", "original.backup", "rejected.compact"),
            ],
        )
        self.assertEqual(self.source.read_bytes(), b"written during the swap")
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_when_the_restore_swap_fails_the_recovery_files_are_kept(self):
        calls = []

        def replace(src, dst, backup):
            calls.append(Path(backup).name)
            if len(calls) == 1:
                self.source.write_bytes(b"written during the swap")
                _plain_replace(src, dst, backup)
                return
            raise OSError("restore swap refused")

        prepared = self.stage(replace)
        work = self.work_dirs()[0]
        with self.assertRaises(RuntimeError) as raised:
            prepared.commit()
        prepared.close()
        self.assertEqual(
            str(raised.exception),
            "The source changed during replacement. "
            f"Recovery files are preserved at {work}.",
        )
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(
            (work / "original.backup").read_bytes(), b"written during the swap"
        )
        self.assertEqual(self.source.read_bytes(), b"compacted")
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_failed_restore_swap_that_vanished_the_source_still_keeps_the_files(
        self,
    ):
        calls = []

        def replace(src, dst, backup):
            calls.append(Path(backup).name)
            if len(calls) == 1:
                self.source.write_bytes(b"written during the swap")
                _plain_replace(src, dst, backup)
                return
            os.rename(src, Path(backup).parent / "rejected.compact")
            raise OSError("restore swap stopped half way")

        prepared = self.stage(replace)
        work = self.work_dirs()[0]
        with self.assertRaisesRegex(RuntimeError, "Recovery files are preserved"):
            prepared.commit()
        prepared.close()
        self.assertTrue((work / "rejected.compact").is_file())
        self.assertEqual(self.source.read_bytes(), b"written during the swap")
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_partial_swap_with_both_files_present_keeps_the_backup_folder(self):
        def replace(src, _dst, backup):
            shutil.copy(src, backup)
            raise OSError("swap stopped after taking the backup")

        prepared = self.stage(replace)
        work = self.work_dirs()[0]
        with self.assertRaisesRegex(OSError, "swap stopped"):
            prepared.commit()
        prepared.close()
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual((work / "original.backup").read_bytes(), b"original")
        self.assertTrue(work.is_dir())
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_swap_that_vanished_the_source_is_rolled_back_by_renaming_the_backup(
        self,
    ):
        def replace(src, _dst, backup):
            os.rename(src, backup)
            raise OSError("swap stopped after moving the source")

        prepared = self.stage(replace)
        with self.assertRaisesRegex(OSError, "swap stopped"):
            prepared.commit()
        prepared.close()
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_a_blocked_rename_back_reports_where_the_original_is_preserved(self):
        real_rename = os.rename

        def replace(src, _dst, backup):
            real_rename(src, backup)
            raise OSError("swap stopped after moving the source")

        prepared = self.stage(replace)
        work = self.work_dirs()[0]
        with patch(f"{_MODULE}.os.rename", side_effect=OSError("rename blocked")):
            with self.assertRaises(RuntimeError) as raised:
                prepared.commit()
        prepared.close()
        self.assertEqual(
            str(raised.exception),
            "Replacement recovery failed. The original database is preserved at "
            f"{work / 'original.backup'}.",
        )
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual((work / "original.backup").read_bytes(), b"original")
        self.assertFalse(self.source.exists())

    def test_a_swap_failure_before_any_move_leaves_everything_untouched_and_cleans_up(
        self,
    ):
        def replace(_src, _dst, _backup):
            raise OSError("swap refused")

        prepared = self.stage(replace)
        with self.assertRaisesRegex(OSError, "swap refused"):
            prepared.commit()
        prepared.close()
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_compact_returns_the_success_result_and_releases_the_lease(self):
        self.enterContext(patch(f"{_MODULE}._replace_file", _plain_replace))
        result = self.backend.compact(str(self.source))
        self.assertIs(result.success, True)
        self.assertEqual(result.message, "Compact/Repair completed successfully.")
        self.assertEqual(self.source.read_bytes(), b"compacted")
        self.assertEqual(list(self.folder.iterdir()), [self.source])
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_compact_releases_the_lease_and_work_folder_when_the_commit_fails(self):
        self.enterContext(patch(f"{_MODULE}._replace_file", _plain_replace))
        with patch.object(self.manager, "is_write_blocked", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self.backend.compact(str(self.source))
        self.assertEqual(self.source.read_bytes(), b"original")
        self.assertEqual(list(self.folder.iterdir()), [self.source])
        self.assertEqual(self.manager._maintenance_paths, set())

    def test_a_target_exits_its_lease_exactly_once_however_often_it_is_closed(self):
        lease = MagicMock()
        target = _MdbMaintenanceTarget(self.source, (0, 0, 0, 0), lease)
        self.assertIs(target.active, True)
        target.close()
        target.close()
        lease.__exit__.assert_called_once_with(None, None, None)
        self.assertIs(target.active, False)

    def test_closing_twice_is_harmless_and_releases_the_lease_once(self):
        lease = Mock()
        prepared = _PreparedMdbMaintenance(
            self.source, (0, 0, 0, 0), lease, self.manager
        )
        prepared._work = self.folder / ".ost-compact-manual"
        prepared._work.mkdir()
        prepared.close()
        prepared.close()
        lease.close.assert_called_once_with()
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_a_work_folder_that_cannot_be_removed_still_releases_the_lease(self):
        lease = Mock()
        prepared = _PreparedMdbMaintenance(
            self.source, (0, 0, 0, 0), lease, self.manager
        )
        prepared._work = self.folder / ".ost-compact-manual"
        prepared._work.mkdir()
        with patch(f"{_MODULE}.shutil.rmtree", side_effect=OSError("locked")):
            with self.assertRaisesRegex(OSError, "locked"):
                prepared.close()
        lease.close.assert_called_once_with()
        self.assertTrue(prepared._work.is_dir())

    def test_repair_errors_message_names_the_unreplaced_original(self):
        table = Mock(Name="MSysCompactError", Attributes=0)
        database = Mock()
        database.TableDefs = [table]
        database.OpenRecordset.return_value.Fields.return_value.Value = 1
        engine = Mock()
        engine.OpenDatabase.return_value = database
        with self.assertRaises(RuntimeError) as raised:
            _table_counts(engine, Path("db.mdb"))
        self.assertEqual(
            str(raised.exception),
            "Access reported repair errors; the original database was not replaced.",
        )

    def _change_only(self, component):
        """Change exactly one component of the source file's signature."""
        before = self.source.stat()
        if component == "mtime":
            os.utime(
                self.source,
                ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000),
            )
        elif component == "size":
            self.source.write_bytes(self.source.read_bytes() + b"+")
            os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        else:
            twin = self.folder / "twin.mdb"
            twin.write_bytes(self.source.read_bytes())
            os.utime(twin, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(twin, self.source)
        after = self.source.stat()
        differing = {
            name
            for name in ("st_ino", "st_size", "st_mtime_ns")
            if getattr(before, name) != getattr(after, name)
        }
        expected = {"mtime": "st_mtime_ns", "size": "st_size", "inode": "st_ino"}
        self.assertEqual(differing, {expected[component]})

    def test_the_signature_is_device_file_index_size_and_modification_time(self):
        stat = self.source.stat()
        self.assertEqual(
            _signature(self.source),
            (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
        )

    def test_each_signature_component_alone_makes_the_captured_target_stale(self):
        for component in ("mtime", "size", "inode"):
            with self.subTest(changed=component):
                target = self.backend.capture_target(str(self.source))
                try:
                    self.assertIs(
                        self.backend.is_target_current(str(self.source), target), True
                    )
                    self._change_only(component)
                    self.assertIs(
                        self.backend.is_target_current(str(self.source), target),
                        False,
                    )
                    with self.assertRaises(RuntimeError) as refused:
                        self.backend.prepare(str(self.source), target)
                    self.assertEqual(
                        str(refused.exception),
                        "The selected database changed; start maintenance again.",
                    )
                finally:
                    target.close()
                self.assertEqual(self.manager._maintenance_paths, set())

    def test_each_signature_component_alone_stops_the_commit_before_the_swap(self):
        for component in ("mtime", "size", "inode"):
            with self.subTest(changed=component):
                prepared = self.stage()
                try:
                    self._change_only(component)
                    untouched = self.source.read_bytes()
                    with self.assertRaises(RuntimeError) as refused:
                        prepared.commit()
                    self.assertEqual(
                        str(refused.exception),
                        "The source database changed during maintenance; "
                        "it was not replaced.",
                    )
                    self.assertEqual(self.source.read_bytes(), untouched)
                finally:
                    prepared.close()
                self.assertEqual(list(self.folder.iterdir()), [self.source])
                self.assertEqual(self.manager._maintenance_paths, set())

    def test_an_interrupt_while_capturing_releases_the_maintenance_reservation(self):
        readings = []

        def interrupted_second_reading(path):
            readings.append(path)
            if len(readings) == 2:
                raise KeyboardInterrupt()
            return (1, 2, 3, 4)

        reserved = None
        with patch(f"{_MODULE}._signature", interrupted_second_reading):
            try:
                self.backend.capture_target(str(self.source))
            except KeyboardInterrupt:
                # Looked at while the traceback still keeps the half-built lease
                # alive, so that garbage collection cannot hide a leaked
                # reservation.
                reserved = set(self.manager._maintenance_paths)
        self.assertEqual(len(readings), 2)
        self.assertEqual(reserved, set())
        target = self.backend.capture_target(str(self.source))
        self.addCleanup(target.close)
        self.assertTrue(target.active)

    def test_an_interrupt_while_compacting_releases_the_lease_and_the_work_folder(
        self,
    ):
        self.counts.side_effect = [{"Data": 1}, KeyboardInterrupt()]
        target = self.backend.capture_target(str(self.source))
        with patch(f"{_MODULE}.pythoncom") as com:
            with self.assertRaises(KeyboardInterrupt):
                self.backend.prepare(str(self.source), target)
        com.CoInitialize.assert_called_once_with()
        com.CoUninitialize.assert_called_once_with()
        self.assertFalse(target.active)
        self.assertEqual(self.manager._maintenance_paths, set())
        self.assertEqual(self.work_dirs(), [])
        self.assertEqual(self.source.read_bytes(), b"original")

    def test_a_database_with_an_upper_case_extension_is_available(self):
        for name in ("PROJECT.MDB", "Mixed.Mdb"):
            with self.subTest(name=name):
                upper = self.folder / name
                upper.write_bytes(b"x")
                self.assertEqual(self.backend.unavailable_reason(str(upper)), "")

    def test_a_locked_work_folder_reports_the_failure_and_can_be_cleaned_up_later(
        self,
    ):
        prepared = self.stage()
        self.addCleanup(prepared.close)
        (work,) = self.work_dirs()
        with open(work / "locked.tmp", "wb"):
            with self.assertRaises(PermissionError):
                prepared.close()
            self.assertTrue(work.is_dir())
            self.assertEqual(self.manager._maintenance_paths, set())
        prepared.close()
        self.assertEqual(self.work_dirs(), [])
