import tempfile
import unittest
import uuid
from pathlib import Path, PureWindowsPath
from PySide6 import QtWidgets
from ost_visualizer.application.services.import_service import ImportService
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    _LoadedFileCache,
)
from ost_visualizer.presentation.handlers import import_handler as import_handler_module
from ost_visualizer.presentation.handlers.import_handler import ImportHandler


class FakeImporter:
    def __init__(self):
        self.calls = []

    def import_ost(self, source_path, target_path, project_uid=None):
        self.calls.append(("ost", source_path, target_path, project_uid))
        return True

    def import_osp(self, source_path, target_path, project_uid=None):
        self.calls.append(("osp", source_path, target_path, project_uid))
        return True

    def import_ost_mutation(self, source_path, target_path, project_uid, recorder):
        self.calls.append(
            ("ost_mutation", source_path, target_path, project_uid, recorder)
        )
        return {"bid_uids": {"source": "target"}}


class FakeOspCab:
    def __init__(self, names=None, ost_xml="<XML_ROOT />"):
        self.extract_calls = []
        self.root = None
        self.names = ["Project.ost"] if names is None else names
        self.ost_xml = ost_xml

    def list_cab(self, _source_path):
        return list(self.names)

    def extract_cab(self, _source_path, output_dir):
        self.extract_calls.append(output_dir)
        normal_output = self._normal_windows_path(output_dir)
        root = Path(normal_output)
        self.root = root
        for member_name in self.names:
            member_path = root.joinpath(*PureWindowsPath(member_name).parts)
            if member_path.suffix.lower() == ".ost":
                member_path.write_text(self.ost_xml, encoding="utf-8")
            elif member_path.suffix:
                member_path.write_bytes(b"packaged")
        return True

    def _normal_windows_path(self, value):
        if value.startswith("\\\\?\\UNC\\"):
            return "\\\\" + value[8:]
        if value.startswith("\\\\?\\"):
            return value[4:]
        return value


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **event_payload):
        self.events.append((event_type, event_payload))


class FakeImportService:
    def __init__(self):
        self.import_calls = []
        self.reloads = []
        self.next_result = True
        self.reload_result = True
        self.sql_collaboration = False
        self.queued_imports = []

    def import_ost(self, filename, target_db, target_project_uid, refresh=True):
        self.import_calls.append((filename, target_db, target_project_uid, refresh))
        return self.next_result

    def reload_and_notify(self, target_db):
        self.reloads.append(target_db)
        return self.reload_result

    def uses_sql_collaboration_import(self, _target_db):
        return self.sql_collaboration

    def queue_project_import(
        self, source, source_kind, target_db, project_uid, callback
    ):
        self.queued_imports.append(
            (source, source_kind, target_db, project_uid, callback)
        )
        return len(self.queued_imports)


class FakeProjectData:
    def get_current_file_path(self):
        return "target.mdb"


class FakeUiState:
    selected_project_uid = None
    selected_file_path = None

    def get_selected_bid_ref(self):
        return None


class FakeDeferredPersistence:
    def __init__(self, result=True):
        self.result = result
        self.flush_calls = []

    def flush_for_file(self, file_path):
        self.flush_calls.append(file_path)
        return self.result


class FakeProgressDialog:
    error = None
    result_code = QtWidgets.QDialog.DialogCode.Accepted
    instances = []

    def __init__(self, filename, task_fn, parent=None):
        self.filename = filename
        self.parent = parent
        self.result = task_fn()
        self.cleanup_calls = 0
        self.delete_later_calls = 0
        self.instances.append(self)

    def exec(self):
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1

    def deleteLater(self):
        self.delete_later_calls += 1


def _write_osp_page_xml_text(image_path: str) -> str:
    return f"""
                <XML_ROOT>
                  <Bid>
                    <BidPages>
                      <BidPage ImagePath="{image_path}"/>
                    </BidPages>
                  </Bid>
                </XML_ROOT>
                """


def _write_osp_page_xml(ost_path: Path, image_path: str) -> str:
    xml = _write_osp_page_xml_text(image_path)
    ost_path.write_text(xml, encoding="utf-8")
    return xml


