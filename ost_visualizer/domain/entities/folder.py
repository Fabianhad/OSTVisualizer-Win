from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from .page import Page


@dataclass
class Folder:
    uid: str
    name: str
    description: str = ""
    pages: List[Page] = field(default_factory=list)
    subfolders: Dict[str, Folder] = field(default_factory=dict)
