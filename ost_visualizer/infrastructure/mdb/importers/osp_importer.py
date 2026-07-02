import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
from ....domain.entities.file_extensions import OSP_IMAGE_EXTENSIONS
from ....presentation.visualization.exporters import ost_cab
from ...app_paths import get_default_working_dir
from .ost_importer import OstImporter

logger = logging.getLogger(__name__)
_OSP_TEMP_PREFIX = "ostv_osp_"
_LEGACY_WINDOWS_PATH_LIMIT = 240


def _cab_extract_output_dir(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt":
        return resolved
    if resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def _extract_temp_parent_candidates() -> list[Path]:
    default_parent = Path(tempfile.gettempdir())
    if os.name != "nt":
        return [default_parent]
    candidates = [default_parent]
    drive_root = default_parent.anchor or f"{os.environ.get('SystemDrive', 'C:')}\\"
    short_parent = Path(drive_root) / "OSTVTemp"
    if short_parent != default_parent:
        candidates.append(short_parent)
    return candidates


def _is_safe_legacy_extract_root(root: Path, member_names: list[str]) -> bool:
    if os.name != "nt":
        return True
    return all(
        len(str(root / member_name)) < _LEGACY_WINDOWS_PATH_LIMIT
        for member_name in member_names
    )


def _create_extract_temp_dir(member_names: list[str]) -> Path:
    fallback_error: Optional[OSError] = None
    candidates = _extract_temp_parent_candidates()
    default_parent = candidates[0]
    for parent in candidates:
        try:
            parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(tempfile.mkdtemp(prefix=_OSP_TEMP_PREFIX, dir=str(parent)))
        except OSError as exc:
            fallback_error = exc
            continue
        if (
            _is_safe_legacy_extract_root(tmp_path, member_names)
            or parent != default_parent
        ):
            return tmp_path
        _remove_temp_tree(tmp_path)
    try:
        return Path(tempfile.mkdtemp(prefix=_OSP_TEMP_PREFIX))
    except OSError:
        if fallback_error is not None:
            raise fallback_error
        raise


def _create_cab_member_parent_dir(tmp_path: Path, member_name: str) -> None:
    subdir = (tmp_path / member_name).parent
    Path(_cab_extract_output_dir(subdir)).mkdir(parents=True, exist_ok=True)


def _remove_temp_tree(path: Path) -> None:
    try:
        shutil.rmtree(_cab_extract_output_dir(path))
    except FileNotFoundError:
        return
    except Exception:
        logger.warning(
            "Failed to remove temporary OSP extraction directory %s",
            path,
            exc_info=True,
        )


class OspImporter:
    def __init__(self, ost_importer: OstImporter):
        self._ost_importer = ost_importer

    def import_osp(
        self,
        osp_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
    ) -> bool:
        tmp_path: Optional[Path] = None
        try:
            names = list(ost_cab.list_cab(osp_file_path))
            tmp_path = _create_extract_temp_dir(names)
            for name in names:
                _create_cab_member_parent_dir(tmp_path, name)
            if not ost_cab.extract_cab(
                osp_file_path, _cab_extract_output_dir(tmp_path)
            ):
                logger.error("Failed to extract .osp archive: %s", osp_file_path)
                return False
            ost_files = list(tmp_path.glob("*.ost"))
            if not ost_files:
                logger.error("No .ost file found in .osp archive: %s", osp_file_path)
                return False
            ost_path = ost_files[0]
            bid_name = ost_path.stem
            dest_dir = get_default_working_dir() / bid_name
            self._extract_images(tmp_path, ost_path, dest_dir)
            return self._ost_importer.import_ost(
                str(ost_path), target_db_path, target_project_uid
            )
        except Exception:
            logger.exception("OSP import failed: %s", osp_file_path)
            return False
        finally:
            if tmp_path is not None:
                _remove_temp_tree(tmp_path)

    def _extract_images(self, tmp_path: Path, ost_path: Path, dest_dir: Path) -> None:
        image_refs = self._collect_image_references(ost_path)
        if not image_refs:
            return
        copied_paths = self._copy_referenced_images(tmp_path, dest_dir, image_refs)
        if not copied_paths:
            return
        self._rewrite_image_paths(ost_path, copied_paths)

    def _collect_image_references(self, ost_path: Path) -> Dict[str, str]:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        image_refs: Dict[str, str] = {}
        for page_elem in root.iter("BidPage"):
            for attr in ("ImagePath", "OverlayImagePath"):
                image_path = page_elem.get(attr)
                if not image_path:
                    continue
                member_name = self._image_member_name(image_path)
                if member_name:
                    image_refs[image_path] = member_name
        return image_refs

    def _image_member_name(self, image_path: str) -> str:
        normalized = image_path.replace("/", "\\")
        marker = "TempImages!.tmp\\"
        marker_index = normalized.lower().find(marker.lower())
        if marker_index >= 0:
            return normalized[marker_index:]
        filename = Path(image_path).name
        if filename:
            return filename
        return ""

    def _copy_referenced_images(
        self,
        tmp_path: Path,
        dest_dir: Path,
        image_refs: Dict[str, str],
    ) -> Dict[str, str]:
        copied_paths: Dict[str, str] = {}
        fallback_by_name: Dict[str, List[Path]] = {}
        for file_path in tmp_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in OSP_IMAGE_EXTENSIONS:
                fallback_by_name.setdefault(file_path.name, []).append(file_path)
        for original_path, member_name in image_refs.items():
            source_path = tmp_path / member_name
            if not source_path.is_file():
                candidates = fallback_by_name.get(Path(member_name).name, [])
                source_path = candidates[0] if len(candidates) == 1 else None
            if source_path is None or not source_path.is_file():
                continue
            relative_dest = self._image_destination_relative_path(member_name)
            dest_path = dest_dir / relative_dest
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_path), str(dest_path))
            copied_paths[original_path] = str(dest_path)
        return copied_paths

    def _image_destination_relative_path(self, member_name: str) -> Path:
        normalized = member_name.replace("/", "\\")
        marker = "TempImages!.tmp\\"
        if normalized.lower().startswith(marker.lower()):
            relative = normalized[len(marker) :]
            return Path("Images") / Path(relative)
        return Path(Path(normalized).name)

    def _rewrite_image_paths(
        self,
        ost_path: Path,
        copied_paths: Dict[str, str],
    ) -> None:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        modified = False
        for page_elem in root.iter("BidPage"):
            for attr in ("ImagePath", "OverlayImagePath"):
                image_path = page_elem.get(attr)
                if image_path and image_path in copied_paths:
                    page_elem.set(attr, copied_paths[image_path])
                    modified = True
        if modified:
            tree.write(str(ost_path), encoding="unicode", xml_declaration=False)
