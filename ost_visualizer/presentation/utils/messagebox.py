import logging
import sys
import weakref
from typing import Callable, List, Optional, Sequence, Set, Tuple
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from .qt_lifecycle import delete_later_if_valid
from ..texts import (
    MESSAGEBOX_BUTTON_GO_BACK,
    MESSAGEBOX_BUTTON_SAVE_ANYWAY,
    MESSAGEBOX_BUTTON_YES_TO_ALL,
    MESSAGEBOX_LABEL_DELETING_THIS_CONDITION_WILL_DELETE_ALL,
    MESSAGEBOX_LABEL_YOU_ARE_DELETING_CONDITIONS,
    MESSAGEBOX_LOG_NOT_SHOWN_THE_APPLICATION_IS_SHUTTING_DOWN,
    MESSAGEBOX_LOG_THE_EXCEPTION_TEXT_BELOW,
    MESSAGEBOX_MESSAGE_CANNOT_DELETE_BECAUSE_IT_IS_IN_USE,
    MESSAGEBOX_MESSAGE_DELETE_ITEMS,
    MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM,
    MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM,
    MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS,
    MESSAGEBOX_MESSAGE_THE_DATABASE_MAY_BE_LOCKED_BY,
    MESSAGEBOX_MESSAGE_THE_PAGE_CONTAINS_TAKEOFF_ANNOTATION_OR,
    MESSAGEBOX_MESSAGE_WAS_NOT_FOUND_WOULD_YOU_LIKE,
    MESSAGEBOX_TITLE_DELETE,
    MESSAGEBOX_TITLE_DELETE_VERIFICATION,
    MESSAGEBOX_TITLE_NOT_FOUND,
)

_Yes = QtWidgets.QMessageBox.StandardButton.Yes
_No = QtWidgets.QMessageBox.StandardButton.No
_Ok = QtWidgets.QMessageBox.StandardButton.Ok
DB_LOCKED_HINT = MESSAGEBOX_MESSAGE_THE_DATABASE_MAY_BE_LOCKED_BY
SAVE_ANYWAY_LABEL = MESSAGEBOX_BUTTON_SAVE_ANYWAY
GO_BACK_LABEL = MESSAGEBOX_BUTTON_GO_BACK
_LOGGER = logging.getLogger(__name__)
_LOGGER_NAMES = ("logger", "_logger", "LOGGER", "_LOGGER")
_shutdown_probes: List[weakref.WeakMethod] = []
_NOT_SHOWN_NOTE = f" {MESSAGEBOX_LOG_NOT_SHOWN_THE_APPLICATION_IS_SHUTTING_DOWN}"


def register_shutdown_probe(probe: Callable[[], bool]) -> None:
    _shutdown_probes.append(weakref.WeakMethod(probe))


def application_shutting_down() -> bool:
    try:
        if QtCore.QCoreApplication.closingDown():
            return True
    except Exception:
        pass
    for reference in list(_shutdown_probes):
        probe = reference()
        if probe is None:
            _shutdown_probes.remove(reference)
            continue
        try:
            if probe():
                return True
        except Exception:
            continue
    return False


def _caller_logger(logger: Optional[logging.Logger], depth: int) -> logging.Logger:
    if logger is not None:
        return logger
    try:
        frame = sys._getframe(depth + 1)
        for name in _LOGGER_NAMES:
            candidate = frame.f_globals.get(name)
            if isinstance(candidate, logging.Logger):
                return candidate
    except ValueError:
        pass
    return _LOGGER


def _log_shown_text(
    level: int,
    title: str,
    message: str,
    exc: Optional[BaseException],
    context: Optional[str],
    logger: Optional[logging.Logger],
    depth: int,
    note: str = "",
) -> logging.Logger:
    target = _caller_logger(logger, depth)
    shown = message
    if exc is not None and str(exc).strip() and str(exc).strip() in message:
        shown = MESSAGEBOX_LOG_THE_EXCEPTION_TEXT_BELOW
    text = f"{title}: {shown}"
    if context:
        text = f"{context} [shown: {text}]"
    text += note
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    try:
        target.log(level, "%s", text, exc_info=exc_info, stacklevel=depth + 1)
    except Exception:
        pass
    return target


