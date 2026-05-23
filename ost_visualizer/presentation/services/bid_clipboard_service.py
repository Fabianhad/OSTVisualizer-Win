from typing import List
from ...domain.entities.identity_refs import BidRef


class BidClipboardService:
    def __init__(self) -> None:
        self._bid_refs: List[BidRef] = []
        self._cut: bool = False

    def copy(self, bid_refs: List[BidRef]) -> None:
        self._set_refs(bid_refs, cut=False)

    def cut(self, bid_refs: List[BidRef]) -> None:
        self._set_refs(bid_refs, cut=True)

    def clear(self) -> None:
        self._bid_refs = []
        self._cut = False

    def has_content(self) -> bool:
        return bool(self._bid_refs)

    @property
    def is_cut(self) -> bool:
        return self._cut

    @property
    def bid_refs(self) -> List[BidRef]:
        return self._bid_refs[:]

    @property
    def source_file_path(self) -> str:
        return self._bid_refs[0].file_path

    def _set_refs(self, bid_refs: List[BidRef], cut: bool) -> None:
        self._bid_refs = list(bid_refs)
        self._cut = bool(cut and self._bid_refs)
