import threading
import time
import unittest
import uuid
from dataclasses import replace
from unittest.mock import patch
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.services.ai_changeset_store import (
    MAX_CLOSED_CHANGESETS,
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.domain.entities.ai_changeset import (
    ASSUMPTION_ACCEPTED,
    ASSUMPTION_OPEN,
    ASSUMPTION_OVERRIDDEN,
    IMPACT_HIGH,
    IMPACT_NORMAL,
    KIND_ELEMENTS,
    KIND_SCALE,
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
    SUBJECT_OTHER,
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
)

SQUARE = (0.0, 0.0, 480.0, 0.0, 480.0, 360.0, 0.0, 360.0)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Tokens:
    def __init__(self):
        self.values = {}
        self.calls = []

    def __call__(self, database_id, bid_uid, resources):
        self.calls.append((database_id, bid_uid, tuple(resources)))
        return {resource: self.values.get(resource, "v0") for resource in resources}


def _changeset(bid_uid="7", page_uid="page-1", assumptions=(), thickness=8.0):
    return AiChangeset(
        uid="",
        database_id="C:/jobs/a.mdb",
        bid_uid=bid_uid,
        bid_key="a" * 32,
        kind=KIND_ELEMENTS,
        created_at=0.0,
        conditions=(ProposedCondition("c1", "Slab", thickness, 1200.0),),
        takeoffs=(ProposedTakeoff("t1", page_uid, "c1", SQUARE),),
        assumptions=assumptions,
    )


def _assumption(uid, subject=SUBJECT_THICKNESS, impact=IMPACT_HIGH):
    return ChangesetAssumption(uid, subject, "c1", "8", "not shown", "S-101", impact)


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.tokens = Tokens()
        self.counter = iter(range(1, 1000))
        self.store = AiChangesetStore(
            clock=self.clock,
            token_reader=self.tokens,
            uid_factory=lambda: f"cs-{next(self.counter)}",
        )
        self.proposals = AiChangesetProposals(self.store)

    def add(self, changeset=None):
        return self.proposals.add(changeset or _changeset())


class ProposalTests(StoreTestCase):
    def test_add_assigns_an_id_the_clock_and_the_touched_base_tokens(self):
        self.tokens.values["page:page-1"] = "v7"
        added = self.add()
        self.assertEqual(added.uid, "cs-1")
        self.assertEqual(added.created_at, 1000.0)
        self.assertEqual(added.status, STATUS_PROPOSED)
        self.assertEqual(added.base_tokens, (("page:page-1", "v7"),))
        self.assertEqual(self.tokens.calls, [("C:/jobs/a.mdb", "7", ("page:page-1",))])

    def test_caps_are_checked_before_storing(self):
        too_many = AiChangeset(
            uid="",
            database_id="C:/jobs/a.mdb",
            bid_uid="7",
            bid_key="a" * 32,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            takeoffs=tuple(
                ProposedTakeoff(f"t{index}", "page-1", "existing:1", SQUARE)
                for index in range(201)
            ),
        )
        with self.assertRaises(ChangesetError) as raised:
            self.add(too_many)
        self.assertEqual(raised.exception.code, "changeset_too_large")
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())

    def test_at_most_five_open_changesets_per_bid(self):
        for _ in range(5):
            self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.add()
        self.assertEqual(raised.exception.code, "changeset_too_large")
        self.add(_changeset(bid_uid="8"))
        self.proposals.discard("cs-1")
        self.assertEqual(self.add().uid, "cs-7")

    def test_changesets_expire_thirty_minutes_after_proposal(self):
        added = self.add()
        self.clock.now = 1000.0 + 1799.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_PROPOSED)
        self.clock.now = 1000.0 + 1800.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_EXPIRED)
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.request_apply(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())

    def test_the_default_ids_are_twelve_hex_characters(self):
        store = AiChangesetStore(clock=self.clock)
        first = store.add(_changeset())
        second = store.add(_changeset())
        self.assertRegex(first.uid, r"\A[0-9a-f]{12}\Z")
        self.assertNotEqual(first.uid, second.uid)

    def test_invalid_takeoff_geometry_is_refused_before_storing(self):
        flat = _changeset()
        flat = AiChangeset(
            uid="",
            database_id=flat.database_id,
            bid_uid=flat.bid_uid,
            bid_key=flat.bid_key,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            conditions=flat.conditions,
            takeoffs=(ProposedTakeoff("t1", "page-1", "c1", (0.0, 0.0, 10.0, 0.0)),),
        )
        with self.assertRaises(ChangesetError) as raised:
            self.add(flat)
        self.assertEqual(raised.exception.code, "invalid_geometry")
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())
        self.assertEqual(self.tokens.calls, [])

    def test_expired_and_closed_changesets_free_an_open_slot(self):
        for _ in range(5):
            self.add()
        self.clock.now = 1000.0 + 1800.0
        self.assertEqual(self.add().uid, "cs-6")
        for _ in range(4):
            self.add()
        with self.assertRaises(ChangesetError):
            self.add()
        self.proposals.request_apply("cs-6")
        self.store.approve("cs-6")
        with self.assertRaises(ChangesetError) as raised:
            self.add()
        self.assertEqual(raised.exception.code, "changeset_too_large")
        self.store.mark_failed("cs-6")
        self.assertEqual(self.add().uid, "cs-11")

    def test_unknown_ids_are_not_found(self):
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.get("missing")
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(raised.exception.message, "Unknown changeset_id")

    def test_discard_closes_an_open_changeset_only(self):
        added = self.add()
        self.assertEqual(self.proposals.discard(added.uid).status, STATUS_DISCARDED)
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.discard(added.uid)
        self.assertEqual(raised.exception.code, "invalid_state")


