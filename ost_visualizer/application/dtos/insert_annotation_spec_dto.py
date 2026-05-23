from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class InsertAnnotationSpec:
    page_uid: str
    annotation_type: str
    position: List[float]
    color: str
    width: float
    properties: Dict[str, Any] = field(default_factory=dict)
    layer_uid: str = ""
