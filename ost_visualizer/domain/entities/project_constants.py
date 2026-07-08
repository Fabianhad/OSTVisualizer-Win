from typing import Optional

DELETED_BIDS_PROJECT_UID = "1"
DELETED_BIDS_PROJECT_NAME = "Deleted Bids"


def is_deleted_bids_project_uid(project_uid: Optional[str]) -> bool:
    return str(project_uid) == DELETED_BIDS_PROJECT_UID
