from typing import Protocol
from ..dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
    UserPageViewState,
)


class ISqlWorkspaceStateRepository(Protocol):
    def load_bid_state(
        self, database_id: str, bid_uid: str
    ) -> UserBidWorkspaceState: ...
    def save_active_page(
        self, database_id: str, bid_uid: str, page_uid: str
    ) -> None: ...
    def save_page_view(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        state: UserPageViewState,
    ) -> None: ...
