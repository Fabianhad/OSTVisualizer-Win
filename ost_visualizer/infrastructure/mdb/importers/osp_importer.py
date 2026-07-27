import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, Optional
from ....domain.entities.file_extensions import OSP_IMAGE_EXTENSIONS
from ....presentation.visualization.exporters import ost_cab
from ...app_paths import get_default_working_dir
from .ost_importer import OstImporter

logger = logging.getLogger(__name__)
_OSP_TEMP_PREFIX = "ostv_osp_"
_LEGACY_WINDOWS_PATH_LIMIT = 240
_IMAGE_MEMBER_PREFIX = "TempImages!.tmp\\"
_IMAGE_PATH_ATTRS = ("ImagePath", "OverlayImagePath")


@dataclass(frozen=True)
class _ImageReference:
    original_path: str
    member_name: str
    relative_destination: Path


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


def _is_safe_cab_member_name(member_name: str) -> bool:
    if not isinstance(member_name, str) or not member_name:
        return False
    member_path = PureWindowsPath(member_name.replace("/", "\\"))
    if member_path.is_absolute() or member_path.drive or member_path.root:
        return False
    parts = member_path.parts
    return bool(parts) and all(
        part not in (".", "..") and ":" not in part for part in parts
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
            unsafe_name = next(
                (name for name in names if not _is_safe_cab_member_name(name)),
                None,
            )
            if unsafe_name is not None:
                logger.error(
                    "Unsafe CAB member path in .osp archive %s: %r",
                    osp_file_path,
                    unsafe_name,
                )
                return False
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
            self._extract_images(tmp_path, ost_path, dest_dir, names)
            return self._ost_importer.import_ost(
                str(ost_path), target_db_path, target_project_uid
            )
        except Exception:
            logger.exception("OSP import failed: %s", osp_file_path)
            return False
        finally:
            if tmp_path is not None:
                _remove_temp_tree(tmp_path)

    def _extract_images(
        self,
        tmp_path: Path,
        ost_path: Path,
        dest_dir: Path,
        member_names: Optional[Iterable[str]] = None,
    ) -> None:
        image_refs = self._collect_image_references(ost_path, member_names)
        if not image_refs:
            return
        copied_paths = self._copy_referenced_images(tmp_path, dest_dir, image_refs)
        if not copied_paths:
            return
        self._rewrite_image_paths(ost_path, copied_paths)

    def _collect_image_references(
        self, ost_path: Path, member_names: Optional[Iterable[str]] = None
    ) -> list[_ImageReference]:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        package_images = _PackageImageIndex(member_names)
        image_refs_by_original: Dict[str, _ImageReference] = {}
        missing_paths: Dict[str, None] = {}
        ambiguous_paths: Dict[str, None] = {}
        for page_elem in root.iter("BidPage"):
            for attr in _IMAGE_PATH_ATTRS:
                image_path = page_elem.get(attr)
                if not image_path:
                    continue
                member_name = self._packaged_image_member_name(image_path)
                if member_name:
                    image_refs_by_original[image_path] = _ImageReference(
                        original_path=image_path,
                        member_name=member_name,
                        relative_destination=self._image_destination_relative_path(
                            member_name
                        ),
                    )
                    continue
                if not _is_supported_image_path(image_path):
                    continue
                image_filename = _windows_path_name(image_path)
                member_name = package_images.unique_member_named(image_filename)
                if member_name:
                    image_refs_by_original[image_path] = _ImageReference(
                        original_path=image_path,
                        member_name=member_name,
                        relative_destination=Path(_windows_path_name(image_path)),
                    )
                elif package_images.has_ambiguous_name(image_filename):
                    ambiguous_paths[image_path] = None
                else:
                    missing_paths[image_path] = None
        self._log_unresolved_images(
            ost_path, list(missing_paths), list(ambiguous_paths)
        )
        return list(image_refs_by_original.values())

    def _packaged_image_member_name(self, image_path: str) -> str:
        normalized = image_path.replace("/", "\\")
        marker_index = normalized.lower().find(_IMAGE_MEMBER_PREFIX.lower())
        if marker_index < 0:
            return ""
        return normalized[marker_index:]

    def _copy_referenced_images(
        self,
        tmp_path: Path,
        dest_dir: Path,
        image_refs: list[_ImageReference],
    ) -> Dict[str, str]:
        copied_paths: Dict[str, str] = {}
        for image_ref in image_refs:
            source_path = _cab_member_path(tmp_path, image_ref.member_name)
            if not source_path.is_file():
                logger.warning(
                    "Packaged OSP image member %s was not extracted for %s",
                    image_ref.member_name,
                    image_ref.original_path,
                )
                continue
            dest_path = dest_dir / image_ref.relative_destination
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_path), str(dest_path))
            copied_paths[image_ref.original_path] = str(dest_path)
        return copied_paths

    def _image_destination_relative_path(self, member_name: str) -> Path:
        normalized = member_name.replace("/", "\\")
        if normalized.lower().startswith(_IMAGE_MEMBER_PREFIX.lower()):
            relative = normalized[len(_IMAGE_MEMBER_PREFIX) :]
            return Path("Images").joinpath(*_windows_path_parts(relative))
        return Path(_windows_path_name(normalized))

    def _rewrite_image_paths(
        self,
        ost_path: Path,
        copied_paths: Dict[str, str],
    ) -> None:
        tree = ET.parse(str(ost_path))
        root = tree.getroot()
        modified = False
        for page_elem in root.iter("BidPage"):
            for attr in _IMAGE_PATH_ATTRS:
                image_path = page_elem.get(attr)
                if image_path and image_path in copied_paths:
                    page_elem.set(attr, copied_paths[image_path])
                    modified = True
        if modified:
            tree.write(str(ost_path), encoding="unicode", xml_declaration=False)

    def _log_unresolved_images(
        self,
        ost_path: Path,
        missing_paths: list[str],
        ambiguous_paths: list[str],
    ) -> None:
        if missing_paths:
            logger.warning(
                "OSP import could not resolve %d referenced image(s) in %s. "
                "Import will continue, but affected page images may be missing. "
                "First missing source path: %s",
                len(missing_paths),
                ost_path,
                missing_paths[0],
            )
        if ambiguous_paths:
            logger.warning(
                "OSP import skipped %d referenced image(s) in %s because multiple "
                "packaged images had the same filename. Import will continue, but "
                "affected page images may be missing. First ambiguous source path: %s",
                len(ambiguous_paths),
                ost_path,
                ambiguous_paths[0],
            )


class _PackageImageIndex:
    def __init__(self, member_names: Optional[Iterable[str]]) -> None:
        self._members_by_basename: Dict[str, list[str]] = {}
        for member_name in member_names or ():
            if not _is_supported_image_path(member_name):
                continue
            basename = _windows_path_name(member_name).casefold()
            self._members_by_basename.setdefault(basename, []).append(member_name)

    def unique_member_named(self, filename: str) -> str:
        matches = self._members_named(filename)
        return matches[0] if len(matches) == 1 else ""

    def has_ambiguous_name(self, filename: str) -> bool:
        return len(self._members_named(filename)) > 1

    def _members_named(self, filename: str) -> list[str]:
        return self._members_by_basename.get(filename.casefold(), [])


def _is_supported_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in OSP_IMAGE_EXTENSIONS


def _windows_path_name(path: str) -> str:
    return PureWindowsPath(path.replace("/", "\\")).name


def _windows_path_parts(path: str) -> tuple[str, ...]:
    return PureWindowsPath(path.replace("/", "\\")).parts


def _cab_member_path(root: Path, member_name: str) -> Path:
    return root.joinpath(*_windows_path_parts(member_name))
