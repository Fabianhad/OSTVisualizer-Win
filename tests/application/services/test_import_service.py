import os
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.collaboration_dtos import ProjectImportPayload
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.import_service import ImportService


class _Importer:
    def __init__(self):
        self.calls = []
        self.success = True
        self.error = None
        self.identities = {
            name: {}
            for name in (
                "project_uids",
                "bid_uids",
                "page_uids",
                "condition_uids",
                "layer_uids",
                "area_uids",
                "takeoff_uids",
                "annotation_uids",
            )
        }
        self.identities["bid_uids"] = {"source": "target"}

    def _import(self, kind, source, target, project, recorder=None):
        self.calls.append((kind, source, target, project, recorder))
        if self.error is not None:
            raise self.error
        return self.identities if recorder is not None else self.success

    def import_ost(self, source, target, project=None):
        return self._import("ost", source, target, project)

    def import_osp(self, source, target, project=None):
        return self._import("osp", source, target, project)

    def import_ost_mutation(self, source, target, project, recorder):
        return self._import("ost", source, target, project, recorder)

    def import_osp_mutation(self, source, target, project, recorder):
        return self._import("osp", source, target, project, recorder)


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **payload):
        self.events.append(event_type(**payload))


class _Writes:
    def __init__(self):
        self.requests = []
        self.request_id = 17
        self.queries = []

    def uses_sql_collaboration_mutations(self, database_id):
        self.queries.append(database_id)
        return database_id == "sql-db"

    def queue_project_import(self, database_id, project_uid, payload, work, callback):
        self.requests.append((database_id, project_uid, payload, work, callback))
        return self.request_id


class ImportServiceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.ost = _Importer()
        self.osp = _Importer()
        self.events = _Events()
        self.writes = _Writes()
        self.reloads = []
        self.reload_result = True
        self.service = ImportService(
            self.ost, self.osp, self.writes, self._reload, self.events
        )

    def _reload(self, database):
        self.reloads.append(database)
        return self.reload_result

    def test_import_service_can_import_without_refreshing_or_publishing(self):
        self.assertIs(
            self.service.import_ost(
                "source.ost", "target.mdb", "project-1", refresh=False
            ),
            True,
        )
        self.assertIs(
            self.service.import_osp("source.osp", "other.mdb", refresh=False), True
        )
        self.assertEqual(
            self.ost.calls, [("ost", "source.ost", "target.mdb", "project-1", None)]
        )
        self.assertEqual(
            self.osp.calls, [("osp", "source.osp", "other.mdb", None, None)]
        )
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.events.events, [])
        self.assertEqual(self.writes.requests, [])

    def test_only_successful_import_and_reload_publish_one_scoped_event(self):
        for operation, importer, kind in (
            (self.service.import_ost, self.ost, "ost"),
            (self.service.import_osp, self.osp, "osp"),
        ):
            for imported, refreshed in ((False, True), (True, False), (True, True)):
                with self.subTest(kind=kind, imported=imported, refreshed=refreshed):
                    self.reloads.clear()
                    self.events.events.clear()
                    importer.calls.clear()
                    importer.success = imported
                    self.reload_result = refreshed
                    # Legacy Boolean reports the write result, not refresh success.
                    self.assertIs(
                        operation("source." + kind, "target.mdb", "project-1"), imported
                    )
                    self.assertEqual(
                        importer.calls,
                        [(kind, "source." + kind, "target.mdb", "project-1", None)],
                    )
                    self.assertEqual(self.reloads, ["target.mdb"] if imported else [])
                    self.assertEqual(
                        self.events.events,
                        (
                            [AppEvents.DATABASE_REFRESHED(file_path="target.mdb")]
                            if imported and refreshed
                            else []
                        ),
                    )

    def test_importer_exception_does_not_reload_or_publish_success(self):
        for operation, importer in (
            (self.service.import_ost, self.ost),
            (self.service.import_osp, self.osp),
        ):
            with self.subTest(operation=operation.__name__):
                importer.error = OSError("source unreadable")
                with self.assertRaisesRegex(OSError, "source unreadable"):
                    operation("source", "target.mdb")
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.events.events, [])
        self.assertEqual(self.ost.calls, [("ost", "source", "target.mdb", None, None)])
        self.assertEqual(self.osp.calls, [("osp", "source", "target.mdb", None, None)])

    def test_backend_selection_is_delegated_for_exact_database(self):
        self.assertTrue(self.service.uses_sql_collaboration_import("sql-db"))
        self.assertFalse(self.service.uses_sql_collaboration_import("target.mdb"))
        self.assertEqual(self.writes.queries, ["sql-db", "target.mdb"])
        self.assertEqual(self.writes.requests, [])

    def test_queued_import_snapshots_source_metadata_and_runs_correct_mutation(self):
        for kind, importer, project in (
            ("ost", self.ost, "project-1"),
            ("osp", self.osp, None),
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / ("source." + kind)
                source.write_bytes(b"captured content")
                stat = source.stat()
                outcomes = []
                callback = outcomes.append
                request_id = self.service.queue_project_import(
                    str(source), kind, "sql-db", project, callback
                )
                self.assertEqual(request_id, 17)
                self.assertEqual(importer.calls, [])
                database, target, payload, work, completion = self.writes.requests[-1]
                self.assertEqual((database, target), ("sql-db", project))
                self.assertEqual(
                    payload,
                    ProjectImportPayload(
                        source_path=str(source),
                        source_kind=kind,
                        source_size=stat.st_size,
                        source_modified_ns=stat.st_mtime_ns,
                        target_project_uid=project or "",
                    ),
                )
                self.assertIs(completion, callback)
                recorder = object()  # Execution-owned opaque token forwarded unchanged.
                self.assertIs(work(recorder), importer.identities)
                self.assertEqual(
                    importer.calls, [(kind, str(source), "sql-db", project, recorder)]
                )
                self.assertEqual(outcomes, [])
        self.assertEqual(len(self.writes.requests), 2)
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.events.events, [])

    def test_changed_or_removed_queued_source_rejects_before_import(self):
        for change in ("size", "mtime", "deleted"):
            with self.subTest(
                change=change
            ), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source.ost"
                source.write_bytes(b"old")
                self.service.queue_project_import(
                    str(source), "ost", "sql-db", None, self.fail
                )
                payload, work = self.writes.requests[-1][2:4]
                if change == "size":
                    source.write_bytes(b"longer content")
                    os.utime(
                        source,
                        ns=(payload.source_modified_ns, payload.source_modified_ns),
                    )
                elif change == "mtime":
                    os.utime(
                        source,
                        ns=(
                            payload.source_modified_ns,
                            payload.source_modified_ns + 2_000_000_000,
                        ),
                    )
                else:
                    source.unlink()
                expected = FileNotFoundError if change == "deleted" else RuntimeError
                with self.assertRaises(expected):
                    work(object())
        self.assertEqual(self.ost.calls, [])
        self.assertEqual(self.osp.calls, [])
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.events.events, [])

    def test_invalid_source_or_kind_never_submits_a_request(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.ost"
            with self.assertRaises(FileNotFoundError):
                self.service.queue_project_import(
                    str(source), "ost", "sql-db", None, self.fail
                )
            source.write_bytes(b"valid file")
            with self.assertRaisesRegex(ValueError, "must be OST or OSP"):
                self.service.queue_project_import(
                    str(source), "unknown", "sql-db", None, self.fail
                )
        self.assertEqual(self.writes.requests, [])
        self.assertEqual(self.ost.calls, [])
        self.assertEqual(self.osp.calls, [])

    def test_queue_rejection_is_returned_without_running_import(self):
        self.writes.request_id = 0
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.ost"
            source.write_bytes(b"valid file")
            self.assertEqual(
                self.service.queue_project_import(
                    str(source), "ost", "sql-db", None, self.fail
                ),
                0,
            )
        self.assertEqual(len(self.writes.requests), 1)
        self.assertEqual(self.ost.calls, [])
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.events.events, [])
