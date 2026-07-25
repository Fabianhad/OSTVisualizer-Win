from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Set
from .employee import Employee, PayClass


@dataclass
class JobStatus:
    uid: str
    name: str
    locked: bool = False
    sequence: int = 0


@dataclass
class CoverSheetPage:
    uid: str
    sheet_no: str
    name: str
    width: float
    height: float
    scale_factor1: float
    scale_factor2: float
    image_path: str
    overlay_image_path: str
    index: int
    show_mode: int
    multi_page_count: int = 0


@dataclass
class CoverSheetFolder:
    uid: str
    name: str
    pages: List[CoverSheetPage] = field(default_factory=list)
    subfolders: Dict[str, CoverSheetFolder] = field(default_factory=dict)


@dataclass
class CoverSheetData:
    bid_uid: str
    job_status_uid: str
    job_name: str
    estimator_uid: str
    notes: str
    bid_date: str
    bid_no: str
    job_id: str
    measure_base: int = 0
    takeoff_increments: float = 1.0
    scale_style: int = 1
    scale_factor1: float = 0.25
    scale_factor2: float = 12.0
    page_width: float = 42.0
    page_height: float = 30.0
    folders: Dict[str, CoverSheetFolder] = field(default_factory=dict)
    pages_without_folder: List[CoverSheetPage] = field(default_factory=list)
    job_statuses: List[JobStatus] = field(default_factory=list)
    employees: List[Employee] = field(default_factory=list)
    pay_classes: List[PayClass] = field(default_factory=list)
    used_job_status_uids: Set[str] = field(default_factory=set)