def log_user_notice(
    level: int,
    title: str,
    message: str,
    exc: Optional[BaseException] = None,
    *,
    context: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    _log_shown_text(level, title, message, exc, context, logger, 2)


def _report(
    level: int,
    show: Callable[..., object],
    parent: Optional[QtWidgets.QWidget],
    title: str,
    message: str,
    exc: Optional[BaseException],
    context: Optional[str],
    logger: Optional[logging.Logger],
) -> Optional[QtWidgets.QMessageBox]:
    shutting_down = application_shutting_down()
    if exc is not None:
        level = max(level, logging.ERROR)
    target = _log_shown_text(
        level,
        title,
        message,
        exc,
        context,
        logger,
        3,
        _NOT_SHOWN_NOTE if shutting_down else "",
    )
    if shutting_down:
        return None
    if parent is not None:
        try:
            if not isValid(parent):
                parent = None
        except Exception:
            parent = None
    try:
        shown = show(parent, title, message)
    except Exception:
        try:
            target.exception("Failed to show the %s dialog", title, stacklevel=3)
        except Exception:
            pass
        return None
    return shown if isinstance(shown, QtWidgets.QMessageBox) else None


def _non_modal_warning(
    parent: Optional[QtWidgets.QWidget], title: str, message: str
) -> QtWidgets.QMessageBox:
    owner = parent if isinstance(parent, QtWidgets.QWidget) else None
    box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Icon.Warning,
        title,
        message,
        QtWidgets.QMessageBox.StandardButton.Ok,
        owner,
    )
    box.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
    box.setModal(False)
    box.show()
    return box


def show_error(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    message: str,
    exc: Optional[BaseException] = None,
    *,
    context: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    _report(
        logging.ERROR,
        QtWidgets.QMessageBox.critical,
        parent,
        title,
        message,
        exc,
        context,
        logger,
    )


def show_warning(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    message: str,
    exc: Optional[BaseException] = None,
    *,
    context: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
    validation: bool = False,
    modal: bool = True,
) -> Optional[QtWidgets.QMessageBox]:
    return _report(
        logging.INFO if validation else logging.WARNING,
        QtWidgets.QMessageBox.warning if modal else _non_modal_warning,
        parent,
        title,
        message,
        exc,
        context,
        logger,
    )


def show_info(
    parent: Optional[QtWidgets.QWidget],
    title: str,
    message: str,
    *,
    context: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    _report(
        logging.INFO,
        QtWidgets.QMessageBox.information,
        parent,
        title,
        message,
        None,
        context,
        logger,
    )


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
    message = MESSAGEBOX_MESSAGE_THE_PAGE_CONTAINS_TAKEOFF_ANNOTATION_OR.format(
        page_name=page_name
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
            MESSAGEBOX_MESSAGE_CANNOT_DELETE_BECAUSE_IT_IS_IN_USE.format(name=name)
            for name, _ in in_use
        )
        n = len(deletable)
        reply = QtWidgets.QMessageBox.question(
            parent,
            title,
            (
                MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM
                if n == 1
                else MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEMS
            ).format(in_use_lines=in_use_lines, item_count=n),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return None
    elif in_use:
        in_use_lines = "\n".join(
            MESSAGEBOX_MESSAGE_CANNOT_DELETE_BECAUSE_IT_IS_IN_USE.format(name=name)
            for name, _ in in_use
        )
        show_warning(parent, title, in_use_lines)
        return None
    else:
        msg = (
            MESSAGEBOX_MESSAGE_DELETE_ONE_ITEM
            if len(deletable) == 1
            else MESSAGEBOX_MESSAGE_DELETE_ITEMS
        ).format(item_count=len(deletable))
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
        box.setText(
            MESSAGEBOX_LABEL_DELETING_THIS_CONDITION_WILL_DELETE_ALL
            if len(names) == 1
            else MESSAGEBOX_LABEL_YOU_ARE_DELETING_CONDITIONS.format(
                condition_count=len(names)
            )
        )
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
