import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from ...application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ...domain.entities.identity_refs import BidRef


class MutationHistoryState(str, Enum):
    READY = "ready"
    UNDO_PENDING = "undo_pending"
    REDO_PENDING = "redo_pending"
    CONFLICTED = "conflicted"
    UNCERTAIN = "uncertain"


@dataclass
class TakeoffHistoryTarget:
    bid_ref: BidRef
    page_uid: str
    uid: str
    available: bool = True


@dataclass
class MutationHistoryEntry:
    bid_ref: BidRef
    undo_action: Callable[[Callable[[QueuedMutationResult], None]], None]
    redo_action: Callable[[Callable[[QueuedMutationResult], None]], None]
    state: MutationHistoryState = MutationHistoryState.READY
    forward_sequence: Optional[int] = None
    takeoff_targets: tuple[TakeoffHistoryTarget, ...] = ()


@dataclass(frozen=True)
class ForwardMutationToken:
    token_id: str
    bid_ref: BidRef
    history_generation: int
    sequence: int


class UndoRedoService:
    def __init__(
        self, max_size: int = 50, logger: Optional[logging.Logger] = None
    ) -> None:
        self._undo_stack: list[MutationHistoryEntry] = []
        self._redo_stack: list[MutationHistoryEntry] = []
        self._max_size = max_size
        self._active_bid_ref: Optional[BidRef] = None
        self._is_write_allowed: Optional[Callable[[], bool]] = None
        self._on_change: Optional[Callable[[], None]] = None
        self._history_transition_pending = False
        self._forward_mutations: dict[str, ForwardMutationToken] = {}
        self._next_forward_sequence = 1
        self._history_generation = 0
        self.logger = logger or logging.getLogger(__name__)

    def set_write_guard(self, guard: Callable[[], bool]) -> None:
        self._is_write_allowed = guard

    def set_change_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_change = callback

    def set_active_bid(self, bid_ref: Optional[BidRef]) -> None:
        if bid_ref != self._active_bid_ref:
            self.clear()
            self._active_bid_ref = bid_ref

    def can_undo(self) -> bool:
        return bool(
            not self._history_transition_pending
            and not self._forward_mutations
            and self._undo_stack
            and self._undo_stack[-1].bid_ref == self._active_bid_ref
            and self._undo_stack[-1].state == MutationHistoryState.READY
        )

    def can_redo(self) -> bool:
        return bool(
            not self._history_transition_pending
            and not self._forward_mutations
            and self._redo_stack
            and self._redo_stack[-1].bid_ref == self._active_bid_ref
            and self._redo_stack[-1].state == MutationHistoryState.READY
        )

    def push(
        self,
        undo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        redo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        *,
        takeoff_targets: tuple[TakeoffHistoryTarget, ...] = (),
    ) -> None:
        bid_ref = self._active_bid_ref
        if not bid_ref:
            return
        self._push_entry(bid_ref, undo_submit, redo_submit, takeoff_targets)

    def push_for_bid(
        self,
        bid_ref: BidRef,
        undo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        redo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        *,
        takeoff_targets: tuple[TakeoffHistoryTarget, ...] = (),
    ) -> None:
        if bid_ref != self._active_bid_ref:
            return
        self._push_entry(bid_ref, undo_submit, redo_submit, takeoff_targets)

    def _push_entry(
        self,
        bid_ref: BidRef,
        undo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        redo_submit: Callable[[Callable[[QueuedMutationResult], None]], None],
        takeoff_targets: tuple[TakeoffHistoryTarget, ...],
    ) -> None:
        self._undo_stack.append(
            MutationHistoryEntry(
                bid_ref,
                undo_submit,
                redo_submit,
                takeoff_targets=takeoff_targets,
            )
        )
        if len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._notify_change()

    def push_local(
        self,
        undo_action: Callable[[], bool],
        redo_action: Callable[[], bool],
        *,
        takeoff_targets: tuple[TakeoffHistoryTarget, ...] = (),
    ) -> None:
        def submit(
            action: Callable[[], bool],
            complete: Callable[[QueuedMutationResult], None],
        ) -> None:
            try:
                status = (
                    MutationOutcomeStatus.COMMITTED
                    if action()
                    else MutationOutcomeStatus.REJECTED
                )
                message = ""
            except Exception:
                self.logger.exception("Error during local history mutation")
                status = MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                message = "The local history mutation failed before completion."
            bid_ref = self._active_bid_ref
            complete(
                QueuedMutationResult(
                    database_id=bid_ref.file_path if bid_ref is not None else "local",
                    runtime_generation=0,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=status,
                    message=message,
                    commit_attempted=status == MutationOutcomeStatus.COMMITTED,
                )
            )

        self.push(
            lambda complete: submit(undo_action, complete),
            lambda complete: submit(redo_action, complete),
            takeoff_targets=takeoff_targets,
        )

    def suspend_deleted_takeoffs(
        self, bid_ref: BidRef, deleted: tuple[TakeoffHistoryTarget, ...]
    ) -> tuple[TakeoffHistoryTarget, ...]:
        if bid_ref != self._active_bid_ref:
            return ()
        identities = {
            (target.page_uid, target.uid)
            for target in deleted
            if target.available and target.bid_ref == bid_ref
        }
        candidates = [
            *deleted,
            *(
                target
                for entry in (*self._undo_stack, *self._redo_stack)
                if entry.bid_ref == bid_ref
                for target in entry.takeoff_targets
            ),
        ]
        suspended = []
        for target in candidates:
            if (
                target.available
                and target.bid_ref == bid_ref
                and (target.page_uid, target.uid) in identities
            ):
                target.available = False
                suspended.append(target)
        return tuple(suspended)

    def rebind_restored_takeoffs(
        self,
        bid_ref: BidRef,
        restored: dict[tuple[str, str], str],
        targets: tuple[TakeoffHistoryTarget, ...],
    ) -> None:
        if bid_ref != self._active_bid_ref:
            return
        retained = {
            id(target)
            for entry in (*self._undo_stack, *self._redo_stack)
            if entry.bid_ref == bid_ref
            for target in entry.takeoff_targets
        }
        replacements = [
            (target, restored[(target.page_uid, target.uid)])
            for target in targets
            if id(target) in retained and target.bid_ref == bid_ref
        ]
        for target, uid in replacements:
            target.uid = uid
            target.available = True

    def begin_forward_mutation(self, bid_ref: BidRef) -> Optional[ForwardMutationToken]:
        if bid_ref != self._active_bid_ref:
            return None
        token = ForwardMutationToken(
            token_id=str(uuid.uuid4()),
            bid_ref=bid_ref,
            history_generation=self._history_generation,
            sequence=self._next_forward_sequence,
        )
        self._next_forward_sequence += 1
        self._forward_mutations[token.token_id] = token
        self._notify_change()
        return token

    def bind_latest_history_to_forward_mutation(
        self, token: Optional[ForwardMutationToken]
    ) -> None:
        if not self.is_forward_mutation_current(token):
            return
        if not self._undo_stack:
            return
        entry = self._undo_stack[-1]
        if entry.bid_ref != token.bid_ref or entry.forward_sequence is not None:
            return
        self._undo_stack.pop()
        entry.forward_sequence = token.sequence
        insert_at = next(
            (
                index
                for index, existing in enumerate(self._undo_stack)
                if existing.forward_sequence is not None
                and existing.forward_sequence > token.sequence
            ),
            len(self._undo_stack),
        )
        self._undo_stack.insert(insert_at, entry)

    def is_forward_mutation_current(
        self, token: Optional[ForwardMutationToken]
    ) -> bool:
        return bool(
            token is not None
            and token.history_generation == self._history_generation
            and self._forward_mutations.get(token.token_id) == token
        )

    def finish_forward_mutation(self, token: Optional[ForwardMutationToken]) -> None:
        if token is None:
            return
        current = self._forward_mutations.get(token.token_id)
        if current != token:
            return
        self._forward_mutations.pop(token.token_id, None)
        self._notify_change()

    def undo(self) -> None:
        if self._forward_mutations or not self._undo_stack:
            return
        if self._is_write_allowed and not self._is_write_allowed():
            return
        entry = self._undo_stack[-1]
        if entry.bid_ref != self._active_bid_ref:
            self.clear()
            return
        self._submit_history_transition(
            entry,
            entry.undo_action,
            self._undo_stack,
            self._redo_stack,
            MutationHistoryState.UNDO_PENDING,
        )

    def redo(self) -> None:
        if self._forward_mutations or not self._redo_stack:
            return
        if self._is_write_allowed and not self._is_write_allowed():
            return
        entry = self._redo_stack[-1]
        if entry.bid_ref != self._active_bid_ref:
            self.clear()
            return
        self._submit_history_transition(
            entry,
            entry.redo_action,
            self._redo_stack,
            self._undo_stack,
            MutationHistoryState.REDO_PENDING,
        )

    def _submit_history_transition(
        self,
        entry: MutationHistoryEntry,
        operation: Callable[[Callable[[QueuedMutationResult], None]], None],
        source_stack: list[MutationHistoryEntry],
        destination_stack: list[MutationHistoryEntry],
        pending_state: MutationHistoryState,
    ) -> None:
        if (
            self._history_transition_pending
            or entry.state != MutationHistoryState.READY
        ):
            return
        entry.state = pending_state
        self._history_transition_pending = True
        history_generation = self._history_generation
        self._notify_change()

        def complete(outcome: QueuedMutationResult) -> None:
            if history_generation != self._history_generation:
                return
            status = outcome.outcome_status
            if status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                entry.state = MutationHistoryState.UNCERTAIN
                self._notify_change()
                return
            self._history_transition_pending = False
            if status == MutationOutcomeStatus.CONFLICT or outcome.conflict is not None:
                entry.state = MutationHistoryState.CONFLICTED
            elif status == MutationOutcomeStatus.COMMITTED:
                entry.state = MutationHistoryState.READY
                if source_stack and source_stack[-1] is entry:
                    source_stack.pop()
                    destination_stack.append(entry)
            else:
                entry.state = MutationHistoryState.READY
            self._notify_change()

        try:
            operation(complete)
        except Exception:
            self.logger.exception("Error while submitting history mutation")
            self._history_transition_pending = False
            entry.state = MutationHistoryState.READY
            self._notify_change()

    def clear(self) -> None:
        had_history = bool(
            self._undo_stack or self._redo_stack or self._forward_mutations
        )
        for entry in (*self._undo_stack, *self._redo_stack):
            for target in entry.takeoff_targets:
                target.available = False
        self._history_generation += 1
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._forward_mutations.clear()
        self._history_transition_pending = False
        if had_history:
            self._notify_change()

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change()
