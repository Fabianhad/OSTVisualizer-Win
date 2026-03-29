from typing import Dict, Iterable, List, Optional
from ..entities.annotation import BidAnnotation
from ..entities.page import Page
from ..entities.takeoff import Takeoff


class PageSelectionService:
    def __init__(self):
        self.pages: Dict[str, Page] = {}
        self.selected_page_uids: List[str] = []
        self._annotations: List[BidAnnotation] = []

    def set_pages(self, pages: Dict[str, Page]) -> None:
        self.pages = dict(pages)
        self.selected_page_uids = [
            uid for uid in self.selected_page_uids if uid in self.pages
        ]

    def set_annotations(self, annotations: List[BidAnnotation]) -> None:
        self._annotations = list(annotations)

    def clear(self) -> None:
        self.pages.clear()
        self.selected_page_uids.clear()
        self._annotations.clear()

    def select_pages(self, page_uids: Iterable[str]) -> List[str]:
        unique_uids: List[str] = []
        seen = set()
        for uid in page_uids:
            if uid and uid not in seen:
                seen.add(uid)
                unique_uids.append(uid)
        self.selected_page_uids = unique_uids
        return self.get_selected_pages()

    def clear_selection(self) -> None:
        self.selected_page_uids.clear()

    def get_selected_pages(self) -> List[str]:
        return self.selected_page_uids[:]

    def has_takeoffs_for_pages(self, page_uids: Iterable[str]) -> bool:
        return any(self.get_page_takeoffs(uid) for uid in page_uids)

    def get_page_name(self, page_uid: str) -> str:
        if page_uid == "NO_PAGE_ID":
            return "Items Without Page"
        page = self.pages.get(page_uid)
        if not page:
            return f"Page {page_uid}"
        return page.name

    def get_page(self, page_uid: str) -> Optional[Page]:
        return self.pages.get(page_uid)

    def get_all_takeoffs(self) -> List[Takeoff]:
        takeoffs: List[Takeoff] = []
        for page in self.pages.values():
            takeoffs.extend(page.takeoffs)
        return takeoffs

    def get_page_takeoffs(self, page_uid: str) -> List[Takeoff]:
        page = self.pages.get(page_uid)
        return page.takeoffs if page else []

    def get_all_selected_takeoffs(self) -> List[Takeoff]:
        takeoffs: List[Takeoff] = []
        for uid in self.selected_page_uids:
            takeoffs.extend(self.get_page_takeoffs(uid))
        return takeoffs

    def get_page_annotations(self, page_uid: str) -> List[BidAnnotation]:
        return [a for a in self._annotations if str(a.page_uid) == str(page_uid)]

    def get_all_annotations(self) -> List[BidAnnotation]:
        return self._annotations[:]
