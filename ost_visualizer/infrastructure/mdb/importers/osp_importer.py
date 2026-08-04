import hashlib
import logging
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional
from ....domain.entities.file_extensions import OSP_IMAGE_EXTENSIONS
from ....presentation.visualization.exporters import ost_cab
from ...app_paths import get_default_working_dir
from .ost_importer import OstImporter

logger = logging.getLogger(__name__)
_OSP_TEMP_PREFIX = "ostv_osp_"
_WINDOWS_PATH_LIMIT = 240
_IMAGE_MEMBER_ROOT = "TempImages!.tmp"
_IMAGE_PATH_ATTRS = ("ImagePath", "OverlayImagePath")


class _OspFormatError(ValueError):
    pass


@dataclass(frozen=True)
class _OspPackage:
    member_names: tuple[str, ...]
    ost_member_name: str
    image_members_by_path: dict[str, str]


@dataclass(frozen=True)
class _ImageReference:
    original_path: str
    member_name: str


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


def _is_safe_extract_root(root: Path, member_names: tuple[str, ...]) -> bool:
    if os.name != "nt":
        return True
    return all(
        len(str(root / member_name)) < _WINDOWS_PATH_LIMIT
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


def _create_extract_temp_dir(member_names: tuple[str, ...]) -> Path:
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
        if _is_safe_extract_root(tmp_path, member_names) or parent != default_parent:
            return tmp_path
        _remove_temp_tree(tmp_path)
    try:
        return Path(tempfile.mkdtemp(prefix=_OSP_TEMP_PREFIX))
    except OSError:
        if fallback_error is not None:
            raise fallback_error
        raise


def _create_cab_member_parent_dir(tmp_path: Path, member_name: str) -> None:
    subdir = _cab_member_path(tmp_path, member_name).parent
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


def _inspect_package(member_names: Iterable[str]) -> _OspPackage:
    normalized_names = []
    seen_names = set()
    ost_members = []
    image_members_by_path: dict[str, str] = {}
    for raw_name in member_names:
        if not _is_safe_cab_member_name(raw_name):
            raise _OspFormatError(f"unsafe CAB member path: {raw_name!r}")
        parts = _windows_path_parts(raw_name)
        member_name = "\\".join(parts)
        member_key = member_name.casefold()
        if member_key in seen_names:
            raise _OspFormatError(
                f"duplicate or conflicting CAB member: {member_name!r}"
            )
        seen_names.add(member_key)
        normalized_names.append(member_name)
        if len(parts) == 1 and PureWindowsPath(member_name).suffix.lower() == ".ost":
            ost_members.append(member_name)
        if parts[0].casefold() != _IMAGE_MEMBER_ROOT.casefold():
            continue
        if len(parts) < 2 or not _is_supported_image_path(member_name):
            raise _OspFormatError(
                f"unsupported member under {_IMAGE_MEMBER_ROOT}: {member_name!r}"
            )
        image_members_by_path[member_key] = member_name
    if len(ost_members) != 1:
        raise _OspFormatError(
            "archive must contain exactly one top-level .ost file; "
            f"found {len(ost_members)}"
        )
    return _OspPackage(
        member_names=tuple(normalized_names),
        ost_member_name=ost_members[0],
        image_members_by_path=image_members_by_path,
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
        try:
            with self._extracted_ost(osp_file_path) as ost_path:
                return self._ost_importer.import_ost(
                    str(ost_path), target_db_path, target_project_uid
                )
        except _OspFormatError as exc:
            logger.error("Cannot import OSP %s: %s", osp_file_path, exc)
            return False
        except ET.ParseError as exc:
            logger.error(
                "Cannot import OSP %s: embedded OST data is corrupt: %s",
                osp_file_path,
                exc,
            )
            return False
        except Exception:
            logger.exception("Unexpected OSP import failure: %s", osp_file_path)
            return False

    def import_osp_mutation(
        self,
        osp_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str],
        recorder,
    ) -> dict[str, object]:
        with self._extracted_ost(osp_file_path) as ost_path:
            return self._ost_importer.import_ost_mutation(
                str(ost_path),
                target_db_path,
                target_project_uid,
                recorder,
            )

    @contextmanager
    def _extracted_ost(self, osp_file_path: str):
        package = _inspect_package(ost_cab.list_cab(osp_file_path))
        tmp_path = _create_extract_temp_dir(package.member_names)
        try:
            for name in package.member_names:
                _create_cab_member_parent_dir(tmp_path, name)
            if not ost_cab.extract_cab(
                osp_file_path, _cab_extract_output_dir(tmp_path)
            ):
                raise _OspFormatError("the OSP archive could not be extracted")
            ost_path = _cab_member_path(tmp_path, package.ost_member_name)
            if not ost_path.is_file():
                raise _OspFormatError(
                    f"embedded OST member was not extracted: {package.ost_member_name}"
                )
            bid_name = ost_path.stem
            dest_dir = get_default_working_dir() / bid_name
            self._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                package.image_members_by_path,
            )
            yield ost_path
        finally:
            _remove_temp_tree(tmp_path)

    def _extract_images(
        self,
        tmp_path: Path,
        ost_path: Path,
        dest_dir: Path,
        image_members_by_path: dict[str, str],
    ) -> None:
        tree = ET.parse(str(ost_path))
        image_refs = self._collect_image_references(
            tree.getroot(), image_members_by_path
        )
        if not image_refs:
            return
        copied_paths = self._copy_referenced_images(tmp_path, dest_dir, image_refs)
        self._rewrite_image_paths(tree, ost_path, copied_paths)

    def _collect_image_references(
        self,
        root: ET.Element,
        image_members_by_path: dict[str, str],
    ) -> list[_ImageReference]:
        image_refs_by_original: dict[str, _ImageReference] = {}
        missing_paths: dict[str, None] = {}
        for page_elem in root.iter("BidPage"):
            for attr in _IMAGE_PATH_ATTRS:
                image_path = page_elem.get(attr)
                if not image_path or not _is_supported_image_path(image_path):
                    continue
                member_name = _resolve_image_member(image_path, image_members_by_path)
                if member_name is None:
                    missing_paths[image_path] = None
                    continue
                image_refs_by_original[image_path] = _ImageReference(
                    original_path=image_path,
                    member_name=member_name,
                )
        if missing_paths:
            logger.warning(
                "OSP import could not resolve %d referenced image(s) in the "
                "package. Import will continue and preserve those original paths. "
                "First missing source path: %s",
                len(missing_paths),
                next(iter(missing_paths)),
            )
        return list(image_refs_by_original.values())

    def _copy_referenced_images(
        self,
        tmp_path: Path,
        dest_dir: Path,
        image_refs: list[_ImageReference],
    ) -> dict[str, str]:
        for image_ref in image_refs:
            source_path = _cab_member_path(tmp_path, image_ref.member_name)
            if not source_path.is_file():
                raise _OspFormatError(
                    f"image member was not extracted: {image_ref.member_name}"
                )
        copied_paths: dict[str, str] = {}
        destinations_by_member: dict[str, str] = {}
        members_by_destination: dict[str, str] = {}
        for image_ref in image_refs:
            source_path = _cab_member_path(tmp_path, image_ref.member_name)
            member_key = image_ref.member_name.casefold()
            destination = destinations_by_member.get(member_key)
            if destination is None:
                dest_path = dest_dir / _image_destination_relative_path(
                    image_ref.member_name
                )
                destination_key = str(dest_path).casefold()
                conflicting_member = members_by_destination.get(destination_key)
                if conflicting_member is not None and conflicting_member != member_key:
                    raise _OspFormatError(
                        "image staging destination collision between "
                        f"{image_ref.member_name!r} and {conflicting_member!r}"
                    )
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source_path), str(dest_path))
                destination = str(dest_path)
                destinations_by_member[member_key] = destination
                members_by_destination[destination_key] = member_key
            copied_paths[image_ref.original_path] = destination
        return copied_paths

    def _rewrite_image_paths(
        self,
        tree: ET.ElementTree,
        ost_path: Path,
        copied_paths: dict[str, str],
    ) -> None:
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


