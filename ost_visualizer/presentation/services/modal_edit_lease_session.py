from typing import Optional, Protocol
from PySide6 import QtWidgets
from ...application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    ResourceRef,
)
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_event_bus import IEventBus


class IModalEditLeaseOwner(Protocol):
    def request_collaboration_edit(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        callback,
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
        operation_id: str = "",
        owning_surface: str = "desktop",
    ) -> None: ...
    def end_collaboration_edit(self, handle: EditLeaseHandle) -> None: ...
class ModalEditLeaseSession:
    def __init__(
        self,
        owner: IModalEditLeaseOwner,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        operation_id: str,
        *,
        event_bus: IEventBus,
        dependency_resources: tuple[ResourceRef, ...] = (),
        owning_surface: str = "main-window-dialog",
    ) -> None:
        self._owner = owner
        self._database_id = database_id
        self._resources = resources
        self._dependency_resources = dependency_resources
        self._operation_id = operation_id
        self._owning_surface = owning_surface
        self._event_bus = event_bus
        self._handle: Optional[EditLeaseHandle] = None
        self._dialog: Optional[QtWidgets.QDialog] = None
        self._closed = False
        self._event_bus.subscribe(AppEvents.EDIT_LEASE_LOST, self._on_edit_lease_lost)

    def bind_dialog(self, dialog: QtWidgets.QDialog) -> None:
        self._dialog = dialog

    def request_initial(self, completed) -> None:
        def resolved(result: EditLeaseResult) -> None:
            if self._closed:
                if result.handle is not None:
                    self._owner.end_collaboration_edit(result.handle)
                completed(
                    EditLeaseResult(
                        False,
                        "The edit was cancelled while the dialog was closing.",
                    )
                )
                return
            if result.granted:
                self._handle = result.handle
            completed(result)

        self._request(resolved)

    def accept_initial_lease(self, result: EditLeaseResult) -> None:
        if result.granted:
            self._handle = result.handle

    def submit_mutation(self, submit, completed) -> bool:
        handle = self._handle
        if self._closed or handle is None:
            completed(False, None)
            return False
        self._handle = None
        synchronous_completion = None

        def finish_mutation(success: bool, value=None) -> None:
            if self._closed:
                return

            def reacquired(result: EditLeaseResult) -> None:
                if self._closed:
                    if result.handle is not None:
                        self._owner.end_collaboration_edit(result.handle)
                    return
                if result.granted:
                    self._handle = result.handle
                    completed(success, value)
                    return
                completed(False, None)
                if self._dialog is not None:
                    self._dialog.reject()

            self._request(reacquired)

        submitting = True

        def mutation_completed(success: bool, value=None) -> None:
            nonlocal synchronous_completion
            if submitting:
                synchronous_completion = (success, value)
                return
            finish_mutation(success, value)

        try:
            started = submit(handle, mutation_completed)
        except Exception:
            self._handle = handle
            raise
        submitting = False
        if not started:
            self._handle = handle
            if synchronous_completion is not None:
                completed(*synchronous_completion)
            return False
        if synchronous_completion is not None:
            finish_mutation(*synchronous_completion)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._event_bus.unsubscribe(
            AppEvents.EDIT_LEASE_LOST,
            self._on_edit_lease_lost,
        )
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._owner.end_collaboration_edit(handle)

    def _on_edit_lease_lost(self, loss: EditLeaseLoss) -> None:
        handle = self._handle
        if (
            self._closed
            or handle is None
            or loss.database_id != handle.database_id
            or loss.runtime_generation != handle.runtime_generation
            or loss.draft_id != handle.draft_id
        ):
            return
        self._handle = None
        if self._dialog is not None:
            self._dialog.reject()

    def _request(self, callback) -> None:
        self._owner.request_collaboration_edit(
            self._database_id,
            self._resources,
            callback,
            dependency_resources=self._dependency_resources,
            operation_id=self._operation_id,
            owning_surface=self._owning_surface,
        )