def _write_packaged_image(tmp_path: Path, member_name: str, content: bytes) -> Path:
    path = tmp_path.joinpath(*PureWindowsPath(member_name).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class ImportRefreshFlowTests(unittest.TestCase):
    def test_import_service_can_import_without_refreshing_or_publishing(self):
        importer = FakeImporter()
        event_bus = FakeEventBus()
        reloads = []
        service = ImportService(
            ost_importer=importer,
            osp_importer=importer,
            project_write_service=type(
                "ProjectWriteService",
                (),
                {"uses_sql_collaboration_mutations": lambda _self, _path: False},
            )(),
            reload_database=lambda path: reloads.append(path) or True,
            event_bus=event_bus,
        )
        self.assertTrue(
            service.import_ost("source.ost", "target.mdb", "project-1", refresh=False)
        )
        self.assertEqual(
            importer.calls,
            [("ost", "source.ost", "target.mdb", "project-1")],
        )
        self.assertEqual(reloads, [])
        self.assertEqual(event_bus.events, [])

    def test_osp_import_extracts_cab_with_windows_extended_output_path(self):
        fake_cab = FakeOspCab()
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            self.assertTrue(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertEqual(len(fake_cab.extract_calls), 1)
        if osp_importer_module.os.name == "nt":
            self.assertTrue(fake_cab.extract_calls[0].startswith("\\\\?\\"))
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost")
        self.assertEqual(importer.calls[0][2:], ("target.mdb", "project-1"))
        self.assertFalse(fake_cab.root.exists())

    def test_osp_mutation_uses_shared_extraction_and_cleans_temp_files(self):
        fake_cab = FakeOspCab()
        importer = FakeImporter()
        recorder = object()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            result = OspImporter(importer).import_osp_mutation(
                "source.osp", "target.sql", "project-1", recorder
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertEqual(result, {"bid_uids": {"source": "target"}})
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost_mutation")
        self.assertEqual(importer.calls[0][2:], ("target.sql", "project-1", recorder))
        self.assertFalse(fake_cab.root.exists())

    def test_osp_import_rejects_unsafe_cab_member_paths_before_extraction(self):
        unsafe_names = (
            "..\\outside\\payload.ost",
            "C:\\outside\\payload.ost",
            "\\outside\\payload.ost",
            "\\\\server\\share\\payload.ost",
            "payload.ost:stream",
            ".",
        )
        original_cab = osp_importer_module.ost_cab
        try:
            for unsafe_name in unsafe_names:
                with self.subTest(member_name=unsafe_name):
                    fake_cab = FakeOspCab(names=["Project.ost", unsafe_name])
                    importer = FakeImporter()
                    osp_importer_module.ost_cab = fake_cab
                    with self.assertLogs(osp_importer_module.logger, level="ERROR"):
                        result = OspImporter(importer).import_osp(
                            "source.osp", "target.mdb", "project-1"
                        )
                    self.assertFalse(result)
                    self.assertEqual(fake_cab.extract_calls, [])
                    self.assertEqual(importer.calls, [])
        finally:
            osp_importer_module.ost_cab = original_cab

    def test_osp_import_requires_exactly_one_top_level_ost_member(self):
        archive_members = (
            [],
            ["First.ost", "Second.ost"],
            ["nested\\Project.ost"],
        )
        original_cab = osp_importer_module.ost_cab
        try:
            for names in archive_members:
                with self.subTest(names=names):
                    fake_cab = FakeOspCab(names=names)
                    importer = FakeImporter()
                    osp_importer_module.ost_cab = fake_cab
                    with self.assertLogs(osp_importer_module.logger, level="ERROR"):
                        result = OspImporter(importer).import_osp(
                            "source.osp", "target.mdb", "project-1"
                        )
                    self.assertFalse(result)
                    self.assertEqual(fake_cab.extract_calls, [])
                    self.assertEqual(importer.calls, [])
        finally:
            osp_importer_module.ost_cab = original_cab

    def test_osp_import_cleanup_failure_does_not_fail_successful_import(self):
        fake_cab = FakeOspCab()
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        original_rmtree = osp_importer_module.shutil.rmtree

        def failing_rmtree(_path):
            raise OSError("cleanup blocked")

        try:
            osp_importer_module.ost_cab = fake_cab
            osp_importer_module.shutil.rmtree = failing_rmtree
            with self.assertLogs(osp_importer_module.logger, level="WARNING"):
                self.assertTrue(
                    OspImporter(importer).import_osp(
                        "source.osp", "target.mdb", "project-1"
                    )
                )
        finally:
            osp_importer_module.ost_cab = original_cab
            osp_importer_module.shutil.rmtree = original_rmtree
            if fake_cab.root and fake_cab.root.exists():
                original_rmtree(fake_cab.root)
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost")

    def test_osp_import_uses_short_temp_root_for_long_archive_paths(self):
        if osp_importer_module.os.name != "nt":
            self.skipTest("Windows path length behavior only applies on Windows")
        base_dir = Path(tempfile.mkdtemp(prefix="ostv_test_osp_"))
        long_parent = base_dir / ("long_parent_" * 10)
        short_parent = base_dir / "s"
        long_member = "TempImages!.tmp\\" + "a" * 180 + ".pdf"
        fake_cab = FakeOspCab(names=["Project.ost", long_member])
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        original_candidates = osp_importer_module._extract_temp_parent_candidates
        try:
            osp_importer_module.ost_cab = fake_cab
            osp_importer_module._extract_temp_parent_candidates = lambda: [
                long_parent,
                short_parent,
            ]
            self.assertTrue(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
            )
        finally:
            osp_importer_module.ost_cab = original_cab
            osp_importer_module._extract_temp_parent_candidates = original_candidates
            if base_dir.exists():
                osp_importer_module.shutil.rmtree(base_dir)
        self.assertEqual(len(importer.calls), 1)
        self.assertTrue(str(fake_cab.root).startswith(str(short_parent)))

    def test_osp_import_rejects_nested_legacy_visualizer_layout(self):
        nested_member = "TempImages!.tmp\\generated-folder\\sheet.pdf"
        fake_cab = FakeOspCab(names=["Project.ost", nested_member])
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "legacy.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn(
            "unsupported legacy Visualizer export layout", "\n".join(logs.output)
        )
        self.assertEqual(fake_cab.extract_calls, [])
        self.assertEqual(importer.calls, [])

    def test_osp_import_uses_same_flat_lookup_for_original_and_visualizer_paths(self):
        member_name = "TempImages!.tmp\\A00.00.pdf"
        image_paths = (
            "C:\\OCS Documents\\OST\\Project\\A00.00.pdf",
            member_name,
        )
        for source_path in image_paths:
            with self.subTest(
                source_path=source_path
            ), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                _write_packaged_image(tmp_path, member_name, b"packaged")
                ost_path = tmp_path / "Project.ost"
                _write_osp_page_xml(ost_path, source_path)
                dest_dir = tmp_path / "dest"
                OspImporter(FakeImporter())._extract_images(
                    tmp_path,
                    ost_path,
                    dest_dir,
                    {member_name.casefold(): member_name},
                )
                dest_path = dest_dir / "A00.00.pdf"
                self.assertEqual(dest_path.read_bytes(), b"packaged")
                rewritten = ost_path.read_text(encoding="utf-8")
                self.assertIn(str(dest_path), rewritten)
                self.assertNotIn(source_path, rewritten)

    def test_osp_import_resolves_page_and_overlay_images_from_flat_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            page_member = "TempImages!.tmp\\page.pdf"
            overlay_member = "TempImages!.tmp\\overlay.tif"
            _write_packaged_image(tmp_path, page_member, b"page")
            _write_packaged_image(tmp_path, overlay_member, b"overlay")
            ost_path = tmp_path / "Project.ost"
            ost_path.write_text(
                """
                <XML_ROOT><Bid><BidPages><BidPage
                  ImagePath="C:\\plans\\page.pdf"
                  OverlayImagePath="TempImages!.tmp\\overlay.tif"
                /></BidPages></Bid></XML_ROOT>
                """,
                encoding="utf-8",
            )
            dest_dir = tmp_path / "dest"
            OspImporter(FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                {
                    page_member.casefold(): page_member,
                    overlay_member.casefold(): overlay_member,
                },
            )
            self.assertEqual((dest_dir / "page.pdf").read_bytes(), b"page")
            self.assertEqual((dest_dir / "overlay.tif").read_bytes(), b"overlay")
            rewritten = ost_path.read_text(encoding="utf-8")
            self.assertIn(str(dest_dir / "page.pdf"), rewritten)
            self.assertIn(str(dest_dir / "overlay.tif"), rewritten)

    def test_osp_import_fails_when_required_image_member_is_missing(self):
        source_path = "C:\\old\\folder\\missing.pdf"
        fake_cab = FakeOspCab(ost_xml=_write_osp_page_xml_text(source_path))
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "missing-image.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("required image member is missing", "\n".join(logs.output))
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())

    def test_osp_import_rejects_case_insensitive_duplicate_members(self):
        fake_cab = FakeOspCab(
            names=[
                "Project.ost",
                "TempImages!.tmp\\sheet.pdf",
                "tempimages!.TMP\\SHEET.PDF",
            ]
        )
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "duplicates.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("duplicate or conflicting CAB member", "\n".join(logs.output))
        self.assertEqual(fake_cab.extract_calls, [])
        self.assertEqual(importer.calls, [])

    def test_osp_import_rejects_corrupt_embedded_ost_and_cleans_temp_files(self):
        fake_cab = FakeOspCab(ost_xml="<XML_ROOT>")
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "corrupt.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("embedded OST data is corrupt", "\n".join(logs.output))
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())

    def test_loaded_databases_have_path_tiebreaker_when_file_times_match(self):
        repository = FileProjectRepository.__new__(FileProjectRepository)

        class FakeHierarchy:
            def set(self, data):
                self.data = data

        repository._current_hierarchy = FakeHierarchy()
        repository._descriptor_registry = None
        repository._loaded_files = {
            "z.mdb": _LoadedFileCache(
                file_path="z.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="z.mdb"),
            ),
            "a.mdb": _LoadedFileCache(
                file_path="a.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="a.mdb"),
            ),
        }
        FileProjectRepository._rebuild_merged_hierarchy(repository)
        self.assertEqual(
            [
                entry.file_path
                for entry in repository._current_hierarchy.data.loaded_files
            ],
            ["a.mdb", "z.mdb"],
        )

    def test_import_handler_runs_import_without_refresh_then_refreshes_on_ui_completion(
        self,
    ):
        service = FakeImportService()
        messages = []
        window = object()
        handler = ImportHandler(
            window=window,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        try:
            FakeProgressDialog.instances = []
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_call_options: ("source.ost", "")
            )
            import_handler_module.show_info = (
                lambda parent, title, message: messages.append((parent, title, message))
            )
            handler.import_ost()
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, ["target.mdb"])
        self.assertEqual(len(FakeProgressDialog.instances), 1)
        self.assertIs(FakeProgressDialog.instances[0].parent, window)
        self.assertEqual(
            messages,
            [
                (
                    window,
                    "Import Complete",
                    "Successfully imported 'source.ost' into the database.",
                )
            ],
        )

    def test_sql_import_handler_queues_without_modal_or_ui_thread_reload(self):
        service = FakeImportService()
        service.sql_collaboration = True
        messages = []
        window = object()
        handler = ImportHandler(
            window=window,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        try:
            import_handler_module.ProgressDialog = lambda *_args, **_kwargs: self.fail(
                "SQL import must not open the synchronous progress path"
            )
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_kwargs: ("source.ost", "")
            )
            import_handler_module.show_info = (
                lambda parent, title, message: messages.append((parent, title, message))
            )
            handler.import_ost()
            self.assertEqual(service.reloads, [])
            self.assertEqual(len(service.queued_imports), 1)
            queued = service.queued_imports[0]
            self.assertEqual(queued[:4], ("source.ost", "ost", "target.mdb", None))
            queued[4](
                QueuedMutationResult(
                    database_id="target.mdb",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(messages[0][1], "Import Complete")
        self.assertEqual(service.reloads, [])

    def test_import_handler_denies_direct_call_when_import_access_is_read_only(self):
        service = FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(False),
        )
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_call_options: self.fail(
                    "denied import must not open the file picker"
                )
            )
            handler.import_ost()
        finally:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
        self.assertEqual(service.import_calls, [])

    def test_import_handler_stops_when_deferred_flush_fails(self):
        service = FakeImportService()
        deferred = FakeDeferredPersistence(result=False)
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=deferred,
            ui_access_manager=FakeAccess(),
        )
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_call_options: ("source.ost", "")
            )
            handler.import_ost()
        finally:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
        self.assertEqual(deferred.flush_calls, ["target.mdb"])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.reloads, [])

    def test_import_handler_does_not_refresh_after_rejected_import(self):
        service = FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_critical = import_handler_module.show_critical
        try:
            FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Rejected
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_call_options: ("source.ost", "")
            )
            import_handler_module.show_critical = lambda *_args, **_call_options: None
            handler.import_ost()
        finally:
            FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Accepted
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_critical = original_show_critical
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, [])

    def test_import_handler_warns_when_successful_import_cannot_refresh(self):
        service = FakeImportService()
        service.reload_result = False
        messages = []
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
            deferred_persistence_manager=FakeDeferredPersistence(),
            ui_access_manager=FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        original_show_warning = import_handler_module.show_warning
        try:
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_call_options: ("source.ost", "")
            )
            import_handler_module.show_info = lambda *_args, **_call_options: self.fail(
                "a failed refresh must not report an unqualified success"
            )
            import_handler_module.show_warning = (
                lambda _parent, title, message: messages.append((title, message))
            )
            handler.import_ost()
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
            import_handler_module.show_warning = original_show_warning
        self.assertEqual(service.reloads, ["target.mdb"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], "Refresh Error")
        self.assertIn("Successfully imported 'source.ost'", messages[0][1])


if __name__ == "__main__":
    unittest.main()


class FakeAccess:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_allowed(self, _feature):
        return self.allowed
