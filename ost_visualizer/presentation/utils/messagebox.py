from typing import List, Optional, Set, Tuple
from PySide6 import QtWidgets

_Yes = QtWidgets.QMessageBox.StandardButton.Yes
_No = QtWidgets.QMessageBox.StandardButton.No
_Ok = QtWidgets.QMessageBox.StandardButton.Ok
DB_LOCKED_HINT = "The database may be locked by another application."


def show_warning(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.warning(parent, title, message)


def show_critical(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.critical(parent, title, message)


def show_info(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.information(parent, title, message)


def confirm(parent: QtWidgets.QWidget, title: str, message: str) -> bool:
    reply = QtWidgets.QMessageBox.question(parent, title, message, _Yes | _No, _No)
    return reply == _Yes


def confirm_delete_page_with_contents(
    parent: QtWidgets.QWidget, page_name: str
) -> bool:
    message = (
        f"The Page '{page_name}' contains takeoff, annotation, or comments. "
        "Deleting this page will remove the page and anything on it, in the Base Bid, "
        "and any Alternates or Change Orders.\n\n"
        "Deleting a Page cannot be undone, are you sure you want to delete this Page?"
    )
    return confirm(parent, "Delete Verification", message)


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
            f"{in_use_lines}\n\nDelete the other {n} item(s)?",
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
        msg = f"Delete {len(deletable)} item(s)?"
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
        box.setWindowTitle(f'Delete "{name}" ?')
        box.setText(
            "Deleting a Condition will Delete all its Takeoff "
            "on all Pages within this Bid.\n\n"
            "THIS CANNOT BE UNDONE!\n\n"
            "Are you sure you want to Delete this condition?"
        )
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        yes_btn = box.addButton(_Yes)
        no_btn = box.addButton(_No)
        box.setDefaultButton(no_btn)
        yes_all_btn = None
        if remaining > 1:
            yes_all_btn = box.addButton(
                "Yes to all", QtWidgets.QMessageBox.ButtonRole.YesRole
            )
        box.exec()
        clicked = box.clickedButton()
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
        "Not Found",
        f'"{name}" was not found.\n\nWould you like to add it?',
        QtWidgets.QMessageBox.StandardButton.Yes
        | QtWidgets.QMessageBox.StandardButton.No,
        QtWidgets.QMessageBox.StandardButton.No,
    )
    return reply == QtWidgets.QMessageBox.StandardButton.Yes
