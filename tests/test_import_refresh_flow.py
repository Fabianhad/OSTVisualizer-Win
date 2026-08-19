import os
import shutil
import struct
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
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


class InspectingImporter(FakeImporter):
    def __init__(self):
        super().__init__()
        self.imported_image_contents = []

    def _record_imported_image(self, source_path):
        root = ET.parse(source_path).getroot()
        image_path = next(root.iter("BidPage")).get("ImagePath")
        self.imported_image_contents.append(Path(image_path).read_bytes())

    def import_ost(self, source_path, target_path, project_uid=None):
        self._record_imported_image(source_path)
        return super().import_ost(source_path, target_path, project_uid)

    def import_ost_mutation(self, source_path, target_path, project_uid, recorder):
        self._record_imported_image(source_path)
        return super().import_ost_mutation(
            source_path, target_path, project_uid, recorder
        )


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


class FakeAccess:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_allowed(self, _feature):
        return self.allowed


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


def _write_legacy_ansi_cab(path: Path, members: list[tuple[str, bytes]]) -> None:
    """Write the uncompressed CAB shape emitted by legacy OST on Windows."""
    file_entries = []
    folder_data = bytearray()
    for member_name, content in members:
        encoded_name = member_name.encode("cp1252")
        file_entries.append(
            struct.pack(
                "<IIHHHH",
                len(content),
                len(folder_data),
                0,
                0,
                0,
                0,
            )
            + encoded_name
            + b"\0"
        )
        folder_data.extend(content)
    if len(folder_data) > 32768:
        raise ValueError("minimal CAB fixture exceeds one uncompressed data block")
    file_table = b"".join(file_entries)
    files_offset = 36 + 8
    data_offset = files_offset + len(file_table)
    data_block = (
        struct.pack("<IHH", 0, len(folder_data), len(folder_data)) + folder_data
    )
    header = struct.pack(
        "<4sIIIIIBBHHHHH",
        b"MSCF",
        0,
        data_offset + len(data_block),
        0,
        files_offset,
        0,
        3,
        1,
        1,
        len(members),
        0,
        12345,
        0,
    )
    folder = struct.pack("<IHH", data_offset, 1, 0)
    path.write_bytes(header + folder + file_table + data_block)


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

    def test_osp_imports_legacy_ansi_members_from_unicode_archive_path(self):
        project_name = "26-061 412 – Corporate Lot K, KS"
        ost_member = f"{project_name}.ost"
        image_member = (
            "TempImages!.tmp\\1 Estimates through 1-12-2015\\2026\\"
            f"{project_name}\\01. Drawings\\A0-0.0.pdf"
        )
        source_image_path = (
            "Q:\\1 Estimates through 1-12-2015\\2026\\"
            f"{project_name}\\01. Drawings\\A0-0.0.pdf"
        )
        ost_xml = _write_osp_page_xml_text(source_image_path).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            osp_path = tmp_path / f"{project_name}.osp"
            _write_legacy_ansi_cab(
                osp_path,
                [(ost_member, ost_xml), (image_member, b"%PDF-1.4 fixture")],
            )
            self.assertEqual(
                list(osp_importer_module.ost_cab.list_cab(str(osp_path))),
                [ost_member, image_member],
            )
            working_dir = tmp_path / "working"
            original_working_dir = osp_importer_module.get_default_working_dir
            osp_importer_module.get_default_working_dir = lambda: working_dir
            try:
                mdb_importer = InspectingImporter()
                self.assertTrue(
                    OspImporter(mdb_importer).import_osp(
                        str(osp_path), "target.mdb", "project-1"
                    )
                )
                sql_importer = InspectingImporter()
                recorder = object()
                self.assertEqual(
                    OspImporter(sql_importer).import_osp_mutation(
                        str(osp_path), "target.sql", "project-1", recorder
                    ),
                    {"bid_uids": {"source": "target"}},
                )
            finally:
                osp_importer_module.get_default_working_dir = original_working_dir
            self.assertEqual(
                mdb_importer.imported_image_contents[0], b"%PDF-1.4 fixture"
            )
            self.assertEqual(
                sql_importer.imported_image_contents[0], b"%PDF-1.4 fixture"
            )
            self.assertEqual(mdb_importer.calls[0][0], "ost")
            self.assertEqual(sql_importer.calls[0][0], "ost_mutation")

    def test_invalid_osp_stops_before_mdb_or_sql_import_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            osp_path = Path(tmp) / "invalid – package.osp"
            _write_legacy_ansi_cab(osp_path, [("not-a-project.txt", b"invalid")])
            importer = FakeImporter()
            osp_importer = OspImporter(importer)
            with self.assertLogs(osp_importer_module.logger, level="ERROR"):
                self.assertFalse(
                    osp_importer.import_osp(str(osp_path), "target.mdb", "project-1")
                )
            with self.assertRaisesRegex(ValueError, "exactly one top-level .ost file"):
                osp_importer.import_osp_mutation(
                    str(osp_path), "target.sql", "project-1", object()
                )
            self.assertEqual(importer.calls, [])

    def test_native_cab_round_trip_preserves_utf8_paths_and_member_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source – drawing.pdf"
            source_path.write_bytes(b"%PDF-1.4 unicode")
            osp_path = tmp_path / "export – project.osp"
            member_name = "TempImages!.tmp\\source – drawing.pdf"
            self.assertTrue(
                osp_importer_module.ost_cab.create_cab_with_names(
                    [str(source_path)], [member_name], str(osp_path)
                )
            )
            self.assertEqual(
                list(osp_importer_module.ost_cab.list_cab(str(osp_path))),
                [member_name],
            )
            extract_path = tmp_path / "extracted – project"
            (extract_path / "TempImages!.tmp").mkdir(parents=True)
            self.assertTrue(
                osp_importer_module.ost_cab.extract_cab(
                    str(osp_path), str(extract_path)
                )
            )
            self.assertEqual(
                (
                    extract_path / "TempImages!.tmp" / "source – drawing.pdf"
                ).read_bytes(),
                b"%PDF-1.4 unicode",
            )

    @unittest.skipUnless(os.name == "nt", "Windows CAB path behavior")
    def test_native_cab_resolves_identical_members_from_long_local_paths(self):
        member_names = ["Project name; 50% (CD).OST", "BidTrans.xml"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_osp = tmp_path / "Package name; spaces (local).osp"
            _write_legacy_ansi_cab(
                local_osp,
                [(member_names[0], b"<XML_ROOT />"), (member_names[1], b"<XML />")],
            )
            long_parent = tmp_path
            segment_index = 0
            while len(str(long_parent / local_osp.name)) < 300:
                long_parent /= (
                    f"network-style segment {segment_index}; spaces (punctuation)"
                )
                segment_index += 1
            extended_long_parent = Path("\\\\?\\" + str(long_parent))
            extended_long_parent.mkdir(parents=True)
            extended_long_osp = extended_long_parent / local_osp.name
            shutil.copyfile(local_osp, extended_long_osp)
            path_forms = (
                str(local_osp),
                "\\\\?\\" + str(local_osp),
                str(extended_long_osp)[4:],
                str(extended_long_osp),
            )
            expected_package = None
            for source_path in path_forms:
                with self.subTest(source_path=source_path):
                    names = list(osp_importer_module.ost_cab.list_cab(source_path))
                    self.assertEqual(names, member_names)
                    package = osp_importer_module._inspect_package(names)
                    if expected_package is None:
                        expected_package = package
                    self.assertEqual(package, expected_package)
            self.assertEqual(local_osp.read_bytes(), extended_long_osp.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows UNC path behavior")
    def test_native_cab_resolves_and_extracts_identically_from_unc_forms(self):
        member_names = ["Project name; 50% (CD).ost", "BidTrans.xml"]
        ost_contents = b"<XML_ROOT />"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            local_osp = tmp_path / "Package name; spaces (network).osp"
            _write_legacy_ansi_cab(
                local_osp,
                [(member_names[0], ost_contents), (member_names[1], b"<XML />")],
            )
            long_parent = tmp_path
            segment_index = 0
            while len(str(long_parent / local_osp.name)) < 300:
                long_parent /= (
                    f"network-style segment {segment_index}; spaces (punctuation)"
                )
                segment_index += 1
            extended_long_parent = Path("\\\\?\\" + str(long_parent))
            extended_long_parent.mkdir(parents=True)
            extended_long_osp = extended_long_parent / local_osp.name
            shutil.copyfile(local_osp, extended_long_osp)
            drive_share = f"{tmp_path.drive[0]}$"

            def as_unc(path: Path, *, extended: bool) -> str:
                normal_path = str(path)
                if normal_path.startswith("\\\\?\\"):
                    normal_path = normal_path[4:]
                relative_path = normal_path[len(tmp_path.drive) :]
                prefix = "\\\\?\\UNC\\localhost\\" if extended else "\\\\localhost\\"
                return prefix + drive_share + relative_path

            short_unc = as_unc(local_osp, extended=False)
            if not Path(short_unc).is_file():
                self.skipTest("the local Windows administrative share is unavailable")
            path_forms = (
                str(local_osp),
                short_unc,
                as_unc(local_osp, extended=True),
                as_unc(extended_long_osp, extended=False),
                as_unc(extended_long_osp, extended=True),
            )
            expected_package = None
            for index, source_path in enumerate(path_forms):
                with self.subTest(source_path=source_path):
                    names = list(osp_importer_module.ost_cab.list_cab(source_path))
                    self.assertEqual(names, member_names)
                    package = osp_importer_module._inspect_package(names)
                    if expected_package is None:
                        expected_package = package
                    self.assertEqual(package, expected_package)
                    output_dir = tmp_path / f"extracted {index}; output"
                    output_dir.mkdir()
                    self.assertTrue(
                        osp_importer_module.ost_cab.extract_cab(
                            source_path, str(output_dir)
                        )
                    )
                    self.assertEqual(
                        (output_dir / member_names[0]).read_bytes(), ost_contents
                    )
            self.assertEqual(local_osp.read_bytes(), extended_long_osp.read_bytes())

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

    def test_osp_import_accepts_nested_legacy_visualizer_layout(self):
        nested_member = "TempImages!.tmp\\generated-folder\\sheet.pdf"
        fake_cab = FakeOspCab(names=["Project.ost", nested_member])
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            result = OspImporter(importer).import_osp(
                "legacy.osp", "target.mdb", "project-1"
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertTrue(result)
        self.assertEqual(len(fake_cab.extract_calls), 1)
        self.assertEqual(len(importer.calls), 1)

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

    def test_osp_import_does_not_overwrite_different_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            member_name = "TempImages!.tmp\\sheet.pdf"
            _write_packaged_image(tmp_path, member_name, b"new drawing")
            ost_path = tmp_path / "Project.ost"
            _write_osp_page_xml(ost_path, r"C:\plans\sheet.pdf")
            dest_dir = tmp_path / "dest"
            dest_dir.mkdir()
            original_path = dest_dir / "sheet.pdf"
            original_path.write_bytes(b"existing drawing")
            OspImporter(FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                {member_name.casefold(): member_name},
            )
            self.assertEqual(original_path.read_bytes(), b"existing drawing")
            imported_paths = [
                path for path in dest_dir.glob("sheet-*.pdf") if path.is_file()
            ]
            self.assertEqual(len(imported_paths), 1)
            self.assertEqual(imported_paths[0].read_bytes(), b"new drawing")
            self.assertIn(str(imported_paths[0]), ost_path.read_text(encoding="utf-8"))

    def test_osp_import_reuses_identical_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            member_name = "TempImages!.tmp\\sheet.pdf"
            _write_packaged_image(tmp_path, member_name, b"same drawing")
            ost_path = tmp_path / "Project.ost"
            _write_osp_page_xml(ost_path, r"C:\plans\sheet.pdf")
            dest_dir = tmp_path / "dest"
            dest_dir.mkdir()
            existing_path = dest_dir / "sheet.pdf"
            existing_path.write_bytes(b"same drawing")
            OspImporter(FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                {member_name.casefold(): member_name},
            )
            self.assertEqual(list(dest_dir.iterdir()), [existing_path])
            self.assertIn(str(existing_path), ost_path.read_text(encoding="utf-8"))

    def test_osp_import_resolves_most_specific_nested_member_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            flat_member = "TempImages!.tmp\\A701-D.pdf"
            nested_member = "TempImages!.tmp\\estimates\\project\\drawings\\A701-D.pdf"
            _write_packaged_image(tmp_path, flat_member, b"generated")
            _write_packaged_image(tmp_path, nested_member, b"original")
            generated_path = "C:\\OST\\Project\\A701-D.pdf"
            original_path = "Q:\\estimates\\project\\drawings\\A701-D.pdf"
            ost_path = tmp_path / "Project.ost"
            ost_path.write_text(
                f"""
                <XML_ROOT><Bid><BidPages><BidPage
                  ImagePath="{generated_path}"
                  OverlayImagePath="{original_path}"
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
                    flat_member.casefold(): flat_member,
                    nested_member.casefold(): nested_member,
                },
            )
            generated_dest = dest_dir / "A701-D.pdf"
            nested_destinations = list((dest_dir / "Images").glob("*/A701-D.pdf"))
            self.assertEqual(generated_dest.read_bytes(), b"generated")
            self.assertEqual(len(nested_destinations), 1)
            self.assertEqual(nested_destinations[0].read_bytes(), b"original")
            rewritten = ost_path.read_text(encoding="utf-8")
            self.assertIn(str(generated_dest), rewritten)
            self.assertIn(str(nested_destinations[0]), rewritten)

    def test_osp_import_does_not_fall_back_to_nested_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nested_member = "TempImages!.tmp\\first\\sheet.pdf"
            _write_packaged_image(tmp_path, nested_member, b"nested")
            source_path = "C:\\unrelated\\sheet.pdf"
            ost_path = tmp_path / "Project.ost"
            original_xml = _write_osp_page_xml(ost_path, source_path)
            dest_dir = tmp_path / "dest"
            with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
                OspImporter(FakeImporter())._extract_images(
                    tmp_path,
                    ost_path,
                    dest_dir,
                    {nested_member.casefold(): nested_member},
                )
            self.assertIn(
                "could not resolve 1 referenced image", "\n".join(logs.output)
            )
            self.assertEqual(ost_path.read_text(encoding="utf-8"), original_xml)
            self.assertFalse(dest_dir.exists())

    def test_osp_import_preserves_missing_image_reference_and_continues(self):
        source_path = "C:\\old\\folder\\missing.pdf"
        fake_cab = FakeOspCab(ost_xml=_write_osp_page_xml_text(source_path))
        importer = FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
                result = OspImporter(importer).import_osp(
                    "missing-image.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertTrue(result)
        self.assertIn("could not resolve 1 referenced image", "\n".join(logs.output))
        self.assertEqual(len(importer.calls), 1)
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

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            FakeProgressDialog.instances = []
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
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

        def reject_progress_dialog(_filename, _task_fn, parent=None):
            self.fail("SQL import must not open the synchronous progress path")

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            import_handler_module.ProgressDialog = reject_progress_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_info = (
                lambda parent, title, message: messages.append((parent, title, message))
            )
            handler.import_ost()
            self.assertEqual(service.reloads, [])
            self.assertEqual(len(service.queued_imports), 1)
            queued = service.queued_imports[0]
            self.assertEqual(queued[:4], ("source.ost", "ost", "target.mdb", None))
            operation_id = str(uuid.uuid4())
            queued[4](
                QueuedMutationResult(
                    database_id="target.mdb",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                )
            )
            self.assertEqual(messages, [])
            queued[4](
                QueuedMutationResult(
                    database_id="target.mdb",
                    runtime_generation=1,
                    operation_id=operation_id,
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

        def reject_file_picker(_parent, _caption, _directory, _filter):
            self.fail("denied import must not open the file picker")

        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                reject_file_picker
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

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
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

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        def ignore_message(_parent, _title, _message):
            pass

        try:
            FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Rejected
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_critical = ignore_message
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

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        def reject_success_message(_parent, _title, _message):
            self.fail("a failed refresh must not report an unqualified success")

        try:
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_info = reject_success_message
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
