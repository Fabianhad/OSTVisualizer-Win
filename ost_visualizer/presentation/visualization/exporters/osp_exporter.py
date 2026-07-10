import hashlib
import logging
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, List
from ....application.dtos.export_dto import ExportErrorCode, ExportResultDto
from ....application.interfaces.i_ost_exporter import IOstExporter
from ....application.interfaces.i_uom_service import IUOMService
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ....domain.entities.file_extensions import OSP_IMAGE_EXTENSIONS
from . import ost_cab

logger = logging.getLogger(__name__)
_DEFAULT_BID_NAME = "Bid"
_IMAGE_PATH_ATTRS = ("ImagePath", "OverlayImagePath")
_INVALID_PATH_CHARS = set('/\\:*?"<>|')
_PACKAGE_IMAGE_ROOT = "TempImages!.tmp"


class OspExporter:
    def __init__(
        self,
        uom_service: IUOMService,
        version: str,
        ost_exporter_factory: Callable[[IUOMService], IOstExporter],
        default_working_dir_provider: Callable[[], Path],
    ):
        self._uom_service = uom_service
        self._version = version
        self._ost_exporter_factory = ost_exporter_factory
        self._default_working_dir_provider = default_working_dir_provider

    def export(
        self,
        raw_data: RawBidData,
        output_file: str,
        bid_name: str = "Bid",
        on_progress=None,
    ) -> ExportResultDto:
        def _report(current: int, total: int, description: str) -> None:
            if on_progress:
                on_progress(current, total, description)

        try:
            _report(1, 4, "Building OST")
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                source_files: List[str] = []
                archive_names: List[str] = []
                package_data, image_sources, missing_images = (
                    self._prepare_package_data(raw_data, bid_name=bid_name)
                )
                if missing_images:
                    preview = "; ".join(missing_images[:10])
                    if len(missing_images) > 10:
                        preview += f"; +{len(missing_images) - 10} more"
                    return ExportResultDto(
                        success=False,
                        format_name="OSP",
                        error_message=(
                            "Cannot export OSP because referenced drawing files are "
                            f"missing: {preview}"
                        ),
                        error_code=ExportErrorCode.WRITE_FAILED,
                    )
                ost_name = (
                    self._safe_path_component(
                        bid_name or _DEFAULT_BID_NAME,
                        default=_DEFAULT_BID_NAME,
                    )
                    + ".ost"
                )
                ost_path = tmp_path / ost_name
                ost_exporter = self._ost_exporter_factory(self._uom_service)
                ost_result = ost_exporter.export(package_data, str(ost_path))
                if not ost_result.success:
                    return ExportResultDto(
                        success=False,
                        format_name="OSP",
                        error_message=(
                            ost_result.error_message or "Failed to generate .ost file"
                        ),
                        error_code=ExportErrorCode.WRITE_FAILED,
                    )
                source_files.append(str(ost_path))
                archive_names.append(ost_name)
                _report(2, 4, "Writing metadata")
                bid_trans_path = self._generate_bid_trans_xml(tmp_path)
                source_files.append(str(bid_trans_path))
                archive_names.append("BidTrans.xml")
                _report(3, 4, "Collecting images")
                self._collect_images(
                    image_sources,
                    source_files,
                    archive_names,
                    _report,
                )
                _report(4, 4, "Packaging archive")
                if not ost_cab.create_cab_with_names(
                    source_files, archive_names, output_file
                ):
                    return ExportResultDto(
                        success=False,
                        format_name="OSP",
                        error_message="Failed to create CAB archive",
                        error_code=ExportErrorCode.WRITE_FAILED,
                    )
            return ExportResultDto(success=True, format_name="OSP")
        except Exception as e:
            logger.exception("OSP export failed")
            return ExportResultDto(
                success=False,
                format_name="OSP",
                error_message=f"Export failed: {e}",
                error_code=ExportErrorCode.UNEXPECTED,
            )

    def _collect_images(
        self,
        image_sources: dict[str, str],
        source_files: List[str],
        archive_names: List[str],
        report: Callable[[int, int, str], None],
    ) -> None:
        total = max(len(image_sources), 1)
        for index, archive_name in enumerate(sorted(image_sources), start=1):
            source_path = image_sources[archive_name]
            report(index, total, f"Collecting {Path(source_path).name}")
            source_files.append(source_path)
            archive_names.append(archive_name)

    def _prepare_package_data(
        self, raw_data: RawBidData, bid_name: str = _DEFAULT_BID_NAME
    ) -> tuple[RawBidData, dict[str, str], list[str]]:
        package_data = self._clone_raw_bid_data(raw_data)
        package_image_sources: dict[str, str] = {}
        package_member_by_source: dict[str, str] = {}
        filename_by_source: dict[str, str] = {}
        packaged_image_refs = []
        missing_images: list[str] = []
        for page_row in package_data.bid_tables.get("BidPages", []):
            page_uid = str(page_row.get("UID", "") or "page")
            for attr in _IMAGE_PATH_ATTRS:
                original_image_path = page_row.get(attr, "") or ""
                if not original_image_path:
                    continue
                source_image_path = Path(original_image_path)
                if source_image_path.suffix.lower() not in OSP_IMAGE_EXTENSIONS:
                    continue
                if not source_image_path.exists():
                    missing_images.append(original_image_path)
                    continue
                source_key = str(source_image_path.resolve())
                package_member_path = package_member_by_source.get(source_key)
                if package_member_path is None:
                    package_member_path = self._package_image_member_path(
                        source_key, source_image_path.name, page_uid
                    )
                    package_member_by_source[source_key] = package_member_path
                    package_image_sources[package_member_path] = source_key
                    filename_by_source[source_key] = source_image_path.name
                packaged_image_refs.append(
                    (page_row, attr, package_member_path, source_key)
                )
        filename_counts = self._filename_counts(filename_by_source.values())
        bid_dir = self._embedded_ost_image_dir(bid_name)
        for page_row, attr, package_member_path, source_key in packaged_image_refs:
            filename = filename_by_source[source_key]
            duplicate_name = filename_counts[filename.casefold()] > 1
            page_row[attr] = str(
                self._embedded_ost_image_path(
                    bid_dir, package_member_path, filename, duplicate_name
                )
            )
        return package_data, package_image_sources, missing_images

    def _filename_counts(self, filenames) -> dict[str, int]:
        counts: dict[str, int] = {}
        for filename in filenames:
            key = filename.casefold()
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _embedded_ost_image_dir(self, bid_name: str) -> Path:
        safe_bid_name = self._safe_path_component(
            bid_name or _DEFAULT_BID_NAME,
            default=_DEFAULT_BID_NAME,
        )
        return Path(self._default_working_dir_provider()) / safe_bid_name

    def _embedded_ost_image_path(
        self,
        bid_dir: Path,
        package_member_path: str,
        filename: str,
        duplicate_name: bool,
    ) -> Path:
        if duplicate_name:
            return bid_dir.joinpath(*self._windows_path_parts(package_member_path))
        return bid_dir / self._safe_path_component(filename, default="image")

    def _safe_path_component(self, value: str, *, default: str) -> str:
        safe = "".join(c if c not in _INVALID_PATH_CHARS else "_" for c in value)
        return safe.strip() or default

    def _windows_path_parts(self, path: str) -> tuple[str, ...]:
        return tuple(part for part in path.replace("/", "\\").split("\\") if part)

    def _clone_raw_bid_data(self, raw_data: RawBidData) -> RawBidData:
        return RawBidData(
            bid_row=dict(raw_data.bid_row),
            bid_tables={
                table: [dict(row) for row in rows]
                for table, rows in raw_data.bid_tables.items()
            },
            page_tables={
                table: [dict(row) for row in rows]
                for table, rows in raw_data.page_tables.items()
            },
            global_tables={
                table: [dict(row) for row in rows]
                for table, rows in raw_data.global_tables.items()
            },
        )

    def _package_image_member_path(
        self, source_key: str, filename: str, page_uid: str
    ) -> str:
        digest = hashlib.sha1(source_key.casefold().encode("utf-8")).hexdigest()[:16]
        safe_page_uid = "".join(c if c.isalnum() else "_" for c in page_uid) or "page"
        safe_filename = self._safe_path_component(
            filename or "image",
            default="image",
        )
        return f"{_PACKAGE_IMAGE_ROOT}\\{safe_page_uid}_{digest}\\{safe_filename}"

    def _generate_bid_trans_xml(self, tmp_path: Path) -> Path:
        root = ET.Element("XML_ROOT")
        now = datetime.now()
        send_date = now.strftime("%m/%d/%Y %I:%M %p")
        dpc = ET.SubElement(root, "DPC")
        dpc.set("Version", self._version)
        dpc.set("STSGUID", "{" + str(uuid.uuid4()).upper() + "}")
        dpc.set("SendDate", send_date)
        xml_path = tmp_path / "BidTrans.xml"
        xml_str = ET.tostring(root, encoding="unicode")
        formatted = xml_str.replace("><DPC", ">\n<DPC").replace("/></", "/>\n</")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(formatted)
        return xml_path
