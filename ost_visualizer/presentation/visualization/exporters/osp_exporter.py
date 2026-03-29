import logging
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Set
from ....application.dtos.export_dto import ExportErrorCode, ExportResultDto
from ....application.interfaces.i_uom_service import IUOMService
from ....domain.dtos.raw_bid_data_dto import RawBidData
from . import ost_cab
from .ost_exporter import OstExporter

logger = logging.getLogger(__name__)
_SUPPORTED_IMAGE_EXTENSIONS: Set[str] = {".pdf", ".tif", ".tiff"}


class OspExporter:
    def __init__(self, uom_service: IUOMService, version: str):
        self._uom_service = uom_service
        self._version = version

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
                _INVALID_FS = set('/\\:*?"<>|')
                ost_name = (
                    "".join(
                        c if c not in _INVALID_FS else "_" for c in (bid_name or "Bid")
                    )
                    + ".ost"
                )
                ost_path = tmp_path / ost_name
                ost_exporter = OstExporter(self._uom_service)
                ost_result = ost_exporter.export(raw_data, str(ost_path))
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
                self._collect_images(raw_data, source_files, archive_names)
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
        raw_data: RawBidData,
        source_files: List[str],
        archive_names: List[str],
    ) -> None:
        seen_paths: set = set()
        for page_row in raw_data.bid_tables.get("BidPages", []):
            for attr in ("ImagePath", "OverlayImagePath"):
                image_path = page_row.get(attr, "") or ""
                if not image_path:
                    continue
                p = Path(image_path)
                if p.suffix.lower() not in _SUPPORTED_IMAGE_EXTENSIONS:
                    continue
                if not p.exists():
                    continue
                abs_path = str(p.resolve())
                if abs_path in seen_paths:
                    continue
                seen_paths.add(abs_path)
                source_files.append(str(p))
                archive_names.append(f"TempImages!.tmp\\{p.name}")

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
