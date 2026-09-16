import sqlite3
import tempfile
import unittest
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationRequest,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.use_cases.project.insert_annotations_use_case import (
    InsertAnnotationsUseCase,
)
from ost_visualizer.application.use_cases.project.delete_annotations_use_case import (
    DeleteAnnotationsUseCase,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from tests.test_infrastructure_lifecycle import (
    _SqliteAnnotationOps,
    _SqliteConnectionWrapper,
    _SqliteSchema,
    _SqliteDuplicateOps,
)
from tests.test_plan_view_action_handler import (
    FakePlanView,
    FakeWriteService,
    FakeUndoService,
)
from tests.test_detached_window_workspace_state import (
    FakeDetachedPlanView,
    _full_plan_surface_access,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter


class _AnnotationOps(BidDataReaderMixin, _SqliteAnnotationOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class _TransactionConnection(_SqliteConnectionWrapper):
    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()


class _Connections:
    def __init__(self, connection):
        self.connection_ref = connection
        self.committed_reads = []

    @contextmanager
    def connection(self, _path, *, autocommit):
        assert not autocommit
        yield _TransactionConnection(self.connection_ref)

    def use_committed_writer_for_reads(self, path):
        self.committed_reads.append(path)


class _RoutedAnnotationWriter(DatabaseProjectWriter):
    def _schema(self, _connection):
        return _SqliteSchema(self._conn_manager.connection_ref)

    _execute_insert_values = _SqliteDuplicateOps._execute_insert_values


class AnnotationLayerOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(
            """
            CREATE TABLE Bids (UID INTEGER);
            INSERT INTO Bids VALUES (1), (179326);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidPages VALUES (10, 1), (20, 179326);
            CREATE TABLE BidLayers (
                UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER,
                Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER);
            INSERT INTO BidLayers VALUES (2, 1, 'Annotation', -1, 1, -1, -1);
            INSERT INTO BidLayers VALUES (7, 179326, 'Annotation', -1, 1, 0, -1);
            CREATE TABLE BidAnnotationRects (
                UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,
                BidLayerUID INTEGER, Position BLOB, Color INTEGER, Width INTEGER);
        """
        )
        self.ops = _AnnotationOps(self.connection)
        self.model = OstAggregate(None)
        self.data = ProjectDataService(self.model)
        self.write_service = Mock()
        self.write_service.insert_annotations.side_effect = (
            lambda path, bid, specs, **_kwargs: self.ops.insert_annotations(
                path, bid, specs
            )
        )
        self.coordinator = AnnotationWriteCoordinator(
            self.write_service, self.data, Mock()
        )

    def select_bid(self, bid_uid, page_uid):
        self.model.clear_bid()
        self.model.current_bid_ref = BidRef("layers.mdb", bid_uid)
        self.model.set_pages({page_uid: Page(uid=page_uid, name="Page")})
        self.data.set_bid_layer_visibility(
            self.ops.get_bid_layers_for_sidebar("layers.mdb", bid_uid)
        )

    @staticmethod
    def spec(page_uid="20", layer_uid=""):
        return InsertAnnotationSpec(
            page_uid=page_uid,
            annotation_type="rect",
            position=[0, 0, 5, 5],
            color="#000000",
            width=1,
            layer_uid=layer_uid,
        )

    def test_switch_bid_uses_owned_layer_despite_foreign_sidebar_template(self):
        self.select_bid("1", "10")
        first = self.spec("10")
        self.assertTrue(
            self.coordinator.insert_annotations(self.model.current_bid_ref, [first])
        )
        self.assertEqual(first.layer_uid, "2")
        self.select_bid("179326", "20")
        self.assertEqual(
            [(layer.uid, layer.bid_uid) for layer in self.model.bid_layers],
            [("2", "1"), ("7", "179326")],
        )
        specs = [self.spec(), self.spec()]
        self.assertEqual(
            len(self.coordinator.insert_annotations(self.model.current_bid_ref, specs)),
            2,
        )
        self.assertEqual([spec.layer_uid for spec in specs], ["7", "7"])
        self.assertEqual(
            self.connection.execute(
                "SELECT BidLayerUID FROM BidAnnotationRects WHERE BidUID=179326"
            ).fetchall(),
            [(7,), (7,)],
        )

    def test_explicit_foreign_layer_still_rejected_before_any_batch_insert(self):
        self.select_bid("179326", "20")
        with self.assertRaisesRegex(
            MissingBidOwnedUidError, r"BidLayers.UID=2.*179326"
        ):
            self.coordinator.insert_annotations(
                self.model.current_bid_ref,
                [self.spec(layer_uid="7"), self.spec(layer_uid="2")],
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM BidAnnotationRects"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(self.model.get_all_annotations(), [])

    def test_routed_rejected_annotation_rolls_back_and_returns_failed_result(self):
        manager = _Connections(self.connection)
        writer = _RoutedAnnotationWriter(
            manager, DatabaseDescriptorRegistry(), object(), object()
        )
        request = DatabaseMutationRequest(
            database_id="layers.mdb",
            session_id="",
            operation_id=str(uuid.uuid4()),
            mutation_type="project_write",
            request_hash="0" * 64,
        )

        def insert(_recorder):
            return writer.insert_annotations(
                "layers.mdb", "179326", [self.spec(layer_uid="2")]
            )

        with self.assertLogs(writer.logger.name, level="ERROR"):
            result = writer.execute(request, insert)
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertIsNone(result.value)
        self.assertFalse(result.commit_attempted)
        self.assertIn("BidLayers.UID=2", result.failure_reason)
        self.assertEqual(manager.committed_reads, [])
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM BidAnnotationRects"
            ).fetchone()[0],
            0,
        )

    def make_handler(self, write_service):
        plan = FakePlanView()
        plan.current_page_uid = "20"
        plan.annotation_key_map = {("1", "rect"): "1_rect"}
        undo = FakeUndoService()
        ui_state = Mock()
        ui_state.get_selected_bid_ref.side_effect = lambda: self.model.current_bid_ref
        project_writer = FakeWriteService()
        handler = PlanViewActionHandler(
            plan_view=plan,
            ui_state_manager=ui_state,
            project_data_svc=self.data,
            project_write_svc=project_writer,
            annotation_write_svc=write_service,
            page_settings_bar=Mock(),
            undo_svc=undo,
            event_bus=Mock(),
            deferred_persistence_manager=Mock(),
            ui_access_manager=Mock(),
        )
        return handler, plan, undo, project_writer

    def make_service(self, writer=None):
        if writer is None:
            writer = _RoutedAnnotationWriter(
                _Connections(self.connection),
                DatabaseDescriptorRegistry(),
                object(),
                object(),
            )
        sessions = Mock()
        sessions.get.return_value = None
        sessions.lock_tokens.return_value = ()
        tokens = Mock()
        tokens.expected_versions.return_value = ()
        tokens.mutation_scope.side_effect = lambda _path: nullcontext()
        guard = Mock()
        guard.blocks_active_locked_bid_write.return_value = False
        return AnnotationWriteService(
            Mock(),
            Mock(),
            Mock(),
            InsertAnnotationsUseCase(writer),
            DeleteAnnotationsUseCase(writer),
            mutation_executor=writer,
            session_registry=sessions,
            concurrency_tokens=tokens,
            database_capability_service=Mock(),
            bid_write_guard=guard,
            project_data_service=self.data,
        )

    def test_action_rejection_has_no_projection_or_history_and_can_retry(self):
        self.select_bid("179326", "20")
        handler, plan, undo, _writer = self.make_handler(self.make_service())
        # The database changes after hydration: retain strict persistence validation.
        self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
        self.connection.commit()
        with patch(
            "ost_visualizer.presentation.handlers.plan_view_action_handler.show_warning"
        ) as warning, self.assertLogs(level="WARNING") as logs:
            handler.on_annotation_created("rect", [0, 0, 5, 5], "20")
        warning.assert_called_once()
        self.assertIn("BidLayers has no row for UID 7", "\n".join(logs.output))
        self.assertIn("bid=179326", "\n".join(logs.output))
        self.assertEqual(undo.count, 0)
        self.assertEqual(plan.selected, set())
        self.assertEqual(self.model.get_all_annotations(), [])
        self.connection.execute(
            "INSERT INTO BidLayers VALUES (7, 179326, 'Annotation', -1, 1, 0, -1)"
        )
        self.connection.commit()
        handler.on_annotation_created("rect", [0, 0, 5, 5], "20")
        self.assertEqual(undo.count, 1)
        self.assertEqual(plan.selected, {"1_rect"})
        self.assertEqual([a.layer_uid for a in self.model.get_all_annotations()], ["7"])
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM BidAnnotationRects"
            ).fetchone()[0],
            1,
        )

    def test_sql_queue_uses_owned_layer_and_scoped_dependency(self):
        self.select_bid("1", "10")
        self.select_bid("179326", "20")
        handler, _plan, _undo, writer = self.make_handler(Mock())
        with patch.object(
            writer, "uses_sql_collaboration_mutations", return_value=True
        ), patch.object(writer, "queue_plan_items_paste") as queue:
            handler.on_annotation_created("rect", [0, 0, 5, 5], "20")
        payload = queue.call_args.args[1]
        self.assertEqual(payload.annotation_specs[0].layer_uid, "7")
        dependencies = queue.call_args.kwargs["dependency_resources"]
        self.assertEqual(dependencies, (ResourceRef("layer", "7", 179326),))

    def test_template_only_keeps_optional_layer_unassigned_not_foreign(self):
        self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
        self.connection.execute("UPDATE BidLayers SET BidUID=NULL WHERE UID=2")
        self.select_bid("179326", "20")
        self.assertEqual(
            [(layer.uid, layer.bid_uid) for layer in self.model.bid_layers],
            [("2", "")],
        )
        spec = self.spec()
        self.assertTrue(
            self.coordinator.insert_annotations(self.model.current_bid_ref, [spec])
        )
        self.assertEqual(spec.layer_uid, "")
        self.assertIsNone(
            self.connection.execute(
                "SELECT BidLayerUID FROM BidAnnotationRects"
            ).fetchone()[0]
        )

    def test_scoped_lookup_rejects_other_bid_or_database(self):
        self.select_bid("179326", "20")
        for ref in (BidRef("layers.mdb", "1"), BidRef("other.mdb", "179326")):
            with self.subTest(ref=ref), self.assertRaisesRegex(
                ValueError, "current Bid"
            ):
                self.data.get_bid_annotation_layer_uid(ref)

    def test_unassigned_annotation_follows_display_visibility_without_taking_its_uid(
        self,
    ):
        self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
        self.connection.execute("UPDATE BidLayers SET BidUID=NULL WHERE UID=2")
        self.select_bid("179326", "20")
        self.coordinator.insert_annotations(self.model.current_bid_ref, [self.spec()])
        annotation = self.model.get_all_annotations()[0]
        self.assertEqual(annotation.layer_uid, "")
        self.assertTrue(annotation.visible)
        self.data.update_layer_visibility("2", False)
        self.assertFalse(annotation.visible)
        self.data.update_layer_visibility("unrelated", True)
        self.assertFalse(annotation.visible)
        self.data.update_all_layer_visibility(True)
        self.assertTrue(annotation.visible)
        self.assertEqual(annotation.layer_uid, "")

    def test_unassigned_annotation_added_to_hidden_template_stays_hidden(self):
        self.select_bid("179326", "20")
        self.data.set_bid_layer_visibility(
            [BidLayer("2", "", "Annotation", False, 1, True, True)]
        )
        annotation = BidAnnotation(
            uid="new", annotation_type="rect", page_uid="20", layer_uid=""
        )
        self.data.add_annotations([annotation])
        self.assertFalse(annotation.visible)
        self.assertEqual(annotation.layer_uid, "")

    def test_reopening_bid_projects_template_visibility_without_assigning_ownership(
        self,
    ):
        annotation = BidAnnotation(
            uid="1", annotation_type="rect", page_uid="20", layer_uid=""
        )
        prepared = PreparedBidLoad(
            BidLoadResult(
                pages={"20": Page(uid="20", name="Page")},
                bid_annotations=[annotation],
                bid_layers=[BidLayer("2", "", "Annotation", False, 1, True, True)],
            ),
            None,
        )
        loader = LoadBidUseCase(self.model, self.data, Mock(), Mock(), Mock())
        self.assertTrue(loader.apply_prepared(BidRef("layers.mdb", "179326"), prepared))
        self.assertIs(self.model.get_all_annotations()[0], annotation)
        self.assertFalse(annotation.visible)
        self.assertEqual(annotation.layer_uid, "")

    def test_native_access_global_template_and_owned_layer_creation(self):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        self.addCleanup(pythoncom.CoUninitialize)
        try:
            engine = win32com.client.Dispatch("DAO.DBEngine.120")
        except pythoncom.com_error as exc:
            self.skipTest(f"Access DAO unavailable: {exc.hresult}")
        folder = tempfile.TemporaryDirectory(prefix="ostv_annotation_acceptance_")
        self.addCleanup(folder.cleanup)
        path = str(Path(folder.name) / "annotations.mdb")
        database = engine.CreateDatabase(path, ";LANGID=0x0409;CP=1252;COUNTRY=0", 64)
        try:
            for statement in (
                "CREATE TABLE Bids (UID LONG)",
                "INSERT INTO Bids VALUES (179326)",
                "CREATE TABLE BidPages (UID LONG, BidUID LONG)",
                "INSERT INTO BidPages VALUES (20, 179326)",
                "CREATE TABLE BidLayers (UID LONG, BidUID LONG, Name TEXT, "
                "Show YESNO, Sequence LONG, IsTemplate YESNO, IsLocked YESNO)",
                "INSERT INTO BidLayers VALUES (2, NULL, 'Annotation', -1, 1, -1, -1)",
                "CREATE TABLE BidAnnotationRects (UID LONG, BidUID LONG, "
                "BidPageUID LONG, BidLayerUID LONG, Position LONGBINARY, "
                "Color LONG, Width LONG)",
            ):
                database.Execute(statement)
        finally:
            database.Close()
        manager = MdbConnectionManager()
        self.addCleanup(manager.close)
        reader = MdbReader(conn_manager=manager)
        writer = DatabaseProjectWriter(
            manager, DatabaseDescriptorRegistry(), object(), object()
        )
        self.model.current_bid_ref = BidRef(path, "179326")
        self.model.set_pages({"20": Page(uid="20", name="Page")})
        coordinator = AnnotationWriteCoordinator(
            self.make_service(writer), self.data, Mock()
        )
        for expected in (None, 7):
            with self.subTest(expected_layer=expected):
                self.data.set_bid_layer_visibility(
                    reader.get_bid_layers_for_sidebar(path, "179326")
                )
                spec = self.spec()
                self.assertTrue(
                    coordinator.insert_annotations(self.model.current_bid_ref, [spec])
                )
                self.assertEqual(spec.layer_uid, "" if expected is None else "7")
                if expected is None:
                    with manager.connection(path, autocommit=False) as connection:
                        connection.cursor().execute(
                            "INSERT INTO BidLayers VALUES (7, 179326, 'Annotation', -1, 1, 0, -1)"
                        )
                        connection.commit()
        with self.assertLogs(writer.logger.name, level="ERROR"):
            self.assertEqual(
                coordinator.insert_annotations(
                    self.model.current_bid_ref, [self.spec(layer_uid="2")]
                ),
                [],
            )
        manager.close()
        # Reopen through the real driver, independently of the projected model.
        with manager.connection(path) as connection:
            rows = (
                connection.cursor()
                .execute("SELECT BidLayerUID FROM BidAnnotationRects ORDER BY UID")
                .fetchall()
            )
            self.assertEqual([row[0] for row in rows], [None, 7])

    def test_main_create_undo_redo_retains_nullable_and_owned_layers(self):
        for owned in (False, True):
            with self.subTest(owned=owned):
                self.connection.execute("DELETE FROM BidAnnotationRects")
                self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
                if owned:
                    self.connection.execute(
                        "INSERT INTO BidLayers VALUES (7,179326,'Annotation',-1,1,0,-1)"
                    )
                self.connection.commit()
                self.select_bid("179326", "20")
                handler, plan, undo, _writer = self.make_handler(self.make_service())
                handler.on_annotation_created("rect", [0, 0, 5, 5], "20")
                self.assertEqual(undo.count, 1)
                self.assertTrue(undo.undo())
                self.assertEqual(self.model.get_all_annotations(), [])
                self.assertEqual(plan.selected, set())
                self.assertTrue(undo.redo())
                self.assertEqual(plan.selected, {"1_rect"})
                self.assertEqual(
                    [
                        row[0]
                        for row in self.connection.execute(
                            "SELECT BidLayerUID FROM BidAnnotationRects"
                        )
                    ],
                    [7 if owned else None],
                )

    def test_detached_creation_uses_same_nullable_and_owned_contract(self):
        for owned in (True, False):
            with self.subTest(owned=owned):
                self.connection.execute("DELETE FROM BidAnnotationRects")
                if not owned:
                    self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
                self.select_bid("179326", "20")
                service = self.make_service()
                window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
                window._config = SimpleNamespace(allow_annotation_editing=True)
                window._access_state = _full_plan_surface_access()
                window._is_closing = False
                window._ann_write_svc = service
                window._project_write_svc = None
                window._file_path = "layers.mdb"
                window._undo_svc = None
                window._annotation_write_coordinator = AnnotationWriteCoordinator(
                    service, self.data, Mock()
                )
                window.plan_view = FakeDetachedPlanView()
                window.plan_view.annotation_key_map[("1", "rect")] = "1_rect"
                window.view = SimpleNamespace(bid_ref=self.model.current_bid_ref)
                window._on_annotation_created("rect", [0, 0, 5, 5], "20")
                self.assertEqual(window.plan_view.selected_uids, {"1_rect"})
                self.assertEqual(
                    [
                        row[0]
                        for row in self.connection.execute(
                            "SELECT BidLayerUID FROM BidAnnotationRects"
                        )
                    ],
                    [7 if owned else None],
                )

    def test_bulk_defaults_preserve_explicit_custom_layer_and_style(self):
        self.connection.execute(
            "INSERT INTO BidLayers VALUES (17,179326,'Custom',-1,2,0,0)"
        )
        self.select_bid("179326", "20")
        default, explicit = self.spec(), self.spec(layer_uid="17")
        explicit.color, explicit.width = "#123456", 3
        self.assertEqual(
            len(
                self.coordinator.insert_annotations(
                    self.model.current_bid_ref, [default, explicit]
                )
            ),
            2,
        )
        annotations = self.model.get_all_annotations()
        self.assertEqual([a.layer_uid for a in annotations], ["7", "17"])
        self.assertEqual((annotations[1].color, annotations[1].width), ("#123456", 3))
        self.data.update_layer_visibility("7", False)
        self.assertFalse(annotations[0].visible)
        self.assertTrue(annotations[1].visible)
        copies = self.coordinator.insert_saved_annotations(
            self.model.current_bid_ref, [annotations[1]]
        )
        self.assertEqual(copies[0].layer_uid, "17")

    def test_null_sql_layer_has_no_dependency_and_is_pdf_exportable(self):
        self.connection.execute("DELETE FROM BidLayers WHERE UID=7")
        self.select_bid("179326", "20")
        handler, _plan, _undo, writer = self.make_handler(Mock())
        with patch.object(
            writer, "uses_sql_collaboration_mutations", return_value=True
        ), patch.object(writer, "queue_plan_items_paste") as queue:
            handler.on_annotation_created("rect", [0, 0, 5, 5], "20")
        self.assertEqual(queue.call_args.kwargs["dependency_resources"], ())
        self.assertEqual(queue.call_args.args[1].annotation_specs[0].layer_uid, "")
        annotation = BidAnnotation(
            uid="1", annotation_type="rect", page_uid="20", layer_uid="", visible=True
        )
        self.assertTrue(PDFExporter._is_annotation_exportable(annotation, "20", "rect"))
        annotation.visible = False
        self.assertFalse(
            PDFExporter._is_annotation_exportable(annotation, "20", "rect")
        )

    def test_remote_projection_preserves_null_and_explicit_ownership_with_display_visibility(
        self,
    ):
        self.select_bid("179326", "20")
        unassigned = BidAnnotation(
            uid="1", annotation_type="rect", page_uid="20", layer_uid=""
        )
        explicit = BidAnnotation(
            uid="2", annotation_type="rect", page_uid="20", layer_uid="7"
        )
        self.assertTrue(
            self.data.replace_remote_bid_families(
                self.model.current_bid_ref,
                BidLoadResult(
                    bid_annotations=[unassigned, explicit],
                    bid_layers=[
                        BidLayer("2", "", "Annotation", False, 1, True, True),
                        BidLayer("7", "179326", "Custom", True, 2),
                    ],
                ),
                {"annotations", "layers"},
            )
        )
        self.assertEqual(
            [a.layer_uid for a in self.model.get_all_annotations()], ["", "7"]
        )
        self.assertFalse(unassigned.visible)
        self.assertTrue(explicit.visible)
        self.data.update_layer_visibility("2", True)
        self.assertTrue(unassigned.visible)
        self.assertEqual(unassigned.layer_uid, "")
