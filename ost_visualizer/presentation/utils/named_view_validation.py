from typing import Iterable, Optional, Tuple
from PySide6 import QtWidgets
from .messagebox import show_warning

NamedViewChoice = Tuple[str, str, str, str]
_DUPLICATE_NAMED_VIEW_MESSAGE = "Named view should have unique name"


def normalize_named_view_name(name: str) -> str:
    return str(name or "").strip().casefold()


def named_view_name_exists(
    choices: Iterable[NamedViewChoice],
    name: str,
    exclude_uid: Optional[str] = None,
) -> bool:
    normalized = normalize_named_view_name(name)
    if not normalized:
        return False
    exclude = str(exclude_uid) if exclude_uid else None
    for uid, _page_uid, _page_name, view_name in choices:
        if exclude is not None and str(uid) == exclude:
            continue
        if normalize_named_view_name(view_name) == normalized:
            return True
    return False


def show_duplicate_named_view_name(parent: QtWidgets.QWidget) -> None:
    show_warning(parent, "Named View", _DUPLICATE_NAMED_VIEW_MESSAGE)
