import logging
from typing import Callable, Optional, Tuple
from ...domain.entities.identity_refs import BidRef


class UndoRedoService:
    def __init__(
        self, max_size: int = 50, logger: Optional[logging.Logger] = None
    ) -> None:
        self._undo_stack: list[Tuple[BidRef, Callable, Callable]] = []
        self._redo_stack: list[Tuple[BidRef, Callable, Callable]] = []
        self._max_size = max_size
        self._active_bid_ref: Optional[BidRef] = None
        self._is_write_allowed: Optional[Callable[[], bool]] = None
        self._on_change: Optional[Callable[[], None]] = None
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
            self._undo_stack and self._undo_stack[-1][0] == self._active_bid_ref
        )

    def can_redo(self) -> bool:
        return bool(
            self._redo_stack and self._redo_stack[-1][0] == self._active_bid_ref
        )

    def push(self, undo_fn: Callable, redo_fn: Callable) -> None:
        bid_ref = self._active_bid_ref
        if not bid_ref:
            return
        self._undo_stack.append((bid_ref, undo_fn, redo_fn))
        if len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._notify_change()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        if self._is_write_allowed and not self._is_write_allowed():
            return
        bid_ref, undo_fn, redo_fn = self._undo_stack[-1]
        if bid_ref != self._active_bid_ref:
            self.clear()
            return
        self._undo_stack.pop()
        self._redo_stack.append((bid_ref, undo_fn, redo_fn))
        try:
            undo_fn()
        except Exception:
            self.logger.exception("Error during undo")
        self._notify_change()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        if self._is_write_allowed and not self._is_write_allowed():
            return
        bid_ref, undo_fn, redo_fn = self._redo_stack[-1]
        if bid_ref != self._active_bid_ref:
            self.clear()
            return
        self._redo_stack.pop()
        self._undo_stack.append((bid_ref, undo_fn, redo_fn))
        try:
            redo_fn()
        except Exception:
            self.logger.exception("Error during redo")
        self._notify_change()

    def clear(self) -> None:
        had_history = bool(self._undo_stack or self._redo_stack)
        self._undo_stack.clear()
        self._redo_stack.clear()
        if had_history:
            self._notify_change()

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change()