def _is_supported_image_path(path: str) -> bool:
    return (
        PureWindowsPath(path.replace("/", "\\")).suffix.lower() in OSP_IMAGE_EXTENSIONS
    )


def _windows_path_parts(path: str) -> tuple[str, ...]:
    return PureWindowsPath(path.replace("/", "\\")).parts


def _resolve_image_member(
    image_path: str,
    image_members_by_path: dict[str, str],
) -> Optional[str]:
    reference_parts = tuple(part.casefold() for part in _windows_path_parts(image_path))
    if reference_parts[0] == _IMAGE_MEMBER_ROOT.casefold():
        return image_members_by_path.get("\\".join(reference_parts))
    best_match: Optional[str] = None
    best_match_depth = 0
    for member_name in image_members_by_path.values():
        member_parts = _windows_path_parts(member_name)[1:]
        member_parts_folded = tuple(part.casefold() for part in member_parts)
        member_depth = len(member_parts_folded)
        if (
            member_depth > best_match_depth
            and member_depth <= len(reference_parts)
            and reference_parts[-member_depth:] == member_parts_folded
        ):
            best_match = member_name
            best_match_depth = member_depth
    return best_match


def _image_destination_relative_path(member_name: str) -> Path:
    member_parts = _windows_path_parts(member_name)
    filename = member_parts[-1]
    if len(member_parts) == 2:
        return Path(filename)
    digest = hashlib.sha1(member_name.casefold().encode("utf-8")).hexdigest()[:16]
    return Path("Images") / digest / filename


def _cab_member_path(root: Path, member_name: str) -> Path:
    return root.joinpath(*_windows_path_parts(member_name))
