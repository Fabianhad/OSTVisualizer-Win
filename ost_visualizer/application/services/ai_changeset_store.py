import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterable, Optional, Tuple
from ..dtos.ai_changeset_write_dtos import AppliedChangeset
from ...domain.entities.ai_changeset import (
    ASSUMPTION_ACCEPTED,
    ASSUMPTION_OPEN,
    ASSUMPTION_OVERRIDDEN,
    ASSUMPTION_SUBJECTS,
    ERROR_APPROVAL_REQUIRED,
    ERROR_CHANGESET_NOT_FOUND,
    ERROR_CHANGESET_TOO_LARGE,
    ERROR_INVALID_STATE,
    ERROR_STALE_CHANGESET,
    KIND_SCALE,
    MAX_OPEN_CHANGESETS_PER_BID,
    STATUS_APPLIED,
    STATUS_APPLYING,
    STATUS_DISCARDED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_UNDONE,
    SUBJECT_CLOSING_SEGMENT,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    assumption_impact,
)

TokenReader = Callable[[str, str, Tuple[str, ...]], Dict[str, str]]
MAX_CLOSED_CHANGESETS = 100
ERROR_CHANGED_DURING_REVIEW = "changed_during_review"
_PRUNABLE_STATUSES = (
    STATUS_DISCARDED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_UNDONE,
)