class FreshnessTests(StoreTestCase):
    def test_apply_request_waits_for_approval(self):
        added = self.add()
        requested = self.proposals.request_apply(added.uid)
        self.assertEqual(requested.status, STATUS_PENDING_APPROVAL)
        again = self.proposals.request_apply(added.uid)
        self.assertIs(again, requested)
        self.assertIs(self.proposals.get(added.uid), requested)

    def test_only_touched_objects_make_a_changeset_stale(self):
        added = self.add()
        self.tokens.values["page:page-2"] = "changed"
        self.tokens.values["condition:99"] = "changed"
        self.assertEqual(
            self.proposals.request_apply(added.uid).status, STATUS_PENDING_APPROVAL
        )
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(
            raised.exception.message,
            "A page or condition this changeset touches changed. Propose it again.",
        )
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_STALE)

    def test_an_apply_request_on_a_touched_change_is_stale(self):
        added = self.add()
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.request_apply(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_STALE)


class ApprovalTests(StoreTestCase):
    def test_high_impact_open_assumptions_block_approval(self):
        added = self.add(
            _changeset(
                assumptions=(
                    _assumption("a1"),
                    _assumption("a2", SUBJECT_OTHER, IMPACT_NORMAL),
                ),
                thickness=None,
            )
        )
        self.proposals.request_apply(added.uid)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "assumption_unresolved")
        self.store.override_assumption(added.uid, "a1", "10")
        approved = self.store.approve(added.uid)
        self.assertEqual(approved.status, STATUS_APPLYING)
        self.assertEqual(approved.resolved_conditions()[0].thickness_in, 10.0)
        statuses = {item.uid: item.status for item in approved.assumptions}
        self.assertEqual(statuses, {"a1": ASSUMPTION_OVERRIDDEN, "a2": ASSUMPTION_OPEN})

    def test_approving_a_stale_revision_is_refused_and_changes_nothing(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        self.proposals.request_apply(added.uid)
        shown = self.proposals.get(added.uid).revision
        self.proposals.revise_assumption(added.uid, "a1", "9", "note")
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid, expected_revision=shown)
        self.assertEqual(raised.exception.code, "changed_during_review")
        self.assertEqual(
            raised.exception.message,
            "The AI changed this changeset while you were reviewing it. Check it again.",
        )
        current = self.proposals.get(added.uid)
        self.assertEqual(current.status, STATUS_PENDING_APPROVAL)
        self.assertEqual(current.revision, shown + 1)
        accepted = self.store.accept_assumption(
            added.uid, "a1", expected_revision=shown + 1
        )
        approved = self.store.approve(added.uid, expected_revision=accepted.revision)
        self.assertEqual(approved.status, STATUS_APPLYING)

    def test_an_expired_apply_request_cannot_be_approved(self):
        added = self.add()
        self.proposals.request_apply(added.uid)
        self.clock.now = 1000.0 + 1800.0
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(
            raised.exception.message,
            "The changeset expired or the objects it touches changed. Propose it again.",
        )
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_EXPIRED)

    def test_closed_changesets_cannot_be_approved(self):
        added = self.add()
        self.proposals.discard(added.uid)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "invalid_state")
        self.assertEqual(
            raised.exception.message, "The changeset is discarded and cannot do that"
        )

    def scale_changeset(self, scale, assumptions=()):
        return AiChangeset(
            uid="",
            database_id="C:/jobs/a.mdb",
            bid_uid="7",
            bid_key="a" * 32,
            kind=KIND_SCALE,
            created_at=0.0,
            scale=scale,
            assumptions=assumptions,
        )

    def test_scale_approval_needs_a_resolved_scale(self):
        scale = ProposedScale("page-1", 0.25, 12.0, 0.125, 12.0)
        blocked = self.add(
            self.scale_changeset(
                scale,
                (
                    ChangesetAssumption(
                        "a1", SUBJECT_SCALE, "page-1", "1/4", "x", "S-1", IMPACT_HIGH
                    ),
                ),
            )
        )
        self.proposals.request_apply(blocked.uid)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(blocked.uid)
        self.assertEqual(raised.exception.code, "assumption_unresolved")
        self.assertEqual(
            self.proposals.get(blocked.uid).status, STATUS_PENDING_APPROVAL
        )
        self.store.accept_assumption(blocked.uid, "a1")
        self.assertEqual(self.store.approve(blocked.uid).status, STATUS_APPLYING)
        missing = self.add(self.scale_changeset(None))
        self.proposals.request_apply(missing.uid)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(missing.uid)
        self.assertEqual(raised.exception.code, "invalid_state")
        self.assertEqual(
            self.proposals.get(missing.uid).status, STATUS_PENDING_APPROVAL
        )

    def test_approval_requires_an_apply_request_first(self):
        added = self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid)
        self.assertEqual(raised.exception.code, "approval_required")
        self.assertEqual(
            raised.exception.message, "The AI has not asked to apply this changeset"
        )

    def test_accept_and_reject(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        self.store.accept_assumption(added.uid, "a1")
        self.assertEqual(
            self.proposals.get(added.uid).assumptions[0].status, ASSUMPTION_ACCEPTED
        )
        self.proposals.request_apply(added.uid)
        self.assertEqual(self.store.reject(added.uid).status, STATUS_REJECTED)
        with self.assertRaises(ChangesetError):
            self.store.approve(added.uid)

    def test_applied_and_undone_are_recorded_per_bid(self):
        first = self.add()
        second = self.add()
        record = AppliedChangeset(
            folder_uid="F1",
            created_folder=True,
            condition_uids=("C1",),
            takeoff_uids=("T1",),
        )
        for changeset in (first, second):
            self.proposals.request_apply(changeset.uid)
            self.store.approve(changeset.uid)
            self.store.mark_applied(changeset.uid, record)
        self.assertEqual(self.proposals.get(second.uid).status, STATUS_APPLIED)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", "7").uid, second.uid)
        self.assertEqual(self.store.applied_record(second.uid), record)
        self.store.mark_undone(second.uid)
        self.assertEqual(self.proposals.get(second.uid).status, STATUS_UNDONE)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", "7").uid, first.uid)
        self.assertEqual(self.proposals.applied_record(second.uid), record)
        self.assertIsNone(self.proposals.applied_record("cs-99"))

    def apply(self, changeset):
        added = self.add(changeset)
        self.proposals.request_apply(added.uid)
        self.store.approve(added.uid)
        self.store.mark_applied(added.uid, AppliedChangeset(takeoff_uids=("T1",)))
        return added

    def test_last_applied_matches_both_the_database_and_the_bid(self):
        self.assertIsNone(self.store.last_applied("C:/jobs/a.mdb", "7"))
        mine = self.apply(_changeset())
        self.apply(_changeset(bid_uid="8"))
        other_database = _changeset()
        other_database = AiChangeset(
            uid="",
            database_id="C:/jobs/b.mdb",
            bid_uid="7",
            bid_key="b" * 32,
            kind=KIND_ELEMENTS,
            created_at=0.0,
            conditions=other_database.conditions,
            takeoffs=other_database.takeoffs,
        )
        theirs = self.apply(other_database)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", "7").uid, mine.uid)
        self.assertEqual(self.store.last_applied("C:/jobs/a.mdb", 8).uid, "cs-2")
        self.assertEqual(self.store.last_applied("C:/jobs/b.mdb", "7").uid, theirs.uid)
        self.assertIsNone(self.store.last_applied("C:/jobs/a.mdb", "9"))
        self.assertIsNone(self.proposals.last_applied("C:/jobs/c.mdb", "7"))


class AssumptionEditTests(StoreTestCase):
    def test_unknown_subjects_are_refused(self):
        added = self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.add_assumption(added.uid, "colour", "c1", "red", "x", "S-1")
        self.assertEqual(raised.exception.code, "invalid_state")
        self.assertEqual(raised.exception.message, "Unknown assumption subject")
        self.assertEqual(self.proposals.get(added.uid).assumptions, ())
        self.assertEqual(self.proposals.get(added.uid).revision, 0)

    def test_unknown_assumption_ids_are_not_found_and_change_nothing(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        actions = {
            "revise": lambda: self.proposals.revise_assumption(
                added.uid, "a9", "9", "x"
            ),
            "accept": lambda: self.store.accept_assumption(added.uid, "a9"),
            "override": lambda: self.store.override_assumption(added.uid, "a9", "9"),
        }
        for name, action in actions.items():
            with self.subTest(action=name):
                with self.assertRaises(ChangesetError) as raised:
                    action()
                self.assertEqual(raised.exception.code, "not_found")
                self.assertEqual(raised.exception.message, "Unknown assumption_id")
                current = self.proposals.get(added.uid)
                self.assertEqual(current.revision, 0)
                self.assertEqual(current.assumptions, (_assumption("a1"),))

    def test_every_assumption_edit_bumps_the_revision_by_one(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        steps = (
            lambda: self.proposals.add_assumption(
                added.uid, SUBJECT_OTHER, "c1", "flat", "ramp", "S-102"
            ),
            lambda: self.proposals.revise_assumption(added.uid, "a1", "9", "note"),
            lambda: self.store.accept_assumption(added.uid, "a1", expected_revision=2),
            lambda: self.store.override_assumption(
                added.uid, "a2", "sloped", expected_revision=3
            ),
        )
        for expected, step in enumerate(steps, start=1):
            self.assertEqual(step().revision, expected)
        with self.assertRaises(ChangesetError) as raised:
            self.store.accept_assumption(added.uid, "a1", expected_revision=3)
        self.assertEqual(raised.exception.code, "changed_during_review")

    def test_only_closing_segment_assumptions_use_the_closing_length(self):
        added = self.add()
        cases = (
            (SUBJECT_CLOSING_SEGMENT, 20.0, IMPACT_HIGH),
            (SUBJECT_CLOSING_SEGMENT, 6.0, IMPACT_NORMAL),
            (SUBJECT_CLOSING_SEGMENT, None, IMPACT_NORMAL),
            (SUBJECT_OTHER, 20.0, IMPACT_NORMAL),
            (SUBJECT_THICKNESS, 6.0, IMPACT_HIGH),
        )
        for index, (subject, length, impact) in enumerate(cases, start=1):
            with self.subTest(subject=subject, length=length):
                changeset = self.proposals.add_assumption(
                    added.uid, subject, "c1", "v", "r", "S-1", closing_length_in=length
                )
                self.assertEqual(changeset.assumptions[-1].uid, f"a{index}")
                self.assertEqual(changeset.assumptions[-1].impact, impact)


class ProposalFacadeTests(StoreTestCase):
    def test_the_facade_offers_no_way_to_approve_or_accept(self):
        public = {name for name in dir(self.proposals) if not name.startswith("_")}
        self.assertEqual(
            public,
            {
                "add",
                "get",
                "discard",
                "request_apply",
                "add_assumption",
                "revise_assumption",
                "last_applied",
                "applied_record",
            },
        )

    def test_assumption_updates_never_change_status(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        added_more = self.proposals.add_assumption(
            added.uid, SUBJECT_OTHER, "c1", "flat", "ramp not shown", "S-102"
        )
        self.assertEqual(
            [(item.uid, item.status) for item in added_more.assumptions],
            [("a1", ASSUMPTION_OPEN), ("a2", ASSUMPTION_OPEN)],
        )
        revised = self.proposals.revise_assumption(
            added.uid, "a1", "9", "per S-101 note"
        )
        first = revised.assumptions[0]
        self.assertEqual(
            (first.value, first.reason, first.status),
            ("9", "per S-101 note", ASSUMPTION_OPEN),
        )
        self.store.accept_assumption(added.uid, "a1")
        reopened = self.proposals.revise_assumption(added.uid, "a1", "10", "changed")
        self.assertEqual(reopened.assumptions[0].status, ASSUMPTION_OPEN)


class RetentionTests(unittest.TestCase):
    def test_closed_changesets_do_not_accumulate(self):
        store = AiChangesetStore(clock=lambda: 100.0)
        proposals = AiChangesetProposals(store)
        first = proposals.add(_changeset())
        proposals.discard(first.uid)
        kept = proposals.add(_changeset())
        proposals.request_apply(kept.uid)
        store.approve(kept.uid)
        store.mark_applied(kept.uid, AppliedChangeset(takeoff_uids=("T1",)))
        last = None
        for _index in range(1000):
            last = proposals.add(_changeset())
            proposals.discard(last.uid)
        with self.assertRaises(ChangesetError) as raised:
            proposals.get(first.uid)
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(proposals.get(last.uid).status, "discarded")
        self.assertEqual(proposals.get(kept.uid).status, "applied")
        self.assertEqual(proposals.last_applied("C:/jobs/a.mdb", "7").uid, kept.uid)


class ClosedPruningTests(StoreTestCase):
    def close_one(self):
        self.proposals.discard(self.add().uid)

    def test_the_oldest_closed_changesets_beyond_the_cap_are_dropped_with_records(self):
        self.assertEqual(MAX_CLOSED_CHANGESETS, 100)
        record = AppliedChangeset(takeoff_uids=("T1",))
        undone = self.add()
        self.proposals.request_apply(undone.uid)
        self.store.approve(undone.uid)
        self.store.mark_applied(undone.uid, record)
        self.store.mark_undone(undone.uid)
        failed = self.add()
        self.proposals.request_apply(failed.uid)
        self.store.approve(failed.uid)
        self.store.mark_failed(failed.uid)
        for _ in range(MAX_CLOSED_CHANGESETS - 2):
            self.close_one()
        self.assertEqual(self.proposals.get(undone.uid).status, STATUS_UNDONE)
        self.assertEqual(self.proposals.applied_record(undone.uid), record)
        self.assertEqual(self.proposals.get(failed.uid).status, STATUS_FAILED)
        self.close_one()
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.get(undone.uid)
        self.assertEqual(raised.exception.code, "not_found")
        self.assertIsNone(self.proposals.applied_record(undone.uid))
        self.assertEqual(self.proposals.get(failed.uid).status, STATUS_FAILED)
        self.close_one()
        with self.assertRaises(ChangesetError):
            self.proposals.get(failed.uid)


class MonotonicExpiryTests(unittest.TestCase):
    def test_expiry_follows_the_monotonic_clock_not_the_wall_clock(self):
        with patch.object(time, "monotonic", return_value=1000.0), patch.object(
            time, "time", return_value=5_000_000.0
        ):
            store = AiChangesetStore()
            proposals = AiChangesetProposals(store)
            added = proposals.add(_changeset())
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1799.0
        ), patch.object(time, "time", return_value=5_000_000.0 + 7200.0):
            self.assertEqual(proposals.get(added.uid).status, "proposed")
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1799.0
        ), patch.object(time, "time", return_value=5_000_000.0 - 7200.0):
            self.assertEqual(proposals.get(added.uid).status, "proposed")
        with patch.object(
            time, "monotonic", return_value=1000.0 + 1800.0
        ), patch.object(time, "time", return_value=5_000_000.0):
            self.assertEqual(proposals.get(added.uid).status, "expired")


class StateMachineTests(StoreTestCase):
    STALE_MESSAGE = (
        "The changeset expired or the objects it touches changed. Propose it again."
    )
    ALL_STATES = (
        STATUS_PROPOSED,
        STATUS_PENDING_APPROVAL,
        STATUS_APPLYING,
        STATUS_APPLIED,
        STATUS_FAILED,
        STATUS_UNDONE,
        STATUS_DISCARDED,
        STATUS_REJECTED,
        STATUS_EXPIRED,
        STATUS_STALE,
    )

    def at_state(self, state):
        added = self.add(
            _changeset(assumptions=(_assumption("a1", SUBJECT_OTHER, IMPACT_NORMAL),))
        )
        uid = added.uid
        if state == STATUS_PROPOSED:
            return uid
        if state == STATUS_DISCARDED:
            self.proposals.discard(uid)
            return uid
        if state == STATUS_EXPIRED:
            self.clock.now += 1800.0
            self.assertEqual(self.store.get(uid).status, STATUS_EXPIRED)
            return uid
        if state == STATUS_STALE:
            self.tokens.values["page:page-1"] = "changed"
            with self.assertRaises(ChangesetError):
                self.proposals.request_apply(uid)
            self.assertEqual(self.store.get(uid).status, STATUS_STALE)
            return uid
        self.proposals.request_apply(uid)
        if state == STATUS_PENDING_APPROVAL:
            return uid
        if state == STATUS_REJECTED:
            self.store.reject(uid)
            return uid
        self.store.approve(uid)
        if state == STATUS_APPLYING:
            return uid
        if state == STATUS_FAILED:
            self.store.mark_failed(uid)
            return uid
        self.store.mark_applied(uid, AppliedChangeset(takeoff_uids=("T1",)))
        if state == STATUS_APPLIED:
            return uid
        self.assertEqual(state, STATUS_UNDONE)
        self.store.mark_undone(uid)
        return uid

    def assert_refused(self, state, action):
        uid = self.at_state(state)
        self.assertEqual(self.store.get(uid).status, state)
        before = self.store.get(uid)
        record_before = self.store.applied_record(uid)
        with self.assertRaises(ChangesetError) as raised:
            action(uid)
        if state in (STATUS_EXPIRED, STATUS_STALE):
            self.assertEqual(raised.exception.code, "stale_changeset")
            self.assertEqual(raised.exception.message, self.STALE_MESSAGE)
        else:
            self.assertEqual(raised.exception.code, "invalid_state")
            self.assertEqual(
                raised.exception.message,
                f"The changeset is {state} and cannot do that",
            )
        self.assertEqual(self.store.get(uid), before)
        self.assertEqual(self.store.applied_record(uid), record_before)
        self.assertEqual(
            self.store.last_applied("C:/jobs/a.mdb", "7") is not None,
            state == STATUS_APPLIED,
        )

    def review_actions(self):
        return {
            "discard": lambda uid: self.store.discard(uid),
            "reject": lambda uid: self.store.reject(uid),
            "request_apply": lambda uid: self.proposals.request_apply(uid),
            "add_assumption": lambda uid: self.proposals.add_assumption(
                uid, SUBJECT_OTHER, "c1", "flat", "ramp", "S-102"
            ),
            "revise_assumption": lambda uid: self.proposals.revise_assumption(
                uid, "a1", "9", "note"
            ),
            "accept_assumption": lambda uid: self.store.accept_assumption(uid, "a1"),
            "override_assumption": lambda uid: self.store.override_assumption(
                uid, "a1", "9"
            ),
        }

    def test_review_operations_are_refused_on_every_changeset_that_is_not_open_for_review(
        self,
    ):
        closed = (
            STATUS_APPLYING,
            STATUS_APPLIED,
            STATUS_FAILED,
            STATUS_UNDONE,
            STATUS_DISCARDED,
            STATUS_REJECTED,
            STATUS_EXPIRED,
            STATUS_STALE,
        )
        for name, action in self.review_actions().items():
            for state in closed:
                with self.subTest(action=name, state=state):
                    self.setUp()
                    self.assert_refused(state, action)

    def test_approval_is_refused_on_every_state_but_a_pending_one(self):
        for state in self.ALL_STATES:
            if state in (STATUS_PENDING_APPROVAL, STATUS_PROPOSED):
                continue
            with self.subTest(state=state):
                self.setUp()
                self.assert_refused(state, lambda uid: self.store.approve(uid))

    def test_completion_marks_are_only_accepted_in_their_own_state(self):
        marks = {
            "mark_applied": (
                lambda uid: self.store.mark_applied(
                    uid, AppliedChangeset(takeoff_uids=("T9",))
                ),
                STATUS_APPLYING,
            ),
            "mark_failed": (lambda uid: self.store.mark_failed(uid), STATUS_APPLYING),
            "mark_undone": (lambda uid: self.store.mark_undone(uid), STATUS_APPLIED),
        }
        for name, (action, only_state) in marks.items():
            for state in self.ALL_STATES:
                if state == only_state:
                    continue
                with self.subTest(action=name, state=state):
                    self.setUp()
                    self.assert_refused(state, action)

    def test_review_operations_work_from_both_open_states_and_keep_the_status(self):
        actions = self.review_actions()
        expected = {
            "discard": STATUS_DISCARDED,
            "reject": STATUS_REJECTED,
            "request_apply": STATUS_PENDING_APPROVAL,
        }
        for start in (STATUS_PROPOSED, STATUS_PENDING_APPROVAL):
            for name, action in actions.items():
                with self.subTest(action=name, start=start):
                    self.setUp()
                    uid = self.at_state(start)
                    result = action(uid)
                    self.assertEqual(result.status, expected.get(name, start))
                    self.assertEqual(self.store.get(uid), result)

    def test_time_never_expires_a_changeset_that_is_applying_or_already_closed(self):
        added = self.add()
        self.proposals.request_apply(added.uid)
        self.store.approve(added.uid)
        self.clock.now += 100000.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_APPLYING)
        self.store.mark_applied(added.uid, AppliedChangeset(takeoff_uids=("T1",)))
        self.clock.now += 100000.0
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_APPLIED)
        self.assertEqual(
            self.proposals.last_applied("C:/jobs/a.mdb", "7").status, STATUS_APPLIED
        )
        discarded = self.add()
        self.proposals.discard(discarded.uid)
        failed = self.add()
        self.proposals.request_apply(failed.uid)
        self.store.approve(failed.uid)
        self.store.mark_failed(failed.uid)
        self.clock.now += 100000.0
        self.assertEqual(self.proposals.get(discarded.uid).status, STATUS_DISCARDED)
        self.assertEqual(self.proposals.get(failed.uid).status, STATUS_FAILED)

    def test_a_pending_request_is_rechecked_for_changed_objects_when_asked_again(self):
        added = self.add()
        self.proposals.request_apply(added.uid)
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.proposals.request_apply(added.uid)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(
            raised.exception.message,
            "A page or condition this changeset touches changed. Propose it again.",
        )
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_STALE)


