import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Set
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
        main_names, overlay_names = self._collect_image_names(ost_path)
        all_names = main_names | overlay_names
        if not all_names:
            return
        image_files = [
            f
            for f in tmp_path.rglob("*")
            if f.is_file()
            and f.suffix.lower() in OSP_IMAGE_EXTENSIONS
            and f.name in all_names
        ]
        if not image_files:
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        overlay_dir = dest_dir / "Overlay"
        conflicting = overlay_names & main_names
        if conflicting:
            overlay_dir.mkdir(parents=True, exist_ok=True)
        for img in image_files:
            if img.name in overlay_names and img.name in main_names:
                shutil.copy2(str(img), str(overlay_dir / img.name))
            else:
                shutil.copy2(str(img), str(dest_dir / img.name))
        self._rewrite_image_paths(ost_path, dest_dir, main_names)

    def _collect_image_names(self, ost_path: Path) -> tuple:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        main_names: Set[str] = set()
        overlay_names: Set[str] = set()
        for page_elem in root.iter("BidPage"):
            image_path = page_elem.get("ImagePath")
            if image_path:
                main_names.add(Path(image_path).name)
            overlay_path = page_elem.get("OverlayImagePath")
            if overlay_path:
                overlay_names.add(Path(overlay_path).name)
        return main_names, overlay_names

    def _rewrite_image_paths(
        self,
        ost_path: Path,
        dest_dir: Path,
        main_names: Set[str],
    ) -> None:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        overlay_dir = dest_dir / "Overlay"
        modified = False
        for page_elem in root.iter("BidPage"):
            image_path = page_elem.get("ImagePath")
            if image_path:
                filename = Path(image_path).name
                page_elem.set("ImagePath", str(dest_dir / filename))
                modified = True
            overlay_path = page_elem.get("OverlayImagePath")
            if overlay_path:
                filename = Path(overlay_path).name
                if filename in main_names:
                    page_elem.set("OverlayImagePath", str(overlay_dir / filename))
                else:
                    page_elem.set("OverlayImagePath", str(dest_dir / filename))
                modified = True
        if modified:
            tree.write(str(ost_path), encoding="unicode", xml_declaration=False)
