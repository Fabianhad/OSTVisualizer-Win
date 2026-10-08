import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ...domain.entities.ai_changeset import (
    STATUS_APPLIED,
    STATUS_APPLYING,
    STATUS_FAILED,
    STATUS_REJECTED,
    AiChangeset,
    ChangesetError,
)
from ..dialogs.ai_changeset_review_dialog import AiChangesetReviewDialog

logger = logging.getLogger(__name__)
APPLY_RAISED_MESSAGE = "The change could not be applied. Nothing was accepted; ask the AI to propose it again."


@dataclass(frozen=True)
class ApplyOutcome:
    success: bool
    record: Optional[AppliedChangeset]
    message: str = ""
    code: str = ""


class AiChangesetApprovalController(QtCore.QObject):
    changeset_finished = QtCore.Signal(str, str)

    def __init__(
        self,
        store,
        applier,
        preview,
        is_sql: Callable[[str], bool],
        parent_widget: Callable[[], Optional[QtWidgets.QWidget]] = lambda: None,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)
        self._store = store
        self._applier = applier
        self._preview = preview
        self._is_sql = is_sql
        self._parent_widget = parent_widget
        self._dialogs: Dict[str, AiChangesetReviewDialog] = {}
        self._errors: Dict[str, str] = {}

    def dialog_for(self, uid: str) -> Optional[AiChangesetReviewDialog]:
        dialog = self._dialogs.get(uid)
        if dialog is None or not isValid(dialog):
            return None
        return dialog

    def last_error(self, uid: str) -> str:
        return self._errors.get(uid, "")

    def on_apply_requested(self, uid: str) -> None:
        try:
            changeset = self._store.get(uid)
        except ChangesetError as exc:
            logger.info("AI changeset request ignored: %s", exc.code)
            return
        dialog = self.dialog_for(uid)
        if dialog is None:
            dialog = AiChangesetReviewDialog(
                changeset,
                bool(self._is_sql(changeset.database_id)),
                self._parent_widget(),
            )
            dialog.accept_requested.connect(lambda uid=uid: self.accept(uid))
            dialog.reject_requested.connect(lambda uid=uid: self.reject(uid))
            dialog.assumption_accepted.connect(
                lambda assumption_uid, uid=uid: self._accept_assumption(
                    uid, assumption_uid
                )
            )
            dialog.assumption_overridden.connect(
                lambda assumption_uid, value, uid=uid: self._override_assumption(
                    uid, assumption_uid, value
                )
            )
            dialog.finished.connect(lambda _result, uid=uid: self._forget(uid))
            self._dialogs[uid] = dialog
        else:
            dialog.refresh(changeset)
        self._preview.show(changeset)
        dialog.show()
        dialog.raise_()

    def accept(self, uid: str) -> None:
        try:
            changeset = self._store.approve(uid, self._shown_revision(uid))
        except ChangesetError as exc:
            self._report(uid, exc.message, refresh=True)
            return
        try:
            self._applier.apply(
                changeset, lambda outcome, uid=uid: self._applied(uid, outcome)
            )
        except Exception as exc:
            logger.exception("AI changeset apply raised: %s", type(exc).__name__)
            if self._store.get(uid).status == STATUS_APPLYING:
                self._applied(
                    uid,
                    ApplyOutcome(False, None, APPLY_RAISED_MESSAGE, "apply_failed"),
                )

    def reject(self, uid: str) -> None:
        try:
            self._store.reject(uid)
        except ChangesetError as exc:
            self._report(uid, exc.message)
            return
        self._close(uid)
        self.changeset_finished.emit(uid, STATUS_REJECTED)

    def cleanup(self) -> None:
        for uid in list(self._dialogs):
            self._close(uid)
        self._preview.clear()

    def _applied(self, uid: str, outcome: ApplyOutcome) -> None:
        if outcome.success and outcome.record is not None:
            self._store.mark_applied(uid, outcome.record)
            self._close(uid)
            self.changeset_finished.emit(uid, STATUS_APPLIED)
            return
        self._store.mark_failed(uid)
        self._report(uid, outcome.message or "The changeset could not be applied.")
        self.changeset_finished.emit(uid, STATUS_FAILED)

    def _accept_assumption(self, uid: str, assumption_uid: str) -> None:
        revision = self._shown_revision(uid)
        self._update(
            uid, lambda: self._store.accept_assumption(uid, assumption_uid, revision)
        )

    def _override_assumption(self, uid: str, assumption_uid: str, value: str) -> None:
        revision = self._shown_revision(uid)
        self._update(
            uid,
            lambda: self._store.override_assumption(
                uid, assumption_uid, value, revision
            ),
        )

    def _shown_revision(self, uid: str) -> Optional[int]:
        dialog = self.dialog_for(uid)
        return None if dialog is None else dialog.shown_revision

    def _update(self, uid: str, change: Callable[[], AiChangeset]) -> None:
        try:
            changeset = change()
        except ChangesetError as exc:
            self._report(uid, exc.message, refresh=True)
            return
        dialog = self.dialog_for(uid)
        if dialog is not None:
            dialog.refresh(changeset)
            dialog.show_error("")

    def _report(self, uid: str, message: str, refresh: bool = False) -> None:
        self._errors[uid] = message
        dialog = self.dialog_for(uid)
        if dialog is None:
            return
        if refresh:
            try:
                dialog.refresh(self._store.get(uid))
            except ChangesetError:
                pass
        dialog.show_error(message)

    def _close(self, uid: str) -> None:
        dialog = self.dialog_for(uid)
        if dialog is not None:
            dialog.close()
        self._forget(uid)

    def _forget(self, uid: str) -> None:
        dialog = self._dialogs.pop(uid, None)
        if dialog is not None and isValid(dialog):
            dialog.deleteLater()
        remaining = next(reversed(self._dialogs), None)
        if remaining is None:
            self._preview.clear()
            return
        try:
            self._preview.show(self._store.get(remaining))
        except ChangesetError:
            self._preview.clear()


class AiChangesetPlanPreview:
    def __init__(self, plan_view: Callable[[], object]):
        self._plan_view = plan_view

    def show(self, changeset: AiChangeset) -> None:
        plan_view = self._plan_view()
        if plan_view is None:
            return
        page_uid = plan_view.current_page_uid
        rings = []
        for takeoff in changeset.takeoffs:
            if takeoff.page_uid == page_uid:
                rings.append(takeoff.polygon)
                rings.extend(takeoff.holes)
        plan_view.set_ai_preview(page_uid, rings)

    def clear(self) -> None:
        plan_view = self._plan_view()
        if plan_view is not None:
            plan_view.clear_ai_preview()