class AiChangesetStore:
    def __init__(
        self,
        clock: Optional[Callable[[], float]] = None,
        token_reader: Optional[TokenReader] = None,
        uid_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    ):
        self._clock = clock or (lambda: time.monotonic())
        self._token_reader = token_reader or (
            lambda _database_id, _bid_uid, resources: {}
        )
        self._uid_factory = uid_factory
        self._lock = threading.RLock()
        self._changesets: Dict[str, AiChangeset] = {}
        self._applied: Dict[str, AppliedChangeset] = {}
        self._applied_order: list = []
        self._closed_order: Dict[str, None] = {}

    def add(self, changeset: AiChangeset) -> AiChangeset:
        changeset.validate_caps()
        for takeoff in changeset.takeoffs:
            takeoff.validate()
        with self._lock:
            if len(self.open_for_bid(changeset.database_id, changeset.bid_uid)) >= (
                MAX_OPEN_CHANGESETS_PER_BID
            ):
                raise ChangesetError(
                    ERROR_CHANGESET_TOO_LARGE,
                    f"At most {MAX_OPEN_CHANGESETS_PER_BID} changesets can be open per bid. "
                    "Discard or apply one first.",
                )
            resources = changeset.touched_resources
            tokens = self._token_reader(
                changeset.database_id, changeset.bid_uid, resources
            )
            stored = replace(
                changeset,
                uid=self._uid_factory(),
                created_at=float(self._clock()),
                status=STATUS_PROPOSED,
                base_tokens=tuple(
                    (resource, str(tokens.get(resource, ""))) for resource in resources
                ),
            )
            self._changesets[stored.uid] = stored
            return stored

    def get(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._changesets.get(str(uid))
            if changeset is None:
                raise ChangesetError(ERROR_CHANGESET_NOT_FOUND, "Unknown changeset_id")
            if (
                changeset.is_open
                and changeset.status != STATUS_APPLYING
                and changeset.is_expired(self._clock())
            ):
                changeset = self._put(replace(changeset, status=STATUS_EXPIRED))
            return changeset

    def open_for_bid(self, database_id: str, bid_uid: str) -> Tuple[AiChangeset, ...]:
        with self._lock:
            matches = [
                self.get(uid)
                for uid, changeset in list(self._changesets.items())
                if changeset.is_open
                and changeset.database_id == database_id
                and changeset.bid_uid == str(bid_uid)
            ]
            return tuple(item for item in matches if item.is_open)

    def discard(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            return self._put(replace(changeset, status=STATUS_DISCARDED))

    def request_apply(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            self._ensure_fresh(changeset)
            if changeset.status == STATUS_PENDING_APPROVAL:
                return changeset
            return self._put(replace(changeset, status=STATUS_PENDING_APPROVAL))

    def approve(self, uid: str, expected_revision: Optional[int] = None) -> AiChangeset:
        with self._lock:
            changeset = self.get(uid)
            if changeset.status != STATUS_PENDING_APPROVAL:
                if changeset.status == STATUS_PROPOSED:
                    raise ChangesetError(
                        ERROR_APPROVAL_REQUIRED,
                        "The AI has not asked to apply this changeset",
                    )
                self._raise_closed(changeset)
            self._require_revision(changeset, expected_revision)
            self._ensure_fresh(changeset)
            if changeset.kind == KIND_SCALE:
                changeset.resolved_scale()
            else:
                changeset.resolved_conditions()
            return self._put(replace(changeset, status=STATUS_APPLYING))

    def reject(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            return self._put(replace(changeset, status=STATUS_REJECTED))

    def mark_applied(self, uid: str, record: AppliedChangeset) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(uid, (STATUS_APPLYING,))
            self._applied[changeset.uid] = record
            self._applied_order.append(changeset.uid)
            return self._put(replace(changeset, status=STATUS_APPLIED))

    def mark_failed(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(uid, (STATUS_APPLYING,))
            return self._put(replace(changeset, status=STATUS_FAILED))

    def mark_undone(self, uid: str) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(uid, (STATUS_APPLIED,))
            if changeset.uid in self._applied_order:
                self._applied_order.remove(changeset.uid)
            return self._put(replace(changeset, status=STATUS_UNDONE))

    def last_applied(self, database_id: str, bid_uid: str) -> Optional[AiChangeset]:
        with self._lock:
            for uid in reversed(self._applied_order):
                changeset = self._changesets[uid]
                if changeset.database_id == database_id and changeset.bid_uid == str(
                    bid_uid
                ):
                    return changeset
            return None

    def applied_record(self, uid: str) -> Optional[AppliedChangeset]:
        with self._lock:
            return self._applied.get(str(uid))

    def accept_assumption(
        self, uid: str, assumption_uid: str, expected_revision: Optional[int] = None
    ) -> AiChangeset:
        return self._set_assumption(
            uid, assumption_uid, ASSUMPTION_ACCEPTED, None, expected_revision
        )

    def override_assumption(
        self,
        uid: str,
        assumption_uid: str,
        value: str,
        expected_revision: Optional[int] = None,
    ) -> AiChangeset:
        return self._set_assumption(
            uid, assumption_uid, ASSUMPTION_OVERRIDDEN, str(value), expected_revision
        )

    def add_assumption(
        self,
        uid: str,
        subject: str,
        target_key: str,
        value: str,
        reason: str,
        sheet_ref: str,
        closing_length_in: Optional[float] = None,
    ) -> AiChangeset:
        if subject not in ASSUMPTION_SUBJECTS:
            raise ChangesetError(ERROR_INVALID_STATE, "Unknown assumption subject")
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            assumption = ChangesetAssumption(
                uid=f"a{len(changeset.assumptions) + 1}",
                subject=subject,
                target_key=str(target_key),
                value=str(value),
                reason=str(reason),
                sheet_ref=str(sheet_ref),
                impact=assumption_impact(
                    subject,
                    closing_length_in if subject == SUBJECT_CLOSING_SEGMENT else None,
                ),
            )
            return self._put(
                replace(
                    changeset,
                    assumptions=changeset.assumptions + (assumption,),
                    revision=changeset.revision + 1,
                )
            )

    def revise_assumption(
        self, uid: str, assumption_uid: str, value: str, reason: str
    ) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            self._require_assumption(changeset, assumption_uid)
            assumptions = tuple(
                (
                    replace(
                        item,
                        value=str(value),
                        reason=str(reason),
                        status=ASSUMPTION_OPEN,
                        override_value=None,
                    )
                    if item.uid == assumption_uid
                    else item
                )
                for item in changeset.assumptions
            )
            return self._put(
                replace(
                    changeset, assumptions=assumptions, revision=changeset.revision + 1
                )
            )

    def _set_assumption(
        self,
        uid: str,
        assumption_uid: str,
        status: str,
        override_value: Optional[str],
        expected_revision: Optional[int] = None,
    ) -> AiChangeset:
        with self._lock:
            changeset = self._require_status(
                uid, (STATUS_PROPOSED, STATUS_PENDING_APPROVAL)
            )
            self._require_revision(changeset, expected_revision)
            self._require_assumption(changeset, assumption_uid)
            assumptions = tuple(
                (
                    replace(item, status=status, override_value=override_value)
                    if item.uid == assumption_uid
                    else item
                )
                for item in changeset.assumptions
            )
            return self._put(
                replace(
                    changeset, assumptions=assumptions, revision=changeset.revision + 1
                )
            )

    @staticmethod
    def _require_revision(
        changeset: AiChangeset, expected_revision: Optional[int]
    ) -> None:
        if expected_revision is not None and expected_revision != changeset.revision:
            raise ChangesetError(
                ERROR_CHANGED_DURING_REVIEW,
                "The AI changed this changeset while you were reviewing it. Check it again.",
            )

    @staticmethod
    def _require_assumption(changeset: AiChangeset, assumption_uid: str) -> None:
        if not any(item.uid == assumption_uid for item in changeset.assumptions):
            raise ChangesetError(ERROR_CHANGESET_NOT_FOUND, "Unknown assumption_id")

    def _require_status(self, uid: str, statuses: Iterable[str]) -> AiChangeset:
        changeset = self.get(uid)
        if changeset.status not in tuple(statuses):
            self._raise_closed(changeset)
        return changeset

    @staticmethod
    def _raise_closed(changeset: AiChangeset) -> None:
        if changeset.status in (STATUS_EXPIRED, STATUS_STALE):
            raise ChangesetError(
                ERROR_STALE_CHANGESET,
                "The changeset expired or the objects it touches changed. Propose it again.",
            )
        raise ChangesetError(
            ERROR_INVALID_STATE,
            f"The changeset is {changeset.status} and cannot do that",
        )

    def _current_tokens(self, changeset: AiChangeset) -> Dict[str, str]:
        resources = tuple(resource for resource, _token in changeset.base_tokens)
        tokens = self._token_reader(changeset.database_id, changeset.bid_uid, resources)
        return {resource: str(tokens.get(resource, "")) for resource in resources}

    def _ensure_fresh(self, changeset: AiChangeset) -> None:
        if self._current_tokens(changeset) != dict(changeset.base_tokens):
            self._put(replace(changeset, status=STATUS_STALE))
            raise ChangesetError(
                ERROR_STALE_CHANGESET,
                "A page or condition this changeset touches changed. Propose it again.",
            )

    def _put(self, changeset: AiChangeset) -> AiChangeset:
        self._changesets[changeset.uid] = changeset
        if changeset.status in _PRUNABLE_STATUSES:
            self._closed_order[changeset.uid] = None
            while len(self._closed_order) > MAX_CLOSED_CHANGESETS:
                oldest = next(iter(self._closed_order))
                del self._closed_order[oldest]
                self._changesets.pop(oldest, None)
                self._applied.pop(oldest, None)
        return changeset


class AiChangesetProposals:
    def __init__(self, store: AiChangesetStore):
        self._store = store

    def add(self, changeset: AiChangeset) -> AiChangeset:
        return self._store.add(changeset)

    def get(self, uid: str) -> AiChangeset:
        return self._store.get(uid)

    def discard(self, uid: str) -> AiChangeset:
        return self._store.discard(uid)

    def request_apply(self, uid: str) -> AiChangeset:
        return self._store.request_apply(uid)

    def add_assumption(
        self,
        uid: str,
        subject: str,
        target_key: str,
        value: str,
        reason: str,
        sheet_ref: str,
        closing_length_in: Optional[float] = None,
    ) -> AiChangeset:
        return self._store.add_assumption(
            uid, subject, target_key, value, reason, sheet_ref, closing_length_in
        )

    def revise_assumption(
        self, uid: str, assumption_uid: str, value: str, reason: str
    ) -> AiChangeset:
        return self._store.revise_assumption(uid, assumption_uid, value, reason)

    def last_applied(self, database_id: str, bid_uid: str) -> Optional[AiChangeset]:
        return self._store.last_applied(database_id, bid_uid)

    def applied_record(self, uid: str) -> Optional[AppliedChangeset]:
        return self._store.applied_record(uid)
