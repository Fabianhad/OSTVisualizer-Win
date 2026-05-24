from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional
from .page_info import BidPageInfo
from .takeoff import Takeoff


@dataclass
class Page:
    uid: str
    name: str
    sheet_no: str = ""
    sequence: int = 0
    takeoffs: List[Takeoff] = field(default_factory=list)
    folder_uid: Optional[str] = None
    image_path: Optional[str] = None
    width_pts: float = 0.0
    height_pts: float = 0.0
    scale_factor1: float = 1.0
    scale_factor2: float = 1.0
    rotation: int = 0
    flip_x: bool = False
    flip_y: bool = False
    page_index: int = 0
    layer_visible: bool = True
    overlay_image_path: Optional[str] = None
    overlay_offset_x: float = 0.0
    overlay_offset_y: float = 0.0
    overlay_rotation: float = 0.0
    overlay_resized: bool = False
    deskew_rotation_overlay: float = 0.0
    overlay_rect: tuple = (0.0, 0.0, 0.0, 0.0)
    image_show_mode: int = 0
    zoom_fac: float = 0.0
    current_x: float = 0.0
    current_y: float = 0.0
    invert: bool = False
    bitonal: bool = False

    @property
    def has_image(self) -> bool:
        return bool(self.image_path)

    @property
    def has_overlay(self) -> bool:
        return bool(self.overlay_image_path)

    @property
    def effective_width_pts(self) -> float:
        return self.height_pts if self.rotation in (90, 270) else self.width_pts

    @property
    def effective_height_pts(self) -> float:
        return self.width_pts if self.rotation in (90, 270) else self.height_pts


def build_pages_from_bid_data(
    bid_pages: Dict[str, BidPageInfo], bid_takeoffs: Iterable[Takeoff]
) -> Dict[str, Page]:
    takeoffs_by_page: Dict[str, List[Takeoff]] = defaultdict(list)
    for takeoff in bid_takeoffs:
        page_uid = takeoff.page_uid or "NO_PAGE_ID"
        takeoffs_by_page[page_uid].append(takeoff)
    pages: Dict[str, Page] = {}
    for uid, info in bid_pages.items():
        pages[uid] = Page(
            uid=uid,
            name=info.name,
            sheet_no=info.sheet_no,
            sequence=info.sequence,
            takeoffs=takeoffs_by_page.get(uid, []),
            image_path=info.image_path,
            width_pts=info.width_pts,
            height_pts=info.height_pts,
            scale_factor1=info.scale_factor1,
            scale_factor2=info.scale_factor2,
            rotation=info.rotation,
            flip_x=info.flip_x,
            flip_y=info.flip_y,
            page_index=info.page_index,
            layer_visible=info.layer_visible,
            overlay_image_path=info.overlay_image_path,
            overlay_offset_x=info.overlay_offset_x,
            overlay_offset_y=info.overlay_offset_y,
            overlay_rotation=info.overlay_rotation,
            overlay_resized=info.overlay_resized,
            deskew_rotation_overlay=info.deskew_rotation_overlay,
            overlay_rect=info.overlay_rect,
            image_show_mode=info.image_show_mode,
            zoom_fac=info.zoom_fac,
            current_x=info.current_x,
            current_y=info.current_y,
            invert=info.invert,
            bitonal=info.bitonal,
        )
    if "NO_PAGE_ID" in takeoffs_by_page:
        pages["NO_PAGE_ID"] = Page(
            uid="NO_PAGE_ID",
            name="Items Without Page",
            takeoffs=takeoffs_by_page["NO_PAGE_ID"],
        )
    for uid, takeoffs in takeoffs_by_page.items():
        if uid not in pages:
            pages[uid] = Page(uid=uid, name=f"Page {uid}", takeoffs=takeoffs)
    return pages
