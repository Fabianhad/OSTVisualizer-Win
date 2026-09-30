import os
import shutil
import struct
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.import_service import ImportService
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
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
from PySide6 import QtWidgets
from shiboken6 import delete


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
    def __init__(self):
        self.file_entry = HierarchyFileEntry(
            file_path="target.mdb",
            bid_projects={"original-project": HierarchyProjectInfo("Original")},
        )

    def get_current_file_path(self):
        return "target.mdb"

    def get_hierarchy(self):
        return HierarchyData([self.file_entry])


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

    def can_import_project_file(self, _database_id, _project_uid):
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
