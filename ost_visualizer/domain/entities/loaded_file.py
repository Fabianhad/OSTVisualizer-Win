from dataclasses import dataclass, field
from typing import List
from .bid import Bid
from .project import Project


@dataclass
class LoadedFile:
    file_path: str
    display_name: str
    projects: List[Project] = field(default_factory=list)
    orphan_bids: List[Bid] = field(default_factory=list)
