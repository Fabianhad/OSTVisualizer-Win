import unittest
from ost_visualizer.application.dtos.file_dto import FileLoadResultDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.domain.entities.file_state import normalize_path
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)


class _Prepared:
    def __init__(self, trace):
        self.trace = trace
        self.result = DatabaseMaintenanceResult(True, "committed")
        self.commit_error = None
        self.close_error = None

    def commit(self):
        self.trace.append("commit")
        if self.commit_error:
            raise self.commit_error
        return self.result

    def close(self):
        self.trace.append("close")
        if self.close_error:
            raise self.close_error


class _Backend:
    def __init__(self, trace):
        self.trace = trace
        self.identity = object()
        self.prepared = None
        self.reason = ""
        self.prepare_error = None
        self.compact_work = lambda _path: DatabaseMaintenanceResult(True, "compacted")

    def capture_target(self, locator):
        self.trace.append(("capture", locator))
        return self.identity

    def is_target_current(self, locator, identity):
        self.trace.append(("current", locator, identity))
        return identity is self.identity

    def release_target(self, locator, identity):
        self.trace.append(("release", locator, identity))

    def prepare(self, locator, identity):
        self.trace.append(("prepare", locator, identity))
        if self.prepare_error:
            raise self.prepare_error
        self.prepared = _Prepared(self.trace)
        return self.prepared

    def unavailable_reason(self, locator):
        self.trace.append(("available", locator))
        return self.reason

    def compact(self, locator):
        self.trace.append(("compact", locator))
        return self.compact_work(locator)


class _Files:
    def __init__(self, trace):
        self.trace = trace
        self.hierarchy = HierarchyData([HierarchyFileEntry("db.mdb")])
        self.data_service = self
        self.reload_result = FileLoadResultDto(True, "db.mdb")
        self.reload_error = None
        self.reload_hook = None
        self.unload_success = True

    def get_hierarchy(self):
        return self.hierarchy

    def reload_database(self, locator):
        self.trace.append(("reload", locator))
        if self.reload_hook:
            self.reload_hook()
        if self.reload_error:
            raise self.reload_error
        return self.reload_result

    def unload(self, locator):
        self.trace.append(("unload", locator))
        if self.unload_success:
            self.hierarchy.loaded_files[:] = [
                entry
                for entry in self.hierarchy.loaded_files
                if normalize_path(entry.file_path) != normalize_path(locator)
            ]
        return self.unload_success


class _Events:
    def __init__(self, trace):
        self.trace = trace
        self.events = []

    def publish(self, event_type, **payload):
        self.events.append(event_type(**payload))
        self.trace.append("event")


class _MaintenanceCase(unittest.TestCase):
    def setUp(self):
        self.trace = []
        self.backend = _Backend(self.trace)
        self.files = _Files(self.trace)
        self.events = _Events(self.trace)
        self.service = DatabaseMaintenanceService(self.backend, self.files, self.events)

    def _prepare(self):
        target = self.service.capture_target("db.mdb")
        return target, self.service.prepare(target)

    def _assert_retry_can_acquire(self):
        target, prepared = self._prepare()
        self.service.discard(prepared)


class MaintenanceRefreshTests(_MaintenanceCase):
    def test_reentrant_compaction_rejects_duplicate_then_refreshes_exact_database(self):
        overlapping = []

        def compact(_locator):
            overlapping.append(self.service.compact("db.mdb"))
            return DatabaseMaintenanceResult(True, "done")

        self.backend.compact_work = compact
        self.assertEqual(
            self.service.compact(""),
            DatabaseMaintenanceResult(False, "Select a database first."),
        )
        self.assertEqual(self.trace, [])
        self.assertEqual(
            self.service.compact("db.mdb"), DatabaseMaintenanceResult(True, "done")
        )
        self.assertEqual(
            overlapping,
            [
                DatabaseMaintenanceResult(
                    False, "Database maintenance is already running."
                )
            ],
        )
        self.assertEqual(self.trace, [("available", "db.mdb"), ("compact", "db.mdb")])
        self.assertEqual(
            self.service.refresh_loaded_database("db.mdb", self.files.unload),
            DatabaseMaintenanceResult(True, "Compact/Repair completed successfully."),
        )
        self.assertEqual(self.trace[-2:], [("reload", "db.mdb"), "event"])
        self.assertEqual(
            self.events.events, [AppEvents.DATABASE_REFRESHED(file_path="db.mdb")]
        )

    def test_unavailable_and_failed_compaction_release_lock_for_retry(self):
        self.backend.reason = "database is read-only"
        self.assertEqual(
            self.service.compact("db.mdb"),
            DatabaseMaintenanceResult(False, "database is read-only"),
        )
        self.assertEqual(self.trace, [("available", "db.mdb")])
        self.backend.reason = ""
        for error in (OSError("locked file"), RuntimeError()):
            with self.subTest(error=error):

                def fail(_locator):
                    raise error

                self.backend.compact_work = fail
                self.assertEqual(
                    self.service.compact("db.mdb"),
                    DatabaseMaintenanceResult(
                        False, str(error) or "Database maintenance failed."
                    ),
                )
        self.backend.compact_work = lambda _locator: DatabaseMaintenanceResult(
            True, "retry"
        )
        self.assertEqual(
            self.service.compact("db.mdb"), DatabaseMaintenanceResult(True, "retry")
        )
        self.assertEqual(self.events.events, [])


