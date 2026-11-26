from typing import List, Optional, Sequence, Set, Tuple
from PySide6 import QtWidgets
from .qt_lifecycle import delete_later_if_valid
from ..texts import (
    MESSAGEBOX_BUTTON_YES_TO_ALL,
    MESSAGEBOX_LABEL_DELETING_A_CONDITION_WILL_DELETE_ALL,
    MESSAGEBOX_MESSAGE_DELETE_ITEMS,
    MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM,
    MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM,
    MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS,
    MESSAGEBOX_MESSAGE_WAS_NOT_FOUND_WOULD_YOU_LIKE,
    MESSAGEBOX_TITLE_DELETE,
    MESSAGEBOX_TITLE_DELETE_VERIFICATION,
    MESSAGEBOX_TITLE_NOT_FOUND,
)

_Yes = QtWidgets.QMessageBox.StandardButton.Yes
_No = QtWidgets.QMessageBox.StandardButton.No
_Ok = QtWidgets.QMessageBox.StandardButton.Ok
DB_LOCKED_HINT = "The database may be locked by another application."
SAVE_ANYWAY_LABEL = "Save Anyway"
GO_BACK_LABEL = "Go Back"


def show_warning(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.warning(parent, title, message)


def show_critical(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.critical(parent, title, message)


def show_info(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.information(parent, title, message)


def confirm(parent: QtWidgets.QWidget, title: str, message: str) -> bool:
    reply = QtWidgets.QMessageBox.question(parent, title, message, _Yes | _No, _No)
    return reply == _Yes


def confirm_save_with_warnings(
    parent: QtWidgets.QWidget, title: str, warnings: Sequence[str]
) -> bool:
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText("\n".join(warnings))
    save_button = box.addButton(
        SAVE_ANYWAY_LABEL, QtWidgets.QMessageBox.ButtonRole.AcceptRole
    )
    back_button = box.addButton(
        GO_BACK_LABEL, QtWidgets.QMessageBox.ButtonRole.RejectRole
    )
    box.setDefaultButton(back_button)
    box.setEscapeButton(back_button)
    try:
        box.exec()
        return box.clickedButton() is save_button
    finally:
        delete_later_if_valid(box)


def confirm_delete_page_with_contents(
    parent: QtWidgets.QWidget, page_name: str
) -> bool:
    message = (
        f'The page "{page_name}" contains takeoff, annotation, or comments. '
        "Deleting this page will remove the page and anything on it, in the Base Bid, "
        "and any Alternates or Change Orders.\n\n"
        "Deleting a page cannot be undone. Are you sure you want to delete this page?"
    )
    return confirm(parent, MESSAGEBOX_TITLE_DELETE_VERIFICATION, message)


def confirm_save_discard_cancel(
    parent: QtWidgets.QWidget, title: str, message: str
) -> Optional[bool]:
    _Cancel = QtWidgets.QMessageBox.StandardButton.Cancel
    reply = QtWidgets.QMessageBox.question(
        parent, title, message, _Yes | _No | _Cancel, _Cancel
    )
    if reply == _Yes:
        return True
    if reply == _No:
        return False
    return None


def confirm_multi_delete(
    parent: QtWidgets.QWidget,
    title: str,
    items: List[Tuple[str, str]],
    used_uids: Set[str],
) -> Optional[List[Tuple[str, str]]]:
    in_use = [(name, uid) for name, uid in items if str(uid) in used_uids]
    deletable = [(name, uid) for name, uid in items if str(uid) not in used_uids]
    if in_use and deletable:
        in_use_lines = "\n".join(
            f'Cannot delete "{name}" because it is in use.' for name, _ in in_use
        )
        n = len(deletable)
        reply = QtWidgets.QMessageBox.question(
            parent,
            title,
            (
                MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM
                if n == 1
                else MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS
            ).format(in_use_lines=in_use_lines, n=n),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return None
    elif in_use:
        in_use_lines = "\n".join(
            f'Cannot delete "{name}" because it is in use.' for name, _ in in_use
        )
        QtWidgets.QMessageBox.warning(parent, title, in_use_lines)
        return None
    else:
        msg = (
            MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM
            if len(deletable) == 1
            else MESSAGEBOX_MESSAGE_DELETE_ITEMS
        ).format(n=len(deletable))
        reply = QtWidgets.QMessageBox.question(
            parent,
            title,
            msg,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return None
    return deletable


def confirm_delete_conditions(
    parent: QtWidgets.QWidget,
    names: List[Tuple[str, str]],
) -> List[str]:
    confirmed: List[str] = []
    for i, (uid, name) in enumerate(names):
        remaining = len(names) - i
        box = QtWidgets.QMessageBox(parent)
        box.setWindowTitle(MESSAGEBOX_TITLE_DELETE.format(name=name))
        box.setText(MESSAGEBOX_LABEL_DELETING_A_CONDITION_WILL_DELETE_ALL)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        yes_btn = box.addButton(_Yes)
        no_btn = box.addButton(_No)
        box.setDefaultButton(no_btn)
        yes_all_btn = None
        if remaining > 1:
            yes_all_btn = box.addButton(
                MESSAGEBOX_BUTTON_YES_TO_ALL, QtWidgets.QMessageBox.ButtonRole.YesRole
            )
        try:
            box.exec()
            clicked = box.clickedButton()
        finally:
            delete_later_if_valid(box)
        if clicked == yes_btn:
            confirmed.append(uid)
        elif yes_all_btn and clicked == yes_all_btn:
            confirmed.append(uid)
            confirmed.extend(u for u, _ in names[i + 1 :])
            break
    return confirmed


def confirm_not_found(parent: QtWidgets.QWidget, name: str) -> bool:
    reply = QtWidgets.QMessageBox.question(
        parent,
        MESSAGEBOX_TITLE_NOT_FOUND,
        MESSAGEBOX_MESSAGE_WAS_NOT_FOUND_WOULD_YOU_LIKE.format(name=name),
        QtWidgets.QMessageBox.StandardButton.Yes
        | QtWidgets.QMessageBox.StandardButton.No,
        QtWidgets.QMessageBox.StandardButton.No,
    )
    return reply == QtWidgets.QMessageBox.StandardButton.Yes
