from dataclasses import dataclass
from typing import Iterable, List
from ...domain.entities.identity_refs import BidRef


def normalize_scene_page_uids(page_uids: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(page_uid) for page_uid in page_uids if page_uid}))


@dataclass(frozen=True)
class MeshSceneIdentity:
    bid_ref: BidRef
    page_uids: tuple[str, ...]
    generation: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "page_uids",
            normalize_scene_page_uids(self.page_uids),
        )
        object.__setattr__(self, "generation", int(self.generation))


@dataclass(frozen=True)
class MeshGeometry:
    vertices: List[float]
    normals: List[float]
    indices: List[int]
    color: str
    opacity: float
    page_uid: str
    condition_uid: str
    takeoff_uid: str