class MaintenanceServiceOwnershipTests(_MaintenanceCase):
    def test_maintenance_exclusion_covers_authoritative_reload(self):
        target, staged = self._prepare()

        def reload_hook():
            with self.assertRaisesRegex(RuntimeError, "already running"):
                self.service.prepare(target)

        self.files.reload_hook = reload_hook
        self.trace.clear()
        self.assertEqual(
            self.service.finish(target, staged, self.files.unload),
            DatabaseMaintenanceResult(True, "Compact/Repair completed successfully."),
        )
        self.assertEqual(
            self.trace,
            [
                ("current", "db.mdb", target.source_identity),
                "commit",
                "close",
                ("reload", "db.mdb"),
                "event",
            ],
        )
        self.assertEqual(
            self.events.events, [AppEvents.DATABASE_REFRESHED(file_path="db.mdb")]
        )
        self._assert_retry_can_acquire()

    def test_refresh_uses_loaded_owner_path_for_case_equivalent_target(self):
        owner = HierarchyFileEntry("C:/Data/Project.mdb")
        self.files.hierarchy.loaded_files = [owner]
        self.assertEqual(
            self.service.refresh_loaded_database(
                "c:/data/project.mdb", self.files.unload
            ),
            DatabaseMaintenanceResult(True, "Compact/Repair completed successfully."),
        )
        self.assertEqual(self.trace, [("reload", owner.file_path), "event"])
        self.assertEqual(
            self.events.events,
            [AppEvents.DATABASE_REFRESHED(file_path=owner.file_path)],
        )

    def test_reload_failure_clears_old_authoritative_projection(self):
        self.files.reload_result = FileLoadResultDto(False, error_message="read failed")
        result = self.service.refresh_loaded_database("db.mdb", self.files.unload)
        self.assertEqual(
            result,
            DatabaseMaintenanceResult(
                False,
                "Compaction completed, but refresh failed. The database was unloaded; reopen it to retry.",
            ),
        )
        self.assertEqual(self.files.hierarchy.loaded_files, [])
        self.assertEqual(self.trace, [("reload", "db.mdb"), ("unload", "db.mdb")])
        self.assertEqual(self.events.events, [])

    def test_reload_exception_and_failed_unload_report_recovery_without_success_event(
        self,
    ):
        self.files.reload_error = OSError("read failed")
        self.files.unload_success = False
        owner = self.files.hierarchy.loaded_files[0]
        self.assertEqual(
            self.service.refresh_loaded_database("db.mdb", self.files.unload),
            DatabaseMaintenanceResult(
                False,
                "Compaction completed, but refresh and unload failed. Close and reopen the application before continuing.",
            ),
        )
        self.assertIs(self.files.hierarchy.loaded_files[0], owner)
        self.assertEqual(self.trace, [("reload", "db.mdb"), ("unload", "db.mdb")])
        self.assertEqual(self.events.events, [])

    def test_unloaded_database_does_not_reload_another_owner_or_publish(self):
        owner = self.files.hierarchy.loaded_files[0]
        self.assertEqual(
            self.service.refresh_loaded_database("other.mdb", self.files.unload),
            DatabaseMaintenanceResult(True, "Compact/Repair completed successfully."),
        )
        self.assertEqual(self.trace, [])
        self.assertIs(self.files.hierarchy.loaded_files[0], owner)

    def test_captured_source_and_loaded_owner_are_both_exact_lifetimes(self):
        for replace_owner in (False, True):
            with self.subTest(replace_owner=replace_owner):
                target = self.service.capture_target("db.mdb")
                self.assertIs(target.loaded_owner, self.files.hierarchy.loaded_files[0])
                self.assertIs(target.source_identity, self.backend.identity)
                self.assertTrue(self.service.is_target_current(target))
                if replace_owner:
                    self.files.hierarchy.loaded_files[0] = HierarchyFileEntry("db.mdb")
                else:
                    self.backend.identity = object()
                self.assertFalse(self.service.is_target_current(target))
                self.trace.clear()
                with self.assertRaisesRegex(RuntimeError, "selected database changed"):
                    self.service.prepare(target)
                self.assertEqual(
                    self.trace[-1], ("release", "db.mdb", target.source_identity)
                )
                self.assertNotIn("commit", self.trace)
                self._assert_retry_can_acquire()

    def test_prepare_failure_releases_source_and_lock(self):
        target = self.service.capture_target("db.mdb")
        self.backend.prepare_error = OSError("stage failed")
        with self.assertRaisesRegex(OSError, "stage failed"):
            self.service.prepare(target)
        self.assertEqual(self.trace[-1], ("release", "db.mdb", target.source_identity))
        self.backend.prepare_error = None
        self._assert_retry_can_acquire()

    def test_stale_finish_closes_without_commit_or_refresh(self):
        target, staged = self._prepare()
        self.files.hierarchy.loaded_files[0] = HierarchyFileEntry("db.mdb")
        self.trace.clear()
        self.assertEqual(
            self.service.finish(target, staged, self.files.unload),
            DatabaseMaintenanceResult(
                False, "The selected database changed; maintenance was cancelled."
            ),
        )
        self.assertEqual(self.trace, ["close"])
        self.assertEqual(self.events.events, [])
        self._assert_retry_can_acquire()

    def test_failed_commit_closes_without_refresh_and_allows_retry(self):
        for raised in (False, True):
            with self.subTest(raised=raised):
                target, staged = self._prepare()
                staged.result = DatabaseMaintenanceResult(False, "commit rejected")
                staged.commit_error = OSError("commit failed") if raised else None
                self.trace.clear()
                expected = DatabaseMaintenanceResult(
                    False, "commit failed" if raised else "commit rejected"
                )
                self.assertEqual(
                    self.service.finish(target, staged, self.files.unload), expected
                )
                self.assertEqual(
                    self.trace,
                    [("current", "db.mdb", target.source_identity), "commit", "close"],
                )
                self.assertEqual(self.events.events, [])
                self._assert_retry_can_acquire()

    def test_close_failure_after_commit_still_refreshes_then_reports_cleanup_failure(
        self,
    ):
        target, staged = self._prepare()
        staged.close_error = OSError("temporary file busy")
        self.trace.clear()
        self.assertEqual(
            self.service.finish(target, staged, self.files.unload),
            DatabaseMaintenanceResult(
                False,
                "Compact/Repair completed successfully. Temporary-file cleanup failed: temporary file busy",
            ),
        )
        self.assertEqual(
            self.trace,
            [
                ("current", "db.mdb", target.source_identity),
                "commit",
                "close",
                ("reload", "db.mdb"),
                "event",
            ],
        )
        self.assertEqual(
            self.events.events, [AppEvents.DATABASE_REFRESHED(file_path="db.mdb")]
        )
        staged.close_error = None
        self._assert_retry_can_acquire()

    def test_discard_closes_without_commit_and_releases_lock_even_if_close_fails(self):
        for raised in (False, True):
            with self.subTest(raised=raised):
                _target, staged = self._prepare()
                staged.close_error = OSError("cleanup failed") if raised else None
                self.trace.clear()
                if raised:
                    with self.assertRaisesRegex(OSError, "cleanup failed"):
                        self.service.discard(staged)
                else:
                    self.service.discard(staged)
                self.assertEqual(self.trace, ["close"])
                self.assertEqual(self.events.events, [])
                staged.close_error = None
                self._assert_retry_can_acquire()
