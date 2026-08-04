from __future__ import annotations
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional


@dataclass(frozen=True)
class UserPageViewState:
    zoom_fac: float
    current_x: float
    current_y: float

    def __post_init__(self) -> None:
        values = (self.zoom_fac, self.current_x, self.current_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Page view state requires finite numeric values")
        if self.zoom_fac <= 0.0:
            raise ValueError("Page view zoom must be greater than zero")


@dataclass(frozen=True)
class UserBidWorkspaceState:
    active_page_uid: Optional[str] = None
    page_views: Mapping[str, UserPageViewState] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "page_views",
            MappingProxyType(dict(self.page_views)),
        )