class ProposalDetailTests(StoreTestCase):
    def test_the_open_limit_message_names_the_limit(self):
        for _ in range(5):
            self.add()
        with self.assertRaises(ChangesetError) as raised:
            self.add()
        self.assertEqual(
            raised.exception.message,
            "At most 5 changesets can be open per bid. Discard or apply one first.",
        )

    def test_open_changesets_are_counted_per_database_and_bid(self):
        other_database = replace(_changeset(), database_id="C:/jobs/b.mdb")
        for _ in range(5):
            self.add()
        self.add(other_database)
        mine = self.store.open_for_bid("C:/jobs/a.mdb", "7")
        theirs = self.store.open_for_bid("C:/jobs/b.mdb", "7")
        self.assertEqual([item.uid for item in mine], [f"cs-{n}" for n in range(1, 6)])
        self.assertEqual([item.uid for item in theirs], ["cs-6"])
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", 7), mine)
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "8"), ())
        self.assertEqual(self.store.open_for_bid("C:/jobs/c.mdb", "7"), ())
        for _ in range(4):
            self.add(other_database)
        with self.assertRaises(ChangesetError) as raised:
            self.add(other_database)
        self.assertEqual(raised.exception.code, "changeset_too_large")

    def test_created_at_is_a_float_even_when_the_clock_returns_an_int(self):
        store = AiChangesetStore(clock=lambda: 1000)
        added = store.add(_changeset())
        self.assertEqual(added.created_at, 1000.0)
        self.assertIsInstance(added.created_at, float)

    def test_the_default_id_factory_takes_twelve_hex_characters_of_a_uuid4(self):
        store = AiChangesetStore(clock=self.clock)
        with patch.object(
            uuid, "uuid4", return_value=uuid.UUID("0123456789abcdef0123456789abcdef")
        ) as factory:
            added = store.add(_changeset())
        factory.assert_called_once_with()
        self.assertEqual(added.uid, "0123456789ab")

    def test_base_tokens_follow_the_sorted_touched_resources(self):
        base = _changeset()
        changeset = replace(
            base,
            takeoffs=(
                ProposedTakeoff("t1", "page-2", "existing:9", SQUARE),
                ProposedTakeoff("t2", "page-1", "c1", SQUARE),
            ),
        )
        self.tokens.values.update({"page:page-1": "v1", "condition:9": "v9"})
        added = self.add(changeset)
        self.assertEqual(
            added.base_tokens,
            (("condition:9", "v9"), ("page:page-1", "v1"), ("page:page-2", "v0")),
        )

    def test_the_default_token_reader_records_empty_tokens_and_never_goes_stale(self):
        store = AiChangesetStore(clock=self.clock)
        added = store.add(_changeset())
        self.assertEqual(added.base_tokens, (("page:page-1", ""),))
        self.assertEqual(store.request_apply(added.uid).status, STATUS_PENDING_APPROVAL)
        self.assertEqual(store.approve(added.uid).status, STATUS_APPLYING)

    def test_tokens_are_compared_as_text_and_a_missing_token_is_empty(self):
        values = {"page:page-1": 5}
        store = AiChangesetStore(
            clock=self.clock,
            token_reader=lambda database_id, bid_uid, resources: dict(values),
            uid_factory=lambda: "7",
        )
        changeset = replace(
            _changeset(),
            takeoffs=(ProposedTakeoff("t1", "page-1", "existing:9", SQUARE),),
        )
        added = store.add(changeset)
        self.assertEqual(added.base_tokens, (("condition:9", ""), ("page:page-1", "5")))
        self.assertEqual(store.request_apply("7").status, STATUS_PENDING_APPROVAL)
        values["page:page-1"] = 6
        with self.assertRaises(ChangesetError) as raised:
            store.approve("7")
        self.assertEqual(raised.exception.code, "stale_changeset")

    def test_characterisation_ids_are_looked_up_as_text(self):
        """Pins the defensive str() on ids: a numeric id finds the same changeset."""
        store = AiChangesetStore(clock=self.clock, uid_factory=lambda: "7")
        added = store.add(_changeset())
        self.assertIs(store.get(7), added)
        store.request_apply("7")
        store.approve("7")
        record = AppliedChangeset(takeoff_uids=("T1",))
        store.mark_applied("7", record)
        self.assertIs(store.applied_record(7), record)


