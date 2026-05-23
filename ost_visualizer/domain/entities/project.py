from dataclasses import dataclass, field
from typing import List
from .bid import Bid


@dataclass
class Project:
    uid: str
    name: str
    description: str = ""
    bids: List[Bid] = field(default_factory=list)
    file_path: str = ""
