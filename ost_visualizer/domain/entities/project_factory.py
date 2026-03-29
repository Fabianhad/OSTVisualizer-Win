from typing import List, Optional
from .bid import Bid
from .folder import Folder
from .hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from .loaded_file import LoadedFile
from .page import Page
from .project import Project


def build_projects(hierarchy: HierarchyData) -> List[Project]:
    if not hierarchy or not hierarchy.loaded_files:
        return []
    projects: List[Project] = []
    all_orphan_bids: List[HierarchyBidInfo] = []
    for file_entry in hierarchy.loaded_files:
        for project_uid, project_info in file_entry.bid_projects.items():
            bids = [build_bid(bid_info) for bid_info in project_info.bids]
            projects.append(
                Project(
                    uid=project_uid,
                    name=project_info.name or f"Project {project_uid}",
                    description=project_info.description,
                    bids=bids,
                    file_path=file_entry.file_path,
                )
            )
        all_orphan_bids.extend(file_entry.orphan_bids)
    if all_orphan_bids:
        bids = [build_bid(bid_info) for bid_info in all_orphan_bids]
        projects.append(
            Project(
                uid="UNASSIGNED",
                name="Unassigned Bids",
                description="Bids without a project",
                bids=bids,
            )
        )
    return projects


def build_loaded_files(hierarchy: HierarchyData) -> List[LoadedFile]:
    if not hierarchy or not hierarchy.loaded_files:
        return []
    result: List[LoadedFile] = []
    for file_entry in hierarchy.loaded_files:
        projects: List[Project] = []
        for project_uid, project_info in file_entry.bid_projects.items():
            bids = [build_bid(b) for b in project_info.bids]
            projects.append(
                Project(
                    uid=project_uid,
                    name=project_info.name or f"Project {project_uid}",
                    description=project_info.description,
                    bids=bids,
                )
            )
        orphan_bids = [build_bid(b) for b in file_entry.orphan_bids]
        result.append(
            LoadedFile(
                file_path=file_entry.file_path,
                display_name=file_entry.display_name,
                projects=projects,
                orphan_bids=orphan_bids,
            )
        )
    return result


def build_bid(bid_info: Optional[HierarchyBidInfo]) -> Bid:
    if not bid_info:
        return Bid(uid="", name="")
    return Bid(
        uid=bid_info.uid,
        name=bid_info.name,
        bid_no=bid_info.bid_no,
        bid_date=bid_info.bid_date,
        notes=bid_info.notes,
        job_id=bid_info.job_id,
        status=bid_info.status,
        estimator=bid_info.estimator,
        page_count=bid_info.page_count,
        condition_count=bid_info.condition_count,
        measure_base=bid_info.measure_base,
        takeoff_increments=bid_info.takeoff_increments,
        orig_bid_project_uid=bid_info.orig_bid_project_uid,
        copy_from_bid_no=bid_info.copy_from_bid_no,
        copy_timestamp=bid_info.copy_timestamp,
        folders={
            uid: _build_folder(uid, folder_info)
            for uid, folder_info in bid_info.folders.items()
        },
        pages_without_folder=[
            _build_page(page_info) for page_info in bid_info.pages_without_folder
        ],
    )


def _build_folder(uid: str, folder_info: HierarchyFolderInfo) -> Folder:
    return Folder(
        uid=uid,
        name=folder_info.name,
        description=folder_info.description,
        pages=[_build_page(p) for p in folder_info.pages],
        subfolders={
            sub_uid: _build_folder(sub_uid, sub_info)
            for sub_uid, sub_info in folder_info.subfolders.items()
        },
    )


def _build_page(page_info: HierarchyPageInfo) -> Page:
    return Page(
        uid=page_info.uid,
        name=page_info.name,
    )