class AssumptionDetailTests(StoreTestCase):
    def test_a_new_assumption_keeps_every_field_it_was_given(self):
        added = self.add()
        self.assertEqual(added.revision, 0)
        updated = self.proposals.add_assumption(
            added.uid,
            SUBJECT_THICKNESS,
            "c1",
            "8 in",
            "slab thickness not dimensioned",
            "S-102",
        )
        self.assertEqual(
            updated.assumptions,
            (
                ChangesetAssumption(
                    uid="a1",
                    subject=SUBJECT_THICKNESS,
                    target_key="c1",
                    value="8 in",
                    reason="slab thickness not dimensioned",
                    sheet_ref="S-102",
                    impact=IMPACT_HIGH,
                    status=ASSUMPTION_OPEN,
                    override_value=None,
                ),
            ),
        )
        self.assertEqual(updated.revision, 1)
        self.assertEqual(self.proposals.get(added.uid), updated)

    def test_characterisation_assumption_text_fields_are_stored_as_text(self):
        """Pins the defensive str() on every free-text assumption input."""
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        updated = self.proposals.add_assumption(added.uid, SUBJECT_OTHER, 5, 10, 3, 1)
        new = updated.assumptions[-1]
        self.assertEqual(
            (new.target_key, new.value, new.reason, new.sheet_ref),
            ("5", "10", "3", "1"),
        )
        revised = self.proposals.revise_assumption(added.uid, "a1", 7, 2)
        self.assertEqual(
            (revised.assumptions[0].value, revised.assumptions[0].reason), ("7", "2")
        )
        overridden = self.store.override_assumption(added.uid, "a1", 11)
        self.assertEqual(overridden.assumptions[0].override_value, "11")

    def test_accepting_clears_an_override_and_revising_reopens_the_assumption(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"), _assumption("a2"))))
        overridden = self.store.override_assumption(added.uid, "a1", "10")
        self.assertEqual(
            (
                overridden.assumptions[0].status,
                overridden.assumptions[0].override_value,
            ),
            (ASSUMPTION_OVERRIDDEN, "10"),
        )
        accepted = self.store.accept_assumption(added.uid, "a1")
        self.assertEqual(
            (accepted.assumptions[0].status, accepted.assumptions[0].override_value),
            (ASSUMPTION_ACCEPTED, None),
        )
        self.store.override_assumption(added.uid, "a1", "12")
        revised = self.proposals.revise_assumption(added.uid, "a1", "9", "re-read")
        self.assertEqual(
            (
                revised.assumptions[0].status,
                revised.assumptions[0].override_value,
                revised.assumptions[0].value,
            ),
            (ASSUMPTION_OPEN, None, "9"),
        )
        self.assertEqual(revised.assumptions[1], _assumption("a2"))

    def test_the_facade_hands_every_argument_to_the_right_place(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        updated = self.proposals.add_assumption(
            added.uid,
            SUBJECT_CLOSING_SEGMENT,
            "target-key",
            "the value",
            "the reason",
            "the sheet",
            closing_length_in=20.0,
        )
        new = updated.assumptions[-1]
        self.assertEqual(
            (new.subject, new.target_key, new.value, new.reason, new.sheet_ref),
            (
                SUBJECT_CLOSING_SEGMENT,
                "target-key",
                "the value",
                "the reason",
                "the sheet",
            ),
        )
        self.assertEqual(new.impact, IMPACT_HIGH)

    def test_characterisation_an_unknown_subject_is_refused_before_the_changeset_is_looked_up(
        self,
    ):
        """No document specifies this order; pins what the store does today."""
        added = self.add()
        self.clock.now += 1800.0
        for label, uid in (("unknown id", "nope"), ("expired changeset", added.uid)):
            with self.subTest(case=label):
                with self.assertRaises(ChangesetError) as raised:
                    self.proposals.add_assumption(uid, "bogus", "c1", "v", "r", "S-1")
                self.assertEqual(raised.exception.code, "invalid_state")
                self.assertEqual(raised.exception.message, "Unknown assumption subject")


class ClosedPruningKindTests(StoreTestCase):
    def close_one(self):
        self.proposals.discard(self.add().uid)

    def test_expired_stale_and_rejected_changesets_are_pruned_like_the_others(self):
        expired = self.add()
        self.clock.now += 1800.0
        self.assertEqual(self.store.get(expired.uid).status, STATUS_EXPIRED)
        stale = self.add()
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError):
            self.proposals.request_apply(stale.uid)
        self.tokens.values.clear()
        rejected = self.add()
        self.proposals.request_apply(rejected.uid)
        self.store.reject(rejected.uid)
        for _ in range(MAX_CLOSED_CHANGESETS):
            self.close_one()
        for changeset in (expired, stale, rejected):
            with self.subTest(uid=changeset.uid):
                with self.assertRaises(ChangesetError) as raised:
                    self.proposals.get(changeset.uid)
                self.assertEqual(raised.exception.code, "not_found")

    def test_an_edited_open_changeset_is_never_pruned_with_the_closed_ones(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        self.store.accept_assumption(added.uid, "a1")
        self.proposals.add_assumption(
            added.uid, SUBJECT_OTHER, "c1", "flat", "ramp", "S-102"
        )
        for _ in range(MAX_CLOSED_CHANGESETS + 2):
            self.close_one()
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_PROPOSED)
        self.proposals.request_apply(added.uid)
        self.proposals.add_assumption(
            added.uid, SUBJECT_OTHER, "c1", "again", "ramp", "S-102"
        )
        for _ in range(MAX_CLOSED_CHANGESETS + 2):
            self.close_one()
        self.assertEqual(self.proposals.get(added.uid).status, STATUS_PENDING_APPROVAL)


class RoundTwoTests(StoreTestCase):
    """Gaps found by the independent verifier of the first rework round."""

    CALL = ("C:/jobs/a.mdb", "7", ("page:page-1",))

    def test_listing_open_changesets_survives_an_expiry_that_prunes_the_closed_ones(
        self,
    ):
        old = self.add()
        for _ in range(MAX_CLOSED_CHANGESETS):
            self.proposals.discard(self.add().uid)
        self.clock.now += 1800.0
        self.assertEqual(self.store.open_for_bid("C:/jobs/a.mdb", "7"), ())
        self.assertEqual(self.store.get(old.uid).status, STATUS_EXPIRED)
        with self.assertRaises(ChangesetError) as raised:
            self.store.get("cs-2")
        self.assertEqual(raised.exception.code, "not_found")

    def test_override_with_a_stale_revision_is_refused_and_changes_nothing(self):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        with self.assertRaises(ChangesetError) as raised:
            self.store.override_assumption(
                added.uid, "a1", "9", expected_revision=added.revision + 1
            )
        self.assertEqual(raised.exception.code, "changed_during_review")
        self.assertEqual(self.store.get(added.uid), added)
        overridden = self.store.override_assumption(
            added.uid, "a1", "9", expected_revision=added.revision
        )
        self.assertEqual(overridden.assumptions[0].override_value, "9")

    def test_every_token_read_names_the_database_the_bid_and_the_resources(self):
        added = self.add()
        self.assertEqual(self.tokens.calls, [self.CALL])
        self.tokens.calls.clear()
        self.proposals.request_apply(added.uid)
        self.assertEqual(self.tokens.calls, [self.CALL])
        self.tokens.calls.clear()
        self.store.approve(added.uid)
        self.assertEqual(self.tokens.calls, [self.CALL])

    def test_time_expiry_is_noticed_by_every_operation_that_looks_a_changeset_up(self):
        operations = {
            "discard": lambda uid: self.proposals.discard(uid),
            "reject": lambda uid: self.store.reject(uid),
            "request_apply": lambda uid: self.proposals.request_apply(uid),
            "approve": lambda uid: self.store.approve(uid),
            "accept": lambda uid: self.store.accept_assumption(uid, "a1"),
            "override": lambda uid: self.store.override_assumption(uid, "a1", "9"),
            "revise": lambda uid: self.proposals.revise_assumption(uid, "a1", "9", "x"),
            "add_assumption": lambda uid: self.proposals.add_assumption(
                uid, SUBJECT_OTHER, "c1", "v", "r", "S-1"
            ),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                self.setUp()
                added = self.add(
                    _changeset(
                        assumptions=(_assumption("a1", SUBJECT_OTHER, IMPACT_NORMAL),)
                    )
                )
                if name == "approve":
                    self.proposals.request_apply(added.uid)
                self.clock.now += 1800.0
                with self.assertRaises(ChangesetError) as raised:
                    operation(added.uid)
                self.assertEqual(raised.exception.code, "stale_changeset")
                self.assertEqual(
                    raised.exception.message,
                    "The changeset expired or the objects it touches changed. "
                    "Propose it again.",
                )
                self.assertEqual(self.store.get(added.uid).status, STATUS_EXPIRED)

    def test_unknown_changeset_ids_are_not_found_for_every_operation(self):
        operations = {
            "discard": lambda: self.proposals.discard("nope"),
            "reject": lambda: self.store.reject("nope"),
            "request_apply": lambda: self.proposals.request_apply("nope"),
            "approve": lambda: self.store.approve("nope"),
            "mark_applied": lambda: self.store.mark_applied(
                "nope", AppliedChangeset(takeoff_uids=("T1",))
            ),
            "mark_failed": lambda: self.store.mark_failed("nope"),
            "mark_undone": lambda: self.store.mark_undone("nope"),
            "accept": lambda: self.store.accept_assumption("nope", "a1"),
            "override": lambda: self.store.override_assumption("nope", "a1", "9"),
            "revise": lambda: self.proposals.revise_assumption("nope", "a1", "9", "x"),
            "add_assumption": lambda: self.proposals.add_assumption(
                "nope", SUBJECT_OTHER, "c1", "v", "r", "S-1"
            ),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaises(ChangesetError) as raised:
                    operation()
                self.assertEqual(raised.exception.code, "not_found")
                self.assertEqual(raised.exception.message, "Unknown changeset_id")

    def test_approving_with_a_stale_revision_reports_the_review_conflict_first(self):
        """AGENTS.md: a different revision raises changed_during_review."""
        added = self.add()
        self.proposals.request_apply(added.uid)
        self.tokens.values["page:page-1"] = "changed"
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid, expected_revision=added.revision + 1)
        self.assertEqual(raised.exception.code, "changed_during_review")
        self.assertEqual(self.store.get(added.uid).status, STATUS_PENDING_APPROVAL)
        with self.assertRaises(ChangesetError) as raised:
            self.store.approve(added.uid, expected_revision=added.revision)
        self.assertEqual(raised.exception.code, "stale_changeset")
        self.assertEqual(self.store.get(added.uid).status, STATUS_STALE)

    def test_assumption_edits_with_a_stale_revision_report_the_conflict_before_an_unknown_assumption(
        self,
    ):
        added = self.add(_changeset(assumptions=(_assumption("a1"),)))
        edits = {
            "accept": lambda: self.store.accept_assumption(
                added.uid, "a9", expected_revision=added.revision + 1
            ),
            "override": lambda: self.store.override_assumption(
                added.uid, "a9", "9", expected_revision=added.revision + 1
            ),
        }
        for name, edit in edits.items():
            with self.subTest(edit=name):
                with self.assertRaises(ChangesetError) as raised:
                    edit()
                self.assertEqual(raised.exception.code, "changed_during_review")


class HeldLock:
    """Re-entrant lock that counts how deep it is held (no threads, no timing)."""

    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1

    def __exit__(self, *exc_info):
        self.depth -= 1
        self._lock.release()


class GuardedDict(dict):
    def __init__(self, lock, *args):
        super().__init__(*args)
        self.lock = lock

    def check(self):
        assert self.lock.depth > 0, "state touched without the store lock"

    def __setitem__(self, key, value):
        self.check()
        super().__setitem__(key, value)

    def __getitem__(self, key):
        self.check()
        return super().__getitem__(key)

    def __delitem__(self, key):
        self.check()
        super().__delitem__(key)

    def __contains__(self, key):
        self.check()
        return super().__contains__(key)

    def __iter__(self):
        self.check()
        return super().__iter__()

    def __len__(self):
        self.check()
        return super().__len__()

    def get(self, key, default=None):
        self.check()
        return super().get(key, default)

    def pop(self, *args):
        self.check()
        return super().pop(*args)

    def items(self):
        self.check()
        return super().items()


class GuardedList(list):
    def __init__(self, lock):
        super().__init__()
        self.lock = lock

    def check(self):
        assert self.lock.depth > 0, "state touched without the store lock"

    def append(self, item):
        self.check()
        super().append(item)

    def remove(self, item):
        self.check()
        super().remove(item)

    def __reversed__(self):
        self.check()
        return super().__reversed__()

    def __contains__(self, item):
        self.check()
        return super().__contains__(item)


class LockDisciplineTests(StoreTestCase):
    def test_every_operation_touches_the_store_state_only_while_holding_the_lock(self):
        lock = HeldLock()
        store = self.store
        store._lock = lock
        store._changesets = GuardedDict(lock, store._changesets)
        store._applied = GuardedDict(lock, store._applied)
        store._closed_order = GuardedDict(lock, store._closed_order)
        store._applied_order = GuardedList(lock)
        first = self.add(
            _changeset(assumptions=(_assumption("a1", SUBJECT_OTHER, IMPACT_NORMAL),))
        )
        store.get(first.uid)
        store.open_for_bid("C:/jobs/a.mdb", "7")
        store.last_applied("C:/jobs/a.mdb", "7")
        store.applied_record(first.uid)
        store.accept_assumption(first.uid, "a1")
        store.override_assumption(first.uid, "a1", "1")
        store.revise_assumption(first.uid, "a1", "1", "r")
        store.add_assumption(first.uid, SUBJECT_OTHER, "c", "v", "r", "s")
        store.request_apply(first.uid)
        store.approve(first.uid)
        store.mark_applied(first.uid, AppliedChangeset(takeoff_uids=("T1",)))
        store.last_applied("C:/jobs/a.mdb", "7")
        store.mark_undone(first.uid)
        store.discard(self.add().uid)
        store.reject(self.add().uid)
        failing = self.add()
        store.request_apply(failing.uid)
        store.approve(failing.uid)
        store.mark_failed(failing.uid)
        self.assertEqual(lock.depth, 0)
        self.assertEqual(store.get(failing.uid).status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
