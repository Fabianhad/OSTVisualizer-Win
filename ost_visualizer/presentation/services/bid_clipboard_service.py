from typing import List
from ...domain.entities.file_state import normalize_path
from ...domain.entities.hierarchy_data import HierarchyData
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.project_constants import DELETED_BIDS_PROJECT_UID


class BidClipboardService:
    def __init__(self) -> None:
        self._bid_refs: List[BidRef] = []
        self._cut: bool = False
        self._ownership_revision: int = 0

    def copy(self, bid_refs: List[BidRef]) -> None:
        self._set_refs(bid_refs, cut=False)

    def cut(self, bid_refs: List[BidRef]) -> None:
        self._set_refs(bid_refs, cut=True)

    def clear(self) -> None:
        self._bid_refs = []
        self._cut = False
        self._ownership_revision += 1

    def clear_for_file(self, file_path: str) -> bool:
        if not file_path or not any(
            normalize_path(ref.file_path) == normalize_path(file_path)
            for ref in self._bid_refs
        ):
            return False
        self.clear()
        return True

    def reconcile(self, hierarchy: HierarchyData) -> bool:
        valid_bid_keys = set()
        for file_entry in hierarchy.loaded_files:
            normalized_path = normalize_path(file_entry.file_path)
            valid_bid_keys.update(
                (normalized_path, bid.uid) for bid in file_entry.orphan_bids
            )
            for project_uid, project in file_entry.bid_projects.items():
                if str(project_uid) == DELETED_BIDS_PROJECT_UID:
                    continue
                valid_bid_keys.update(
                    (normalized_path, bid.uid) for bid in project.bids
                )
        retained_refs = [
            ref
            for ref in self._bid_refs
            if (normalize_path(ref.file_path), ref.bid_uid) in valid_bid_keys
        ]
        if retained_refs == self._bid_refs:
            return False
        self._bid_refs = retained_refs
        if not retained_refs:
            self._cut = False
        return True

    def has_content(self) -> bool:
        return bool(self._bid_refs)

    @property
    def is_cut(self) -> bool:
        return self._cut

    @property
    def bid_refs(self) -> List[BidRef]:
        return self._bid_refs[:]

    @property
    def ownership_revision(self) -> int:
        return self._ownership_revision

    @property
    def source_file_path(self) -> str:
        return self._bid_refs[0].file_path

    def source_matches_file(self, file_path: str) -> bool:
        return bool(
            self.has_content()
            and file_path
            and normalize_path(self.source_file_path) == normalize_path(file_path)
        )

    @staticmethod
    def refs_share_database(bid_refs: List[BidRef]) -> bool:
        if not bid_refs:
            return False
        file_path = bid_refs[0].file_path
        return all(
            normalize_path(ref.file_path) == normalize_path(file_path)
            for ref in bid_refs
        )

    def _set_refs(self, bid_refs: List[BidRef], cut: bool) -> None:
        self._bid_refs = list(bid_refs)
        self._cut = bool(cut and self._bid_refs)
        self._ownership_revision += 1

    def complete_cut(
        self,
        ownership_revision: int,
        moved_bid_refs: List[BidRef],
    ) -> bool:
        if not self._cut or ownership_revision != self._ownership_revision:
            return False
        moved_keys = {
            (normalize_path(ref.file_path), ref.bid_uid) for ref in moved_bid_refs
        }
        retained_refs = [
            ref
            for ref in self._bid_refs
            if (normalize_path(ref.file_path), ref.bid_uid) not in moved_keys
        ]
        if retained_refs == self._bid_refs:
            return False
        self._bid_refs = retained_refs
        self._cut = bool(retained_refs)
        self._ownership_revision += 1
        return True
